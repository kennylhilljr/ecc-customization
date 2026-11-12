"""lib/ecctools.py openclaw-restore: archive safety and staging cleanup.

Run from the repository root: python3 -m unittest discover -s tests
Archives are built in temporary folders; every destination, and every target
a hostile member points at, lies inside the disposable fixture.
"""
import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")


def file_member(name, data=b"x", mode=0o644):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    return info, data


def dir_member(name, mode=0o755):
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    return info, None


def special_member(name, kind, linkname=""):
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    return info, None


class OpenclawRestore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fx = os.path.realpath(self.tmp.name)
        self.archive = os.path.join(self.fx, "src", "openclaw-state.tar.gz")
        os.makedirs(os.path.dirname(self.archive))
        self.out = os.path.join(self.fx, "out")
        os.makedirs(self.out)
        self.dest = os.path.join(self.out, "openclaw")

    def build(self, members):
        with tarfile.open(self.archive, "w:gz") as tar:
            for info, data in members:
                tar.addfile(info, io.BytesIO(data) if data is not None else None)

    def run_restore(self):
        return subprocess.run(
            [sys.executable, "-B", LIB, "openclaw-restore", "--archive", self.archive,
             "--dest", self.dest], capture_output=True, text=True)

    def staging_left(self):
        return [n for n in os.listdir(self.out) if n.startswith(".openclaw-restore-")]

    def assert_refused(self, r, needle="openclaw-restore:"):
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn(needle, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse(os.path.lexists(self.dest))
        self.assertEqual(self.staging_left(), [])

    def test_success(self):
        self.build([dir_member("openclaw", 0o755), file_member("openclaw/a.json", b"{}"),
                    dir_member("openclaw/sub"), file_member("openclaw/sub/b.txt", b"hello"),
                    file_member("other/ignored.txt", b"no")])
        r = self.run_restore()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"4 entries restored to {self.dest}", r.stdout)
        with open(os.path.join(self.dest, "sub", "b.txt"), "rb") as fh:
            self.assertEqual(fh.read(), b"hello")
        self.assertEqual(stat.S_IMODE(os.stat(self.dest).st_mode), 0o700)
        self.assertEqual(sorted(os.listdir(self.out)), ["openclaw"])
        self.assertFalse(os.path.exists(os.path.join(self.out, "other")))

    def test_root_created_implicitly_by_a_file_member(self):
        self.build([file_member("openclaw/only.txt", b"1")])
        r = self.run_restore()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "only.txt")))
        self.assertEqual(stat.S_IMODE(os.stat(self.dest).st_mode), 0o700)
        self.assertEqual(self.staging_left(), [])

    def test_missing_root(self):
        self.build([file_member("other/f")])
        self.assert_refused(self.run_restore(), "no openclaw directory")

    def test_regular_file_root(self):
        self.build([file_member("openclaw", b"not a folder")])
        self.assert_refused(self.run_restore(), "no openclaw directory")

    def test_existing_destination_untouched(self):
        os.makedirs(self.dest)
        with open(os.path.join(self.dest, "keep"), "w") as fh:
            fh.write("mine")
        self.build([file_member("openclaw/keep", b"theirs")])
        r = self.run_restore()
        self.assertEqual(r.returncode, 1)
        self.assertIn("exists; not touching it", r.stderr)
        with open(os.path.join(self.dest, "keep")) as fh:
            self.assertEqual(fh.read(), "mine")
        self.assertEqual(self.staging_left(), [])

    def test_unsafe_members_refused(self):
        escaped = os.path.join(self.fx, "escaped")
        cases = {
            "absolute": [file_member(escaped, b"x")],
            "parent traversal": [dir_member("openclaw"), file_member("../escaped", b"x")],
            "nested traversal": [file_member("openclaw/../../escaped", b"x")],
            "symlink": [dir_member("openclaw"),
                        special_member("openclaw/link", tarfile.SYMTYPE, escaped)],
            "hard link": [file_member("openclaw/a"),
                          special_member("openclaw/b", tarfile.LNKTYPE, escaped)],
            "device": [dir_member("openclaw"), special_member("openclaw/dev", tarfile.CHRTYPE)],
            "fifo": [dir_member("openclaw"), special_member("openclaw/fifo", tarfile.FIFOTYPE)],
        }
        for label, members in cases.items():
            with self.subTest(label):
                self.build(members)
                self.assert_refused(self.run_restore(), "refusing archive member")
                self.assertFalse(os.path.lexists(escaped))

    def test_manifest_checksum(self):
        self.build([file_member("openclaw/a", b"1")])
        manifest = os.path.join(os.path.dirname(self.archive), "manifest.json")
        with open(manifest, "w") as fh:
            json.dump({"archive_sha256": "0" * 64}, fh)
        self.assert_refused(self.run_restore(), "checksum does not match")
        with open(self.archive, "rb") as fh:
            digest = hashlib.sha256(fh.read()).hexdigest()
        with open(manifest, "w") as fh:
            json.dump({"archive_sha256": digest}, fh)
        r = self.run_restore()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(self.dest, "a")))

    def test_unreadable_archive(self):
        with open(self.archive, "wb") as fh:
            fh.write(b"not a tarball")
        self.assert_refused(self.run_restore(), "cannot read")


if __name__ == "__main__":
    unittest.main()
