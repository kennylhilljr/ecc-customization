#!/usr/bin/env python3
"""Verify queued "@openclaw" GitHub commands and wake the OpenClaw ops agent.

    gh_command_drain.py [--queue DIR] [--dry-run] [--retry-pending]

The github-event-router plugin writes a `command` event file into
~/.local/state/github-events/ops/ when a GitHub Slack app post mentions
@openclaw. The post text is written by whoever commented on GitHub, so it is
never handed to an agent. This drain asks the GitHub API for recent comments
instead and wakes the ops agent only with comments that kennylhilljr wrote and
that mention @openclaw. Three sources are read: issue and pull request
conversation comments, inline pull request review comments, and pull request
review bodies (the last only when the event names a pull request; GitHub has
no repository-wide list of reviews).

A comment counts as delivered only when its own "<source>:<id>" key is in the
state file; there is no id watermark. Keys are kept for 7 days, far longer
than the 15 minute window that already excludes older comments.

Before each `openclaw agent` run the drain records a pending entry for that
comment in the state file. A run that dies before the result is recorded
leaves the entry behind, and later runs do not wake the agent for that
comment again, so nothing is posted twice. An agent run that times out or
exits nonzero keeps its entry for the same reason, since it may have posted
before failing; only a run that could not be started at all clears it.
--retry-pending clears those entries so a later event can deliver the comment.
Such a run also sends a short alert to Slack with `openclaw message send`;
a failed alert is only logged.

Only comments created from 15 minutes before to 2 minutes after the event's
received_at count, and "@openclaw" must be a whole handle (MENTION, the same
pattern the router uses). Each run first replays the router's failed-request
journal (ops-failed.jsonl next to the queue) into the queue.

Before the first agent run of a drain run, `openclaw health` checks that the
local Gateway answers. If it does not, no pending entry is written, the agent
is not started, and the event is deferred.

Exit codes: 0 when every event was handled (or there was nothing to do, or
another run holds the lock), 1 when an event was deferred or given up on, 2
when the queue directory is refused. Standard library only; Python 3.9+. The
GitHub token is never printed or logged.
"""
import argparse
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

TRUSTED_LOGIN = "kennylhilljr"
# the same pattern as the router's: "@openclaw" as a whole handle, not inside an email address,
# a longer handle (@openclawbot) or a domain (@openclaw.com); trailing punctuation is fine
MENTION = re.compile(r"(?<![A-Za-z0-9_.+-])@openclaw(?![A-Za-z0-9_-])(?!\.[A-Za-z0-9])", re.I)
REPLY_CHANNEL = "C0CEMPH1L0N"
ALERT_CHANNEL = "C0CERFQ8UJV"    # where a run with an unknown outcome is reported
HEALTH_TIMEOUT_MS = 5000         # passed to `openclaw health --timeout`
HEALTH_KILL_AFTER = 15
ALERT_TIMEOUT = 60
AGENT_TIMEOUT = 600          # passed to `openclaw agent --timeout`
AGENT_KILL_AFTER = 660       # subprocess timeout, a bit above the agent's own
TOKEN_TIMEOUT = 60
HTTP_TIMEOUT = 30
WINDOW = timedelta(minutes=15)   # comments created this long before received_at still count
AFTER_RECEIVED = timedelta(minutes=2)   # and up to this long after it (clock skew, Slack delay)
FAILED_JOURNAL = "ops-failed.jsonl"     # command requests the router could not publish
REPLAYING = re.compile(r"^\.ops-failed\.replaying-[A-Za-z0-9_-]+\.jsonl$")
MAX_ATTEMPTS = 24            # deferrals before an event file is given up on and rejected
QUEUE_SETTLE = 30            # seconds an unparsable file is left alone in case it is still being written
CLOCK_SKEW = 300             # an mtime up to this far in the future still counts as just written
REQUEUE_AFTER = 3600         # deferred files older than this go back into the queue
MAX_PAGES = 10               # more pages than this is an error, never a silent cut
DELIVERED_KEEP = timedelta(days=7)   # delivered keys are kept this long, far beyond WINDOW
QUEUE_MARKER = ".github-events-queue"
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ISSUE_URL_NUMBER = re.compile(r"/issues/(\d+)$")
PULL_URL_NUMBER = re.compile(r"/pulls/(\d+)$")
TARGET_KINDS = (None, "issue", "pull_request")
# the three comment sources have separate id spaces, so state keys are "<source>:<id>"
ISSUE_COMMENT, REVIEW_COMMENT, REVIEW = "issue_comment", "review_comment", "review"


class GitHubError(Exception):
    """A token, HTTP or network failure. The message never holds the token."""

    def __init__(self, msg, status=None):
        super().__init__(msg)
        self.status = status


def log(msg):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def default_queue():
    return Path.home() / ".local/state/github-events/ops"


def state_dir():
    d = os.environ.get("OPENCLAW_GH_COMMAND_STATE_DIR")
    return Path(d).expanduser() if d else Path.home() / ".local/state/openclaw-gh-command-drain"


# ---------------------------------------------------------------- queue safety

def sibling(qdir, kind):
    """<parent>/ops-deferred or ops-rejected, outside the queue so launchd does not see them."""
    return qdir.parent / f"{qdir.name}-{kind}"


def checked_queue_dir(qdir):
    """(resolved path, None) when qdir is safe to drain, else (None, why)."""
    qdir = Path(qdir).expanduser()
    if os.path.islink(qdir):
        return None, f"{qdir} is a symlink"
    if os.path.lexists(qdir) and not qdir.is_dir():
        return None, f"{qdir} is not a directory"
    real = Path(os.path.realpath(qdir))
    try:
        marked = stat.S_ISREG(os.lstat(real.parent / QUEUE_MARKER).st_mode)
    except OSError:
        marked = False
    if real != Path(os.path.realpath(default_queue())) and not marked:
        return None, (f"{qdir} is not {default_queue()} and its parent has no {QUEUE_MARKER} file, "
                      f"so it does not look like a GitHub event queue")
    for kind in ("deferred", "rejected"):
        side = sibling(real, kind)
        try:
            mode = os.lstat(side).st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(mode):
            return None, f"{side} exists but is not a directory (a symlink or a file)"
    return real, None


def queue_entries(qdir):
    """(event files, other entries), sorted by name. Judged with lstat, so symlinks are never followed."""
    try:
        names = sorted(os.listdir(qdir))
    except (FileNotFoundError, NotADirectoryError):
        return [], []
    files, other = [], []
    for n in names:
        p = qdir / n
        try:
            mode = os.lstat(p).st_mode
        except FileNotFoundError:
            continue
        ok = stat.S_ISREG(mode) and n.endswith(".json") and not n.startswith(".")
        (files if ok else other).append(p)
    return files, other


def write_json_atomic(path, data, mode=0o600):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=1)
            fh.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def move_into(path, dest, data=None):
    """Move path into dest, adding -1, -2... to the name on a collision. Without data this is one
    os.replace (a symlink moves as a link). With data, that JSON is written atomically under the final
    name in dest first and the source is removed only afterwards; on any failure the source stays where
    it was, nothing new is left in dest, and the error propagates."""
    dest.mkdir(parents=True, exist_ok=True)
    stem, suffix = (path.stem, path.suffix) if path.suffix == ".json" else (path.name, "")
    target, i = dest / path.name, 0
    while os.path.lexists(target):
        i += 1
        target = dest / f"{stem}-{i}{suffix}"
    if data is None:
        os.replace(path, target)
        return target
    if not os.path.lexists(path):
        raise FileNotFoundError(2, "No such file or directory", str(path))
    write_json_atomic(target, data)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:
        try:
            os.unlink(target)
        except OSError:
            pass
        raise
    return target


def requeue_deferred(qdir, now):
    moved = 0
    for p in queue_entries(sibling(qdir, "deferred"))[0]:
        try:
            age = now - os.lstat(p).st_mtime
        except FileNotFoundError:
            continue
        if age > REQUEUE_AFTER:
            move_into(p, qdir)
            moved += 1
    if moved:
        log(f"queue: moved {moved} deferred event file{'s' if moved != 1 else ''} back to {qdir}")


# ---------------------------------------------------------------- events

def parse_time(value):
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


def parse_event(path):
    """The event dict when path holds a valid command event, None when it is JSON but not one.
    Raises ValueError when it is not JSON at all."""
    return validate_event(json.loads(path.read_text()))


def validate_event(ev):
    """ev when it is a valid command event, else None."""
    if not isinstance(ev, dict) or ev.get("kind") != "command":
        return None
    repo, n = ev.get("repo"), ev.get("number")
    if repo is not None and not (isinstance(repo, str) and REPO_NAME.match(repo)):
        return None
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 1):
        return None
    if n is not None and repo is None:
        return None
    if ev.get("target_kind") not in TARGET_KINDS:
        return None
    if parse_time(ev.get("received_at")) is None:
        return None
    return ev


# ---------------------------------------------------------------- state

def empty_state():
    return {"delivered": {}, "pending": {}}


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def load_state(path, dry_run, now=None):
    """The state, keyed by lower-case repository: "delivered" maps each "<source>:<id>" key sent to
    the agent to {"time": the comment's created_at or submitted_at}, and "pending" maps the keys whose
    agent run started but was never recorded as finished to their start time and URL.

    Delivered keys older than DELIVERED_KEEP are dropped; the WINDOW check already excludes those
    comments. Older formats are migrated: a "repos" watermark is dropped, and a list of plain integer
    ids (issue comments) or keys becomes entries with no time and "first_seen" set to now, dropped
    DELIVERED_KEEP after first_seen."""
    now = now or datetime.now(timezone.utc)
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return empty_state()
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or not all(isinstance(data.get(k, {}), dict)
                                                 for k in ("delivered", "pending")):
            raise ValueError("not an object with delivered and pending objects")
    except ValueError as e:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dest = path.with_name(f"{path.name}.corrupt-{stamp}")
        if dry_run:
            log(f"state: {path} is malformed ({e}); would move it to {dest.name} and start empty")
        else:
            os.replace(path, dest)
            log(f"state: {path} is malformed ({e}); moved it to {dest.name} and started empty")
        return empty_state()
    state = empty_state()
    for repo, entries in data.get("delivered", {}).items():
        if not isinstance(repo, str):
            continue
        if isinstance(entries, list):  # first format: ids or keys, no times
            entries = {(f"{ISSUE_COMMENT}:{k}" if isinstance(k, int) and not isinstance(k, bool) else k):
                       {"time": None, "first_seen": iso(now)} for k in entries}
        if not isinstance(entries, dict):
            continue
        kept = {}
        for key, entry in entries.items():
            if not isinstance(key, str) or not isinstance(entry, dict):
                continue
            seen = parse_time(entry.get("time")) or parse_time(entry.get("first_seen"))
            if seen is None:  # no usable time at all: start the clock now
                entry, seen = {"time": None, "first_seen": iso(now)}, now
            if now - seen <= DELIVERED_KEEP:
                kept[key] = entry
        if kept:
            state["delivered"][repo] = kept
    for repo, entries in data.get("pending", {}).items():
        if isinstance(repo, str) and isinstance(entries, dict):
            state["pending"][repo] = {k: v for k, v in entries.items() if isinstance(k, str) and isinstance(v, dict)}
    return state


def already_handled(state, repo, source, cid):
    """True when this exact comment was delivered before. Only explicit keys count: a lookup scoped to
    one issue cannot prove that lower ids elsewhere in the repository were handled."""
    return f"{source}:{cid}" in state["delivered"].get(repo, {})


def mark_pending(state, repo, key, url):
    state["pending"].setdefault(repo, {})[key] = {"since": iso(datetime.now(timezone.utc)), "url": url}


def clear_pending(state, repo, key):
    entries = state["pending"].get(repo, {})
    entries.pop(key, None)
    if not entries:
        state["pending"].pop(repo, None)


def mark_delivered(state, repo, source, cid, created):
    key = f"{source}:{cid}"
    clear_pending(state, repo, key)
    state["delivered"].setdefault(repo, {})[key] = {"time": iso(created)}


# ---------------------------------------------------------------- GitHub

def urllib_get(url, headers):
    """(status, lower-cased headers, body bytes). Raises GitHubError on a network failure."""
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        hdrs = {k.lower(): v for k, v in (e.headers.items() if e.headers else [])}
        return e.code, hdrs, e.read() or b""
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise GitHubError(f"network error: {getattr(e, 'reason', e)}") from None


def next_link(link):
    for part in (link or "").split(","):
        m = re.match(r'\s*<([^>]+)>\s*;\s*rel="next"', part)
        if m:
            return m.group(1)
    return None


class GitHub:
    def __init__(self, http_get=None, run=None):
        self.http_get = http_get or urllib_get
        self.run = run or subprocess.run
        self.base = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
        self._token = None

    def token(self):
        if self._token is None:
            cmd = os.environ.get("OPENCLAW_GH_APP_TOKEN_CMD") or str(Path.home() / ".local/bin/openclaw-gh-app-token")
            try:
                r = self.run([cmd], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                             timeout=TOKEN_TIMEOUT)
            except (OSError, subprocess.SubprocessError) as e:
                raise GitHubError(f"token command could not run ({type(e).__name__})") from None
            tok = (r.stdout or "").strip()
            if r.returncode != 0 or not tok or any(c.isspace() or not c.isprintable() for c in tok):
                raise GitHubError(f"token command failed (exit {r.returncode})")
            self._token = tok
        return self._token

    def get_pages(self, path, params):
        """Every page of a list endpoint, following Link rel="next" on the same API host only. More than
        MAX_PAGES pages raises GitHubError rather than returning a cut-off list."""
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        pages = []
        while True:
            if len(pages) == MAX_PAGES:
                raise GitHubError(f"GET {path} has more than {MAX_PAGES} pages")
            headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "openclaw-gh-command-drain"}
            status, hdrs, body = self.http_get(url, headers)
            if status != 200:
                msg = ""
                try:
                    msg = str(json.loads(body).get("message", ""))[:200]
                except (ValueError, AttributeError):
                    pass
                raise GitHubError(f"GET {path} failed: HTTP {status}{': ' + msg if msg else ''}", status)
            try:
                pages.append(json.loads(body))
            except ValueError:
                raise GitHubError(f"GET {path} returned a body that is not JSON") from None
            url = next_link(hdrs.get("link"))
            if not url:
                return pages
            if not url.startswith(self.base + "/"):
                raise GitHubError(f"GET {path}: next page points outside {self.base}")

    def installation_repos(self):
        repos = []
        for page in self.get_pages("/installation/repositories", {"per_page": 100}):
            if not isinstance(page, dict) or not isinstance(page.get("repositories"), list):
                raise GitHubError("GET /installation/repositories returned an unexpected shape")
            repos += [r["full_name"] for r in page["repositories"]
                      if isinstance(r, dict) and isinstance(r.get("full_name"), str)
                      and REPO_NAME.match(r["full_name"])]
        return repos

    def list(self, path, params):
        out = []
        for page in self.get_pages(path, params):
            if not isinstance(page, list):
                raise GitHubError(f"GET {path} returned an unexpected shape")
            out += [c for c in page if isinstance(c, dict)]
        return out

    def comments(self, repo, number, target_kind, since):
        """[(source, comment)] from every source that applies to the target. With a number and no
        target_kind the pull request endpoints are tried too, and a 404 there means it is an issue."""
        if number is None:
            wide = {"sort": "created", "direction": "desc", "per_page": 100, "since": since}
            return ([(ISSUE_COMMENT, c) for c in self.list(f"/repos/{repo}/issues/comments", wide)]
                    + [(REVIEW_COMMENT, c) for c in self.list(f"/repos/{repo}/pulls/comments", wide)])
        out = [(ISSUE_COMMENT, c) for c in self.list(f"/repos/{repo}/issues/{number}/comments",
                                                     {"per_page": 100, "since": since})]
        if target_kind == "issue":
            return out
        try:
            out += [(REVIEW_COMMENT, c) for c in self.list(f"/repos/{repo}/pulls/{number}/comments",
                                                           {"per_page": 100, "since": since})]
            out += [(REVIEW, c) for c in self.list(f"/repos/{repo}/pulls/{number}/reviews", {"per_page": 100})]
        except GitHubError as e:
            if target_kind is None and e.status == 404:
                return out
            raise
        return out


def select(comments, repo, window_start, window_end, state):
    """Trusted @openclaw comments created in [window_start, window_end] and not yet delivered, oldest first.
    comments holds (source, comment) pairs. Each item is (time, source, id, repo, number, html_url, body)."""
    picked = {}
    for source, c in comments:
        user, cid, body = c.get("user"), c.get("id"), c.get("body")
        if not isinstance(user, dict) or user.get("login") != TRUSTED_LOGIN or user.get("type") != "User":
            continue
        if isinstance(cid, bool) or not isinstance(cid, int) or not isinstance(body, str) or not body.strip():
            continue
        if not MENTION.search(body):
            continue
        created = parse_time(c.get("submitted_at" if source == REVIEW else "created_at"))
        if created is None or not window_start <= created <= window_end:
            continue
        if source == ISSUE_COMMENT:
            m = ISSUE_URL_NUMBER.search(str(c.get("issue_url", "")))
        else:
            m = PULL_URL_NUMBER.search(str(c.get("pull_request_url", "")))
        url = c.get("html_url")
        if not m or not isinstance(url, str):
            continue
        if already_handled(state, repo.lower(), source, cid):
            continue
        picked[(source, cid)] = (created, source, cid, repo, int(m.group(1)), url, body)
    return sorted(picked.values(), key=lambda item: item[:3])


# ---------------------------------------------------------------- agent

def message_text(repo, number, url, body):
    return (f"Verified GitHub command from {TRUSTED_LOGIN} (the drain checked the author with the GitHub API).\n"
            f"Comment: {url}\nOn: {repo}#{number}\n\n{body}")


AGENT_OK, AGENT_NOT_STARTED, AGENT_UNKNOWN = "ok", "not_started", "unknown"


def wake_agent(text, run):
    """Run `openclaw agent` with the message in a private file. Returns (outcome, detail): AGENT_OK when
    it exits 0, AGENT_NOT_STARTED when it could not be started at all (nothing can have been posted), and
    AGENT_UNKNOWN when it timed out or exited nonzero (it may already have acted and posted). detail is
    "timeout" or "exit N" for AGENT_UNKNOWN."""
    try:
        tmpdir = tempfile.mkdtemp(prefix="openclaw-gh-command-")
    except OSError as e:
        log(f"agent: could not create the message folder ({e.strerror or e})")
        return AGENT_NOT_STARTED, "not started"
    try:
        path = os.path.join(tmpdir, "message.txt")
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as fh:
                fh.write(text)
        except OSError as e:
            log(f"agent: could not write the message file ({e.strerror or e})")
            return AGENT_NOT_STARTED, "not started"
        argv = [openclaw_bin(), "agent", "--agent", "ops",
                "--message-file", path, "--deliver", "--reply-channel", "slack",
                "--reply-to", f"channel:{REPLY_CHANNEL}", "--timeout", str(AGENT_TIMEOUT)]
        try:
            r = run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=AGENT_KILL_AFTER)
        except subprocess.TimeoutExpired:
            log(f"agent: openclaw agent timed out after {AGENT_KILL_AFTER}s")
            return AGENT_UNKNOWN, "timeout"
        except OSError as e:
            log(f"agent: could not run openclaw ({e.strerror or e})")
            return AGENT_NOT_STARTED, "not started"
        if r.returncode != 0:
            tail = (r.stderr or "").strip()[-300:]
            log(f"agent: openclaw agent exited {r.returncode}{': ' + tail if tail else ''}")
            return AGENT_UNKNOWN, f"exit {r.returncode}"
        return AGENT_OK, ""
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def openclaw_bin():
    return os.environ.get("OPENCLAW_BIN") or "openclaw"


def gateway_reachable(run):
    """True when `openclaw health` exits 0 in time. Output is discarded."""
    try:
        r = run([openclaw_bin(), "health", "--timeout", str(HEALTH_TIMEOUT_MS)], stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=HEALTH_KILL_AFTER)
    except subprocess.TimeoutExpired:
        log(f"gateway: openclaw health timed out after {HEALTH_KILL_AFTER}s; gateway not reachable")
        return False
    except OSError as e:
        log(f"gateway: could not run openclaw health ({e.strerror or e}); gateway not reachable")
        return False
    if r.returncode != 0:
        log(f"gateway: openclaw health exited {r.returncode}; gateway not reachable")
        return False
    return True


def send_alert(url, detail, run):
    """Tell the owner in Slack that a comment was left pending. A failure is only logged."""
    text = (f"openclaw-gh-command-drain: the ops agent run for {url} did not finish cleanly ({detail}). "
            f"It was not resent. If nothing was posted, run: openclaw-gh-command-drain --retry-pending")
    argv = [openclaw_bin(), "message", "send", "--channel", "slack", "--target", f"channel:{ALERT_CHANNEL}",
            "-m", text]
    try:
        r = run(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=ALERT_TIMEOUT)
    except subprocess.TimeoutExpired:
        log(f"alert: openclaw message send timed out after {ALERT_TIMEOUT}s")
        return
    except OSError as e:
        log(f"alert: could not run openclaw message send ({e.strerror or e})")
        return
    if r.returncode != 0:
        log(f"alert: openclaw message send exited {r.returncode}")


# ---------------------------------------------------------------- failed-request journal

def compact_timestamp(iso_text):
    """The router's file name prefix: 2026-11-03T14:15:02.123Z -> 20261103T141502123Z."""
    return re.sub(r"[-:.]", "", iso_text)


def safe_part(value):
    return (re.sub(r"[^A-Za-z0-9_-]+", "_", str(value))[:80]) or "x"


def publish_event(root, qdir, ev):
    """Write ev into qdir the way the router does: a temporary file in <root>/.tmp, then os.replace."""
    tmpdir = root / ".tmp"
    tmpdir.mkdir(mode=0o700, exist_ok=True)
    qdir.mkdir(mode=0o700, exist_ok=True)
    while True:
        name = (f"{compact_timestamp(ev['received_at'])}-{safe_part(ev.get('slack_message_id') or 'nots')}"
                f"-command-{os.urandom(3).hex()}.json")
        if not os.path.lexists(qdir / name):
            break
    fd, tmp = tempfile.mkstemp(dir=tmpdir, prefix=".command-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(ev, fh)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, qdir / name)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return name


def unique_path(path):
    stem, suffix, i, target = path.stem, path.suffix, 0, path
    while os.path.lexists(target):
        i += 1
        target = path.with_name(f"{stem}-{i}{suffix}")
    return target


def write_lines_atomic(path, lines):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write("".join(line + "\n" for line in lines))
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise


def replay_one(root, qdir, path):
    """Publish every valid line of one replaying file and reject the rest. True when done, in which case
    the file is deleted. On a failure the unpublished lines stay in the file for the next run."""
    try:
        lines = [line for line in path.read_text().splitlines() if line.strip()]
    except (OSError, UnicodeDecodeError) as e:
        log(f"replay: could not read {path.name} ({e}); leaving it for the next run")
        return False
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rejects, published = [], 0
    for i, line in enumerate(lines):
        try:
            ev = validate_event(json.loads(line))
        except ValueError:
            ev = None
        if ev is None:
            log(f"replay: {path.name} line {i + 1} is not a valid command request; rejecting it")
            rejects.append(line)
            continue
        try:
            publish_event(root, qdir, ev)
            published += 1
        except OSError as e:
            log(f"replay: could not publish {path.name} line {i + 1} ({e.strerror or e}); "
                f"leaving the rest for the next run")
            try:
                if rejects:
                    rejected = sibling(qdir, "rejected")
                    rejected.mkdir(parents=True, exist_ok=True)
                    write_lines_atomic(unique_path(rejected / f"ops-failed-{stamp}.jsonl"), rejects)
                write_lines_atomic(path, lines[i:])
            except OSError as e2:
                log(f"replay: could not shorten {path.name} ({e2.strerror or e2}); "
                    f"lines already published may be published again (repeats are harmless)")
            return False
    try:
        if rejects:
            rejected = sibling(qdir, "rejected")
            rejected.mkdir(parents=True, exist_ok=True)
            write_lines_atomic(unique_path(rejected / f"ops-failed-{stamp}.jsonl"), rejects)
        os.unlink(path)
    except OSError as e:
        log(f"replay: could not finish {path.name} ({e.strerror or e}); leaving it for the next run")
        return False
    log(f"replay: {path.name}: published {published}, rejected {len(rejects)}")
    return True


def replay_failed(qdir, dry_run):
    """Turn the router's failed-request journal back into queue events. The journal is renamed first, so
    the router's later appends start a fresh file and are never lost; leftovers from an earlier run that
    did not finish are replayed too. Returns False when something is left for the next run."""
    root = qdir.parent
    journal = root / FAILED_JOURNAL
    try:
        mode = os.lstat(journal).st_mode
    except FileNotFoundError:
        mode = None
    ok = True
    if mode is not None:
        if not stat.S_ISREG(mode):
            log(f"replay: {journal} is not a regular file; {'would move' if dry_run else 'moving'} it "
                f"to {sibling(qdir, 'rejected')}")
            if not dry_run:
                try:
                    move_into(journal, sibling(qdir, "rejected"))
                except OSError as e:
                    log(f"replay: could not move {journal.name} ({e.strerror or e})")
                    ok = False
        elif dry_run:
            log(f"replay: would replay {journal}")
        else:
            stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
            try:
                os.replace(journal, unique_path(root / f".ops-failed.replaying-{stamp}.jsonl"))
            except OSError as e:
                log(f"replay: could not rename {journal} ({e.strerror or e})")
                ok = False
    try:
        names = sorted(os.listdir(root))
    except FileNotFoundError:
        names = []
    for name in names:
        path = root / name
        if not REPLAYING.match(name):
            continue
        try:
            if not stat.S_ISREG(os.lstat(path).st_mode):
                continue
        except FileNotFoundError:
            continue
        if dry_run:
            log(f"replay: would replay {path.name}")
            continue
        ok = replay_one(root, qdir, path) and ok
    return ok


# ---------------------------------------------------------------- the run

def lock(sdir):
    sdir.mkdir(parents=True, exist_ok=True, mode=0o700)
    f = open(sdir / "drain.lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        f.close()
        return None
    return f


def drain(qdir, dry_run, gh, run, now):
    rejected, deferred = sibling(qdir, "rejected"), sibling(qdir, "deferred")
    failed = False

    def act(verb, path, why, fn):
        nonlocal failed
        log(f"queue: {'would ' + verb if dry_run else verb} {path.name}: {why}")
        if not dry_run:
            try:
                fn()
            except FileNotFoundError:
                pass
            except OSError as e:  # the file stays where it was; the next run tries again
                failed = True
                log(f"queue: could not {verb} {path.name} ({e.strerror or e}); it stays where it was")

    def defer(path, ev, why):
        nonlocal failed
        failed = True
        attempts = ev.get("attempts", 0)
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 0:
            attempts = 0
        ev = dict(ev, attempts=attempts + 1)
        if ev["attempts"] >= MAX_ATTEMPTS:
            act(f"move to {rejected}", path, f"{why}; giving up after {ev['attempts']} attempts",
                lambda: move_into(path, rejected, ev))
        else:
            act(f"move to {deferred}", path, f"{why}; attempt {ev['attempts']}",
                lambda: move_into(path, deferred, ev))

    files, other = queue_entries(qdir)
    for p in other:
        kind = "a directory" if os.path.isdir(p) and not os.path.islink(p) else "not an event file"
        act(f"move to {rejected}", p, kind, lambda p=p: move_into(p, rejected))

    state_path = state_dir() / "state.json"
    state = None
    gateway = None
    for path in files:
        try:
            ev = parse_event(path)
        except FileNotFoundError:
            continue
        except ValueError:
            try:
                age = now - path.stat().st_mtime
            except FileNotFoundError:
                continue
            if -CLOCK_SKEW <= age < QUEUE_SETTLE:
                log(f"queue: leaving {path.name} for now: not valid JSON yet, written {age:.0f}s ago")
                continue
            act(f"move to {rejected}", path, f"not valid JSON, written {age:.0f}s ago",
                lambda: move_into(path, rejected))
            continue
        if ev is None:
            act(f"move to {rejected}", path, "not a valid command event", lambda: move_into(path, rejected))
            continue
        if state is None:
            state = load_state(state_path, dry_run)
        window_start = parse_time(ev["received_at"]) - WINDOW
        window_end = parse_time(ev["received_at"]) + AFTER_RECEIVED  # a retry hours later must not reach newer comments
        since = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            repos = [ev["repo"]] if ev["repo"] is not None else gh.installation_repos()
            picked = []
            for repo in repos:
                picked += select(gh.comments(repo, ev["number"], ev.get("target_kind"), since),
                                 repo, window_start, window_end, state)
        except GitHubError as e:
            log(f"github: {path.name}: {e}")
            defer(path, ev, "GitHub lookup failed")
            continue
        picked.sort(key=lambda item: item[:3])
        ok, why = True, ""
        for created, source, cid, repo, number, url, body in picked:
            key, rkey = f"{source}:{cid}", repo.lower()
            pending = state["pending"].get(rkey, {}).get(key)
            if pending is not None:
                log(f"agent: not waking the ops agent again for {url}: a run started at "
                    f"{pending.get('since', '?')} was never recorded as finished; run with --retry-pending "
                    f"to allow it again")
                continue
            if dry_run:
                log(f"agent: would wake the ops agent for {url}")
                continue
            if gateway is None:  # probed once per run, before the first pending record
                gateway = gateway_reachable(run)
            if not gateway:
                ok, why = False, "gateway not reachable"
                break
            mark_pending(state, rkey, key, url)
            try:
                write_json_atomic(state_path, state)
            except OSError as e:
                clear_pending(state, rkey, key)
                log(f"state: could not record the pending run for {url} ({e.strerror or e}); not waking the agent")
                ok, why = False, "state write failed"
                break
            log(f"agent: waking the ops agent for {url}")
            outcome, detail = wake_agent(message_text(repo, number, url, body), run)
            if outcome == AGENT_NOT_STARTED:  # nothing ran, so a later run may safely try again
                clear_pending(state, rkey, key)
                try:
                    write_json_atomic(state_path, state)
                except OSError as e:
                    log(f"state: could not clear the pending entry for {url} ({e.strerror or e}); "
                        f"it stays pending until --retry-pending")
                ok, why = False, "ops agent could not be started"
                break
            if outcome == AGENT_UNKNOWN:  # it may have posted already: keep the entry so it is not sent twice
                log(f"agent: {url} stays pending, so it will not be sent again automatically; check Slack, "
                    f"and if the ops agent did not answer, run with --retry-pending")
                send_alert(url, detail, run)
                ok, why = False, "ops agent run failed or timed out"
                break
            mark_delivered(state, rkey, source, cid, created)
            try:
                write_json_atomic(state_path, state)
            except OSError as e:
                log(f"state: {url} was delivered but could not be recorded ({e.strerror or e}); "
                    f"it stays pending, so it is not sent again")
        if not ok:
            defer(path, ev, why)
            continue
        found = f"{len(picked)} verified comment{'s' if len(picked) != 1 else ''}"
        act("delete", path, f"handled, {found}", lambda: os.unlink(path))
    return 1 if failed else 0


def retry_pending(dry_run):
    path = state_dir() / "state.json"
    state = load_state(path, dry_run)
    urls = [e.get("url", key) for entries in state["pending"].values() for key, e in entries.items()]
    for url in urls:
        log(f"state: {'would clear' if dry_run else 'clearing'} the pending entry for {url}")
    if urls and not dry_run:
        state["pending"] = {}
        write_json_atomic(path, state)


def main(argv=None, http_get=None, run=None):
    ap = argparse.ArgumentParser(prog="openclaw-gh-command-drain",
                                 description="Verify queued @openclaw GitHub commands and wake the ops agent.")
    ap.add_argument("--queue", default=None, help="queue directory (default ~/.local/state/github-events/ops)")
    ap.add_argument("--dry-run", action="store_true", help="read and log only: no agent runs, moves or state writes")
    ap.add_argument("--retry-pending", action="store_true",
                    help="clear pending entries left by runs that never finished, so those comments can be "
                         "delivered by a later event")
    args = ap.parse_args(argv)
    run = run or subprocess.run
    held = lock(state_dir())
    if held is None:
        log("another drain run holds the lock; leaving the queue for the next run")
        return 0
    with held:
        qdir, why = checked_queue_dir(args.queue if args.queue is not None else default_queue())
        if qdir is None:
            print(f"openclaw-gh-command-drain: refusing the queue: {why}. Nothing was moved.", file=sys.stderr)
            return 2
        if args.retry_pending:
            retry_pending(args.dry_run)
        replayed = replay_failed(qdir, args.dry_run)
        if not qdir.exists():
            return 0 if replayed else 1
        now = time.time()
        if not args.dry_run:
            requeue_deferred(qdir, now)
        code = drain(qdir, args.dry_run, GitHub(http_get, run), run, now)
        return code if replayed else max(code, 1)


if __name__ == "__main__":
    sys.exit(main())
