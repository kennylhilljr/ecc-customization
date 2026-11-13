import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 40 lines with no trailing newline, so "\n" + more text becomes line 41.
LOREM = "\n".join(f"lorem ipsum dolor sit amet line {n} consectetur adipiscing elit"
                  for n in range(1, 41))


def _token():
    # Built at run time so the repository's own scan never sees a literal.
    return "ghp_" + "A1b2" * 6


class PreCommitHookTest(unittest.TestCase):
    """Run .githooks/pre-commit in throwaway repositories only."""

    def _env(self, repo):
        env = os.environ.copy()
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        env.update(HOME=repo, GIT_CONFIG_NOSYSTEM="1",
                   GIT_AUTHOR_NAME="tester", GIT_AUTHOR_EMAIL="tester@example.invalid",
                   GIT_COMMITTER_NAME="tester", GIT_COMMITTER_EMAIL="tester@example.invalid")
        return env

    def _git(self, repo, *args, extra_env=None):
        env = self._env(repo)
        env.update(extra_env or {})
        return subprocess.run(["git", "-C", repo, *args], env=env,
                              capture_output=True, stdin=subprocess.DEVNULL)

    def _ok(self, repo, *args):
        r = self._git(repo, *args)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def _repo(self):
        repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        self._ok(repo, "init", "-q")
        self._ok(repo, "config", "commit.gpgsign", "false")
        self._ok(repo, "config", "core.hooksPath", ".githooks")
        os.makedirs(os.path.join(repo, ".githooks"))
        hook = os.path.join(repo, ".githooks", "pre-commit")
        shutil.copy(os.path.join(ROOT, ".githooks", "pre-commit"), hook)
        os.chmod(hook, 0o755)
        os.makedirs(os.path.join(repo, "lib"))
        shutil.copy(os.path.join(ROOT, "lib", "ecctools.py"), os.path.join(repo, "lib", "ecctools.py"))
        return repo

    def _write(self, repo, name, text):
        with open(os.path.join(repo, name), "w", encoding="utf-8") as fh:
            fh.write(text)

    def _commit(self, repo):
        return self._git(repo, "commit", "-q", "-m", "test")

    def _assert_refused(self, result, filename_bytes, expected_line):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(filename_bytes, result.stderr)
        decoded = result.stderr.decode(errors="replace")
        self.assertIn(f"{filename_bytes.decode()}:{expected_line}: looks like a github token", decoded)
        self.assertNotIn(_token().encode(), result.stdout + result.stderr)
        # The fixtures sit at the repository root, so any "/" right before the
        # name is a leftover /tmp/, /var/folders/ or repository prefix.
        self.assertNotIn(b"/" + filename_bytes, result.stderr)

    def _rename_fixture(self, extra):
        repo = self._repo()
        self._write(repo, "old.txt", LOREM)
        self._ok(repo, "add", "old.txt")
        self._ok(repo, "commit", "-q", "-m", "initial")
        self._ok(repo, "mv", "old.txt", "new.txt")
        with open(os.path.join(repo, "new.txt"), "a", encoding="utf-8") as fh:
            fh.write(extra)
        self._ok(repo, "add", "-A")
        status = self._ok(repo, "diff", "--cached", "--name-status", "-M").stdout
        if not re.search(rb"^R\d*\told\.txt\tnew\.txt$", status, re.M):
            self.fail("fixture did not produce a rename")
        return repo

    def test_refuses_plain_name(self):
        repo = self._repo()
        self._write(repo, "plain.md", _token() + "\n")
        self._ok(repo, "add", "plain.md")
        self._assert_refused(self._commit(repo), b"plain.md", 1)

    def test_refuses_name_with_space(self):
        repo = self._repo()
        self._write(repo, "a b.md", _token() + "\n")
        self._ok(repo, "add", "--", "a b.md")
        self._assert_refused(self._commit(repo), b"a b.md", 1)

    def test_refuses_non_ascii_name(self):
        repo = self._repo()
        self._write(repo, "café.md", _token() + "\n")
        self._ok(repo, "add", "--", "café.md")
        self._assert_refused(self._commit(repo), "café.md".encode("utf-8"), 1)

    def test_refuses_rename_with_edit(self):
        repo = self._rename_fixture("\n" + _token())
        self._assert_refused(self._commit(repo), b"new.txt", 41)

    def test_accepts_clean_awkward_names(self):
        repo = self._repo()
        for name in ("plain.md", "a b.md", "café.md"):
            self._write(repo, name, "hello\n")
        self._ok(repo, "add", "-A")
        r = self._commit(repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_accepts_clean_rename_with_edit(self):
        repo = self._rename_fixture("\none more harmless closing line\n")
        r = self._commit(repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_accepts_staged_gitlink(self):
        # A submodule entry has no blob, so "git show :sub" fails; the hook
        # must skip it rather than refuse every submodule commit.
        repo = self._repo()
        self._write(repo, "plain.md", "hello\n")
        self._ok(repo, "add", "plain.md")
        self._ok(repo, "commit", "-q", "-m", "initial")
        # The submodule's commit lives in another repository, not this one.
        self._ok(repo, "update-index", "--add", "--cacheinfo", "160000," + "1234567890" * 4 + ",sub")
        r = self._commit(repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_refuses_when_mktemp_fails_and_keeps_worktree(self):
        # With an empty $tmp the staged copies would land in the work tree.
        repo = self._repo()
        os.makedirs(os.path.join(repo, "docs"))
        self._write(repo, os.path.join("docs", "f.txt"), "staged\n")
        self._ok(repo, "add", "docs/f.txt")
        self._write(repo, os.path.join("docs", "f.txt"), "unstaged edit\n")
        fake_bin = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, fake_bin, ignore_errors=True)
        fake = os.path.join(fake_bin, "mktemp")
        with open(fake, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\nexit 1\n")
        os.chmod(fake, 0o755)
        path = fake_bin + os.pathsep + os.environ.get("PATH", "")
        r = self._git(repo, "commit", "-q", "-m", "test", extra_env={"PATH": path})
        self.assertNotEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(repo, "docs", "f.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "unstaged edit\n")

    def _failing_git(self, subcommand):
        # Git puts its exec directory first on PATH for hooks, so a PATH
        # wrapper would be bypassed; the hook calls ECC_PRECOMMIT_GIT instead.
        real_git = shutil.which("git")
        self.assertIsNotNone(real_git)
        stub_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, stub_dir, ignore_errors=True)
        log = os.path.join(stub_dir, "git.log")
        stub = os.path.join(stub_dir, "git")
        with open(stub, "w", encoding="utf-8") as fh:
            fh.write("#!/bin/sh\n"
                     f"printf '%s\\n' \"$*\" >> {shlex.quote(log)}\n"
                     f"if [ \"$1\" = {shlex.quote(subcommand)} ]; then exit 1; fi\n"
                     f"exec {shlex.quote(real_git)} \"$@\"\n")
        os.chmod(stub, 0o755)
        return stub, log

    def _commit_with_git(self, repo, stub):
        return self._git(repo, "commit", "-q", "-m", "test",
                         extra_env={"ECC_PRECOMMIT_GIT": stub})

    def _assert_failed_without_commit(self, repo, result, message, log, subcommand):
        self.assertNotEqual(result.returncode, 0, result.stderr)
        self.assertIn(message, result.stderr.decode(errors="replace"))
        self.assertNotIn(_token().encode(), result.stdout + result.stderr)
        self.assertNotEqual(self._git(repo, "rev-parse", "-q", "--verify", "HEAD").returncode, 0)
        with open(log, encoding="utf-8") as fh:
            calls = [line.split(" ", 1)[0] for line in fh.read().splitlines()]
        self.assertIn(subcommand, calls)

    def test_refuses_when_listing_staged_files_fails(self):
        repo = self._repo()
        self._write(repo, "plain.md", _token() + "\n")
        self._ok(repo, "add", "plain.md")
        stub, log = self._failing_git("diff")
        r = self._commit_with_git(repo, stub)
        self._assert_failed_without_commit(
            repo, r, "pre-commit: could not list staged files", log, "diff")

    def test_refuses_when_copying_staged_file_fails(self):
        repo = self._repo()
        self._write(repo, "a b.md", _token() + "\n")
        self._ok(repo, "add", "--", "a b.md")
        stub, log = self._failing_git("show")
        r = self._commit_with_git(repo, stub)
        self._assert_failed_without_commit(
            repo, r, "pre-commit: could not read staged content for a b.md", log, "show")

    def test_checkout_shared_config_is_untouched(self):
        # Linked worktrees share one config file; the hook tests must only
        # write the config of their own temporary repositories.
        common = subprocess.run(["git", "-C", ROOT, "rev-parse", "--git-common-dir"],
                                capture_output=True, text=True)
        if common.returncode != 0:
            self.skipTest("not a git checkout")
        common_dir = common.stdout.strip()
        if not os.path.isabs(common_dir):
            common_dir = os.path.join(ROOT, common_dir)
        config = os.path.join(common_dir, "config")
        with open(config, "rb") as fh:
            before = fh.read()

        repo = self._repo()
        self._write(repo, "a b.md", _token() + "\n")
        self._ok(repo, "add", "--", "a b.md")
        self.assertNotEqual(self._commit(repo).returncode, 0)
        # The refused commit leaves the token staged; replace it before retrying.
        self._write(repo, "a b.md", "hello\n")
        self._ok(repo, "add", "--", "a b.md")
        r = self._commit(repo)
        self.assertEqual(r.returncode, 0, r.stderr)

        with open(config, "rb") as fh:
            self.assertEqual(fh.read(), before)


if __name__ == "__main__":
    unittest.main()
