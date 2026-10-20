---
name: ecc-operator
description: Operate the ECC agent team on a project - set a repository up for ECC, start or continue a milestone run, read why a drive stopped and follow its next steps. Use when asked to kick off, drive, resume or check an ECC run, or to make a new project ECC-ready.
---

# Operate ECC

ECC (openclaw-ecc-orchestrator) runs a team of agent personas over a milestone plan: authors (Codex, Claude), reviewers, a verifier, an architect, a designer, a delivery lead and product owners (Codex, Claude, Gemini). The process is TEAM-DELIVERY v7 in agent-control-plane-infra `docs/specs/`.

The `ecc` command is `~/Documents/GitHub/ecc-customization/bin/ecc`. Run it from inside the project (or pass `--project DIR`); it loads Keychain keys itself. Never read, print or pass a key.

## Make a project ECC-ready

```sh
~/Documents/GitHub/ecc-customization/bin/ecc-kit new <repo> --name "<Project name>" --spec docs/spec/SPEC-v1.md --prd docs/prd/PRD-v1.md --test-plan docs/test-plan/TEST-PLAN-v1.md --test-cmd "<test command>" --gate "<full gate>" --fast-gate "<fast gate>" --setup "<setup command>"
```

Then fill what it lists as TODO (high-risk paths, contract paths, milestone doc sections, the run skill's section 3) and generate `.orchestration/plan-m0.json` from the specification's work breakdown. Commit on `main`.

## Run a milestone

```sh
ecc catalog-refresh
ecc preflight                       # must pass before a run
ecc create-run --run-id <id> --plan .orchestration/plan-m0.json
ecc drive --run-id <id>
```

## When a drive stops

The drive stops only when no unit can move after the delivery lead's recoveries. Its output ends with `next:` lines: run them in order; the last one continues the drive. `ecc status --run-id <id>` shows every unit. `ecc resume --run-id <id> --unit <unit> --extra-attempts N` (1 to 3) gives a unit more attempts; only the owner grants those.

## Rules

- Never push, never run `security` or `launchctl`, never commit to a project's `main` by hand while a run is active.
- Report what the drive printed; never claim a unit merged without `ecc status` showing it.
- Lessons: when something generalizes beyond one project, propose it for ecc-customization's `kit/` (run `ecc-kit diff <repo>` to see how a project's practices have moved on from the kit).
