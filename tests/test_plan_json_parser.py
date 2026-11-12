"""Configuration and task-table parsing for ecc-kit plan-json (lib/ecctools.py).

Run from the repository root: python3 -m unittest discover -s tests
Everything runs on strings and temporary folders.
"""
import importlib.util
import json
import os
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIX = os.path.join(ROOT, "tests", "fixtures", "plan_json")
_spec = importlib.util.spec_from_file_location("ecctools", os.path.join(ROOT, "lib", "ecctools.py"))
ecctools = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ecctools)
PlanJsonError = ecctools.PlanJsonError

HEADER = ("| # | Task | Criteria | Depends on | Persona | Implements | Files (scope) | Risk | Status |\n"
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")


def plan(rows, header=HEADER, clar="", after="### 2.1 Notes\n\n| M0-99 | x | y |\n"):
    return f"# Plan\n\n## 2. Tasks\n\nIntro text.\n\n{header}{rows}\n{after}\n{clar}"


def row(uid, files="`tests/test_a.py`", deps="none", status="planned", risk="low",
        criteria="REQ-1", extra=""):
    return (f"| {uid} | Task {uid} | {criteria} | {deps} | `implementer` | `docs/d.md` (§1) | {files} "
            f"| {risk} | {status} |{extra}\n")


def config(**over):
    cfg = json.loads(json.dumps(ecctools.PLAN_DEFAULTS))
    cfg.update(over)
    return cfg


class Config(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        os.makedirs(os.path.join(self.root, ".orchestration"))
        self.path = os.path.join(self.root, ".orchestration", "plan-json.json")

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, data):
        with open(self.path, "w") as fh:
            fh.write(data if isinstance(data, str) else json.dumps(data))

    def test_found_upward_from_the_plan(self):
        self.write({})
        os.makedirs(os.path.join(self.root, "docs", "build"))
        plan_path = os.path.join(self.root, "docs", "build", "M0.md")
        self.assertEqual(ecctools.find_plan_config(plan_path),
                         (self.root, self.path))

    def test_missing_config(self):
        with self.assertRaisesRegex(PlanJsonError, "no .orchestration"):
            ecctools.find_plan_config(os.path.join(tempfile.gettempdir(), "nowhere", "x", "p.md"))

    def test_defaults_and_package_slash(self):
        self.write({"package_path": "src/pkg"})
        cfg = ecctools.load_plan_config(self.path)
        self.assertEqual(cfg["package_path"], "src/pkg/")
        self.assertEqual(cfg["unit_defaults"]["budget"], {"attempts": 2, "minutes": 30, "maximum_cost_usd": 5})
        self.assertEqual(cfg["unit_defaults"]["rollback"], "Revert the commit.")
        self.assertIs(cfg["unit_defaults"]["capabilities"]["network"], False)

    def test_invalid_configurations(self):
        cases = [
            ("{", "not valid JSON"),
            ("[]", "must be a JSON object"),
            ({"nope": 1}, "unknown keys"),
            ({"package_path": 3}, "'package_path' must be"),
            ({"root_files": "pyproject.toml"}, "'root_files' must be a list"),
            ({"adapter_ids": {"a": 1}}, "'adapter_ids' must map"),
            ({"adapter_folder": "/abs/sources"}, "project-relative"),
            ({"adapter_folder": "../sources"}, "project-relative"),
            ({"acceptance_overrides": {"M0-01": "uv sync"}}, "acceptance_overrides.M0-01"),
            ({"unit_defaults": {"budget": 3}}, "unit_defaults.budget"),
            ({"unit_defaults": {"other": 3}}, "unknown keys in 'unit_defaults'"),
            ({"description_template": "{uid} {oops}"}, r"unknown placeholders \['oops'\]"),
            ({"description_template": "{uid"}, "bad template"),
            ({"test_command": "pytest {files}"}, "'test_command' has unknown"),
            ({"conformance_command": "pytest -k x"}, "must contain {expression}"),
            ({"fixture_names": ["a.{kind}"]}, "unknown placeholders"),
        ]
        for data, msg in cases:
            with self.subTest(data=data):
                self.write(data)
                with self.assertRaisesRegex(PlanJsonError, msg) as ctx:
                    ecctools.load_plan_config(self.path)
                self.assertIn(self.path, str(ctx.exception))

    def test_research_mcp_config(self):
        cfg = ecctools.load_plan_config(os.path.join(FIX, "research-mcp.config.json"))
        self.assertEqual(cfg["package_path"], "src/research_mcp/")
        self.assertEqual(len(cfg["fixture_names"]), 7)
        self.assertEqual(cfg["fixture_extensions"], {"tests/sources/arxiv/fixtures": "xml"})
        self.assertEqual(cfg["acceptance_overrides"]["M0-01"], ["uv sync --frozen", "uv run pytest tests/unit -q"])
        self.assertEqual(sorted(cfg["criterion_prds"]), ["CACHE", "HLTH", "PLAT", "SEC", "SRC", "SRCH"])
        self.assertEqual(cfg["unit_defaults"]["budget"]["attempts"], 4)


class Cells(unittest.TestCase):
    def test_escaped_pipes_and_code_spans(self):
        cells = ecctools.split_table_row(r"| a \| b | `x | y` | ``c ` | d`` | `e` f |")
        self.assertEqual(cells, ["a | b", "`x | y`", "``c ` | d``", "`e` f"])

    def test_trailing_cell_without_pipe(self):
        self.assertEqual(ecctools.split_table_row("| a | b"), ["a", "b"])


class Tables(unittest.TestCase):
    def parse(self, text, milestone=None, cfg=None):
        return ecctools.parse_plan(text, cfg or config(), milestone, "p.md")

    def test_order_done_rows_and_dependencies(self):
        text = plan(row("M0-01", status="done") + row("M0-02", deps="M0-01") +
                    row("M0-03", deps="M0-01, M0-02"))
        rows, _ = self.parse(text)
        self.assertEqual([r["#"] for r in rows], ["M0-02", "M0-03"])
        self.assertEqual([r["_deps"] for r in rows], [[], ["M0-02"]])

    def test_done_ids_collected_across_milestones(self):
        text = plan(row("M0-01", status="done") + row("M0-02") +
                    row("M1-01", deps="M0-01, M0-02") + row("M1-02", status="done") +
                    row("M1-03", deps="M1-02, M1-01"))
        rows, _ = self.parse(text, "M1")
        self.assertEqual([(r["#"], r["_deps"]) for r in rows],
                         [("M1-01", ["M0-02"]), ("M1-03", ["M1-01"])])

    def test_milestone_inference(self):
        rows, _ = self.parse(plan(row("M0-01", status="done")))
        self.assertEqual(rows, [])
        both = plan(row("M0-01") + row("M1-01"))
        with self.assertRaisesRegex(PlanJsonError, "pick one with --milestone"):
            self.parse(both)
        with self.assertRaisesRegex(PlanJsonError, "no task of milestone M2"):
            self.parse(both, "M2")

    def test_table_stops_at_next_subsection(self):
        rows, _ = self.parse(plan(row("M0-01")))
        self.assertEqual([r["#"] for r in rows], ["M0-01"])

    def test_malformed_tables(self):
        with self.assertRaisesRegex(PlanJsonError, "no section"):
            self.parse("# nothing\n")
        with self.assertRaisesRegex(PlanJsonError, "has no table"):
            self.parse("## 2. Tasks\n\nno table\n")
        with self.assertRaisesRegex(PlanJsonError, r"lacks columns \['Risk'\]"):
            self.parse(plan("| M0-01 | a | b | none | p | i | f | done |\n",
                            header=HEADER.replace("| Risk ", "")))
        with self.assertRaisesRegex(PlanJsonError, "unknown columns"):
            self.parse(plan("", header=HEADER.replace("| Status |", "| Status | Owner |")))
        with self.assertRaisesRegex(PlanJsonError, r"p.md:\d+: row has 8 cells"):
            self.parse(plan("| M0-01 | a | b | none | p | i | f | low |\n"))
        with self.assertRaisesRegex(PlanJsonError, "not PREFIX-NUMBER"):
            self.parse(plan(row("first")))
        with self.assertRaisesRegex(PlanJsonError, "appears twice"):
            self.parse(plan(row("M0-01") + row("M0-01")))

    def test_header_by_name_and_inline_code(self):
        header = ("| Status | # | Task | Criteria | Depends on | Persona | Implements | Files (scope) | Risk |\n"
                  "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")
        text = plan("| planned | M0-01 | Use `a|b` | REQ-1 | none | p | `x` | `tests/test_a.py` | low |\n",
                    header=header)
        rows, _ = self.parse(text)
        self.assertEqual(rows[0]["Task"], "Use `a|b`")
        self.assertEqual(rows[0]["Risk"], "low")

    def test_clarification_targets_use_the_first_cell(self):
        clar = ("### 2.2 Clarifications\n\n| Unit | Source | Requirement |\n| --- | --- | --- |\n"
                "| M0-02 | x | applies to every unit and every adapter unit in prose |\n"
                "| every adapter unit | x | y |\n")
        _, targets = self.parse(plan(row("M0-01"), clar=clar))
        self.assertEqual(targets, ["M0-02", "every adapter unit"])


class Scope(unittest.TestCase):
    def cfg(self):
        return ecctools.load_plan_config(os.path.join(FIX, "research-mcp.config.json"))

    def test_expansion(self):
        files = ("`core/ids.py`, `src/other/x.py`, `tests/a/test_b.py`, `tools/ci.sh`, `docs/x.md`, "
                 "`.github/workflows/ci.yml`, `pyproject.toml`, `uv.lock`, `sources/data/`, "
                 "`tests/sources/arxiv/fixtures/*`, `tests/sources/crossref/fixtures/*`")
        out = ecctools._scope(files, self.cfg(), "p.md:1")
        self.assertEqual(out[:9], [
            "src/research_mcp/core/ids.py", "src/other/x.py", "tests/a/test_b.py", "tools/ci.sh",
            "docs/x.md", ".github/workflows/ci.yml", "pyproject.toml", "uv.lock",
            "src/research_mcp/sources/data/"])
        self.assertEqual(out[9], "tests/sources/arxiv/fixtures/search_ok.xml")
        self.assertIn("tests/sources/arxiv/fixtures/err_429.json", out)
        self.assertIn("tests/sources/crossref/fixtures/malformed.json", out)
        self.assertEqual(len(out), 9 + 14)

    def test_wildcard_needs_fixture_names(self):
        with self.assertRaisesRegex(PlanJsonError, "fixture_names"):
            ecctools._scope("`tests/fx/*`", config(), "p.md:1")

    def test_adapters_anywhere_in_scope(self):
        files = ["tests/x/test_a.py", "src/research_mcp/sources/registry.py",
                 "src/research_mcp/sources/__init__.py", "src/research_mcp/sources/crossref.py",
                 "src/research_mcp/sources/sub/deep.py", "src/research_mcp/sources/arxiv.py"]
        self.assertEqual(ecctools._adapters(files, self.cfg()), ["crossref", "arxiv"])
        self.assertEqual(ecctools._adapters(files, config()), [])

    def test_provides_requires_tokens(self):
        self.assertEqual(ecctools._tokens("`a`, b ,`c-d`"), ["a", "b", "c-d"])
        self.assertEqual(ecctools._tokens(" none "), [])
        self.assertEqual(ecctools._tokens(""), [])


class Prds(unittest.TestCase):
    def test_numeric_version_selection(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "docs"))
            for v in (2, 9, 10):
                open(os.path.join(root, "docs", f"PRD-x-v{v}.md"), "w").close()
            cfg = config(criterion_prds={"X": "docs/PRD-x-v*.md", "Y": "docs/fixed.md", "Z": "docs/none-v*.md"})
            self.assertEqual(ecctools._resolve_prd("X", cfg, root, "p"), "docs/PRD-x-v10.md")
            self.assertEqual(ecctools._resolve_prd("Y", cfg, root, "p"), "docs/fixed.md")
            with self.assertRaisesRegex(PlanJsonError, "matches no versioned file"):
                ecctools._resolve_prd("Z", cfg, root, "p")
            with self.assertRaisesRegex(PlanJsonError, "no 'criterion_prds' entry for criterion prefix Q"):
                ecctools._resolve_prd("Q", cfg, root, "p")


class Units(unittest.TestCase):
    def test_unknown_risk_is_an_error(self):
        cfg = config(criterion_prds={"REQ": "docs/prd.md"})
        with self.assertRaisesRegex(PlanJsonError, r"p.md:\d+: risk 'severe'"):
            ecctools.build_units(plan(row("M0-01", risk="severe")), cfg, "/x", "p.md", None, "p.md")

    def test_provides_requires_columns(self):
        header = HEADER.replace("| Status |", "| Status | Provides | Requires |").replace(
            "| --- |\n", "| --- | --- | --- |\n")
        cfg = config(criterion_prds={"REQ": "docs/prd.md"})
        units = ecctools.build_units(plan(row("M0-01", extra=" `a`, b | none |"), header=header),
                                     cfg, "/x", "p.md", None, "p.md")
        self.assertEqual((units[0]["provides"], units[0]["requires"]), (["a", "b"], []))
        plain = ecctools.build_units(plan(row("M0-01")), cfg, "/x", "p.md", None, "p.md")
        self.assertNotIn("provides", plain[0])
        self.assertNotIn("requires", plain[0])


if __name__ == "__main__":
    unittest.main()
