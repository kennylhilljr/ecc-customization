"""bin/openclaw-gh-app-token with fake security and curl commands: no network,
no Keychain, and a throwaway RSA key generated for each run.

Run from the repository root: python3 -m unittest discover -s tests
"""
import base64
import json
import os
import shutil
import stat
import subprocess
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "bin", "openclaw-gh-app-token")

FAKE_SECURITY = """#!/bin/bash
[ "$1" = find-generic-password ] || exit 2
[ -n "${FAKE_KEY_B64:-}" ] || exit 44
printf '%s\\n' "$FAKE_KEY_B64"
"""
FAKE_CURL = """#!/bin/bash
printf '%s\\n' "$@" > "$CURL_LOG"
[ "${CURL_EXIT:-0}" = 0 ] || exit "$CURL_EXIT"
printf '%s' "$CURL_REPLY"
"""


def b64url_decode(part):
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


class TokenScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fake = os.path.join(self.tmp.name, "fakebin")
        os.makedirs(self.fake)
        for name, body in (("security", FAKE_SECURITY), ("curl", FAKE_CURL)):
            path = os.path.join(self.fake, name)
            with open(path, "w") as fh:
                fh.write(body)
            os.chmod(path, 0o755)
        self.key = os.path.join(self.tmp.name, "key.pem")
        subprocess.run(["openssl", "genrsa", "-out", self.key, "2048"],
                       check=True, capture_output=True)
        with open(self.key, "rb") as fh:
            self.key_b64 = base64.b64encode(fh.read()).decode()
        self.curl_log = os.path.join(self.tmp.name, "curl.log")
        self.env = {
            "PATH": f"{self.fake}:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": self.tmp.name, "USER": "tester",
            "CURL_LOG": self.curl_log, "CURL_REPLY": json.dumps({"token": "ghs_fake"}),
            "FAKE_KEY_B64": self.key_b64,
        }

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, *args, script=SCRIPT, **env):
        e = dict(self.env)
        for k, v in env.items():
            if v is None:
                e.pop(k, None)
            else:
                e[k] = v
        return subprocess.run(["/bin/bash", script, *args], capture_output=True, text=True, env=e)

    def installed_copy(self, render):
        """Copy the script outside the repository, rendered the way bootstrap.sh does."""
        dest = os.path.join(self.tmp.name, ".local", "bin", "openclaw-gh-app-token")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        if render:
            with open(dest, "w") as out:
                subprocess.run(["sed", "-e", "s#__OPENCLAW_OPS_APP_ID__#5509685#g",
                                "-e", "s#__OPENCLAW_OPS_INSTALLATION_ID__#176165995#g", SCRIPT],
                               stdout=out, check=True)
        else:
            shutil.copy(SCRIPT, dest)
        return dest

    # ---- configuration
    def test_repository_copy_reads_stack_conf(self):
        r = self.run_script("--print-config")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("app_id=5509685\n", r.stdout)
        self.assertIn("installation_id=176165995\n", r.stdout)

    def test_environment_overrides(self):
        r = self.run_script("--print-config", OPENCLAW_OPS_APP_ID="11", OPENCLAW_OPS_INSTALLATION_ID="22")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("app_id=11\n", r.stdout)
        self.assertIn("installation_id=22\n", r.stdout)

    def test_rendered_copy_needs_no_stack_conf(self):
        r = self.run_script("--print-config", script=self.installed_copy(render=True))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("app_id=5509685\n", r.stdout)
        self.assertIn("installation_id=176165995\n", r.stdout)

    def test_unrendered_copy_without_stack_conf_fails(self):
        r = self.run_script("--print-config", script=self.installed_copy(render=False))
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("App id", r.stderr)

    def test_executable_and_bash_syntax(self):
        self.assertTrue(os.stat(SCRIPT).st_mode & stat.S_IXUSR)
        self.assertEqual(subprocess.run(["bash", "-n", SCRIPT]).returncode, 0)

    # ---- token exchange, mocked
    def test_token_exchange(self):
        before = int(time.time())
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, "ghs_fake\n")
        with open(self.curl_log) as fh:
            args = fh.read().splitlines()
        self.assertEqual(args[-1], "https://api.github.com/app/installations/176165995/access_tokens")
        self.assertIn("Accept: application/vnd.github+json", args)
        self.assertIn("X-GitHub-Api-Version: 2022-11-28", args)
        auth = [a for a in args if a.startswith("Authorization: Bearer ")]
        self.assertEqual(len(auth), 1)
        jwt = auth[0][len("Authorization: Bearer "):]
        header, payload, sig = jwt.split(".")
        self.assertEqual(json.loads(b64url_decode(header)), {"alg": "RS256", "typ": "JWT"})
        claims = json.loads(b64url_decode(payload))
        self.assertEqual(claims["iss"], "5509685")
        self.assertLessEqual(claims["iat"], before)
        self.assertLessEqual(claims["exp"] - claims["iat"], 600)
        pub = os.path.join(self.tmp.name, "pub.pem")
        subprocess.run(["openssl", "rsa", "-in", self.key, "-pubout", "-out", pub],
                       check=True, capture_output=True)
        data = os.path.join(self.tmp.name, "data")
        sigf = os.path.join(self.tmp.name, "sig")
        with open(data, "w") as fh:
            fh.write(f"{header}.{payload}")
        with open(sigf, "wb") as fh:
            fh.write(b64url_decode(sig))
        v = subprocess.run(["openssl", "dgst", "-sha256", "-verify", pub, "-signature", sigf, data],
                           capture_output=True, text=True)
        self.assertEqual(v.returncode, 0, v.stdout + v.stderr)

    def test_missing_key_prints_the_store_command(self):
        r = self.run_script(FAKE_KEY_B64=None)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("security add-generic-password -a \"$USER\" -s openclaw-ops-assist/private-key -U -w",
                      r.stderr)
        self.assertFalse(os.path.exists(self.curl_log))

    def test_invalid_key(self):
        r = self.run_script(FAKE_KEY_B64=base64.b64encode(b"not a key").decode())
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("could not sign", r.stderr)
        self.assertFalse(os.path.exists(self.curl_log))

    def test_http_failure(self):
        r = self.run_script(CURL_EXIT="22")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(r.stdout, "")
        self.assertIn("refused", r.stderr)

    def test_reply_without_token(self):
        for reply in (json.dumps({"message": "Bad credentials"}), "not json"):
            with self.subTest(reply=reply):
                r = self.run_script(CURL_REPLY=reply)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")
                self.assertIn("no token", r.stderr)
                self.assertNotIn("Bad credentials", r.stderr)


if __name__ == "__main__":
    unittest.main()
