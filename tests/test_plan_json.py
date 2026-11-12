"""ecc-kit plan-json end to end: the wrapper, regression baselines, quoting and --check.

Run from the repository root: python3 -m unittest discover -s tests
Each test builds a temporary project; nothing outside it is written.
"""
import json
import os
import re
import shlex
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KIT = os.path.join(ROOT, "bin", "ecc-kit")
FIX = os.path.join(ROOT, "tests", "fixtures", "plan_json")
PLAN_REL = "docs/build/M0-plan-v4.md"

HEADER = ("| # | Task | Criteria | Depends on | Persona | Implements | Files (scope) | Risk | Status |"
          " Provides | Requires |\n| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")


def ecc_kit(*args, cwd):
    return subprocess.run([KIT, *args], cwd=cwd, capture_output=True, text=True)


def normalize(data):
    """Strip one pair of double quotes from each conformance -k expression."""
    for unit in data["units"]:
        unit["acceptance"]["commands"] = [
            re.sub(r'(-k )"([^"]*)"', r"\1\2", c, count=1) for c in unit["acceptance"]["commands"]]
    return data


def prds_from_baseline(data):
    names = set()
    for unit in data["units"]:
        names.update(re.findall(r"docs/prd/components/PRD-[a-z]+-v\d+\.md", unit["description"]))
    return names


class Project:
    def __init__(self, config, plan_text=None, plan_rel=PLAN_REL, prds=()):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self.tmp.name)
        os.makedirs(os.path.join(self.root, ".orchestration"))
        with open(os.path.join(self.root, ".orchestration", "plan-json.json"), "w") as fh:
            json.dump(config, fh) if isinstance(config, dict) else fh.write(config)
        self.plan_rel = plan_rel
        if plan_text is not None:
            self.write(plan_rel, plan_text)
        for p in prds:
            self.write(p, "")

    def write(self, rel, text):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def read(self, rel):
        with open(os.path.join(self.root, rel), encoding="utf-8") as fh:
            return fh.read()

    def run(self, *args, cwd=None):
        return ecc_kit("plan-json", *args, cwd=cwd or self.root)

    def close(self):
        self.tmp.cleanup()


def research_config():
    with open(os.path.join(FIX, "research-mcp.config.json")) as fh:
        return json.load(fh)


def generic_config(**over):
    cfg = {
        "package_path": "src/pkg/",
        "adapter_folder": "src/pkg/sources",
        "adapter_exclude": ["base"],
        "adapter_ids": {"open_alex": "openalex"},
        "criterion_prds": {"REQ": "docs/prd.md"},
        "description_template": "{uid}|{plan}|{implemented}|{note}|{criteria}|{prds}|{rules}",
        "rules": "R",
        "test_command": "pytest {tests} -q",
        "conformance_command": "pytest tests/test_conformance.py -k {expression} -q",
        "gate_command": "tools/ci.sh",
    }
    cfg.update(over)
    return cfg


def row(uid, files, deps="none", status="planned", criteria="REQ-1", provides="none", requires="none"):
    return (f"| {uid} | Task {uid} | {criteria} | {deps} | `implementer` | `docs/d.md` (§1) | {files} | low "
            f"| {status} | {provides} | {requires} |\n")


def plan_text(rows, clar=""):
    return f"# P\n\n## 2. Tasks\n\n{HEADER}{rows}\n### 2.1 Notes\n\n{clar}\n## 3. Verification\n"


class Baselines(unittest.TestCase):
    def regenerate(self, rev):
        with open(os.path.join(FIX, f"{rev}-plan.json")) as fh:
            baseline = json.load(fh)
        with open(os.path.join(FIX, "5235c26-plan.json")) as fh:
            prds = prds_from_baseline(json.load(fh))
        with open(os.path.join(FIX, f"{rev}-plan.md")) as fh:
            text = fh.read()
        proj = Project(research_config(), text, prds=sorted(prds))
        self.addCleanup(proj.close)
        res = proj.run(PLAN_REL, ".orchestration/plan-m0.json")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), f"{len(baseline['units'])} units")
        return proj, baseline, json.loads(proj.read(".orchestration/plan-m0.json"))

    def test_5235c26_matches_after_quote_normalization(self):
        proj, baseline, out = self.regenerate("5235c26")
        self.assertEqual(len(out["units"]), 18)
        self.assertEqual(normalize(out), baseline)
        text = proj.read(".orchestration/plan-m0.json")
        self.assertTrue(text.startswith('{\n "units": [\n  {\n   "schema_version"'))
        self.assertTrue(text.endswith("}\n"))

    def test_5235c26_quotes_every_conformance_expression(self):
        _, _, out = self.regenerate("5235c26")
        conf = {u["id"]: c for u in out["units"] for c in u["acceptance"]["commands"] if " -k " in c}
        self.assertEqual(conf, {
            "M0-10": 'uv run pytest tests/sources/test_conformance.py -k "arxiv" -q',
            "M0-11": 'uv run pytest tests/sources/test_conformance.py -k "crossref" -q',
            "M0-12": 'uv run pytest tests/sources/test_conformance.py -k "openalex" -q',
        })

    def test_27baf2d_is_exactly_empty(self):
        proj, _, _ = self.regenerate("27baf2d")
        with open(os.path.join(FIX, "27baf2d-plan.json")) as fh:
            self.assertEqual(proj.read(".orchestration/plan-m0.json"), fh.read())

    def test_m0_01_override_and_no_test_behavior(self):
        cfg = research_config()
        rows = (row("M0-01", "`pyproject.toml`, `tests/unit/test_version.py`", criteria="PLAT-1") +
                row("M0-02", "`core/x.py`", criteria="PLAT-2"))
        proj = Project(cfg, plan_text(rows), prds=["docs/prd/components/PRD-platform-v4.md"])
        self.addCleanup(proj.close)
        res = proj.run(PLAN_REL, "out.json", "--milestone", "M0")
        self.assertEqual(res.returncode, 0, res.stderr)
        units = json.loads(proj.read("out.json"))["units"]
        self.assertEqual(units[0]["acceptance"]["commands"],
                         ["uv sync --frozen", "uv run pytest tests/unit -q", "tools/ci.sh --python-only"])
        self.assertEqual(units[1]["acceptance"]["commands"], ["uv run pytest  -q", "tools/ci.sh --python-only"])


class Generation(unittest.TestCase):
    def project(self, rows, clar="", **over):
        proj = Project(generic_config(**over), plan_text(rows, clar), plan_rel="docs/build/plan.md",
                       prds=["docs/prd.md"])
        self.addCleanup(proj.close)
        return proj

    def units(self, proj, *args):
        res = proj.run(proj.plan_rel, "build/out.json", *args)
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(proj.read("build/out.json"))["units"]

    def conformance(self, unit):
        return [c for c in unit["acceptance"]["commands"] if "test_conformance" in c]

    def test_single_and_multiple_adapter_quoting(self):
        rows = (row("M0-01", "`sources/arxiv.py`, `tests/test_arxiv.py`") +
                row("M0-02", "`tests/test_multi.py`, `sources/base.py`, `sources/arxiv.py`, "
                    "`sources/open_alex.py`, `sources/crossref.py`, `sources/arxiv.py`"))
        u1, u2 = self.units(self.project(rows))
        self.assertEqual(self.conformance(u1), ['pytest tests/test_conformance.py -k "arxiv" -q'])
        (multi,) = self.conformance(u2)
        self.assertEqual(multi, 'pytest tests/test_conformance.py -k "arxiv or openalex or crossref" -q')
        self.assertEqual(shlex.split(multi),
                         ["pytest", "tests/test_conformance.py", "-k", "arxiv or openalex or crossref", "-q"])
        self.assertEqual(u2["acceptance"]["commands"][0], "pytest tests/test_multi.py -q")
        self.assertEqual(u2["acceptance"]["commands"][-1], "tools/ci.sh")

    def test_support_modules_are_not_adapters(self):
        rows = row("M0-01", "`sources/base.py`, `sources/__init__.py`, `tests/test_base.py`")
        (u,) = self.units(self.project(rows))
        self.assertEqual(u["acceptance"]["commands"], ["pytest tests/test_base.py -q", "tools/ci.sh"])

    def test_milestone_selection_and_cross_milestone_done(self):
        rows = (row("M0-01", "`a.py`", status="done") + row("M1-01", "`b.py`", deps="M0-01") +
                row("M1-02", "`c.py`", deps="M1-01, M0-01"))
        proj = self.project(rows)
        units = self.units(proj, "--milestone", "M1")
        self.assertEqual([(u["id"], u["depends_on"]) for u in units], [("M1-01", []), ("M1-02", ["M1-01"])])
        res = proj.run(proj.plan_rel, "x.json")
        self.assertEqual(res.returncode, 2)
        self.assertIn("--milestone", res.stderr)

    def test_clarification_targets(self):
        rows = (row("M0-01", "`a.py`") + row("M0-02", "`b.py`") + row("M0-03", "`sources/arxiv.py`"))
        note = " docs/build/plan.md section 2.2 lists clarifications for this unit; they are requirements."

        def notes(clar_rows):
            clar = "### 2.2 Clarifications\n\n| Unit | Source | Requirement |\n| --- | --- | --- |\n" + clar_rows
            return [u["description"].split("|")[3] for u in self.units(self.project(rows, clar))]

        self.assertEqual(notes("| M0-02 | x | mentions every unit in prose |\n"), ["", note, ""])
        self.assertEqual(notes("| every unit | x | y |\n"), [note, note, note])
        self.assertEqual(notes("| every adapter unit | x | y |\n"), ["", "", note])

    def test_description_fields(self):
        rows = row("M0-01", "`a.py`", criteria="REQ-1, REQ-2")
        (u,) = self.units(self.project(rows))
        self.assertEqual(u["description"], "M0-01|docs/build/plan.md|docs/d.md (§1)||REQ-1, REQ-2|docs/prd.md|R")
        self.assertEqual(u["scope"]["files"], ["src/pkg/a.py"])
        self.assertEqual(u["capabilities"], {"network": False, "secrets": []})
        self.assertEqual(u["budget"], {"attempts": 2, "minutes": 30, "maximum_cost_usd": 5})
        self.assertEqual(u["rollback"], "Revert the commit.")
        self.assertEqual(u["routing"], {"initial_tier": 0, "maximum_tier": 2,
                                        "reviewer_must_differ_from_author": True})

    def test_provides_and_requires(self):
        rows = (row("M0-01", "`a.py`", provides="`store`, `ids`") +
                row("M0-02", "`b.py`", deps="M0-01", requires="store"))
        u1, u2 = self.units(self.project(rows))
        self.assertEqual((u1["provides"], u1["requires"]), (["store", "ids"], []))
        self.assertEqual((u2["provides"], u2["requires"]), ([], ["store"]))
        self.assertEqual(list(u1)[-2:], ["provides", "requires"])

    def test_repeatable_and_paths_from_invocation_folder(self):
        proj = self.project(row("M0-01", "`a.py`"))
        first = self.units(proj)
        text = proj.read("build/out.json")
        sub = os.path.join(proj.root, "docs")
        res = proj.run("build/plan.md", "../build/out.json", cwd=sub)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(proj.read("build/out.json"), text)
        self.assertEqual(first[0]["description"].split("|")[1], "docs/build/plan.md")


class Check(unittest.TestCase):
    def setUp(self):
        self.proj = Project(generic_config(), plan_text(row("M0-01", "`a.py`")), plan_rel="plan.md",
                            prds=["docs/prd.md"])
        self.addCleanup(self.proj.close)

    def test_missing_output_creates_nothing(self):
        res = self.proj.run("plan.md", "new/dir/out.json", "--check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("missing", res.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.proj.root, "new")))

    def test_fresh_and_stale(self):
        self.assertEqual(self.proj.run("plan.md", "out.json").returncode, 0)
        self.assertEqual(self.proj.run("plan.md", "out.json", "--check").returncode, 0)
        self.proj.write("out.json", self.proj.read("out.json").replace("Task M0-01", "Old"))
        before = self.proj.read("out.json")
        res = self.proj.run("plan.md", "out.json", "--check")
        self.assertEqual(res.returncode, 1)
        self.assertIn("stale", res.stderr)
        self.assertEqual(self.proj.read("out.json"), before)

    def test_invalid_input_keeps_existing_output(self):
        self.proj.write("out.json", "keep me\n")
        self.proj.write("plan.md", plan_text(row("M0-01", "`a.py`", criteria="NOPE-1")))
        for args in ((), ("--check",)):
            res = self.proj.run("plan.md", "out.json", *args)
            self.assertEqual(res.returncode, 2)
            self.assertIn("plan-json: plan.md:", res.stderr)
            self.assertEqual(res.stderr.count("plan-json:"), 1)
            self.assertEqual(self.proj.read("out.json"), "keep me\n")
        self.assertEqual(sorted(os.listdir(self.proj.root)), [".orchestration", "docs", "out.json", "plan.md"])

    def test_bad_config_names_the_file(self):
        self.proj.write(".orchestration/plan-json.json", '{"rules": 1}')
        res = self.proj.run("plan.md", "out.json")
        self.assertEqual(res.returncode, 2)
        self.assertIn("plan-json.json: 'rules' must be a str", res.stderr)


class Wrapper(unittest.TestCase):
    def test_usage_lists_every_command(self):
        res = ecc_kit(cwd=ROOT)
        self.assertEqual(res.returncode, 2)
        for cmd in ("ecc-kit new", "ecc-kit diff", "ecc-kit sync",
                    "ecc-kit plan-json <plan.md> <out.json> [--milestone M1] [--check]", "--fast-gate"):
            self.assertIn(cmd, res.stdout)
        self.assertNotIn("HERE=", res.stdout)

    def test_help(self):
        res = ecc_kit("plan-json", "--help", cwd=ROOT)
        self.assertEqual(res.returncode, 0)
        self.assertIn("usage: ecc-kit plan-json", res.stdout)
        self.assertIn("--check", res.stdout)


if __name__ == "__main__":
    unittest.main()
