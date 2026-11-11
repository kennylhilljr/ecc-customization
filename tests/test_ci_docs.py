"""Read-only checks for the workflow Kenny will install.

Compare the small YAML example's indented sections directly, without a YAML
dependency. Exact lines enforce nesting, quoting and the allowed keys/steps.
Paths are relative to this file so these tests also run in check-runner copies.
"""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parent.parent
CHECK_DESCRIPTIONS = {
    "unit-tests": r"isolated Python test suite",
    "bash-syntax": r"each Bash input separately",
    "sh-syntax": r"each POSIX shell script separately",
    "python-syntax": r"both Python helpers with `ast`",
    "ecctools-help": r"helper entry point",
    "kit-help": r"kit wrapper help path",
    "bootstrap-help": r"safe bootstrap help path",
    "secret-scan": r"scan .*maintained .*content",
    "plist-lint": r"lint .*launchd property lists",
    "plugin-tests": r"GitHub event router Node tests",
    "diff-check": r"working tree diff for whitespace errors",
}


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


class CIDocs(unittest.TestCase):
    def setUp(self):
        self.document = (ROOT / "docs/ci.md").read_text(encoding="utf-8")
        blocks = re.findall(
            r"^```yaml\n(.*?)^```$",
            self.document,
            flags=re.MULTILINE | re.DOTALL,
        )
        self.assertEqual(len(blocks), 1, "Expected exactly one YAML block")
        self.assertEqual(
            re.findall(r"^[ \t]*(?:`{3,}|~{3,}).*$", self.document, re.MULTILINE),
            ["```yaml", "```"],
            "The workflow must be the document's only fenced block",
        )
        self.workflow = blocks[0]
        self.sections = {}
        current = None
        for line in self.workflow.splitlines():
            if not line.strip():
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
        self.assertEqual(set(self.sections), {"name", "on", "permissions", "jobs"})
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
        self.assertEqual(self.sections["jobs"], [
            "jobs:",
            "  check:",
            "    runs-on: macos-latest",
            "    strategy:",
            "      fail-fast: false",
            "      matrix:",
            "        python-version: ['3.9', '3.13']",
            "    steps:",
            "      - uses: actions/checkout@v4",
            "        with:",
            "          persist-credentials: false",
            "      - uses: actions/setup-python@v5",
            "        with:",
            "          python-version: ${{ matrix.python-version }}",
            "      - uses: actions/setup-node@v4",
            "        with:",
            "          node-version: '24'",
            "      - run: sh scripts/check.sh",
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

    def test_installation_explanation_and_forbidden_content(self):
        for required in (
            "Kenny", "save", "`.github/workflows/check.yml`", "Node 24",
            "`NODE_VERSION`", "`stack.conf`", "macOS", "`plutil`",
            "`/bin/bash`", "Bash 3.2",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.document)
        self.assertNotRegex(self.document, r"[\u2013\u2014]")
        self.assertNotRegex(self.document, r"(?i)\bsecrets\s*[.\[]")
        self.assertNotIn("pull_request_target", self.workflow)
        self.assertNotRegex(self.workflow, r"(?i)\b(?:cache|write-all)\b")

    def test_check_documentation(self):
        for filename, heading, no_ci in (
            ("AGENTS.md", "Checks",
             "There is no CI workflow, bats setup or shellcheck config."),
            ("README.md", "Testing", "There is no CI workflow or coverage report."),
        ):
            with self.subTest(filename=filename):
                section = markdown_section(
                    (ROOT / filename).read_text(encoding="utf-8"), heading,
                )
                self.assertIn(no_ci, section)
                self.assertIn("```sh\nsh scripts/check.sh\n```", section)
                checks = re.findall(r"^- `([-a-z]+)`: (.+)$", section, re.MULTILINE)
                self.assertEqual([name for name, _ in checks], list(CHECK_DESCRIPTIONS))
                for name, description in checks:
                    self.assertRegex(description, CHECK_DESCRIPTIONS[name])
                if filename == "README.md":
                    self.assertIn("[docs/ci.md](docs/ci.md)", section)


if __name__ == "__main__":
    unittest.main()
