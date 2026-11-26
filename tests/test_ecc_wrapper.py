"""bin/ecc help path: runs with a temporary HOME and no project or orchestrator."""

from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
ECC = ROOT / "bin/ecc"


class EccWrapperHelpTests(unittest.TestCase):
    def run_ecc(self, *args):
        with tempfile.TemporaryDirectory() as tmp:
            env = {"HOME": tmp, "PATH": "/usr/bin:/bin"}
            return subprocess.run(["sh", str(ECC), *args], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=30)

    def test_help_exits_zero_without_project(self):
        for flag in ("--help", "-h"):
            with self.subTest(flag=flag):
                result = self.run_ecc(flag)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("usage: ecc [--project DIR] <command>", result.stdout)
                self.assertEqual(result.stderr, "")

    def test_command_without_project_still_fails(self):
        result = self.run_ecc("status", "--run-id", "x")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no .orchestration/ecc.json", result.stderr)

    def test_help_after_command_is_not_intercepted(self):
        result = self.run_ecc("status", "--help")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no .orchestration/ecc.json", result.stderr)


if __name__ == "__main__":
    unittest.main()
