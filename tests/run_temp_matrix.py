"""Run the whole unittest suite under two temporary-folder settings.

    python3 -B tests/run_temp_matrix.py

The suite runs twice in a child Python, each time with HOME set to a
disposable folder under /tmp: once with TMPDIR=/tmp and once with TMPDIR set
to that home's .openclaw/tmp (the nested layout OpenClaw agents use). The
file name does not match test_*.py, so normal discovery never runs it and it
cannot recurse into itself.
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CHILD = r"""
import os, sys, tempfile, unittest
from unittest import mock
want = sys.argv[1]
with mock.patch.object(tempfile, "tempdir", want):
    if os.path.realpath(tempfile.gettempdir()) != os.path.realpath(want):
        sys.exit("matrix: tempfile did not pick up " + want)
    with tempfile.TemporaryDirectory() as probe:
        if os.path.dirname(os.path.realpath(probe)) != os.path.realpath(want):
            sys.exit("matrix: temporary folder created outside " + want)
    suite = unittest.defaultTestLoader.discover(os.path.join(sys.argv[2], "tests"), top_level_dir=os.path.join(sys.argv[2], "tests"))
    if suite.countTestCases() == 0:
        sys.exit("matrix: discovery found no tests")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""


class TempMatrix(unittest.TestCase):
    def test_suite_passes_for_each_tmpdir(self):
        with tempfile.TemporaryDirectory(prefix="ecc-matrix-home-", dir="/tmp") as home:
            nested = os.path.join(home, ".openclaw", "tmp")
            os.makedirs(nested)
            for tmpdir in ("/tmp", nested):
                with self.subTest(TMPDIR=tmpdir):
                    env = dict(os.environ, HOME=home, TMPDIR=tmpdir, PYTHONDONTWRITEBYTECODE="1")
                    r = subprocess.run([sys.executable, "-B", "-c", CHILD, tmpdir, ROOT],
                                       cwd=ROOT, env=env, capture_output=True, text=True)
                    self.assertEqual(r.returncode, 0,
                                     f"suite failed with TMPDIR={tmpdir}\n{r.stdout}{r.stderr[-4000:]}")
                    self.assertRegex(r.stderr, r"Ran [1-9][0-9]* tests")
        self.assertFalse(os.path.exists(home))


if __name__ == "__main__":
    unittest.main()
