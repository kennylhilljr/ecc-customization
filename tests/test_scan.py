"""lib/ecctools.py secret detection: secret_kind, scan_paths and the scan CLI.

Run from the repository root: python3 -m unittest discover -s tests
Fake secret values are assembled at runtime so this file passes the scan.
Everything runs in temporary folders.
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")


def load_ecctools():
    spec = importlib.util.spec_from_file_location("ecctools_under_test", LIB)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ecc = load_ecctools()

# One runtime-built sample per TOKEN_SHAPES kind.
SAMPLES = {
    "anthropic or openai key": "sk" + "-" + "a1B2" * 5,
    "github token": "gh" + "p_" + "Q" * 24,
    "slack token": "xo" + "xb-" + "1" * 12,
    "google api key": "AI" + "za" + "B" * 32,
    "groq key": "gs" + "k_" + "C" * 24,
    "aws key id": "AK" + "IA" + "ABCDEFGHIJKLMNOP",
    "jwt": "ey" + "J" + "a" * 12 + "." + "b" * 12 + ".",
    "private key": "-----BEGIN " + "RSA PRIVATE KEY-----",
    "credential in url": "https" + "://" + "bob:hunter2" + "@example.com/x",
}
OPAQUE = "Xy7" * 11


def write(path, data, mode="w"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode) as fh:
        fh.write(data)


class SecretKind(unittest.TestCase):
    def test_every_token_shape_has_a_sample(self):
        self.assertEqual(sorted(SAMPLES), sorted(kind for kind, _ in ecc.TOKEN_SHAPES))

    def test_each_token_shape_is_detected(self):
        for kind, sample in SAMPLES.items():
            with self.subTest(kind=kind):
                self.assertEqual(ecc.secret_kind(f"value = {sample} # trailing"), kind)

    def test_short_lookalikes_are_not_tokens(self):
        for text in ("sk" + "-short", "gh" + "p_abc", "AK" + "IAabc", "https://example.com/path"):
            with self.subTest(text=text):
                self.assertIsNone(ecc.secret_kind(text))

    def test_long_opaque_string(self):
        self.assertEqual(ecc.secret_kind(f"x = {OPAQUE}"), "long opaque string")

    def test_hex_shas_are_not_secrets(self):
        sha1 = "0123456789abcdef0123456789abcdef01234567"
        sha256 = ("0123456789ABCDEF" * 4)
        uuidish = "01234567-89ab-cdef-0123-456789abcdef0123"
        for text in (sha1, sha256, uuidish):
            with self.subTest(text=text):
                self.assertIsNone(ecc.secret_kind(f"commit {text}"))

    def test_single_case_long_strings_are_not_secrets(self):
        for text in ("abcdefgh1" * 5, "ABCDEFGH1" * 5, "abcdEFGH" * 5):
            with self.subTest(text=text):
                self.assertIsNone(ecc.secret_kind(text))

    def test_opaque_inside_path_or_word_is_not_flagged(self):
        self.assertIsNone(ecc.secret_kind(f"/usr/lib/{OPAQUE}.so"))


class ScanPaths(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def test_reports_line_numbers(self):
        p = os.path.join(self.root, "a.txt")
        write(p, "clean\nkey " + SAMPLES["github token"] + "\nclean\n" + OPAQUE + "\n")
        self.assertEqual(ecc.scan_paths([self.root]),
                         [(p, 2, "github token"), (p, 4, "long opaque string")])

    def test_skips_git_folders(self):
        write(os.path.join(self.root, ".git", "config"), SAMPLES["github token"] + "\n")
        write(os.path.join(self.root, "sub", ".git", "x"), SAMPLES["github token"] + "\n")
        self.assertEqual(ecc.scan_paths([self.root]), [])

    def test_skips_symlinks_met_during_traversal(self):
        outside = os.path.join(self.root, "outside")
        write(os.path.join(outside, "secret.txt"), SAMPLES["slack token"] + "\n")
        tree = os.path.join(self.root, "tree")
        os.makedirs(tree)
        os.symlink(os.path.join(outside, "secret.txt"), os.path.join(tree, "file-link"))
        os.symlink(outside, os.path.join(tree, "dir-link"))
        self.assertEqual(ecc.scan_paths([tree]), [])

    def test_directly_supplied_file_symlink_is_scanned(self):
        target = os.path.join(self.root, "secret.txt")
        write(target, SAMPLES["slack token"] + "\n")
        link = os.path.join(self.root, "link")
        os.symlink(target, link)
        self.assertEqual(ecc.scan_paths([link]), [(link, 1, "slack token")])

    def test_skips_binary_files(self):
        write(os.path.join(self.root, "blob.bin"),
              b"\xff\xfe\x00" + SAMPLES["github token"].encode() + b"\n", mode="wb")
        self.assertEqual(ecc.scan_paths([self.root]), [])


class ScanCli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = os.path.realpath(self.tmp.name)

    def scan(self, *paths):
        return subprocess.run([sys.executable, "-B", LIB, "scan", *paths],
                              capture_output=True, text=True)

    def test_clean_exits_zero_silently(self):
        write(os.path.join(self.root, "a.txt"), "nothing here\n")
        r = self.scan(self.root)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_findings_exit_one_without_values(self):
        p = os.path.join(self.root, "a.txt")
        write(p, "x\n" + SAMPLES["groq key"] + "\n")
        q = os.path.join(self.root, "b.txt")
        write(q, SAMPLES["credential in url"] + "\n")
        r = self.scan(p, q)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, f"{p}:2: looks like a groq key\n"
                                   f"{q}:1: looks like a credential in url\n")
        for value in (SAMPLES["groq key"], SAMPLES["credential in url"], "hunter2"):
            self.assertNotIn(value, r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()
