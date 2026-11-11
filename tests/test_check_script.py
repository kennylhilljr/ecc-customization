"""Integration tests for scripts/check.sh.

Each check runs in a copied repository with its own Git index and temporary
home. The copy omits this file so the check script cannot recursively run its
own integration suite.
"""

import hashlib
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHECK = os.path.join(ROOT, "scripts", "check.sh")
LABELS = [
    "unit-tests",
    "bash-syntax",
    "sh-syntax",
    "python-syntax",
    "ecctools-help",
    "kit-help",
    "bootstrap-help",
    "secret-scan",
    "plist-lint",
    "plugin-tests",
    "diff-check",
]


def write_executable(path, body):
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    os.chmod(path, 0o755)


def tree_state(path, exclude_git=False):
    state = {}
    for current, dirs, files in os.walk(path):
        if exclude_git and current == path and ".git" in dirs:
            dirs.remove(".git")
        rel_dir = os.path.relpath(current, path)
        state[("dir", rel_dir)] = stat.S_IMODE(os.stat(current).st_mode)
        for name in files:
            full = os.path.join(current, name)
            rel = os.path.relpath(full, path)
            with open(full, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()
            state[("file", rel)] = (stat.S_IMODE(os.stat(full).st_mode), digest)
    return state


class CheckScript(unittest.TestCase):
    def setUp(self):
        self.storage = tempfile.TemporaryDirectory(prefix="ecc-check-test-")
        self.base = self.storage.name
        self.home = os.path.join(self.base, "temporary home")
        os.makedirs(self.home)

    def tearDown(self):
        self.storage.cleanup()

    def fixture(self, name="fixture repository"):
        repo = os.path.join(self.base, name)
        os.makedirs(repo)
        result = subprocess.run(
            ["git", "-C", ROOT, "ls-files", "-z"],
            check=True,
            stdout=subprocess.PIPE,
        )
        paths = set(result.stdout.decode().rstrip("\0").split("\0"))
        paths.discard("")
        paths.discard("tests/test_check_script.py")
        for extra in ("scripts/check.sh", "docs/ci.md", "tests/test_ci_docs.py"):
            if os.path.isfile(os.path.join(ROOT, extra)):
                paths.add(extra)
        for rel in sorted(paths):
            source = os.path.join(ROOT, rel)
            target = os.path.join(repo, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(source, target)
        subprocess.run(["git", "init", "-q", repo], check=True)
        subprocess.run(["git", "-C", repo, "add", "-A"], check=True)
        return repo

    def environment(self, incoming_tmpdir, **updates):
        env = os.environ.copy()
        env.update({
            "HOME": self.home,
            "TMPDIR": incoming_tmpdir,
            "PYTHONDONTWRITEBYTECODE": "0",
            "npm_config_cache": os.path.join(self.home, "incoming npm cache"),
        })
        env.update(updates)
        return env

    def run_check(self, repo, *, cwd=None, env=None):
        return subprocess.run(
            [os.path.join(repo, "scripts", "check.sh")],
            cwd=cwd or repo,
            env=env or self.environment("/tmp"),
            capture_output=True,
            text=True,
        )

    def assert_statuses(self, result):
        statuses = []
        for line in result.stdout.splitlines():
            match = re.match(r"^(?:PASS|FAIL|SKIP) ([-a-z]+)(?:\s|$)", line)
            if match and match.group(1) in LABELS:
                statuses.append(match.group(1))
        self.assertEqual(statuses, LABELS, result.stdout + result.stderr)

    def assert_failed_check(self, result, label):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertRegex(result.stdout, rf"(?m)^FAIL {re.escape(label)}$")
        self.assert_statuses(result)

    def test_script_has_valid_sh_syntax(self):
        result = subprocess.run(["sh", "-n", CHECK], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_clean_real_runs_ignore_incoming_tmpdir_and_change_nothing(self):
        cases = []
        first = self.fixture("fixture with spaces one")
        cases.append((first, "/tmp", first))

        second = self.fixture("fixture with spaces two")
        incoming = os.path.join(self.home, ".openclaw", "tmp")
        os.makedirs(incoming)
        outside = os.path.join(self.base, "outside working directory")
        os.makedirs(outside)
        cases.append((second, incoming, outside))

        for repo, incoming_tmpdir, cwd in cases:
            with self.subTest(incoming_tmpdir=incoming_tmpdir, cwd=cwd):
                fixture_before = tree_state(repo, exclude_git=True)
                config_path = os.path.join(repo, ".git", "config")
                with open(config_path, "rb") as fh:
                    config_before = fh.read()
                home_before = tree_state(self.home)

                result = self.run_check(
                    repo,
                    cwd=cwd,
                    env=self.environment(incoming_tmpdir),
                )

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_statuses(result)
                self.assertNotIn("FAIL ", result.stdout)
                self.assertEqual(tree_state(repo, exclude_git=True), fixture_before)
                with open(config_path, "rb") as fh:
                    self.assertEqual(fh.read(), config_before)
                self.assertEqual(tree_state(self.home), home_before)

    def test_shell_syntax_failure_does_not_stop_later_checks(self):
        repo = self.fixture()
        path = os.path.join(repo, "bin", "ecc-snapshot")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("\nif then\n")
        result = self.run_check(repo)
        self.assert_failed_check(result, "sh-syntax")

    def test_failing_unittest_does_not_stop_later_checks(self):
        repo = self.fixture()
        path = os.path.join(repo, "tests", "test_forced_failure.py")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                "import unittest\n\n"
                "class ForcedFailure(unittest.TestCase):\n"
                "    def test_failure(self):\n"
                "        self.fail('forced failure')\n"
            )
        result = self.run_check(repo)
        self.assert_failed_check(result, "unit-tests")

    def test_secret_scan_failure_does_not_stop_later_checks(self):
        repo = self.fixture()
        fake_token = "gh" + "p_" + ("A" * 20)
        with open(os.path.join(repo, "docs", "fake-token.md"), "w", encoding="utf-8") as fh:
            fh.write(fake_token + "\n")
        result = self.run_check(repo)
        self.assert_failed_check(result, "secret-scan")

    def test_missing_required_script_is_a_failure(self):
        repo = self.fixture()
        os.unlink(os.path.join(repo, "bin", "ecc-snapshot"))
        result = self.run_check(repo)
        self.assert_failed_check(result, "sh-syntax")

    def test_missing_plutil_is_the_only_plist_skip(self):
        repo = self.fixture()
        controlled = os.path.join(self.base, "path without plutil")
        os.makedirs(controlled)
        seen = set()
        search_dirs = ["/bin", "/usr/bin", "/usr/sbin", "/sbin"]
        for directory in search_dirs:
            if not os.path.isdir(directory):
                continue
            for name in os.listdir(directory):
                source = os.path.join(directory, name)
                if name == "plutil" or name in seen or not os.access(source, os.X_OK):
                    continue
                try:
                    os.symlink(source, os.path.join(controlled, name))
                except OSError:
                    continue
                seen.add(name)
        for name in ("python3", "git", "npm", "node"):
            source = shutil.which(name)
            if source and name not in seen:
                os.symlink(source, os.path.join(controlled, name))
                seen.add(name)

        result = self.run_check(
            repo,
            env=self.environment("/tmp", PATH=controlled),
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(
            result.stdout,
            r"(?m)^SKIP plist-lint \(plutil is not available\)$",
        )
        self.assert_statuses(result)

    def test_available_failing_plutil_fails_the_check(self):
        repo = self.fixture()
        stub = os.path.join(self.base, "failing plutil")
        os.makedirs(stub)
        write_executable(
            os.path.join(stub, "plutil"),
            "#!/bin/sh\nprintf 'controlled plutil failure\\n' >&2\nexit 9\n",
        )
        env = self.environment("/tmp", PATH=stub + os.pathsep + os.environ["PATH"])
        result = self.run_check(repo, env=env)
        self.assert_failed_check(result, "plist-lint")
        self.assertIn("controlled plutil failure", result.stderr)

    def test_temp_cleanup_cache_and_python_environment(self):
        repo = self.fixture()
        stub = os.path.join(self.base, "environment wrappers")
        os.makedirs(stub)
        python_log = os.path.join(self.base, "python-environment.log")
        npm_log = os.path.join(self.base, "npm-environment.log")
        real_python = shutil.which("python3")
        real_npm = shutil.which("npm")
        self.assertIsNotNone(real_python)
        self.assertIsNotNone(real_npm)
        write_executable(
            os.path.join(stub, "python3"),
            "#!/bin/sh\n"
            "printf '%s|%s\\n' \"${TMPDIR-}\" \"${PYTHONDONTWRITEBYTECODE-}\" >> \"$CHECK_PYTHON_LOG\"\n"
            f'exec "{real_python}" "$@"\n',
        )
        write_executable(
            os.path.join(stub, "npm"),
            "#!/bin/sh\n"
            "printf '%s|%s\\n' \"${TMPDIR-}\" \"${npm_config_cache-}\" >> \"$CHECK_NPM_LOG\"\n"
            f'exec "{real_npm}" "$@"\n',
        )
        env = self.environment(
            os.path.join(self.home, "incoming tmp"),
            PATH=stub + os.pathsep + os.environ["PATH"],
            CHECK_PYTHON_LOG=python_log,
            CHECK_NPM_LOG=npm_log,
        )
        result = self.run_check(repo, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        with open(python_log, encoding="utf-8") as fh:
            python_values = [line.rstrip("\n").split("|", 1) for line in fh]
        with open(npm_log, encoding="utf-8") as fh:
            npm_values = [line.rstrip("\n").split("|", 1) for line in fh]
        self.assertTrue(python_values)
        self.assertTrue(npm_values)
        temp_paths = {value[0] for value in python_values + npm_values}
        self.assertEqual(len(temp_paths), 1)
        check_tmp = temp_paths.pop()
        self.assertRegex(check_tmp, r"^/tmp/ecc-check\.[^/]+$")
        self.assertTrue(all(value[1] == "1" for value in python_values))
        self.assertTrue(all(value[1] == os.path.join(check_tmp, "npm-cache") for value in npm_values))
        self.assertFalse(os.path.exists(check_tmp))
        for current, dirs, _files in os.walk(repo):
            self.assertNotIn("__pycache__", dirs, current)

    def test_mktemp_setup_failure_is_reported(self):
        repo = self.fixture()
        stub = os.path.join(self.base, "failing mktemp")
        os.makedirs(stub)
        write_executable(os.path.join(stub, "mktemp"), "#!/bin/sh\nexit 71\n")
        env = self.environment("/tmp", PATH=stub + os.pathsep + os.environ["PATH"])
        result = self.run_check(repo, env=env)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot create temporary storage under /tmp", result.stderr)


if __name__ == "__main__":
    unittest.main()
