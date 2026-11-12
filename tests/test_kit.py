"""lib/ecctools.py kit-new, kit-diff and kit-sync against an empty project.

Run from the repository root: python3 -m unittest discover -s tests
Each test uses a temporary HOME holding a fresh project folder. kit/ itself
is only read.
"""
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib", "ecctools.py")
KIT = os.path.join(ROOT, "kit")
PLACEHOLDER = re.compile(r"\{\{[A-Z_]+\}\}")

spec = importlib.util.spec_from_file_location("ecctools_under_test", LIB)
ecc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecc)


def kit_templates():
    """{kit-relative path: text} for every kit file, hidden folders included."""
    out = {}
    for d, _, files in os.walk(KIT):
        for f in files:
            p = os.path.join(d, f)
            with open(p, encoding="utf-8") as fh:
                out[os.path.relpath(p, KIT)] = fh.read()
    return out


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


class KitTemplates(unittest.TestCase):
    def test_every_placeholder_is_a_kit_var(self):
        used = set()
        for text in kit_templates().values():
            used.update(m[2:-2] for m in PLACEHOLDER.findall(text))
        self.assertTrue(used)
        self.assertLessEqual(used, set(ecc.KIT_VARS))

    def test_render_rejects_unknown_placeholder(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad-template.md")
            with open(bad, "w") as fh:
                fh.write("{{NAME}} and {{NOT_A_VAR}}\n")
            with self.assertRaises(SystemExit) as cm:
                ecc._render(bad, {k: "v" for k in ecc.KIT_VARS})
            self.assertIn("bad-template.md", str(cm.exception.code))
            self.assertIn("{{NOT_A_VAR}}", str(cm.exception.code))


class KitCommands(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.realpath(self.tmp.name)
        self.repo = os.path.join(self.home, "proj")
        os.makedirs(self.repo)
        self.env = dict(os.environ, HOME=self.home)
        r = self.kit("kit-new", self.repo, "--name", "Demo Project", "--slug", "demo",
                     "--milestone", "M2", "--gate", "tools/gate.sh", "--test-cmd", "make test")
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(os.path.join(self.repo, ".agents", "kit.json")) as fh:
            self.record = json.load(fh)

    def kit(self, *args):
        return subprocess.run([sys.executable, "-B", LIB, *args], capture_output=True,
                              text=True, env=self.env)

    def expected(self):
        """{project-relative destination: rendered text}, computed independently."""
        out = {}
        for rel, text in kit_templates().items():
            if rel == "gitignore":
                continue
            for k, v in self.record["vars"].items():
                text = text.replace("{{" + k + "}}", v)
            out[rel.replace("skills/run-project", "skills/run-demo")] = text
        return out

    def read(self, rel):
        with open(os.path.join(self.repo, rel), encoding="utf-8") as fh:
            return fh.read()

    def test_vars_recorded(self):
        v = self.record["vars"]
        self.assertEqual(sorted(v), sorted(ecc.KIT_VARS))
        self.assertEqual(v["NAME"], "Demo Project")
        self.assertEqual(v["SLUG"], "demo")
        self.assertEqual(v["REPO"], "~/proj")
        self.assertEqual((v["MILESTONE"], v["MILESTONE_LC"]), ("M2", "m2"))
        self.assertEqual(v["RUN_ID"], "demo-m2a")
        self.assertEqual((v["GATE_CMD"], v["FAST_GATE_CMD"]), ("tools/gate.sh", "tools/gate.sh"))
        self.assertEqual(v["TEST_CMD"], "make test")

    def test_every_template_rendered(self):
        expected = self.expected()
        self.assertIn(".agents/skills/run-demo/SKILL.md", expected)
        self.assertEqual(sorted(self.record["files"]), sorted(expected))
        for rel, text in expected.items():
            with self.subTest(rel):
                got = self.read(rel)
                self.assertEqual(got, text)
                self.assertEqual(PLACEHOLDER.findall(got), [])
                self.assertEqual(self.record["files"][rel], sha(text))
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".agents/skills/run-project")))
        self.assertFalse(os.path.exists(os.path.join(self.repo, "gitignore")))

    def test_skills_link_and_gitignore(self):
        link = os.path.join(self.repo, ".claude", "skills")
        self.assertTrue(os.path.islink(link))
        self.assertEqual(os.readlink(link), "../.agents/skills")
        with open(os.path.join(KIT, "gitignore")) as fh:
            want = [line for line in fh.read().splitlines() if line]
        have = self.read(".gitignore").splitlines()
        for line in want:
            self.assertIn(line, have)

    def test_diff_is_clean_after_new(self):
        r = self.kit("kit-diff", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("0 file(s) differ", r.stdout)

    def save_record(self):
        with open(os.path.join(self.repo, ".agents", "kit.json"), "w") as fh:
            json.dump(self.record, fh)

    def test_sync_updates_unchanged_files(self):
        rel = "AGENTS.md"
        old = "older kit text\n"
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(old)
        self.record["files"][rel] = sha(old)
        self.save_record()
        r = self.kit("kit-sync", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"updated  {rel}", r.stdout)
        self.assertEqual(self.read(rel), self.expected()[rel])
        with open(os.path.join(self.repo, ".agents", "kit.json")) as fh:
            self.assertEqual(json.load(fh)["files"][rel], sha(self.expected()[rel]))

    def test_sync_restores_deleted_file(self):
        rel = "CLAUDE.md"
        os.remove(os.path.join(self.repo, rel))
        r = self.kit("kit-sync", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"updated  {rel}", r.stdout)
        self.assertEqual(self.read(rel), self.expected()[rel])

    def test_sync_keeps_project_edits(self):
        rel = "GEMINI.md"
        edited = self.read(rel) + "\nproject-only rule\n"
        with open(os.path.join(self.repo, rel), "w") as fh:
            fh.write(edited)
        r = self.kit("kit-sync", self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"evolved  {rel} (changed in the project; see kit-diff)", r.stdout)
        self.assertEqual(self.read(rel), edited)
        r = self.kit("kit-diff", self.repo)
        self.assertIn("1 file(s) differ", r.stdout)
        self.assertIn("+project-only rule", r.stdout)


if __name__ == "__main__":
    unittest.main()
