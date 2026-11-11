"""Read-only documentation checks; no ECC or adopting-project integration calls."""

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/ecc-operator/SKILL.md"


def section(text, heading):
    """Select one heading and its body, stopping at a sibling or parent heading."""
    lines = text.splitlines()
    matches = [i for i, line in enumerate(lines) if line == heading]
    if len(matches) != 1:
        raise AssertionError(f"Expected one heading: {heading}")
    start = matches[0]
    level = len(heading.split(" ", 1)[0])
    for end in range(start + 1, len(lines)):
        match = re.match(r"^(#{1,6}) ", lines[end])
        if match and len(match[1]) <= level:
            return "\n".join(lines[start + 1:end])
    return "\n".join(lines[start + 1:])


class EccOperatorDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = SKILL.read_text(encoding="utf-8")
        cls.approval = section(cls.skill, "## approve-plan")
        cls.resolve = section(cls.approval, "### Resolve inputs")
        cls.validate = section(cls.approval, "### Record approval and validate")
        cls.commit = section(cls.approval, "### Commit and optionally merge")
        cls.handoff = section(cls.approval, "### Print next commands")
        cls.readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cls.skills_readme = (ROOT / "skills/README.md").read_text(encoding="utf-8")

    def assert_instructions(self, text, *patterns):
        for pattern in patterns:
            with self.subTest(instruction=pattern):
                self.assertRegex(text, pattern)

    def run_case(self, label):
        matches = [line for line in self.handoff.splitlines()
                   if line.startswith(f"- {label}:")]
        self.assertEqual(len(matches), 1, label)
        return matches[0]

    def test_heading_placement_and_frontmatter(self):
        self.assertLess(self.skill.index("## approve-plan\n"),
                        self.skill.index("## Run a milestone\n"))
        self.assertEqual(re.findall(r"^### (.+)$", self.approval, re.MULTILINE), [
            "Resolve inputs", "Record approval and validate",
            "Commit and optionally merge", "Print next commands",
        ])
        frontmatter = self.skill.split("---", 2)[1]
        self.assertRegex(frontmatter, r"(?m)^description: .*plan approval")

    def test_resolves_inputs_before_editing(self):
        self.assert_instructions(
            self.resolve,
            r"owner's reply and the adopting project before editing",
            r"selected `docs/build/<M>-plan-v<N>\.md` revision",
            r"Do not assume the highest version",
            r"plan branch and target branch, approving owner",
            r"approval date in `YYYY-MM-DD`",
            r"bot for `prbot git`, generated ECC plan JSON path, doc-map path, and run ID",
            r"approval alone or approval and merge",
            r"Stop before editing if essential inputs remain ambiguous",
            r"branch cannot be used without disturbing unrelated work",
        )

    def test_discovers_commands_and_authoritative_history(self):
        self.assert_instructions(
            self.resolve,
            r"Inspect project instructions, local scripts and generator configuration",
            r"installed CLI documentation or argument-parser source",
            r"exact commands to regenerate the ECC plan JSON and doc map",
            r"applicable generator `--check` commands",
            r"supported arguments for `ecc lint-plan`, `ecc plan-check`, "
            r"`ecc create-run` and `ecc drive`",
            r"configuration determines the doc-map path",
            r"authoritative dispatch history",
            r"durable dispatch events and attempt records",
            r"Record the evidence source",
            r"Current unit status alone cannot prove that no unit has ever dispatched",
            r"Name every command, including inspection commands, with its resolved "
            r"arguments and working directory before running it",
            r"Inspect `git status --short`",
        )

    def test_owner_reply_requires_no_manual_edits_or_reconfirmation(self):
        introduction = self.approval.split("### Resolve inputs", 1)[0]
        self.assert_instructions(
            introduction,
            r'one owner reply such as "approved and merge" authorizes',
            r"do not ask for another confirmation",
            r"or require manual file edits from the owner",
        )
        self.assertIn("On the plan branch", self.validate)
        self.assertIn("The operator performs these edits", self.validate)

    def test_approval_fields_and_preservation(self):
        yaml = re.findall(r"```yaml\n(.*?)\n```", self.validate, re.DOTALL)
        self.assertEqual(len(yaml), 1)
        self.assert_instructions(
            yaml[0], r"(?m)^status: approved$",
            r"(?m)^approved_by: <approving owner>$",
            r"(?m)^approved: <approval date in YYYY-MM-DD>$",
        )
        self.assertRegex(self.validate, r"resolved owner and date, preserving all other content")

    def test_regeneration_and_required_validation(self):
        self.assert_instructions(
            self.validate,
            r"Run the resolved ECC plan JSON regeneration command",
            r"then the resolved doc-map regeneration command",
            r"Run `node tools/sdd/cli\.mjs check` and every applicable generator `--check`",
            r"including checks for the ECC plan JSON and doc map where supported",
            r"Name each exact command before running it and record its result",
            r"Any generation or check failure stops before commit or merge",
            r"Report the failed command and its output",
            r"leave the changes available for inspection",
            r"do not print a success handoff",
            r"rerun generation and validation before continuing",
        )

    def test_diff_staging_commit_and_attribution(self):
        self.assert_instructions(
            self.commit,
            r"After successful checks, review `git diff` and `git diff --check`",
            r"Stage only intended changes with explicit paths",
            r"review `git diff --cached`",
            r"Exclude unrelated work from the commit",
            r"Commit on the plan branch through `prbot git <bot> -- commit",
            r"project's agent attribution requirements",
            r"branch naming, author and committer identity, and agent labels",
            r"verify published attribution through GitHub",
            r"Do not change shared Git configuration",
        )

    def test_merge_authorization_and_failure_stops(self):
        self.assert_instructions(
            self.commit,
            r"Approval alone leaves the commit on the plan branch and the target unchanged",
            r"Only explicit owner merge authorization permits a local "
            r"`git merge --ff-only <plan-branch>` into the resolved target branch",
            r"after successful checks and commit",
            r'"Approved and merge" authorizes both actions without another confirmation',
            r"Use the target's clean checkout, verify its branch",
            r"Stop on commit failure or branch divergence",
            r"Do not reset branches or overwrite unrelated work",
            r"Report the failed command and whether the approval commit exists",
        )

    def test_preserves_restrictions(self):
        self.assert_instructions(
            self.commit, r"Never push\.",
            r"never push the target branch during a milestone",
            r"Never commit to a project's `main` by hand while a run is active",
        )
        rules = section(self.skill, "## Rules")
        self.assert_instructions(
            rules, r"Never push", r"never run `security` or `launchctl`",
            r"never commit to a project's `main` by hand while a run is active",
        )

    def test_existing_undispatched_run(self):
        self.assert_instructions(
            self.run_case("Existing, undispatched run"),
            r"select `--replace` only when authoritative history confirms "
            r"no unit has ever dispatched", r"Retain that run ID",
        )

    def test_dispatched_run(self):
        self.assert_instructions(
            self.run_case("Dispatched run"),
            r"if any unit has dispatched, preserve that run",
            r"select the next unused run ID",
            r"verified against the project's run store", r"without `--replace`",
        )

    def test_fresh_run(self):
        self.assert_instructions(
            self.run_case("Fresh run"),
            r"confirmed unused run ID", r"omit `--replace`",
        )

    def test_unknown_history_blocks_replacement(self):
        self.assert_instructions(
            self.run_case("Unknown dispatch history"),
            r"stop replacement until the history is resolved",
            r"Do not infer safety from missing records",
            r"or print a replacement command while history is unknown",
        )

    def test_resolved_handoff_order_and_first_failure(self):
        blocks = re.findall(r"```sh\n(.*?)\n```", self.handoff, re.DOTALL)
        self.assertEqual(len(blocks), 1)
        lines = blocks[0].splitlines()
        self.assertEqual(len(lines), 4)
        for line, command in zip(lines, ("lint-plan", "plan-check", "create-run", "drive")):
            self.assertTrue(line.startswith(f"ecc {command} "), line)
        for line in lines[:3]:
            self.assertIn("--plan <generated ECC JSON path>", line)
            self.assertTrue(line.endswith("&&"), line)
        for line in lines[2:]:
            self.assertIn("--run-id <resolved run ID>", line)
        self.assertIn("<replacement argument>", lines[2])
        self.assertNotIn("--replace", blocks[0])
        self.assert_instructions(
            self.handoff,
            r"After successful approval and any authorized merge",
            r"one owner reply with no manual file edits",
            r"Approval-only leaves the commit on the plan branch",
            r"target prerequisite that must be resolved",
            r"Print one resolved command block",
            r"replace every placeholder with actual paths and IDs, shell-quote values",
            r"use only arguments confirmed by the installed CLI documentation",
            r"State the working directory",
            r"otherwise remove it",
            r"Require stopping at the first failure",
            r"Do not execute the handoff commands or automatically dispatch work",
            r"failed generation or validation check produces a failure report instead",
        )

    def test_readme_links_resolve_to_approval_anchor(self):
        operate = section(self.readme, "### Operate an ECC project")
        rows = [line for line in self.skills_readme.splitlines()
                if line.startswith("| `ecc-operator` |")]
        self.assertEqual(len(rows), 1)
        for parent, text, expected in (
            (ROOT, operate, "skills/ecc-operator/SKILL.md#approve-plan"),
            (ROOT / "skills", rows[0], "ecc-operator/SKILL.md#approve-plan"),
        ):
            with self.subTest(link=expected):
                links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
                self.assertIn(expected, links)
                path, anchor = expected.split("#")
                target = (parent / path).resolve()
                self.assertEqual(target, SKILL.resolve())
                self.assertTrue(target.is_file())
                self.assertEqual(anchor, "approve-plan")
                section(target.read_text(encoding="utf-8"), f"## {anchor}")

    def test_testing_scope_is_documented(self):
        testing = section(self.readme, "## Testing")
        self.assert_instructions(
            testing, r"python3 tests/test_ecc_operator\.py",
            r"local, read-only documentation checks",
            r"does not validate research-mcp integration",
            r"or execute ECC, project generators, credentials or external repositories",
        )

    def test_prose_avoids_em_and_en_dashes(self):
        for text in (self.skill, self.readme, self.skills_readme):
            self.assertNotRegex(text, "[\u2013\u2014]")


if __name__ == "__main__":
    unittest.main()
