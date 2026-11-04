"""lib/gh_command_drain.py with a fake GitHub API, a fake token command and a
fake `openclaw` command: no network, no real credentials, temporary folders.

Run from the repository root: python3 -m unittest discover -s tests
"""
import contextlib
import importlib.util
import io
import json
import os
import subprocess
import tempfile
import time
import unittest
import re
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WRAPPER = os.path.join(ROOT, "bin", "openclaw-gh-command-drain")
MENTION_CASES = os.path.join(ROOT, "openclaw-plugins", "github-event-router", "tests", "fixtures", "mention-cases.json")
spec = importlib.util.spec_from_file_location("gh_command_drain", os.path.join(ROOT, "lib", "gh_command_drain.py"))
drain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(drain)

TOKEN = "fake-installation-token-for-tests"
API = "https://api.example.test"
RECEIVED = "2026-11-04T01:02:03.123Z"
IN_WINDOW = "2026-11-04T01:01:00Z"
BEFORE_WINDOW = "2026-11-04T00:40:00Z"
FMT = "%Y-%m-%dT%H:%M:%SZ"

FAKE_TOKEN = """#!/bin/sh
[ "${FAKE_TOKEN_EXIT:-0}" = 0 ] || exit "$FAKE_TOKEN_EXIT"
printf '%s\\n' "$FAKE_TOKEN"
"""
FAKE_OPENCLAW = """#!/bin/sh
case "$1" in
  health) echo "$*" >> "$AGENT_LOG.health"; exit "${FAKE_HEALTH_EXIT:-0}" ;;
  message) printf '%s\\n' "$@" > "$AGENT_LOG.alert.$$"; echo "$$" >> "$AGENT_LOG.alerts"
           exit "${FAKE_ALERT_EXIT:-0}" ;;
esac
printf '%s\\n' "$@" > "$AGENT_LOG.argv.$$"
file=""
prev=""
for a in "$@"; do [ "$prev" = --message-file ] && file=$a; prev=$a; done
cat "$file" > "$AGENT_LOG.msg.$$"
ls -l "$file" | cut -c1-10 > "$AGENT_LOG.mode.$$"
echo "$$" >> "$AGENT_LOG"
exit "${FAKE_AGENT_EXIT:-0}"
"""


def comment(cid, body="@openclaw please fix", login="kennylhilljr", type_="User", created=IN_WINDOW,
            repo="octo/app", number=7):
    return {"id": cid, "body": body, "user": {"login": login, "type": type_}, "created_at": created,
            "html_url": f"https://github.com/{repo}/issues/{number}#issuecomment-{cid}",
            "issue_url": f"{API}/repos/{repo}/issues/{number}"}


def review_comment(cid, body="@openclaw fix this line", created=IN_WINDOW, repo="octo/app", number=7, **kw):
    c = comment(cid, body, created=created, repo=repo, number=number, **kw)
    del c["issue_url"]
    c["html_url"] = f"https://github.com/{repo}/pull/{number}#discussion_r{cid}"
    c["pull_request_url"] = f"{API}/repos/{repo}/pulls/{number}"
    return c


def review(rid, body="@openclaw address these", submitted=IN_WINDOW, repo="octo/app", number=7, **kw):
    c = review_comment(rid, body, repo=repo, number=number, **kw)
    del c["created_at"]
    c["submitted_at"] = submitted
    c["html_url"] = f"https://github.com/{repo}/pull/{number}#pullrequestreview-{rid}"
    return c


class Paged:
    """A route answered over several pages, with Link rel="next" headers."""

    def __init__(self, pages):
        self.pages = pages


class FakeGitHub:
    """Answers by request path. routes maps a path to a JSON value, a Paged, or an int HTTP status."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers):
        parts = urllib.parse.urlsplit(url)
        self.calls.append((parts.path, dict(urllib.parse.parse_qsl(parts.query)), headers))
        reply = self.routes.get(parts.path, 404)
        if isinstance(reply, int):
            return reply, {}, json.dumps({"message": "Not Found"}).encode()
        if isinstance(reply, Paged):
            page = int(dict(urllib.parse.parse_qsl(parts.query)).get("page", "1"))
            hdrs = {}
            if page < len(reply.pages):
                hdrs["link"] = f'<{API}{parts.path}?per_page=100&page={page + 1}>; rel="next"'
            return 200, hdrs, json.dumps(reply.pages[page - 1]).encode()
        return 200, {}, json.dumps(reply).encode()


class DrainTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = self.tmp.name
        self.home = os.path.join(t, "home")
        self.root = os.path.join(self.home, ".local/state/github-events")
        self.queue = os.path.join(self.root, "ops")
        self.deferred = os.path.join(self.root, "ops-deferred")
        self.rejected = os.path.join(self.root, "ops-rejected")
        self.state_dir = os.path.join(t, "state")
        self.state = os.path.join(self.state_dir, "state.json")
        os.makedirs(self.queue)
        with open(os.path.join(self.root, ".github-events-queue"), "w"):
            pass
        fake = os.path.join(t, "fakebin")
        os.makedirs(fake)
        self.token_cmd = os.path.join(fake, "openclaw-gh-app-token")
        self.openclaw = os.path.join(fake, "openclaw")
        for path, body in ((self.token_cmd, FAKE_TOKEN), (self.openclaw, FAKE_OPENCLAW)):
            with open(path, "w") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        self.agent_log = os.path.join(t, "agent")
        self.env = {
            "HOME": self.home, "OPENCLAW_GH_COMMAND_STATE_DIR": self.state_dir,
            "OPENCLAW_GH_APP_TOKEN_CMD": self.token_cmd, "OPENCLAW_BIN": self.openclaw,
            "GITHUB_API_URL": API, "FAKE_TOKEN": TOKEN, "AGENT_LOG": self.agent_log,
            "FAKE_AGENT_EXIT": "0", "FAKE_TOKEN_EXIT": "0",
        }
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def event(self, repo="octo/app", number=7, name=None, **extra):
        self.n += 1
        ev = {"kind": "command", "repo": repo, "number": number,
              "target_kind": "issue" if number else None, "received_at": RECEIVED,
              "slack_message_id": "1730643302.123456", "slack_channel": "C0CEMPH1L0N",
              "source": "github-event-router", "version": 1}
        ev.update(extra)
        path = os.path.join(self.queue, name or f"20261104T010203123Z-{self.n}-command-abc.json")
        with open(path, "w") as fh:
            json.dump(ev, fh)
        return path

    def run_drain(self, *args, routes=None, env=None, run=None):
        gh = FakeGitHub(routes or {})
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, dict(self.env, **(env or {}))):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = drain.main(list(args), http_get=gh, run=run)
        self.output = out.getvalue() + err.getvalue()
        self.assertNotIn(TOKEN, self.output)
        return code, gh

    def agent_runs(self):
        """[(argv, message, mode)] for each fake openclaw run, in order."""
        if not os.path.exists(self.agent_log):
            return []
        def read(path):
            with open(path) as fh:
                return fh.read()
        runs = []
        for pid in read(self.agent_log).split():
            base = f"{self.agent_log}.%s.{pid}"
            runs.append((read(base % "argv").splitlines(), read(base % "msg"), read(base % "mode").strip()))
        return runs

    def delivered(self, repo="octo/app"):
        return list(self.load_state()["delivered"].get(repo, {}))

    def health_checks(self):
        p = f"{self.agent_log}.health"
        if not os.path.exists(p):
            return []
        with open(p) as fh:
            return fh.read().splitlines()

    def alerts(self):
        """[argv] for each fake `openclaw message send`, in order."""
        p = f"{self.agent_log}.alerts"
        if not os.path.exists(p):
            return []
        out = []
        with open(p) as fh:
            for pid in fh.read().split():
                with open(f"{self.agent_log}.alert.{pid}") as a:
                    out.append(a.read().splitlines())
        return out

    def listing(self, d):
        return sorted(os.listdir(d)) if os.path.isdir(d) else []

    def load_state(self):
        with open(self.state) as fh:
            return json.load(fh)

    # ---- queue safety
    def assert_refused(self, *args):
        before = {d: self.listing(d) for d in (self.queue, self.deferred, self.rejected)}
        code, gh = self.run_drain(*args)
        self.assertEqual(code, 2, self.output)
        self.assertIn("refusing", self.output)
        self.assertEqual(gh.calls, [])
        self.assertEqual(before, {d: self.listing(d) for d in (self.queue, self.deferred, self.rejected)})
        self.assertEqual(self.agent_runs(), [])

    def test_refuses_unmarked_directory(self):
        other = os.path.join(self.tmp.name, "elsewhere", "ops")
        os.makedirs(other)
        with open(os.path.join(other, "x.json"), "w") as fh:
            fh.write("{}")
        self.assert_refused("--queue", other)
        self.assertEqual(os.listdir(other), ["x.json"])

    def test_refuses_symlinked_queue(self):
        link = os.path.join(self.root, "ops-link")
        os.symlink(self.queue, link)
        self.assert_refused("--queue", link)

    def test_refuses_queue_that_is_a_file(self):
        f = os.path.join(self.root, "notdir")
        open(f, "w").close()
        self.assert_refused("--queue", f)

    def test_refuses_marker_that_is_a_symlink(self):
        other = os.path.join(self.tmp.name, "other")
        os.makedirs(os.path.join(other, "ops"))
        os.symlink(os.path.join(self.root, ".github-events-queue"), os.path.join(other, ".github-events-queue"))
        self.assert_refused("--queue", os.path.join(other, "ops"))

    def test_refuses_symlinked_side_directories(self):
        elsewhere = os.path.join(self.tmp.name, "elsewhere")
        os.makedirs(elsewhere)
        for kind in ("deferred", "rejected"):
            with self.subTest(kind=kind):
                side = os.path.join(self.root, f"ops-{kind}")
                os.symlink(elsewhere, side)
                self.event()
                self.assert_refused()
                os.unlink(side)

    def test_missing_default_queue_is_quiet(self):
        os.rmdir(self.queue)
        code, gh = self.run_drain()
        self.assertEqual(code, 0)
        self.assertEqual(self.output, "")
        self.assertFalse(os.path.exists(self.queue))

    def test_lock_held_exits_zero(self):
        self.event()
        os.makedirs(self.state_dir)
        import fcntl
        with open(os.path.join(self.state_dir, "drain.lock"), "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            code, gh = self.run_drain()
        self.assertEqual(code, 0)
        self.assertEqual(gh.calls, [])
        self.assertEqual(len(self.listing(self.queue)), 1)

    # ---- entries
    def test_stray_entries_rejected(self):
        os.makedirs(os.path.join(self.queue, "subdir"))
        open(os.path.join(self.queue, ".hidden.json"), "w").close()
        open(os.path.join(self.queue, "notes.txt"), "w").close()
        target = os.path.join(self.tmp.name, "target.json")
        with open(target, "w") as fh:
            fh.write("{}")
        os.symlink(target, os.path.join(self.queue, "link.json"))
        with open(os.path.join(self.queue, "other.json"), "w") as fh:
            json.dump({"kind": "pull_request", "repo": "octo/app", "number": 1}, fh)
        with open(os.path.join(self.queue, "badrepo.json"), "w") as fh:
            json.dump({"kind": "command", "repo": "nope", "number": None, "received_at": RECEIVED}, fh)
        with open(os.path.join(self.queue, "badnum.json"), "w") as fh:
            json.dump({"kind": "command", "repo": "octo/app", "number": 0, "received_at": RECEIVED}, fh)
        code, gh = self.run_drain()
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.listing(self.queue), [])
        self.assertEqual(self.listing(self.rejected),
                         [".hidden.json", "badnum.json", "badrepo.json", "link.json", "notes.txt",
                          "other.json", "subdir"])
        self.assertTrue(os.path.islink(os.path.join(self.rejected, "link.json")))
        self.assertTrue(os.path.exists(target))
        self.assertEqual(gh.calls, [])

    def test_young_partial_file_kept_old_one_rejected(self):
        young = os.path.join(self.queue, "young.json")
        old = os.path.join(self.queue, "old.json")
        for p in (young, old):
            with open(p, "w") as fh:
                fh.write('{"kind": "comm')
        os.utime(old, (time.time() - 60, time.time() - 60))
        code, _ = self.run_drain()
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.listing(self.queue), ["young.json"])
        self.assertEqual(self.listing(self.rejected), ["old.json"])

    # ---- verification and delivery
    def test_trusted_comment_wakes_agent(self):
        path = self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(105, "Hey @OpenClaw rebase this\nplease")]}
        code, gh = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.listing(self.deferred), [])
        (argv, msg, mode), = self.agent_runs()
        self.assertEqual(msg, "Verified GitHub command from kennylhilljr (the drain checked the author with the "
                              "GitHub API).\nComment: https://github.com/octo/app/issues/7#issuecomment-105\n"
                              "On: octo/app#7\n\nHey @OpenClaw rebase this\nplease")
        self.assertEqual(mode, "-rw-------")
        self.assertEqual(argv[:4], ["agent", "--agent", "ops", "--message-file"])
        self.assertEqual(argv[5:], ["--deliver", "--reply-channel", "slack", "--reply-to",
                                    "channel:C0CEMPH1L0N", "--timeout", "600"])
        self.assertFalse(os.path.exists(argv[4]))
        self.assertFalse(os.path.exists(os.path.dirname(argv[4])))
        self.assertEqual(self.load_state()["delivered"], {"octo/app": {"issue_comment:105": {"time": IN_WINDOW}}})
        self.assertEqual(self.health_checks(), ["health --timeout 5000"])
        self.assertEqual(self.alerts(), [])
        self.assertEqual(os.stat(self.state).st_mode & 0o777, 0o600)
        (p, q, headers), = gh.calls
        self.assertEqual(q, {"per_page": "100", "since": "2026-11-04T00:47:03Z"})
        self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
        self.assertEqual(headers["Accept"], "application/vnd.github+json")
        self.assertEqual(headers["X-GitHub-Api-Version"], "2022-11-28")
        # a second command for the same issue does not repeat the delivered comment
        self.event()
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(len(self.agent_runs()), 1)

    def test_untrusted_comments_ignored(self):
        path = self.event()
        os.makedirs(self.state_dir)
        with open(self.state, "w") as fh:
            json.dump({"delivered": {"octo/app": {"issue_comment:40": {"time": IN_WINDOW}}}}, fh)
        routes = {"/repos/octo/app/issues/7/comments": [
            comment(101, login="kennylhilljr-evil"),
            comment(102, login="KennyLHillJr"),
            comment(103, type_="Bot"),
            comment(104, body="please fix this"),
            comment(40),
            comment(106, created=BEFORE_WINDOW),
            {"id": 107, "body": "@openclaw", "user": "kennylhilljr"},
        ]}
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertFalse(os.path.exists(path))
        self.assertEqual(self.agent_runs(), [])
        self.assertEqual(self.delivered(), ["issue_comment:40"])

    def test_comments_delivered_oldest_first(self):
        self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(120, "@openclaw second"),
                                                         comment(110, "@openclaw first")]}
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual([m.rsplit("\n", 1)[1] for _, m, _ in self.agent_runs()],
                         ["@openclaw first", "@openclaw second"])
        self.assertEqual(self.delivered(), ["issue_comment:110", "issue_comment:120"])

    def test_number_null_uses_repo_wide_endpoint(self):
        self.event(number=None)
        routes = {"/repos/octo/app/issues/comments": [comment(130, number=9)],
                  "/repos/octo/app/pulls/comments": [review_comment(131, number=4)]}
        code, gh = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual([c[0] for c in gh.calls], ["/repos/octo/app/issues/comments",
                                                    "/repos/octo/app/pulls/comments"])
        for _, q, _ in gh.calls:
            self.assertEqual(q, {"sort": "created", "direction": "desc", "per_page": "100",
                                 "since": "2026-11-04T00:47:03Z"})
        msgs = [m for _, m, _ in self.agent_runs()]
        self.assertEqual(len(msgs), 2)
        self.assertIn("\nOn: octo/app#9\n", msgs[0])
        self.assertIn("\nOn: octo/app#4\n", msgs[1])

    def test_repo_null_lists_installation_repos(self):
        self.event(repo=None, number=None)
        routes = {
            "/installation/repositories": {"total_count": 2, "repositories": [
                {"full_name": "octo/app"}, {"full_name": "octo/lib"}]},
            "/repos/octo/app/issues/comments": [comment(150, repo="octo/app", number=1)],
            "/repos/octo/lib/issues/comments": [comment(140, repo="octo/lib", number=2)],
            "/repos/octo/app/pulls/comments": [], "/repos/octo/lib/pulls/comments": [],
        }
        code, gh = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual([c[0] for c in gh.calls], ["/installation/repositories",
                                                    "/repos/octo/app/issues/comments",
                                                    "/repos/octo/app/pulls/comments",
                                                    "/repos/octo/lib/issues/comments",
                                                    "/repos/octo/lib/pulls/comments"])
        self.assertEqual(gh.calls[0][1], {"per_page": "100"})
        msgs = [m for _, m, _ in self.agent_runs()]
        self.assertIn("On: octo/lib#2", msgs[0])
        self.assertIn("On: octo/app#1", msgs[1])
        self.assertEqual(self.delivered("octo/app"), ["issue_comment:150"])
        self.assertEqual(self.delivered("octo/lib"), ["issue_comment:140"])

    # ---- pull request sources
    def test_pull_request_review_comment_and_review_body(self):
        self.event(target_kind="pull_request")
        routes = {
            "/repos/octo/app/issues/7/comments": [comment(300, created="2026-11-04T01:00:00Z")],
            "/repos/octo/app/pulls/7/comments": [review_comment(300, created="2026-11-04T01:00:30Z"),
                                                 review_comment(301, login="someone")],
            "/repos/octo/app/pulls/7/reviews": [review(300, submitted="2026-11-04T01:01:30Z"),
                                                review(302, body=""), review(303, body="looks good"),
                                                review(304, submitted=BEFORE_WINDOW),
                                                review(305, submitted=None)],
        }
        code, gh = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual([c[0] for c in gh.calls], ["/repos/octo/app/issues/7/comments",
                                                    "/repos/octo/app/pulls/7/comments",
                                                    "/repos/octo/app/pulls/7/reviews"])
        self.assertEqual(gh.calls[2][1], {"per_page": "100"})
        msgs = [m for _, m, _ in self.agent_runs()]
        self.assertEqual(len(msgs), 3)  # the same id 300 in each source is three different comments
        self.assertIn("Comment: https://github.com/octo/app/issues/7#issuecomment-300\n", msgs[0])
        self.assertIn("Comment: https://github.com/octo/app/pull/7#discussion_r300\nOn: octo/app#7\n\n"
                      "@openclaw fix this line", msgs[1])
        self.assertIn("Comment: https://github.com/octo/app/pull/7#pullrequestreview-300\nOn: octo/app#7\n\n"
                      "@openclaw address these", msgs[2])
        state = self.load_state()
        self.assertEqual(list(state["delivered"]["octo/app"]),
                         ["issue_comment:300", "review_comment:300", "review:300"])
        self.assertEqual(state["pending"], {})
        # nothing is delivered twice
        self.event(target_kind="pull_request")
        self.run_drain(routes=routes)
        self.assertEqual(len(self.agent_runs()), 3)

    def test_unknown_target_kind_treats_404_as_issue(self):
        path = self.event(target_kind=None)
        routes = {"/repos/octo/app/issues/7/comments": [comment(310)]}
        code, gh = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertFalse(os.path.exists(path))
        self.assertEqual([c[0] for c in gh.calls], ["/repos/octo/app/issues/7/comments",
                                                    "/repos/octo/app/pulls/7/comments"])
        self.assertEqual(len(self.agent_runs()), 1)

    def test_pull_request_404_defers(self):
        path = self.event(target_kind="pull_request")
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": []})
        self.assertEqual(code, 1)
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])

    def test_integer_state_ids_migrate_to_issue_comments(self):
        os.makedirs(self.state_dir)
        with open(self.state, "w") as fh:
            json.dump({"repos": {"octo/app": 320}, "delivered": {"octo/app": [320]}}, fh)
        self.event(target_kind="pull_request")
        routes = {"/repos/octo/app/issues/7/comments": [comment(320)],
                  "/repos/octo/app/pulls/7/comments": [review_comment(320)],
                  "/repos/octo/app/pulls/7/reviews": []}
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        (_, msg, _), = self.agent_runs()
        self.assertIn("#discussion_r320", msg)
        self.assertEqual(self.delivered(), ["issue_comment:320", "review_comment:320"])
        self.assertNotIn("repos", self.load_state())

    def test_too_many_pages_defers(self):
        path = self.event()
        pages = [[comment(400 + i)] for i in range(drain.MAX_PAGES + 1)]
        code, gh = self.run_drain(routes={"/repos/octo/app/issues/7/comments": Paged(pages)})
        self.assertEqual(code, 1)
        self.assertEqual(len(gh.calls), drain.MAX_PAGES)
        self.assertIn(f"more than {drain.MAX_PAGES} pages", self.output)
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])
        self.assertEqual(self.agent_runs(), [])

    def test_pages_followed(self):
        self.event()
        pages = [[comment(410)], [comment(411)]]
        code, gh = self.run_drain(routes={"/repos/octo/app/issues/7/comments": Paged(pages)})
        self.assertEqual(code, 0, self.output)
        self.assertEqual(len(self.agent_runs()), 2)

    # ---- the delivery journal
    def test_journal_write_failure_defers_without_invoking(self):
        path = self.event()
        real = drain.write_json_atomic

        def failing(target, data, *a, **kw):
            if os.path.basename(str(target)) == "state.json":
                raise OSError(28, "No space left on device")
            return real(target, data, *a, **kw)
        with mock.patch.object(drain, "write_json_atomic", failing):
            code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(500)]})
        self.assertEqual(code, 1)
        self.assertEqual(self.agent_runs(), [])
        self.assertIn("could not record the pending run", self.output)
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])
        self.assertFalse(os.path.exists(self.state))

    def run_crashing(self, routes):
        """A drain run whose process dies right after `openclaw agent` returns."""
        def crash(argv, *a, **kw):
            r = subprocess.run(argv, *a, **kw)
            if argv[1:2] == ["agent"]:
                raise KeyboardInterrupt("simulated crash after the agent run")
            return r
        gh = FakeGitHub(routes)
        with mock.patch.dict(os.environ, self.env), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(KeyboardInterrupt):
                drain.main([], http_get=gh, run=crash)

    def test_crash_after_invoke_is_not_repeated(self):
        path = self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(510)]}
        self.run_crashing(routes)
        self.assertEqual(len(self.agent_runs()), 1)
        self.assertTrue(os.path.exists(path))  # the event stayed in the queue
        pending = self.load_state()["pending"]["octo/app"]["issue_comment:510"]
        self.assertEqual(pending["url"], "https://github.com/octo/app/issues/7#issuecomment-510")
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(len(self.agent_runs()), 1)
        self.assertIn("not waking the ops agent again for https://github.com/octo/app/issues/7#issuecomment-510",
                      self.output)
        self.assertFalse(os.path.exists(path))
        # --retry-pending clears the entry, so the next event for the comment delivers it
        self.event()
        code, _ = self.run_drain("--retry-pending", routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertIn("clearing the pending entry", self.output)
        self.assertEqual(len(self.agent_runs()), 2)
        state = self.load_state()
        self.assertEqual(state["pending"], {})
        self.assertEqual(list(state["delivered"]["octo/app"]), ["issue_comment:510"])

    def test_retry_pending_dry_run_keeps_entry(self):
        self.event()
        self.run_crashing({"/repos/octo/app/issues/7/comments": [comment(520)]})
        before = self.load_state()
        code, _ = self.run_drain("--retry-pending", "--dry-run",
                                 routes={"/repos/octo/app/issues/7/comments": [comment(520)]})
        self.assertEqual(code, 0, self.output)
        self.assertIn("would clear the pending entry", self.output)
        self.assertEqual(self.load_state(), before)

    def assert_unknown_outcome_kept_pending(self, detail, **kw):
        path = self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(530), comment(531)]}
        code, _ = self.run_drain(routes=routes, **kw)
        first_output = self.output
        self.assertEqual(code, 1)
        self.assertIn("stays pending", first_output)
        self.assertEqual(len(self.agent_runs()), 1)
        url = "https://github.com/octo/app/issues/7#issuecomment-530"
        self.assertEqual(self.alerts(), [[
            "message", "send", "--channel", "slack", "--target", "channel:C0CERFQ8UJV", "-m",
            f"openclaw-gh-command-drain: the ops agent run for {url} did not finish cleanly ({detail}). "
            f"It was not resent. If nothing was posted, run: openclaw-gh-command-drain --retry-pending"]])
        state = self.load_state()
        self.assertEqual(list(state["pending"]["octo/app"]), ["issue_comment:530"])
        self.assertNotIn("octo/app", state["delivered"])
        name = os.path.basename(path)
        self.assertEqual(self.listing(self.deferred), [name])
        # the retry skips the pending comment, delivers the next one, and finishes the event
        os.replace(os.path.join(self.deferred, name), path)
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertIn("not waking the ops agent again for https://github.com/octo/app/issues/7#issuecomment-530",
                      self.output)
        runs = self.agent_runs()
        self.assertEqual(len(runs), 2)
        self.assertIn("#issuecomment-531", runs[1][1])
        self.assertFalse(os.path.exists(path))
        self.assertEqual(list(self.load_state()["pending"]["octo/app"]), ["issue_comment:530"])
        self.assertEqual(len(self.alerts()), 1)  # skipping a pending comment does not alert again
        return first_output

    def test_nonzero_exit_keeps_pending(self):
        self.assert_unknown_outcome_kept_pending("exit 1", env={"FAKE_AGENT_EXIT": "1"})

    def test_alert_failure_changes_nothing(self):
        out = self.assert_unknown_outcome_kept_pending("exit 4", env={"FAKE_AGENT_EXIT": "4", "FAKE_ALERT_EXIT": "9"})
        self.assertIn("alert: openclaw message send exited 9", out)

    def test_alert_that_cannot_run_or_times_out_changes_nothing(self):
        for exc in (OSError(2, "No such file"), subprocess.TimeoutExpired("openclaw", 60)):
            with self.subTest(exc=type(exc).__name__):
                def alert_breaks(argv, *a, **kw):
                    if argv[1:2] == ["message"]:
                        raise exc
                    return subprocess.run(argv, *a, **kw)
                path = self.event(name=f"{type(exc).__name__}-command.json")
                routes = {"/repos/octo/app/issues/7/comments": [comment(540 + len(self.agent_runs()))]}
                code, _ = self.run_drain(routes=routes, env={"FAKE_AGENT_EXIT": "1"}, run=alert_breaks)
                self.assertEqual(code, 1)
                self.assertIn("alert: ", self.output)
                self.assertIn(os.path.basename(path), self.listing(self.deferred))
                cid = routes["/repos/octo/app/issues/7/comments"][0]["id"]
                self.assertIn(f"issue_comment:{cid}", self.load_state()["pending"]["octo/app"])

    def test_timeout_keeps_pending(self):
        def timing_out(argv, *a, **kw):
            r = subprocess.run(argv, *a, **kw)
            if argv[1:2] == ["agent"]:
                raise subprocess.TimeoutExpired(argv, kw.get("timeout"))
            return r
        out = self.assert_unknown_outcome_kept_pending("timeout", run=timing_out)
        self.assertIn("agent: openclaw agent timed out", out)

    def test_agent_not_started_clears_pending_and_retries(self):
        path = self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(160), comment(161)]}
        def agent_missing(argv, *a, **kw):
            if argv[1:2] == ["agent"]:
                raise FileNotFoundError(2, "No such file or directory")
            return subprocess.run(argv, *a, **kw)
        code, _ = self.run_drain(routes=routes, run=agent_missing)
        self.assertEqual(code, 1)
        self.assertIn("could not run openclaw", self.output)
        self.assertEqual(self.agent_runs(), [])
        self.assertEqual(self.alerts(), [])
        name = os.path.basename(path)
        self.assertEqual(self.listing(self.deferred), [name])
        with open(os.path.join(self.deferred, name)) as fh:
            self.assertEqual(json.load(fh)["attempts"], 1)
        self.assertEqual(self.load_state()["pending"], {})
        self.assertNotIn("octo/app", self.load_state()["delivered"])
        # a later command for the same repository goes first; the deferred one still gets its comments
        self.event()
        routes2 = {"/repos/octo/app/issues/7/comments": [comment(160), comment(161), comment(170)]}
        code, _ = self.run_drain(routes=routes2)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(len(self.agent_runs()), 3)
        os.replace(os.path.join(self.deferred, name), path)
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(len(self.agent_runs()), 3)
        self.assertEqual(self.delivered(), ["issue_comment:160", "issue_comment:161", "issue_comment:170"])
        self.assertEqual(self.listing(self.queue), [])

    # ---- gateway probe
    def test_gateway_unreachable_defers_without_pending(self):
        first = self.event()
        second = self.event()
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(600)]},
                                 env={"FAKE_HEALTH_EXIT": "1"})
        self.assertEqual(code, 1)
        self.assertIn("gateway not reachable", self.output)
        self.assertEqual(self.health_checks(), ["health --timeout 5000"])  # once per run
        self.assertEqual(self.agent_runs(), [])
        self.assertEqual(self.alerts(), [])
        self.assertFalse(os.path.exists(self.state))
        self.assertEqual(self.listing(self.deferred), sorted(os.path.basename(p) for p in (first, second)))

    def test_gateway_probe_that_cannot_run_defers(self):
        path = self.event()
        missing = os.path.join(self.tmp.name, "no-such-openclaw")
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(610)]},
                                 env={"OPENCLAW_BIN": missing})
        self.assertEqual(code, 1)
        self.assertIn("gateway not reachable", self.output)
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])
        self.assertFalse(os.path.exists(self.state))

    def test_gateway_probe_not_run_without_comments(self):
        self.event()
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": []})
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.health_checks(), [])

    # ---- mention matching and the time window
    def test_mention_cases_shared_with_router(self):
        with open(MENTION_CASES) as fh:
            cases = json.load(fh)
        self.assertTrue(cases["match"] and cases["no_match"])
        for text in cases["match"]:
            with self.subTest(match=text):
                self.assertIsNotNone(drain.MENTION.search(text))
        for text in cases["no_match"]:
            with self.subTest(no_match=text):
                self.assertIsNone(drain.MENTION.search(text))

    def test_mention_must_be_whole_handle(self):
        self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(800, "ping @openclawbot"),
                                                         comment(801, "mail me@openclaw.com"),
                                                         comment(802, "ok (@OpenClaw), go")]}
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.delivered(), ["issue_comment:802"])

    def test_retry_hours_later_ignores_newer_comments(self):
        path = self.event()
        os.makedirs(self.deferred)
        deferred = os.path.join(self.deferred, os.path.basename(path))
        os.replace(path, deferred)
        os.utime(deferred, (time.time() - 3 * 3600, time.time() - 3 * 3600))
        routes = {"/repos/octo/app/issues/7/comments": [
            comment(810, "@openclaw three hours later", created="2026-11-04T04:02:03Z"),
            comment(811, "@openclaw just past the slack", created="2026-11-04T01:04:04Z"),
            comment(812, "@openclaw within the slack", created="2026-11-04T01:04:03Z")]}
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.delivered(), ["issue_comment:812"])
        self.assertEqual(self.listing(self.deferred), [])

    # ---- replay of the router's failed-request journal
    def journal_line(self, **extra):
        ev = {"kind": "command", "repo": "octo/app", "number": 7, "target_kind": "issue",
              "received_at": RECEIVED, "slack_message_id": "1730643302.123456", "slack_channel": "C0CEMPH1L0N",
              "source": "github-event-router", "version": 1}
        ev.update(extra)
        return json.dumps(ev)

    def write_journal(self, *lines, name="ops-failed.jsonl"):
        with open(os.path.join(self.root, name), "w") as fh:
            fh.write("".join(line + "\n" for line in lines))

    def replaying(self):
        return [n for n in self.listing(self.root) if n.startswith(".ops-failed.replaying-")]

    def test_replay_publishes_events_and_rejects_bad_lines(self):
        self.write_journal(self.journal_line(), "not json", self.journal_line(number=8, slack_message_id=None),
                           json.dumps({"kind": "command", "repo": "bad"}))
        code, gh = self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})  # so the published events stay visible
        self.assertEqual(code, 1)
        self.assertFalse(os.path.exists(os.path.join(self.root, "ops-failed.jsonl")))
        self.assertEqual(self.replaying(), [])
        names = self.listing(self.deferred)
        self.assertEqual(len(names), 2)
        stamp, tail = drain.compact_timestamp(RECEIVED), r"-command-[0-9a-f]{6}\.json$"
        self.assertEqual(stamp, "20261104T010203123Z")
        for slack_part in ("1730643302_123456", "nots"):
            self.assertTrue(any(re.match("^" + stamp + "-" + slack_part + tail, n) for n in names), slack_part)
        rejected, = self.listing(self.rejected)
        self.assertTrue(re.match(r"^ops-failed-\d{8}T\d{6}Z\.jsonl$", rejected))
        with open(os.path.join(self.rejected, rejected)) as fh:
            self.assertEqual(fh.read(), 'not json\n{"kind": "command", "repo": "bad"}\n')
        self.assertEqual(self.listing(os.path.join(self.root, ".tmp")), [])

    def test_replayed_event_is_drained(self):
        self.write_journal(self.journal_line())
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(820)]})
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.delivered(), ["issue_comment:820"])
        self.assertEqual(self.listing(self.queue), [])

    def test_line_appended_during_replay_survives(self):
        self.write_journal(self.journal_line())
        real = drain.replay_one

        def router_appends(root, qdir, path):
            self.write_journal(self.journal_line(number=9))  # the router starts a fresh journal
            return real(root, qdir, path)
        with mock.patch.object(drain, "replay_one", router_appends):
            self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertEqual(len(self.listing(self.deferred)), 1)
        with open(os.path.join(self.root, "ops-failed.jsonl")) as fh:
            self.assertIn('"number": 9', fh.read())
        self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertFalse(os.path.exists(os.path.join(self.root, "ops-failed.jsonl")))
        self.assertEqual(len(self.listing(self.deferred)), 2)

    def test_publish_failure_keeps_rest_for_next_run(self):
        self.write_journal(self.journal_line(number=1), "garbage", self.journal_line(number=2),
                           self.journal_line(number=3))
        real, calls = drain.publish_event, []

        def fail_second(root, qdir, ev):
            calls.append(ev["number"])
            if len(calls) == 2:
                raise OSError(28, "No space left on device")
            return real(root, qdir, ev)
        with mock.patch.object(drain, "publish_event", fail_second):
            code, _ = self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertEqual(code, 1)
        self.assertIn("could not publish", self.output)
        left, = self.replaying()
        with open(os.path.join(self.root, left)) as fh:
            self.assertEqual([json.loads(line)["number"] for line in fh.read().splitlines()], [2, 3])
        self.assertEqual(len(self.listing(self.rejected)), 1)  # "garbage"
        self.assertEqual(len(self.listing(self.deferred)), 1)
        self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertEqual(self.replaying(), [])
        self.assertEqual(len(self.listing(self.deferred)), 3)
        self.assertEqual(len(self.listing(self.rejected)), 1)

    def test_replay_dry_run_changes_nothing(self):
        self.write_journal(self.journal_line())
        self.write_journal(self.journal_line(), name=".ops-failed.replaying-20261104T000000Z.jsonl")
        before = self.listing(self.root)
        code, _ = self.run_drain("--dry-run")
        self.assertEqual(code, 0, self.output)
        self.assertIn("would replay", self.output)
        self.assertEqual(self.listing(self.root), before)
        self.assertEqual(self.listing(self.queue), [])

    # ---- dedupe by explicit keys only
    def test_deferred_lower_id_on_another_issue_still_delivered(self):
        """Codex review round 9: command comment 100 on issue A is deferred, then comment 105 on issue B
        is delivered; retrying A must still deliver comment 100."""
        a = self.event(number=1, name="a-command.json")
        routes = {"/repos/octo/app/issues/1/comments": [comment(100, "@openclaw on A", number=1)],
                  "/repos/octo/app/issues/2/comments": [comment(105, "@openclaw on B", number=2)]}

        def agent_missing(argv, *args, **kw):
            if argv[1:2] == ["agent"]:
                raise FileNotFoundError(2, "No such file or directory")
            return subprocess.run(argv, *args, **kw)
        code, _ = self.run_drain(routes=routes, run=agent_missing)
        self.assertEqual(code, 1)
        self.assertEqual(self.listing(self.deferred), ["a-command.json"])
        self.event(number=2, name="b-command.json")
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.delivered(), ["issue_comment:105"])
        os.replace(os.path.join(self.deferred, "a-command.json"), a)
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertEqual([m.rsplit("\n", 1)[1] for _, m, _ in self.agent_runs()], ["@openclaw on B", "@openclaw on A"])
        self.assertEqual(self.delivered(), ["issue_comment:105", "issue_comment:100"])
        self.assertEqual(self.listing(self.queue), [])

    def test_delivered_keys_pruned_after_seven_days(self):
        os.makedirs(self.state_dir)
        now = datetime.now(timezone.utc)
        old, recent = (now - timedelta(days=8)).strftime(FMT), (now - timedelta(days=6)).strftime(FMT)
        with open(self.state, "w") as fh:
            json.dump({"repos": {"octo/app": 999},
                       "delivered": {"octo/app": {"issue_comment:1": {"time": old},
                                                  "issue_comment:2": {"time": recent},
                                                  "review:3": {"time": None, "first_seen": old},
                                                  "review:4": {"time": None, "first_seen": recent}},
                                     "octo/lib": [5, "review_comment:6"]}}, fh)
        self.event()
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(700)]})
        self.assertEqual(code, 0, self.output)
        state = self.load_state()
        self.assertNotIn("repos", state)
        self.assertEqual(list(state["delivered"]["octo/app"]), ["issue_comment:2", "review:4", "issue_comment:700"])
        lib = state["delivered"]["octo/lib"]
        self.assertEqual(list(lib), ["issue_comment:5", "review_comment:6"])
        for entry in lib.values():
            self.assertIsNone(entry["time"])
            self.assertLess(now - timedelta(minutes=1), drain.parse_time(entry["first_seen"]))

    # ---- moving with a rewrite
    def test_failed_deferral_write_leaves_source(self):
        path = self.event()
        with open(path) as fh:
            before = fh.read()
        os.makedirs(self.deferred)
        os.chmod(self.deferred, 0o500)
        try:
            code, _ = self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
            listing = os.listdir(self.deferred)
        finally:
            os.chmod(self.deferred, 0o700)
        self.assertEqual(code, 1)
        self.assertIn("could not move to", self.output)
        with open(path) as fh:
            self.assertEqual(fh.read(), before)
        self.assertEqual(listing, [])

    def test_move_into_rewrites_before_removing(self):
        src = os.path.join(self.queue, "x.json")
        with open(src, "w") as fh:
            fh.write('{"attempts": 1}')
        open(os.path.join(self.queue, "y.json"), "w").close()
        dest = drain.Path(self.deferred)
        os.makedirs(dest)
        open(os.path.join(dest, "x.json"), "w").close()
        target = drain.move_into(drain.Path(src), dest, {"attempts": 2})
        self.assertEqual(os.path.basename(target), "x-1.json")
        self.assertFalse(os.path.exists(src))
        with open(target) as fh:
            self.assertEqual(json.load(fh), {"attempts": 2})
        self.assertEqual(os.stat(target).st_mode & 0o777, 0o600)
        self.assertEqual(drain.move_into(drain.Path(os.path.join(self.queue, "y.json")), dest).name, "y.json")

    # ---- failures
    def test_partial_delivery_advances_only_delivered(self):
        self.event()
        routes = {"/repos/octo/app/issues/7/comments": [comment(160), comment(161)]}
        # the first run succeeds, every later one fails
        script = FAKE_OPENCLAW.replace('exit "${FAKE_AGENT_EXIT:-0}"',
                                       '[ -e "$AGENT_LOG.fail" ] && exit 1; touch "$AGENT_LOG.fail"; exit 0')
        with open(self.openclaw, "w") as fh:
            fh.write(script)
        code, _ = self.run_drain(routes=routes)
        self.assertEqual(code, 1)
        state = self.load_state()
        self.assertEqual(list(state["delivered"]["octo/app"]), ["issue_comment:160"])
        self.assertEqual(list(state["pending"]["octo/app"]), ["issue_comment:161"])
        self.assertEqual(len(self.listing(self.deferred)), 1)

    def test_token_failure_defers(self):
        path = self.event()
        code, gh = self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertEqual(code, 1)
        self.assertEqual(gh.calls, [])
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])
        self.assertEqual(self.agent_runs(), [])

    def test_http_error_defers(self):
        path = self.event()
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": 502})
        self.assertEqual(code, 1)
        self.assertIn("HTTP 502", self.output)
        self.assertEqual(self.listing(self.deferred), [os.path.basename(path)])

    def test_twenty_fourth_attempt_is_rejected(self):
        path = self.event(attempts=23)
        bad = self.event(attempts=-5)
        code, _ = self.run_drain(env={"FAKE_TOKEN_EXIT": "1"})
        self.assertEqual(code, 1)
        self.assertEqual(self.listing(self.rejected), [os.path.basename(path)])
        with open(os.path.join(self.rejected, os.path.basename(path))) as fh:
            self.assertEqual(json.load(fh)["attempts"], 24)
        with open(os.path.join(self.deferred, os.path.basename(bad))) as fh:
            self.assertEqual(json.load(fh)["attempts"], 1)

    def test_old_deferred_requeued(self):
        os.makedirs(self.deferred)
        old = self.event(name="old-command.json")
        new = self.event(name="new-command.json")
        for p in (old, new):
            os.replace(p, os.path.join(self.deferred, os.path.basename(p)))
        t = time.time() - 3700
        os.utime(os.path.join(self.deferred, "old-command.json"), (t, t))
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": []})
        self.assertEqual(code, 0, self.output)
        self.assertEqual(self.listing(self.deferred), ["new-command.json"])
        self.assertEqual(self.listing(self.queue), [])  # requeued, then handled in the same run

    def test_dry_run_changes_nothing(self):
        os.makedirs(self.deferred)
        self.event()
        old = os.path.join(self.deferred, "old.json")
        with open(old, "w") as fh:
            fh.write("{}")
        os.utime(old, (time.time() - 7200, time.time() - 7200))
        open(os.path.join(self.queue, "notes.txt"), "w").close()
        os.makedirs(self.state_dir)
        with open(self.state, "w") as fh:
            fh.write("not json")
        before = {d: self.listing(d) for d in (self.queue, self.deferred, self.state_dir)}
        routes = {"/repos/octo/app/issues/7/comments": [comment(180)]}
        code, _ = self.run_drain("--dry-run", routes=routes)
        self.assertEqual(code, 0, self.output)
        self.assertIn("would wake the ops agent", self.output)
        self.assertEqual(self.agent_runs(), [])
        after = {d: self.listing(d) for d in (self.queue, self.deferred, self.state_dir)}
        after[self.state_dir].remove("drain.lock")
        self.assertEqual(before, after)
        self.assertFalse(os.path.exists(self.rejected))
        with open(self.state) as fh:
            self.assertEqual(fh.read(), "not json")

    def test_corrupt_state_quarantined(self):
        self.event()
        os.makedirs(self.state_dir)
        with open(self.state, "w") as fh:
            fh.write("[1, 2]")
        code, _ = self.run_drain(routes={"/repos/octo/app/issues/7/comments": [comment(190)]})
        self.assertEqual(code, 0, self.output)
        self.assertIn("malformed", self.output)
        corrupt = [n for n in os.listdir(self.state_dir) if n.startswith("state.json.corrupt-")]
        self.assertEqual(len(corrupt), 1)
        self.assertEqual(self.delivered(), ["issue_comment:190"])

    def test_token_never_written(self):
        self.event()
        self.event(number=None, name="zz-command.json")
        routes = {"/repos/octo/app/issues/7/comments": [comment(200)], "/repos/octo/app/issues/comments": 500}
        self.run_drain(routes=routes, env={"FAKE_AGENT_EXIT": "1"})
        for d in (self.state_dir, self.deferred, self.rejected, self.queue):
            for n in self.listing(d):
                p = os.path.join(d, n)
                if os.path.isfile(p):
                    with open(p, errors="replace") as fh:
                        self.assertNotIn(TOKEN, fh.read(), p)
        for _, msg, _ in self.agent_runs():
            self.assertNotIn(TOKEN, msg)

    # ---- the wrapper
    def test_wrapper_refuses_and_exits_two(self):
        self.assertEqual(subprocess.run(["sh", "-n", WRAPPER]).returncode, 0)
        other = os.path.join(self.tmp.name, "plain")
        os.makedirs(other)
        env = dict(os.environ, **self.env)
        r = subprocess.run(["/bin/sh", WRAPPER, "--queue", other], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("refusing", r.stderr)


if __name__ == "__main__":
    unittest.main()
