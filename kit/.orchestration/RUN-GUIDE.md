# {{MILESTONE}} run guide

Milestone {{MILESTONE}} of {{NAME}}, delivered by the agent team under ECC (TEAM-DELIVERY v7, agent-control-plane-infra).

## Providers

Codex and Claude write code; Codex, Claude and Gemini review, verify and play the architect, delivery lead and product owners (`.orchestration/config.yaml`, `team.json`). Every unit applies the build skills in `.agents/skills` (AGENTS.md); after a unit written by Codex, a Claude Code skills pass runs `/simplify`, `/verify` and `/code-review` on it before the gates. Lessons from every role are collected during the run and the delivery lead folds the ones that generalize into AGENTS.md, the skills and `.agents/LESSONS.md`.

## Before the first run

1. The plan: `.orchestration/plan-{{MILESTONE_LC}}.json`, generated from the milestone plan's task table:

   ```sh
   cp .orchestration/PLAN-TEMPLATE.md docs/build/{{MILESTONE}}-plan-v1.md   # once; then write the real tasks
   ecc-kit plan-json docs/build/{{MILESTONE}}-plan-v1.md .orchestration/plan-{{MILESTONE_LC}}.json
   ```

   Set `package_path`, `criterion_prds` and, for projects with source adapters, `adapter_folder`, `adapter_exclude`, `adapter_ids`, `fixture_names` and `conformance_command` in `.orchestration/plan-json.json` first. Add the freshness check to `tools/ci.sh` so a stale plan JSON fails the gate:

   ```sh
   ecc-kit plan-json --check docs/build/{{MILESTONE}}-plan-v1.md .orchestration/plan-{{MILESTONE_LC}}.json
   ```

   `--check` writes nothing and exits 1 when the JSON is missing or differs from what the plan generates. Then lint it with `ecc lint-plan`.
2. From this folder (the `ecc` command is in ecc-customization's `bin/`):

   ```sh
   ecc catalog-refresh
   ecc preflight
   ```

   Preflight must pass for both coding CLIs before a run.

## Run

```sh
ecc create-run --run-id {{RUN_ID}} --plan .orchestration/plan-{{MILESTONE_LC}}.json
ecc drive --run-id {{RUN_ID}}
```

The drive checks the plan (architect), then builds, reviews, verifies and merges units wave by wave. Agents merge into `main` locally; nothing is pushed.

## When the drive stops

It stops only when no unit can move after the delivery lead's own recoveries. The output lists `next:` lines: run them in order; the last one continues the drive. `ecc status --run-id {{RUN_ID}}` shows every unit.

## Done

The drive ends with the product owners' report under the ECC state folder (`reports/`), including the practices learned. {{MILESTONE}} is complete when the product owners accept; then push `main`.
