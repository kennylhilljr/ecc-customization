"""bin/ecc-kit help path: runs with a temporary HOME and no project."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ECC_KIT = ROOT / "bin/ecc-kit"


class EccKitWrapperHelpTests(unittest.TestCase):
    def run_kit(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOME": tmp, "PATH": "/usr/bin:/bin"}
            return subprocess.run(["sh", str(ECC_KIT), *args], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=30)

    def test_help_exits_zero(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = self.run_kit(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("ecc-kit new REPO --name NAME", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_no_command_still_fails(self):
        result = self.run_kit()
        self.assertEqual(result.returncode, 2)
        self.assertIn("ecc-kit new REPO --name NAME", result.stdout)

    def test_unknown_command_still_fails(self):
        result = self.run_kit("bogus")
        self.assertEqual(result.returncode, 2)

    def test_help_with_extra_args_is_not_intercepted(self):
        result = self.run_kit("--help", "extra")
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
