---
name: review-change
description: Review a unit's changes against the specification, the test plan and AGENTS.md, and report findings by severity. Use as the author's self-review before handoff, and as the PR reviewer or verifier.
---

# Review a change

Review `git diff $(git merge-base HEAD main)...HEAD` for the unit named in the branch (`ecc/<run>/<unit>`).

## Checklist

1. **Contract.** Every name, signature, field, table, setting and error code matches the specification sections the unit implements. Anything the specification does not mention is not added.
2. **Clarifications.** Every clarification the specification records for this unit holds.
3. **Tests.** Each acceptance test id the unit owns exists, comes first in its docstring, and tests the behavior the test plan describes, including refusals. No test was weakened, skipped or deleted.
4. **Scope.** Only the unit's files changed.
5. **Rules.** Everything in AGENTS.md "Rules" holds; no secrets in code, logs or fixtures; tests pass with the network blocked.
6. **Simplicity.** Nothing the simplify-change skill would remove.

## Report

One finding per line: `severity | file:line | what is wrong and what the specification or test plan requires`. Severities: `blocker` (violates the specification, a test id or a rule), `major` (a likely defect or a missing case), `minor` (clarity). If there are none, say so. When reviewing for ECC, end with the verdict line the prompt specifies.
