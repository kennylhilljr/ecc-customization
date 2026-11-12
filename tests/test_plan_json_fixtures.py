"""The pinned research-mcp generator and plan fixtures for ecc-kit plan-json.

Run from the repository root: python3 -m unittest discover -s tests
The tests read local files only; they neither fetch nor run the historical generator.
"""
import hashlib
import json
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "plan_json")
EXPECTED = {
    "gen_m0_plan.py.txt": ("5235c26", "tools/gen_m0_plan.py", "ce22565eaa9532330fdc02e31498ae55e0487a34"),
    "5235c26-plan.md": ("5235c26", "docs/build/M0-plan-v4.md", "38c93992134564731a709705451856d22858a4bc"),
    "5235c26-plan.json": ("5235c26", ".orchestration/plan-m0.json", "dc6c6b1101bda8720acc298f900a9139403dba36"),
    "27baf2d-plan.md": ("27baf2d", "docs/build/M0-plan-v4.md", "0fd8b2c8f57a2cd10fca7be729dc29a8dd1732e5"),
    "27baf2d-plan.json": ("27baf2d", ".orchestration/plan-m0.json", "badd7297493f62c0ce195c760664b60b340ef240"),
}


def blob_sha(path):
    with open(path, "rb") as fh:
        data = fh.read()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def pending_ids(plan_path):
    """Task ids whose status is not done, read with a plain regex (not the generator)."""
    with open(plan_path, encoding="utf-8") as fh:
        text = fh.read()
    tasks = text.split("## 2. Tasks", 1)[1].split("\n### ", 1)[0]
    out = []
    for line in tasks.splitlines():
        m = re.match(r"^\| (M\d+-\d+) \|", line)
        if m and line.rstrip().rstrip("|").rsplit("|", 1)[1].strip() != "done":
            out.append(m.group(1))
    return out


class Sources(unittest.TestCase):
    def test_sources_record(self):
        with open(os.path.join(FIX, "SOURCES.json")) as fh:
            sources = json.load(fh)
        self.assertEqual(sources["repository"], "kennylhilljr/research-mcp")
        self.assertEqual(sorted(sources["files"]), sorted(EXPECTED))
        for name, (rev, path, sha) in EXPECTED.items():
            entry = sources["files"][name]
            self.assertEqual((entry["revision"], entry["path"], entry["blob_sha"]), (rev, path, sha), name)

    def test_blob_hashes(self):
        for name, (_, _, sha) in EXPECTED.items():
            self.assertEqual(blob_sha(os.path.join(FIX, name)), sha, name)


class Baselines(unittest.TestCase):
    def load(self, name):
        with open(os.path.join(FIX, name)) as fh:
            return json.load(fh)

    def test_5235c26_has_18_units(self):
        units = self.load("5235c26-plan.json")["units"]
        self.assertEqual(len(units), 18)
        self.assertEqual(units[0]["id"], "M0-06")

    def test_27baf2d_is_empty(self):
        self.assertEqual(self.load("27baf2d-plan.json"), {"units": []})

    def test_pending_tasks_match_units(self):
        for rev in ("5235c26", "27baf2d"):
            ids = [u["id"] for u in self.load(f"{rev}-plan.json")["units"]]
            self.assertEqual(pending_ids(os.path.join(FIX, f"{rev}-plan.md")), ids, rev)


if __name__ == "__main__":
    unittest.main()
