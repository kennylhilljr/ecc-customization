# SDD Framework 1.1.0: Alignment Results

Oct 22, 2026 · @Kenny

## Summary

Release 1.1.0 aligns the SDD Framework repository with the white paper's operating model and keeps it a **reusable toolkit with an Access Management reference profile**. It answers the repository alignment analysis of commit `6d7e15e`.

- **Committed locally** as `ea7cfe9` in `~/Documents/GitHub/sdd_framework`, authored by `khillerkb <khill@klhjr.net>`. **Not pushed** to GitHub.
- **Size:** 85 files: 78 changed (1,609 lines added, 538 removed) and 7 new.
- **Checks:** 50 of 50 tests pass, the type check is clean, and spec-lint and trace-check report 0 errors.
- **Approved documents untouched.** The new standard (v2) is in review, waiting for the owner's approval.

The central change separates three ideas the repository had blended. **L0 to L3** now mean organizational scope only. Documents form an **unnumbered delivery artifact chain**. **Gates 1 to 3** are approval checkpoints that do not map to scope levels.

## What changed

Every recommendation in the analysis that did not need an owner decision was implemented, using the defaults the owner approved.

| Area | Change | Where |
| --- | --- | --- |
| Positioning | README and overview lead with the Product-to-Engineering bridge: a reusable toolkit with an Access Management reference profile, not a finished enterprise standard. Audience routes for executives, Product, Engineering and Security, and adopters | `README.md`, `docs/guide/framework-overview.md` |
| Scope, artifact chain, gates | L0 to L3 reserved for organizational scope, in a new scope map checked by spec-lint. Documents form an unnumbered artifact chain. Gates are approval checkpoints. L0 to L6 stage labels removed everywhere, including the doc map generator | `docs/scope/scope-map.yaml`, `tools/sdd/docs.mjs` |
| Standard v2 | Bridge roles, portable core and local choices, scope metadata, decision ownership, intake checkpoint, component-bound gates, ID lifecycle, evidence states, drift rule, priority and severity lenses, open decisions | `docs/standards/spec-driven-development-v2.md` |
| Decision ownership | Requirements, acceptance criteria, test strategy, contracts, schema and authorization are C: an agent drafts, a person selects and approves | Templates, skills, personas |
| Gate 0 | Renamed to the intake checkpoint, a local control outside the three formal gates | All docs, skills, commands |
| Gates | Bound to the named component or milestone. `/sdd-lld billing` is blocked while the billing PRD is a draft; `/sdd-implement M2` checks every LLD behind the M2 plan | `tools/hooks/gate.mjs` |
| Evidence | `covered` becomes `test linked`. New states: planned, passing, failing (from a JUnit report), deferred, excepted, drifted, gap. Missing tests are an error only once a plan exists, so design is not blocked after Gate 1 | `tools/trace-check/trace-check.mjs` |
| Audit record | Trace index records scope, owner, findings, disposition, drift IDs and governing artifact versions. Evidence goes stale when a governing PRD, SPEC, LLD or test plan changes after the last audit | `docs/trace/index.yaml` |
| IDs | ID history table in PRDs; spec-lint blocks reuse and flags removed IDs. Optional richer form such as `AM-PRIV-001-AC1` | `tools/spec-lint/spec-lint.mjs`, `sdd.config.json` |
| Approvals | `approved_by` and `approved` fields, optionally required. CODEOWNERS scaffold, inert until filled in | Templates, `tools/sdd/scaffold/CODEOWNERS` |
| Navigation and integrity | Doc map in three views: scope map, artifact index, approval workflow. ADR index, postmortem linked, glossary terms, redrawn diagrams and header | `docs/README.md`, `docs/adr/README.md`, `docs/assets/` |
| Claims | Traceability described as structural links, not proof of meaning. Hooks described as Claude Code adapters; other agents follow gates procedurally | README, guides |
| `AGENTS.md` | Described as a repository instruction adapter, not organizational authority | `AGENTS.md`, scaffold |
| Versions | Framework 1.1.0; every changed skill, persona and command at 1.1.0 with a changelog row | `CHANGELOG.md`, catalog |

## What did not change, and why

Nine items were left alone on purpose: they are frozen, belong to a person to decide, or are out of scope for this release.

| Item | Why it did not change |
| --- | --- |
| Approved sample documents (PRDs, SPEC, LLDs, test plan, ADRs, standard v1, persona standard) | Approved versions are frozen. Scope for those docs comes from `sdd.config.json`; the synthetic example disclaimer sits at the README and doc map instead |
| Standard v2 status | Left `in-review`. Only a person approves; agents never set `status: approved` |
| Pilot L2 capability and L3 Business Application | Owner decision. The scope map uses illustrative names only |
| License | Owner and legal decision. The README now says reuse should wait until one is published |
| Controlled standard, gate approvers, exception authority, fast path criteria | Recorded as open decisions in standard v2, not settled by tools |
| Default ID syntax `IAM-2` | Kept. Encoding scope in IDs conflicts with the analysis's own lifecycle rule; the richer form is an option |
| Checks across the whole chain (L0 direction to handoff) | Described as planned. The doc map shows those links, and spec-lint checks `derives_from` paths, but no check enforces the full chain yet |
| White paper v2 | Not requested in this round. Its suggested notes depend on this release being tagged |
| `adopt` adding CODEOWNERS | Deliberately not added: a new CODEOWNERS can change how an existing team's pull requests are reviewed. Adopt lists it as missing information |

## Independent review

A separate agent that did not write the change reviewed it before commit and found eight issues; all eight are fixed, five of them with new tests.

| Finding | Fix |
| --- | --- |
| A configured richer ID form (`AM-PRIV-001-AC1`) switched off the tests-required-in-build rule and blocked `/sdd-implement` | Plans now recognize any criterion ID form; new test |
| Deferrals and exceptions counted from a draft test plan | They count only once the owner approves the test plan; a draft lists them as a warning; new test |
| A withdrawn or removed ID could come back in a later version | spec-lint errors on any retired ID defined again; new test |
| Words typed after `/sdd-lld iam` were read as more components, causing a false block | Only the leading component and milestone words count, from the first line; new test |
| An approved document with only a `date:` field never marked an audit stale | Staleness reads `approved` or `date` on approved documents |
| "Constitution" left in two templates and the adopt report | Changed to `AGENTS.md` and repository instructions |
| "Layer" still used for fix starting points in triage, verify, hld and the postmortem template | Changed to the first artifact that lost intent |
| Fresh `init` failed the CI doc map check on its first run (pre-existing) | `init` now writes the doc map; new test |

The reviewer also confirmed: hooks exit 0 on any unexpected error, no approved file changed, links resolve, and prose has no em or en dashes.

## Verification

Every check passed on the final tree. spec-lint, trace-check, the doc map and the catalog were run again on the Mac copy before commit.

| Check | Result |
| --- | --- |
| `npm test` (Vitest) | 50 of 50 pass, up from 35 at 1.0.0 |
| `npm run typecheck` | Clean |
| spec-lint | 0 errors, 0 warnings |
| trace-check | 0 errors, 1 expected warning: the draft billing component has never been audited |
| Doc map and catalog | Both current (`--check`) |
| `doctor` | Environment ready |
| Gate hook by hand | `sdd-lld billing` blocks with exit 2; `sdd-lld iam` passes; malformed input exits 0 |
| JUnit report | All four IAM criteria read as `passing` from a real Vitest report |
| `adopt` on an open-source Node app | 112 files planned, 0 tracked files changed, scope map and ADR index added, checks run in advisory mode |
| Links in a freshly installed repository | All resolve (now a test) |
| Prose scan of changed files | 0 em dashes, 0 en dashes; no real names |
| Approved documents | None modified |

## Next steps for the owner

- [ ] Push `ea7cfe9` to `github.com/kennylhilljr/sdd_framework` when ready (`git push` from the repository folder).
- [ ] Review standard v2. To approve it, set `status: approved`, `approved_by` and `approved` in its front matter, and set v1's status to `superseded`.
- [ ] Decide the open items recorded in standard v2: where the controlled standard lives and who approves it; the pilot's L2 capability and L3 Business Application; named gate approvers, exception authority, fast path criteria and audit timing; whether the intake checkpoint and combined queue stay; the license.
- [ ] Fill in `.github/CODEOWNERS` for reviewers of `docs/`, then require code owner review in branch protection, so approvals are enforced by the repository and not only by front matter.
- [ ] Tag the release (for example `v1.1.0`) and cite it from the white paper's implementation section.

Repositories already on 1.0.0 upgrade with `sdd upgrade`, plus six manual steps (scope map, config keys, merging the new `AGENTS.md` and doc map, test plan fields, regenerating evidence, naming components in gated skills). They are listed in `docs/guide/versioning.md`.
