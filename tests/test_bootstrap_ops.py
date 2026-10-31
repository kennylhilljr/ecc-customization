"""bootstrap.sh --only ops against a temporary HOME, with a fake security
command so the real Keychain is never queried.

Run from the repository root: python3 -m unittest discover -s tests
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BOOTSTRAP = os.path.join(ROOT, "bootstrap.sh")

FAKE_SECURITY = """#!/bin/bash
[ "${FAKE_KEY_PRESENT:-0}" = 1 ] && exit 0
exit 44
"""


class BootstrapOps(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = os.path.join(self.tmp.name, "home dir")
        self.fake = os.path.join(self.tmp.name, "fakebin")
        os.makedirs(self.fake)
        with open(os.path.join(self.fake, "security"), "w") as fh:
            fh.write(FAKE_SECURITY)
        os.chmod(os.path.join(self.fake, "security"), 0o755)
        self.ws = os.path.join(self.home, ".openclaw", "workspace-ops")
        self.settings = os.path.join(self.ws, ".claude", "settings.json")
        self.other = os.path.join(self.home, ".openclaw", "workspace-main", ".claude", "settings.json")
        self.token = os.path.join(self.home, ".local", "bin", "openclaw-gh-app-token")
        os.makedirs(self.ws)
        os.makedirs(os.path.dirname(self.other))
        with open(self.other, "w") as fh:
            fh.write('{"model": "sonnet"}\n')
        pydir = os.path.dirname(sys.executable)
        self.env = {"HOME": self.home, "USER": "tester",
                    "PATH": f"{self.fake}:{pydir}:/usr/bin:/bin:/usr/sbin:/sbin"}

    def tearDown(self):
        self.tmp.cleanup()

    def bootstrap(self, *args, **env):
        e = dict(self.env, **env)
        return subprocess.run([BOOTSTRAP, "--only", "ops", *args], capture_output=True, text=True,
                              env=e, stdin=subprocess.DEVNULL)

    def test_help_lists_ops_between_openclaw_and_secrets(self):
        r = subprocess.run([BOOTSTRAP, "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"openclaw\s+ops\s+secrets")
        with open(BOOTSTRAP) as fh:
            self.assertIn("openclaw ops secrets", fh.read())

    def test_install_merge_and_idempotence(self):
        r = self.bootstrap()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.access(self.token, os.X_OK))
        with open(self.token) as fh:
            body = fh.read()
        self.assertIn('BAKED_APP_ID="5509685"', body)
        self.assertIn('BAKED_INSTALLATION_ID="176165995"', body)
        cfg = subprocess.run(["/bin/bash", self.token, "--print-config"], capture_output=True,
                             text=True, env={"PATH": "/usr/bin:/bin", "HOME": self.home})
        self.assertEqual(cfg.returncode, 0, cfg.stderr)
        self.assertIn("app_id=5509685", cfg.stdout)

        with open(self.settings) as fh:
            data = json.load(fh)
        gh = os.path.join(self.home, "Documents", "GitHub")
        self.assertEqual(data["env"]["GATEGUARD_BASH_ROUTINE_DISABLED"], "1")
        self.assertIn(f"{gh}/*/.git", data["sandbox"]["filesystem"]["allowWrite"])
        with open(self.other) as fh:
            self.assertEqual(fh.read(), '{"model": "sonnet"}\n')
        self.assertIn("security add-generic-password -a \"$USER\" -s openclaw-ops-assist/private-key -U -w",
                      r.stdout)
        self.assertIn(".local/bin to PATH", r.stdout)

        stamps = {p: os.stat(p).st_mtime_ns for p in (self.token, self.settings)}
        r = self.bootstrap(FAKE_KEY_PRESENT="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("up to date", r.stdout)
        self.assertIn("openclaw-ops-assist/private-key: present", r.stdout)
        self.assertEqual(stamps, {p: os.stat(p).st_mtime_ns for p in stamps})

    def test_dry_run_with_absent_destinations_writes_nothing(self):
        r = self.bootstrap("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("+ install", r.stdout)
        self.assertIn("would add env", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".local")))
        self.assertFalse(os.path.exists(self.settings))

    def test_existing_different_token_command_needs_consent(self):
        os.makedirs(os.path.dirname(self.token))
        with open(self.token, "w") as fh:
            fh.write("#!/bin/bash\necho old\n")
        r = self.bootstrap("--dry-run")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.token) as fh:
            self.assertEqual(fh.read(), "#!/bin/bash\necho old\n")
        r = self.bootstrap()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("rerun with --only ops --yes", r.stdout)
        with open(self.token) as fh:
            self.assertEqual(fh.read(), "#!/bin/bash\necho old\n")
        r = self.bootstrap("--yes")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(self.token + ".ecc-backup") as fh:
            self.assertEqual(fh.read(), "#!/bin/bash\necho old\n")
        with open(self.token) as fh:
            self.assertIn('BAKED_APP_ID="5509685"', fh.read())

    def test_broken_settings_file_is_reported_and_kept(self):
        os.makedirs(os.path.dirname(self.settings))
        with open(self.settings, "w") as fh:
            fh.write("{broken")
        r = self.bootstrap()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ops settings not merged", r.stdout)
        with open(self.settings) as fh:
            self.assertEqual(fh.read(), "{broken")

    def test_missing_workspace_is_an_owner_task(self):
        os.rmdir(self.ws)
        r = self.bootstrap()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("no OpenClaw ops workspace", r.stdout)
        self.assertFalse(os.path.exists(self.ws))


if __name__ == "__main__":
    unittest.main()
