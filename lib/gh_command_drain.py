#!/usr/bin/env python3
"""Verify queued "@openclaw" GitHub commands and wake the OpenClaw ops agent.

    gh_command_drain.py [--queue DIR] [--dry-run]

The github-event-router plugin writes a `command` event file into
~/.local/state/github-events/ops/ when a GitHub Slack app post mentions
@openclaw. The post text is written by whoever commented on GitHub, so it is
never handed to an agent. This drain asks the GitHub API for recent comments
instead and wakes the ops agent only with comments that kennylhilljr wrote and
that mention @openclaw.

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
MENTION = "@openclaw"
REPLY_CHANNEL = "C0CEMPH1L0N"
AGENT_TIMEOUT = 600          # passed to `openclaw agent --timeout`
AGENT_KILL_AFTER = 660       # subprocess timeout, a bit above the agent's own
TOKEN_TIMEOUT = 60
HTTP_TIMEOUT = 30
WINDOW = timedelta(minutes=15)   # comments created this long before received_at still count
MAX_ATTEMPTS = 24            # deferrals before an event file is given up on and rejected
QUEUE_SETTLE = 30            # seconds an unparsable file is left alone in case it is still being written
CLOCK_SKEW = 300             # an mtime up to this far in the future still counts as just written
REQUEUE_AFTER = 3600         # deferred files older than this go back into the queue
MAX_PAGES = 10
DELIVERED_KEEP = 1000        # delivered comment ids remembered per repository
QUEUE_MARKER = ".github-events-queue"
REPO_NAME = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
ISSUE_URL_NUMBER = re.compile(r"/issues/(\d+)$")


class GitHubError(Exception):
    """A token, HTTP or network failure. The message never holds the token."""


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
    """Move path into dest with os.replace (a symlink moves as a link), adding -1, -2... on a name
    collision. With data, the moved file is then rewritten as that JSON, atomically, in dest."""
    dest.mkdir(parents=True, exist_ok=True)
    stem, suffix = (path.stem, path.suffix) if path.suffix == ".json" else (path.name, "")
    target, i = dest / path.name, 0
    while os.path.lexists(target):
        i += 1
        target = dest / f"{stem}-{i}{suffix}"
    os.replace(path, target)
    if data is not None:
        try:
            write_json_atomic(target, data)
        except OSError as e:
            log(f"queue: moved {path.name} to {dest} but could not update it ({e})")
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
    ev = json.loads(path.read_text())
    if not isinstance(ev, dict) or ev.get("kind") != "command":
        return None
    repo, n = ev.get("repo"), ev.get("number")
    if repo is not None and not (isinstance(repo, str) and REPO_NAME.match(repo)):
        return None
    if n is not None and (isinstance(n, bool) or not isinstance(n, int) or n < 1):
        return None
    if n is not None and repo is None:
        return None
    if parse_time(ev.get("received_at")) is None:
        return None
    return ev


# ---------------------------------------------------------------- state

def load_state(path, dry_run):
    try:
        raw = path.read_text()
    except FileNotFoundError:
        return {"repos": {}, "delivered": {}}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("repos", {}), dict) \
                or not isinstance(data.get("delivered", {}), dict):
            raise ValueError("not an object with a repos object")
    except ValueError as e:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        dest = path.with_name(f"{path.name}.corrupt-{stamp}")
        if dry_run:
            log(f"state: {path} is malformed ({e}); would move it to {dest.name} and start empty")
        else:
            os.replace(path, dest)
            log(f"state: {path} is malformed ({e}); moved it to {dest.name} and started empty")
        return {"repos": {}, "delivered": {}}
    repos = {k: v for k, v in data.get("repos", {}).items()
             if isinstance(k, str) and isinstance(v, int) and not isinstance(v, bool)}
    delivered = {}
    for k, v in data.get("delivered", {}).items():
        if isinstance(k, str) and isinstance(v, list):
            delivered[k] = [i for i in v if isinstance(i, int) and not isinstance(i, bool)]
    return {"repos": repos, "delivered": delivered}


def already_handled(state, key, cid):
    """True when comment cid was delivered before. Ids are remembered per repository, so a comment held
    back by a deferred event is still delivered after a later event moved last_id past it. Ids older than
    the oldest remembered one fall back to the last_id watermark."""
    done = state["delivered"].get(key, [])
    if cid in done:
        return True
    last = state["repos"].get(key, 0)
    floor = min(done) if done else None
    return cid <= last and (floor is None or cid < floor)


def mark_delivered(state, key, cid):
    done = state["delivered"].setdefault(key, [])
    done.append(cid)
    state["delivered"][key] = sorted(set(done))[-DELIVERED_KEEP:]
    state["repos"][key] = max(state["repos"].get(key, 0), cid)


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
        """Every page of a list endpoint, following Link rel="next" on the same API host only."""
        url = f"{self.base}{path}?{urllib.parse.urlencode(params)}"
        pages = []
        for _ in range(MAX_PAGES):
            headers = {"Authorization": f"Bearer {self.token()}", "Accept": "application/vnd.github+json",
                       "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "openclaw-gh-command-drain"}
            status, hdrs, body = self.http_get(url, headers)
            if status != 200:
                msg = ""
                try:
                    msg = str(json.loads(body).get("message", ""))[:200]
                except (ValueError, AttributeError):
                    pass
                raise GitHubError(f"GET {path} failed: HTTP {status}{': ' + msg if msg else ''}")
            try:
                pages.append(json.loads(body))
            except ValueError:
                raise GitHubError(f"GET {path} returned a body that is not JSON") from None
            url = next_link(hdrs.get("link"))
            if not url:
                break
            if not url.startswith(self.base + "/"):
                raise GitHubError(f"GET {path}: next page points outside {self.base}")
        return pages

    def installation_repos(self):
        repos = []
        for page in self.get_pages("/installation/repositories", {"per_page": 100}):
            if not isinstance(page, dict) or not isinstance(page.get("repositories"), list):
                raise GitHubError("GET /installation/repositories returned an unexpected shape")
            repos += [r["full_name"] for r in page["repositories"]
                      if isinstance(r, dict) and isinstance(r.get("full_name"), str)
                      and REPO_NAME.match(r["full_name"])]
        return repos

    def comments(self, repo, number, since):
        if number is not None:
            path, params = f"/repos/{repo}/issues/{number}/comments", {"per_page": 100, "since": since}
        else:
            path = f"/repos/{repo}/issues/comments"
            params = {"sort": "created", "direction": "desc", "per_page": 100, "since": since}
        out = []
        for page in self.get_pages(path, params):
            if not isinstance(page, list):
                raise GitHubError(f"GET {path} returned an unexpected shape")
            out += [c for c in page if isinstance(c, dict)]
        return out


def select(comments, repo, window_start, state):
    """Trusted @openclaw comments created in the window and not yet delivered, oldest first.
    Each item is (comment id, repo, issue number, html_url, body)."""
    picked = {}
    for c in comments:
        user, cid, body = c.get("user"), c.get("id"), c.get("body")
        if not isinstance(user, dict) or user.get("login") != TRUSTED_LOGIN or user.get("type") != "User":
            continue
        if isinstance(cid, bool) or not isinstance(cid, int) or not isinstance(body, str):
            continue
        if MENTION not in body.lower():
            continue
        created = parse_time(c.get("created_at"))
        if created is None or created < window_start:
            continue
        m = ISSUE_URL_NUMBER.search(str(c.get("issue_url", "")))
        url = c.get("html_url")
        if not m or not isinstance(url, str):
            continue
        if already_handled(state, repo.lower(), cid):
            continue
        picked[cid] = (cid, repo, int(m.group(1)), url, body)
    return [picked[k] for k in sorted(picked)]


# ---------------------------------------------------------------- agent

def message_text(repo, number, url, body):
    return (f"Verified GitHub command from {TRUSTED_LOGIN} (the drain checked the author with the GitHub API).\n"
            f"Comment: {url}\nOn: {repo}#{number}\n\n{body}")


def wake_agent(text, run):
    """Run `openclaw agent` with the message in a private file. True when it exits 0."""
    tmpdir = tempfile.mkdtemp(prefix="openclaw-gh-command-")
    try:
        path = os.path.join(tmpdir, "message.txt")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(text)
        argv = [os.environ.get("OPENCLAW_BIN") or "openclaw", "agent", "--agent", "ops",
                "--message-file", path, "--deliver", "--reply-channel", "slack",
                "--reply-to", f"channel:{REPLY_CHANNEL}", "--timeout", str(AGENT_TIMEOUT)]
        try:
            r = run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=AGENT_KILL_AFTER)
        except subprocess.TimeoutExpired:
            log(f"agent: openclaw agent timed out after {AGENT_KILL_AFTER}s")
            return False
        except OSError as e:
            log(f"agent: could not run openclaw ({e.strerror or e})")
            return False
        if r.returncode != 0:
            tail = (r.stderr or "").strip()[-300:]
            log(f"agent: openclaw agent exited {r.returncode}{': ' + tail if tail else ''}")
            return False
        return True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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
        log(f"queue: {'would ' + verb if dry_run else verb} {path.name}: {why}")
        if not dry_run:
            try:
                fn()
            except FileNotFoundError:
                pass

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
        since = window_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            repos = [ev["repo"]] if ev["repo"] is not None else gh.installation_repos()
            picked = []
            for repo in repos:
                picked += select(gh.comments(repo, ev["number"], since), repo, window_start, state)
        except GitHubError as e:
            log(f"github: {path.name}: {e}")
            defer(path, ev, "GitHub lookup failed")
            continue
        picked.sort()
        ok = True
        for cid, repo, number, url, body in picked:
            if dry_run:
                log(f"agent: would wake the ops agent for {url}")
                continue
            log(f"agent: waking the ops agent for {url}")
            if not wake_agent(message_text(repo, number, url, body), run):
                ok = False
                break
            mark_delivered(state, repo.lower(), cid)
            write_json_atomic(state_path, state)
        if not ok:
            defer(path, ev, "ops agent run failed")
            continue
        found = f"{len(picked)} verified comment{'s' if len(picked) != 1 else ''}"
        act("delete", path, f"handled, {found}", lambda: os.unlink(path))
    return 1 if failed else 0


def main(argv=None, http_get=None, run=None):
    ap = argparse.ArgumentParser(prog="openclaw-gh-command-drain",
                                 description="Verify queued @openclaw GitHub commands and wake the ops agent.")
    ap.add_argument("--queue", default=None, help="queue directory (default ~/.local/state/github-events/ops)")
    ap.add_argument("--dry-run", action="store_true", help="read and log only: no agent runs, moves or state writes")
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
        if not qdir.exists():
            return 0
        now = time.time()
        if not args.dry_run:
            requeue_deferred(qdir, now)
        return drain(qdir, args.dry_run, GitHub(http_get, run), run, now)


if __name__ == "__main__":
    sys.exit(main())
