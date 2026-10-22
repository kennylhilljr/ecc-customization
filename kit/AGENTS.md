# Agent instructions for {{NAME}}

Read this file, then [the specification]({{SPEC}}) section 0 and the sections your work unit names, before changing anything. The specification is the contract; the [PRD]({{PRD}}) says why.

## Documents

- **The specification** owns every name (modules, classes, functions, tables, columns, settings keys, routes), every interface and format, and the work breakdown. Code follows it. If it is wrong or contradicts the PRD or the test plan, do not pick a side: record the conflict in your handoff and build everything it does not touch.
- **The [test plan]({{TEST_PLAN}})** owns test ids. Put each acceptance test id first in its test's docstring (`"""AT-XXX-01: ..."""`).
- Docs are versioned: to change one, add the next `-vN` file and update links; never edit an earlier version. Do not edit generated files; run their generators.

## Branches

- Every unit has one branch, `ecc/<run>/<unit>`, created by ECC from `main` after the unit's dependencies merged. Work only on the branch you are on.
- Commit your work there. Never push, never create or switch branches, never rebase or rewrite history, never commit to `main`. Only ECC's merge queue writes `main`, after review and verification pass.
- Before each attempt ECC merges the current `main` into your branch. If it did, keep both sides; your unit must pass on top of the merged `main`. If ECC reports a merge conflict, resolving it is the first part of your attempt.
- Stay inside your unit's scope (its file list). If you need a file another unit owns and it is not on your branch yet, do not create it: finish what you can, then hand off with status `blocked`, naming the file and the unit. ECC re-runs you after that unit merges.

## Repairs

- A failed attempt comes back with a brief: the failing gate output, or the reviewers' findings. Fix exactly those, keep everything that passed, and say in the handoff how each finding was addressed. Reviewers re-check the same findings.
- Never weaken, skip or delete a test to make it pass. A test that contradicts the specification is a conflict to record, not a test to change.

## Skills while building (every agent)

The skills live in the repository at `.agents/skills/` (Codex and Gemini read that folder; `.claude/skills` points to it for Claude Code). They are required, not optional: skip one only when its trigger does not apply, and say so in your handoff.

| When | Skill | Claude Code | Codex | Gemini |
|---|---|---|---|---|
| While developing anything you can run | `run-{{SLUG}}` | `/run`, following the skill | `$run-{{SLUG}}` | ask for the run-{{SLUG}} skill |
| After the change works, before verifying | `simplify-change` | `/simplify` | `$simplify-change` | ask for the simplify-change skill |
| After the acceptance commands and `{{FAST_GATE_CMD}}` pass | `verify-change` | `/verify`, following the skill | `$verify-change` | ask for the verify-change skill |
| Before your handoff (self-review), and when reviewing | `review-change` | `/code-review`, then the skill's checklist | `$review-change` | the skill (plus the `code-review` extension if installed) |
| High-risk units (the `high_risk_paths` in `.orchestration/config.yaml`) | `security-review` | `/security-review`, then the skill | `$security-review` | the skill (plus `/security:analyze` if installed) |

**Codex and many skills.** When Codex has more skills installed than its skills budget allows (the ECC plugin adds hundreds), it drops the descriptions and may not list these at all. Do not rely on `$name` alone: open `.agents/skills/<name>/SKILL.md` and follow it.

**When Claude Code's own skills are not available.** Codex and Gemini have no built-in simplify, verify or run, so the repository skills carry those steps for them. In addition, when a unit is written by any agent other than Claude Code, ECC runs a **Claude skills pass** after the author's attempt and before the gates: a fresh Claude Code session in the unit's worktree runs `/simplify`, `/verify` and `/code-review` (and `/security-review` for high-risk units) with these skills, and commits any fixes within the unit's scope. Outside ECC, run the same pass by hand before handing off:

```sh
claude -p "Read AGENTS.md. For this branch's changes against main, run /simplify, /verify and /code-review (and /security-review if the unit is high risk), using the skills in .agents/skills. Fix what they find within the unit's scope and commit on this branch."
```

## Lessons

The team's practices evolve during a build (TEAM-DELIVERY v7). Every reviewer, the verifier, the architect and the designer may add `lessons` to their verdicts; when you hand off, add a `Lesson:` line to your handoff `notes` for anything future units should do differently (for example "Lesson: the spec does not say whether X includes Y; I assumed not"). The delivery lead turns lessons that generalize into this file, the skills and [.agents/LESSONS.md](.agents/LESSONS.md), and those changes are reviewed and merged like code. Read the ledger before you start; it records why each rule exists.

## Rules

- Work only inside this repository.
- Never read the Keychain, client configs or any real credential. Use fakes and recorded fixtures. Tests pass with the network blocked.
- Never print, log, commit or put in fixtures any secret, token or password.
- Every change needs tests.
- Keep `{{FAST_GATE_CMD}}` green.
- Do not use em dashes or en dashes in prose, comments or UI text.
- Never start another agent CLI (`codex`, `claude`, `gemini`) inside a unit, including `codex review`: the unit sandbox cannot run it, and ECC's reviewers review every unit.
- Never run `git push`, `security`, `launchctl` or anything that changes the machine outside this repository.
<!-- Project rules: add them here (read-only neighbours, layering rules, forbidden imports). -->

## Commands

```sh
{{SETUP_CMD}}
{{FAST_GATE_CMD}}
{{TEST_CMD}}
```
