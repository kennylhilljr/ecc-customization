---
title: "{{MILESTONE}} plan"
type: plan
version: 1
status: draft
milestone: {{MILESTONE}}
derives_from: {{SPEC}}
---

# {{MILESTONE}} plan (v1)

Copy this file to `docs/build/{{MILESTONE}}-plan-v1.md` and replace the example rows. `ecc-kit plan-json` builds `.orchestration/plan-{{MILESTONE_LC}}.json` from the task table in section 2, using the settings in `.orchestration/plan-json.json`.

## 1. Slices

Each slice is a wave; units in one wave have no overlapping files and can run in parallel.

| Slice | Units | Checkpoint |
| --- | --- | --- |
| 1 | {{MILESTONE}}-01 | merged (`done`; not in the generated plan) |
| 2 | {{MILESTONE}}-02, {{MILESTONE}}-03 | every unit merged with its criteria passing |

## 2. Tasks

How `ecc-kit plan-json` reads the columns:

- `#`: the unit id, `PREFIX-NUMBER`. The prefix is the milestone; a table with more than one prefix needs `--milestone`.
- `Criteria`: comma-separated criterion ids. Each id's prefix (before the first `-`) is looked up in `criterion_prds`.
- `Depends on`: comma-separated unit ids, or `none`. Dependencies on `done` tasks are dropped, in any milestone.
- `Files (scope)`: backticked paths. A path is under `package_path` unless it starts with `src/`, `tests/`, `tools/`, `docs/` or `.github/` or is one of `root_files`. A path ending in `/` stays a folder scope. `dir/*` stands for every name in `fixture_names`.
- `Risk`: `low`, `medium` or `high`; it sets the routing tier (0, 1, 2).
- `Status`: `done` rows are left out of the generated plan.
- `Provides` and `Requires` (optional): comma-separated capability tokens, backticked or not; blank or `none` means no tokens. The generator writes them as the `provides` and `requires` arrays that `ecc lint-plan` checks: every token a unit requires must be provided by a unit it depends on. Leave both columns out and the generated units have neither field.

| # | Task | Criteria | Depends on | Persona | Implements | Files (scope) | Risk | Status | Provides | Requires |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| {{MILESTONE}}-01 | Repository scaffold | REQ-1 | none | `implementer` | `docs/design/scaffold.md` | `pyproject.toml`, `tools/ci.sh`, `tests/test_scaffold.py` | low | done | `scaffold` | none |
| {{MILESTONE}}-02 | Settings loader | REQ-2, REQ-3 | {{MILESTONE}}-01 | `implementer` | `docs/design/settings.md` | `settings.py`, `tests/unit/test_settings.py` | medium | planned | `settings` | none |
| {{MILESTONE}}-03 | Example fixtures folder | REQ-4 | {{MILESTONE}}-02 | `implementer` | `docs/design/settings.md` | `tests/fixtures/`, `tests/unit/test_examples.py` | low | planned | none | `settings` |

### 2.1 Notes

- Add notes about the table here. The table ends at the first heading after it.

### 2.2 Clarifications

The first column (or, for a list item, the text before its first `:`) names the units a row applies to: a unit id, `every unit`, or `every adapter unit` (units whose scope holds a module in `adapter_folder`). Each matching unit's prompt says that this section lists requirements for it.

| Unit | Source | Requirement |
| --- | --- | --- |
| {{MILESTONE}}-02 | design review | Settings MUST reject unknown keys. |
| every unit | AGENTS.md | Tests MUST pass with the network blocked. |
| every adapter unit | design review | Adapters MUST pass the conformance suite. |

## 3. Verification

At the end of each slice, check that every merged unit's criteria have passing tests.
