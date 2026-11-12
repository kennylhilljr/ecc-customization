"""lib/ecctools.py restore --dry-run writes nothing.

Run from the repository root: python3 -m unittest discover -s tests
Uses a synthetic snapshot root, an empty plugin manifest (so no agent CLI
runs) and an explicit temporary --home.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(text)


def state(top):
    """Every entry under top with its kind, bytes and modification time."""
    out = {}
    for d, dirs, files in os.walk(top):
        for name in dirs + files:
            p = os.path.join(d, name)
            st = os.lstat(p)
            data = None
            if os.path.isfile(p):
                with open(p, "rb") as fh:
                    data = fh.read()
            out[os.path.relpath(p, top)] = (os.path.isdir(p), data, st.st_mtime_ns)
    return out


class RestoreDryRun(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        fx = os.path.realpath(self.tmp.name)
        self.snap = os.path.join(fx, "machine")
        self.home = os.path.join(fx, "home")
        os.makedirs(self.home)
        files = {
            ".claude/settings.json": '{"model": "opus"}\n',
            ".codex/config.toml": 'model = "o3"\n',
            ".gemini/GEMINI.md": "same\n",
            ".claude/skills/demo/SKILL.md": "demo skill\n",
            ".claude/skills/demo/ref/notes.md": "notes in __HOME__\n",
        }
        for rel, text in files.items():
            write(os.path.join(self.snap, "home", rel), text)
        manifest = {"schema_version": 1, "files": [".claude/settings.json", ".codex/config.toml",
                                                    ".gemini/GEMINI.md"],
                    "dirs": [".claude/skills/demo"],
                    "removed": {".codex/config.toml": ["api_key"]}, "skipped": [], "plugins": {}}
        write(os.path.join(self.snap, "manifest.json"), json.dumps(manifest))
        # Absent: .claude/settings.json and the skill folder. Conflicting:
        # .codex/config.toml. Identical: .gemini/GEMINI.md.
        write(os.path.join(self.home, ".codex", "config.toml"), 'model = "mine"\n')
        write(os.path.join(self.home, ".gemini", "GEMINI.md"), "same\n")

    def restore(self, *extra):
        return subprocess.run(
            [sys.executable, "-B", LIB, "restore", "--root", self.snap, "--home", self.home,
             "--dry-run", *extra], capture_output=True, text=True)

    def check_nothing_written(self, *extra):
        home_before, snap_before = state(self.home), state(self.snap)
        r = self.restore(*extra)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(state(self.home), home_before)
        self.assertEqual(state(self.snap), snap_before)
        for name in home_before:
            self.assertFalse(name.endswith((".ecc-snapshot", ".ecc-backup")))
        return r.stdout

    def test_without_overwrite(self):
        out = self.check_nothing_written()
        h = self.home
        self.assertIn(f"+ write {h}/.claude/settings.json", out)
        self.assertIn(f"+ write {h}/.claude/skills/demo/SKILL.md", out)
        self.assertIn(f"+ write {h}/.claude/skills/demo/ref/notes.md", out)
        self.assertIn(f"differs, left as is: {h}/.codex/config.toml", out)
        self.assertIn("~/.codex/config.toml: secrets were removed", out)
        self.assertNotIn(".gemini/GEMINI.md", out)
        self.assertNotIn("restored", out)

    def test_with_overwrite(self):
        out = self.check_nothing_written("--overwrite")
        self.assertIn(f"+ write {self.home}/.codex/config.toml", out)
        self.assertNotIn("differs", out)
        self.assertNotIn("restored", out)


if __name__ == "__main__":
    unittest.main()
