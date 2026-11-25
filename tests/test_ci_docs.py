"""Read-only checks for the check workflow and the documents that describe it.

Compare the workflow's indented sections directly, without a YAML dependency.
Exact lines enforce nesting, quoting and the allowed keys/steps.
Paths are relative to this file so these tests also run in check-runner copies.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ".github/workflows/check.yml"
CHECK_DESCRIPTIONS = {
    "unit-tests": r"isolated Python test suite",
    "bash-syntax": r"each Bash input separately",
    "sh-syntax": r"each POSIX shell script separately",
    "python-syntax": r"both Python helpers with `ast`",
    "ruff-lint": r"`ruff check` .*Python 3\.9",
    "ecctools-help": r"helper entry point",
    "kit-help": r"kit wrapper help path",
    "bootstrap-help": r"safe bootstrap help path",
    "secret-scan": r"scan .*maintained .*content",
    "plist-lint": r"lint .*launchd property lists",
    "plugin-tests": r"GitHub event router Node tests",
    "diff-check": r"working tree diff for whitespace errors",
}
PINNED_ACTION = re.compile(
    r"^ +- uses: (?P<action>[a-z-]+/[a-z-]+)@(?P<sha>[0-9a-f]{40})"
    r" # (?P<tag>v\d+\.\d+\.\d+)$"
)


def markdown_section(text, heading):
    """Return only the requested level-two section, not neighboring prose."""
    match = re.search(
        rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)",
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    if match is None:
        raise AssertionError("Missing section: " + heading)
    return match.group(1)


class CheckWorkflow(unittest.TestCase):
    def setUp(self):
        self.workflow = (ROOT / WORKFLOW).read_text(encoding="utf-8")
        self.sections = {}
        current = None
        for line in self.workflow.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            self.assertNotIn("\t", line)
            if not line.startswith(" "):
                key, separator, _ = line.partition(":")
                self.assertEqual(separator, ":")
                self.assertNotIn(key, self.sections, "Duplicate top-level key")
                self.sections[key] = [line]
                current = key
            else:
                self.assertIsNotNone(current, "Content before top-level key")
                self.sections[current].append(line)

    def test_top_level_keys(self):
        self.assertEqual(
            set(self.sections),
            {"name", "on", "permissions", "concurrency", "jobs"},
        )
        self.assertEqual(self.sections["name"], ["name: Repository checks"])

    def test_events_and_main_push_restriction(self):
        self.assertEqual(self.sections["on"], [
            "on:",
            "  pull_request:",
            "  push:",
            "    branches:",
            "      - main",
        ])

    def test_top_level_read_only_permissions(self):
        self.assertEqual(self.sections["permissions"], [
            "permissions:",
            "  contents: read",
        ])

    def test_job_matrix_actions_inputs_and_final_command(self):
        steps = [
            PINNED_ACTION.sub(r"      - uses: \g<action>", line)
            for line in self.sections["jobs"]
        ]
        self.assertEqual(steps, [
            "jobs:",
            "  check:",
            "    runs-on: macos-latest",
            "    timeout-minutes: 30",
            "    strategy:",
            "      fail-fast: false",
            "      matrix:",
            "        python-version: ['3.9', '3.13']",
            "    steps:",
            "      - uses: actions/checkout",
            "        with:",
            "          persist-credentials: false",
            "      - uses: actions/setup-python",
            "        with:",
            "          python-version: ${{ matrix.python-version }}",
            "      - uses: actions/setup-node",
            "        with:",
            "          node-version: '24'",
            "          package-manager-cache: false",
            "      - run: python -m pip install ruff==0.15.1",
            "      - run: sh scripts/check.sh",
        ])

    def test_every_action_is_pinned_to_a_full_sha(self):
        uses = [line for line in self.workflow.splitlines()
                if re.match(r"^\s*-?\s*uses:", line)]
        self.assertEqual(len(uses), 3)
        for line in uses:
            with self.subTest(line=line):
                self.assertRegex(line, PINNED_ACTION)

    def test_only_pull_request_runs_are_cancelled(self):
        self.assertEqual(self.sections["concurrency"], [
            "concurrency:",
            "  group: check-${{ github.event_name == 'pull_request'"
            " && github.ref || github.run_id }}",
            "  cancel-in-progress: true",
        ])

    def test_node_version_matches_stack(self):
        documented = re.findall(r"^          node-version: '([^']+)'$",
                                self.workflow, re.MULTILINE)
        configured = re.findall(r'^NODE_VERSION="([^"]+)"$',
                               (ROOT / "stack.conf").read_text(encoding="utf-8"),
                               re.MULTILINE)
        self.assertEqual(len(documented), 1)
        self.assertEqual(len(configured), 1)
        self.assertEqual(documented, configured)

    def test_forbidden_workflow_content(self):
        self.assertNotRegex(self.workflow, r"(?i)\bsecrets\s*[.\[]")
        self.assertNotIn("pull_request_target", self.workflow)
        self.assertNotRegex(self.workflow, r"(?i)\bwrite(?:-all)?\b")
        self.assertNotRegex(self.workflow, r"(?i)^\s*cache:")


class CIDocs(unittest.TestCase):
    def setUp(self):
        self.document = (ROOT / "docs/ci.md").read_text(encoding="utf-8")

    def test_explanation_and_forbidden_content(self):
        for required in (
            "`.github/workflows/check.yml`", "`sh scripts/check.sh`",
            "Python 3.9", "Python 3.13", "Node 24", "`NODE_VERSION`",
            "`stack.conf`", "macOS", "`plutil`", "`/bin/bash`", "Bash 3.2",
            "commit SHA",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.document)
        self.assertNotRegex(self.document, r"[–—]")
        self.assertNotIn("Kenny", self.document)
        self.assertNotRegex(self.document, r"^[ \t]*(?:`{3,}|~{3,})")

    def test_check_documentation(self):
        for filename, heading in (("AGENTS.md", "Checks"), ("README.md", "Testing")):
            with self.subTest(filename=filename):
                section = markdown_section(
                    (ROOT / filename).read_text(encoding="utf-8"), heading,
                )
                self.assertNotIn("There is no CI workflow", section)
                self.assertNotIn("Kenny", section)
                self.assertIn("`.github/workflows/check.yml`", section)
                self.assertIn("```sh\nsh scripts/check.sh\n```", section)
                checks = re.findall(r"^- `([-a-z]+)`: (.+)$", section, re.MULTILINE)
                self.assertEqual([name for name, _ in checks], list(CHECK_DESCRIPTIONS))
                for name, description in checks:
                    self.assertRegex(description, CHECK_DESCRIPTIONS[name])
                if filename == "README.md":
                    self.assertIn("[docs/ci.md](docs/ci.md)", section)


if __name__ == "__main__":
    unittest.main()
