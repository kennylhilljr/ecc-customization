"""The plan-json settings and plan template that ecc-kit new and sync deliver.

Run from the repository root: python3 -m unittest discover -s tests
Projects are temporary folders with a temporary HOME; no real project is touched.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "bin", "ecc-kit")
CONFIG = ".orchestration/plan-json.json"
TEMPLATE = ".orchestration/PLAN-TEMPLATE.md"
RECORD = ".agents/kit.json"


class KitPlanJson(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.join(tmp.name, "home")
        self.repo = os.path.join(tmp.name, "proj")
        os.makedirs(self.home)
        os.makedirs(self.repo)
        self.env = dict(os.environ, HOME=self.home)

    def kit(self, *args, cwd=None):
        res = subprocess.run([KIT, *args], cwd=cwd or self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        return res.stdout

    def path(self, rel):
        return os.path.join(self.repo, rel)

    def read(self, rel):
        with open(self.path(rel), encoding="utf-8") as fh:
            return fh.read()

    def write(self, rel, text):
        os.makedirs(os.path.dirname(self.path(rel)), exist_ok=True)
        with open(self.path(rel), "w", encoding="utf-8") as fh:
            fh.write(text)

    def new(self):
        self.kit("new", self.repo, "--name", "Demo", "--milestone", "M2")

    def make_old(self, keep_files=False):
        """Turn the project into one made by a kit without the two files."""
        with open(self.path(RECORD)) as fh:
            record = json.load(fh)
        for rel in (CONFIG, TEMPLATE):
            record["files"].pop(rel)
            if not keep_files:
                os.remove(self.path(rel))
        self.write(RECORD, json.dumps(record, indent=2) + "\n")

    def test_new_renders_both_files(self):
        self.new()
        cfg = json.loads(self.read(CONFIG))
        self.assertEqual(cfg["criterion_prds"], {"REQ": "docs/prd/PRD-v1.md"})
        self.assertIsNone(cfg["conformance_command"])
        template = self.read(TEMPLATE)
        self.assertNotRegex(template, r"\{\{[A-Z_]+\}\}")
        self.assertIn("| M2-02 | Settings loader |", template)
        for target in ("| M2-02 |", "| every unit |", "| every adapter unit |"):
            self.assertIn(target, template.split("### 2.2", 1)[1])
        self.assertIn("| Provides | Requires |", template)

    def test_sync_installs_into_an_older_project_and_generates(self):
        self.new()
        self.make_old()
        out = self.kit("sync", self.repo)
        self.assertIn(f"updated  {CONFIG}", out)
        self.assertIn(f"updated  {TEMPLATE}", out)
        with open(self.path(RECORD)) as fh:
            self.assertIn(CONFIG, json.load(fh)["files"])

        cfg = json.loads(self.read(CONFIG))
        cfg["package_path"] = "src/demo"
        self.write(CONFIG, json.dumps(cfg, indent=2) + "\n")
        self.write("docs/build/M2-plan-v1.md", self.read(TEMPLATE))
        self.kit("plan-json", "docs/build/M2-plan-v1.md", ".orchestration/plan-m2.json")
        units = json.loads(self.read(".orchestration/plan-m2.json"))["units"]
        self.assertEqual([u["id"] for u in units], ["M2-02", "M2-03"])
        u2, u3 = units
        self.assertEqual(u2["depends_on"], [])
        self.assertEqual(u2["scope"]["files"], ["src/demo/settings.py", "tests/unit/test_settings.py"])
        self.assertEqual(u2["acceptance"]["commands"], ["uv run pytest tests/unit/test_settings.py -q", "tools/ci.sh"])
        self.assertEqual((u2["provides"], u2["requires"]), (["settings"], []))
        self.assertEqual(u3["scope"]["files"], ["tests/fixtures/", "tests/unit/test_examples.py"])
        self.assertEqual((u3["provides"], u3["requires"]), ([], ["settings"]))
        note = "docs/build/M2-plan-v1.md section 2.2 lists clarifications for this unit; they are requirements."
        self.assertIn(note, u2["description"])
        self.assertIn(note, u3["description"])
        self.assertIn("docs/prd/PRD-v1.md", u2["description"])
        self.kit("plan-json", "--check", "docs/build/M2-plan-v1.md", ".orchestration/plan-m2.json")

    def test_repeated_sync_is_idempotent_and_keeps_local_edits(self):
        self.new()
        self.make_old()
        self.kit("sync", self.repo)
        before = {rel: self.read(rel) for rel in (CONFIG, TEMPLATE)}
        out = self.kit("sync", self.repo)
        self.assertNotIn(CONFIG, out)
        self.assertNotIn(TEMPLATE, out)
        self.assertEqual({rel: self.read(rel) for rel in before}, before)

        self.write(CONFIG, before[CONFIG].replace("src/my_package/", "src/mine/"))
        self.write(TEMPLATE, before[TEMPLATE] + "\nLocal note.\n")
        out = self.kit("sync", self.repo)
        self.assertIn(f"evolved  {CONFIG}", out)
        self.assertIn(f"evolved  {TEMPLATE}", out)
        self.assertIn("src/mine/", self.read(CONFIG))
        self.assertTrue(self.read(TEMPLATE).endswith("Local note.\n"))

    def test_sync_keeps_local_files_absent_from_the_old_record(self):
        self.new()
        self.make_old(keep_files=True)
        self.write(CONFIG, '{"package_path": "src/own/"}\n')
        self.write(TEMPLATE, "# our own template\n")
        out = self.kit("sync", self.repo)
        self.assertIn(f"evolved  {CONFIG}", out)
        self.assertEqual(self.read(CONFIG), '{"package_path": "src/own/"}\n')
        self.assertEqual(self.read(TEMPLATE), "# our own template\n")

    def test_templates_have_only_known_placeholders(self):
        with open(os.path.join(ROOT, "lib", "ecctools.py")) as fh:
            source = fh.read()
        known = set(re.findall(r'"([A-Z_]+)"', source.split("KIT_VARS = ", 1)[1].split("]", 1)[0]))
        for rel in (CONFIG, TEMPLATE):
            with open(os.path.join(ROOT, "kit", rel)) as fh:
                used = set(re.findall(r"\{\{([A-Z_]+)\}\}", fh.read()))
            self.assertLessEqual(used, known, rel)


if __name__ == "__main__":
    unittest.main()
