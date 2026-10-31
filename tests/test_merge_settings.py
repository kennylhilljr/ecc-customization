"""lib/ecctools.py merge-settings and machine/ops/workspace-ops.settings.json.

Run from the repository root: python3 -m unittest discover -s tests
Everything runs against temporary folders; nothing touches the real home.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")
FRAGMENT = os.path.join(ROOT, "machine", "ops", "workspace-ops.settings.json")


def merge(target, home, *extra, source=FRAGMENT):
    return subprocess.run(
        [sys.executable, LIB, "merge-settings", "--source", source, "--target", target,
         "--home", home, *extra],
        capture_output=True, text=True)


class TrackedFragment(unittest.TestCase):
    def test_owner_decisions(self):
        with open(FRAGMENT) as fh:
            data = json.load(fh)
        env = data["env"]
        self.assertEqual(env["GATEGUARD_BASH_ROUTINE_DISABLED"], "1")
        globs = env["GATEGUARD_EXEMPT_GLOBS"].split(",")
        for g in ("docs/**", "**/*.md", "tests/**"):
            self.assertIn(g, globs)
        allow = data["sandbox"]["filesystem"]["allowWrite"]
        self.assertIn("__GITHUB_DIR__/*/.git", allow)
        self.assertEqual(sorted(data), ["env", "sandbox"])


class MergeSettings(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home with space")
        os.makedirs(self.home)
        self.target = os.path.join(self.home, ".openclaw", "workspace-ops", ".claude", "settings.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write_target(self, data):
        os.makedirs(os.path.dirname(self.target), exist_ok=True)
        with open(self.target, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data, indent=2))

    def read_bytes(self):
        with open(self.target, "rb") as fh:
            return fh.read()

    def test_absent_target_gets_fragment_with_home_expanded(self):
        r = merge(self.target, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read_bytes().decode()
        self.assertNotIn("__", text)
        self.assertNotIn("$HOME", text)
        data = json.loads(text)
        gh = os.path.join(self.home, "Documents", "GitHub")
        self.assertEqual(data["sandbox"]["filesystem"]["allowWrite"],
                         [f"{gh}/*/.git", f"{gh}/*/.git/**"])
        self.assertIn(f"{gh}/**/*.md", data["env"]["GATEGUARD_EXEMPT_GLOBS"].split(","))
        self.assertEqual(data["env"]["GATEGUARD_BASH_ROUTINE_DISABLED"], "1")

    def test_github_dir_option(self):
        gh = os.path.join(self.tmp.name, "src dir")
        r = merge(self.target, self.home, "--github-dir", gh)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self.read_bytes())
        self.assertIn(f"{gh}/*/.git", data["sandbox"]["filesystem"]["allowWrite"])

    def test_foreign_keys_kept_and_owned_keys_enforced(self):
        gh = os.path.join(self.home, "Documents", "GitHub")
        self.write_target({
            "model": "opus",
            "permissions": {"deny": ["Bash(git push --force *)"]},
            "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
            "env": {"GATEGUARD_BASH_ROUTINE_DISABLED": "0", "FOO": "bar"},
            "sandbox": {"enabled": True, "filesystem": {
                "allowWrite": ["/tmp/other/**", f"{gh}/*/.git"],
                "denyRead": ["~/.ssh"], "denyWrite": ["./.env*"]}},
        })
        r = merge(self.target, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        data = json.loads(self.read_bytes())
        self.assertEqual(data["model"], "opus")
        self.assertEqual(data["permissions"], {"deny": ["Bash(git push --force *)"]})
        self.assertEqual(data["hooks"], {"PreToolUse": [{"matcher": "Bash"}]})
        self.assertEqual(data["env"]["FOO"], "bar")
        self.assertEqual(data["env"]["GATEGUARD_BASH_ROUTINE_DISABLED"], "1")
        fs = data["sandbox"]["filesystem"]
        self.assertTrue(data["sandbox"]["enabled"])
        self.assertEqual(fs["allowWrite"], ["/tmp/other/**", f"{gh}/*/.git", f"{gh}/*/.git/**"])
        self.assertEqual(fs["denyRead"], ["~/.ssh"])
        self.assertEqual(fs["denyWrite"], ["./.env*", f"{gh}/*/.git/hooks"])

    def test_second_run_writes_nothing(self):
        self.write_target({"model": "opus"})
        self.assertEqual(merge(self.target, self.home).returncode, 0)
        first = self.read_bytes()
        os.utime(self.target, ns=(1_000_000_000, 1_000_000_000))
        r = merge(self.target, self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already up to date", r.stdout)
        self.assertEqual(self.read_bytes(), first)
        self.assertEqual(os.stat(self.target).st_mtime_ns, 1_000_000_000)

    def test_dry_run_changes_nothing(self):
        r = merge(self.target, self.home, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would add env", r.stdout)
        self.assertFalse(os.path.exists(self.target))
        self.write_target({"env": {"GATEGUARD_BASH_ROUTINE_DISABLED": "0"}})
        before = self.read_bytes()
        r = merge(self.target, self.home, "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("would set env.GATEGUARD_BASH_ROUTINE_DISABLED", r.stdout)
        self.assertEqual(self.read_bytes(), before)

    def test_bad_targets_are_refused_and_left_alone(self):
        for bad in ("{not json", "[1, 2]", json.dumps({"sandbox": ["x"]}),
                    json.dumps({"env": {"GATEGUARD_EXEMPT_GLOBS": ["a"]}}),
                    json.dumps({"sandbox": {"filesystem": {"allowWrite": "/tmp"}}})):
            with self.subTest(target=bad):
                self.write_target(bad)
                r = merge(self.target, self.home)
                self.assertEqual(r.returncode, 2)
                self.assertIn("left as is", r.stderr)
                self.assertEqual(self.read_bytes().decode(), bad)
                self.assertFalse(os.path.exists(self.target + ".ecc-tmp"))

    def test_unknown_placeholder_is_refused(self):
        src = os.path.join(self.tmp.name, "fragment.json")
        with open(src, "w") as fh:
            json.dump({"env": {"X": "__NOT_A_TOKEN__/y"}}, fh)
        r = merge(self.target, self.home, source=src)
        self.assertEqual(r.returncode, 2)
        self.assertIn("__NOT_A_TOKEN__", r.stderr)
        self.assertFalse(os.path.exists(self.target))


if __name__ == "__main__":
    unittest.main()
