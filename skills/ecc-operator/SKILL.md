---
name: ecc-operator
description: Operate the ECC agent team on a project - set a repository up for ECC, record plan approval, start or continue a milestone run, read why a drive stopped and follow its next steps. Use when asked to approve a plan, kick off, drive, resume or check an ECC run, or to make a new project ECC-ready.
---

# Operate ECC

ECC (openclaw-ecc-orchestrator) runs a team of agent personas over a milestone plan: authors (Codex, Claude), reviewers, a verifier, an architect, a designer, a delivery lead and product owners (Codex, Claude, Gemini). The process is TEAM-DELIVERY v7 in agent-control-plane-infra `docs/specs/`.

The `ecc` command is `~/Documents/GitHub/ecc-customization/bin/ecc`. Run it from inside the project (or pass `--project DIR`); it loads Keychain keys itself. Never read, print or pass a key.

## Make a project ECC-ready

```sh
~/Documents/GitHub/ecc-customization/bin/ecc-kit new <repo> --name "<Project name>" --spec docs/spec/SPEC-v1.md --prd docs/prd/PRD-v1.md --test-plan docs/test-plan/TEST-PLAN-v1.md --test-cmd "<test command>" --gate "<full gate>" --fast-gate "<fast gate>" --setup "<setup command>"
```

Then fill what it lists as TODO (high-risk paths, contract paths, milestone doc sections, the run skill's section 3) and generate `.orchestration/plan-m0.json` from the specification's work breakdown. Commit on `main`.

## approve-plan

Use the owner's reply to approve a selected plan revision. With resolved inputs, one owner reply such as "approved and merge" authorizes recording approval and merging locally; do not ask for another confirmation or require manual file edits from the owner.

### Resolve inputs

Resolve these values from the owner's reply and the adopting project before editing:

- The selected `docs/build/<M>-plan-v<N>.md` revision, including milestone and version. Do not assume the highest version is the selected revision.
- The plan branch and target branch, approving owner, and approval date in `YYYY-MM-DD` format.
- The bot for `prbot git`, generated ECC plan JSON path, doc-map path, and run ID.
- Whether the owner authorized approval alone or approval and merge.

Inspect project instructions, local scripts and generator configuration, plus installed CLI documentation or argument-parser source. Identify the exact commands to regenerate the ECC plan JSON and doc map, the project's applicable generator `--check` commands, and the supported arguments for `ecc lint-plan`, `ecc plan-check`, `ecc create-run` and `ecc drive`. Verify which configuration determines the doc-map path. Do not invent generator names, copy flags from another project, or invoke a credential-loading wrapper just to discover its syntax.

Identify the authoritative dispatch history for the selected run from the installed runtime's documentation and implementation, then inspect that run's durable dispatch events and attempt records at the configured state location. Record the evidence source. Current unit status alone cannot prove that no unit has ever dispatched, even if every unit is now pending or ready.

Name every command, including inspection commands, with its resolved arguments and working directory before running it. Inspect `git status --short`, the current branch and relevant diffs for unrelated work. Stop before editing if essential inputs remain ambiguous, a required command is unavailable, or the selected branch cannot be used without disturbing unrelated work. Ask only for the missing information.

### Record approval and validate

On the plan branch, edit the selected plan's frontmatter for the owner:

```yaml
status: approved
approved_by: <approving owner>
approved: <approval date in YYYY-MM-DD>
```

Substitute the resolved owner and date, preserving all other content. The operator performs these edits; the owner does not edit files manually.

Run the resolved ECC plan JSON regeneration command, then the resolved doc-map regeneration command. Run `node tools/sdd/cli.mjs check` and every applicable generator `--check` command identified above, including checks for the ECC plan JSON and doc map where supported. Name each exact command before running it and record its result.

Any generation or check failure stops before commit or merge. Report the failed command and its output, leave the changes available for inspection, and do not print a success handoff. Correct the failure and rerun generation and validation before continuing.

### Commit and optionally merge

After successful checks, review `git diff` and `git diff --check`. Stage only intended changes with explicit paths to the selected plan and generated outputs, then review `git diff --cached`. Exclude unrelated work from the commit. Commit on the plan branch through `prbot git <bot> -- commit -m "Approve <M> plan v<N>"`, substituting the resolved bot, milestone and version.

Follow the project's agent attribution requirements for branch naming, author and committer identity, and agent labels. Do not substitute a human identity or claim remote attribution from local metadata. Where required, verify published attribution through GitHub before a later PR handoff or PR merge; this workflow grants no permission to push. Do not change shared Git configuration.

Approval alone leaves the commit on the plan branch and the target unchanged. Only explicit owner merge authorization permits a local `git merge --ff-only <plan-branch>` into the resolved target branch, after successful checks and commit. "Approved and merge" authorizes both actions without another confirmation. Use the target's clean checkout, verify its branch, and name the resolved merge command before running it.

Stop on commit failure or branch divergence. Do not reset branches or overwrite unrelated work to force a commit or merge. Report the failed command and whether the approval commit exists. Never push. In particular, never push the target branch during a milestone. Never commit to a project's `main` by hand while a run is active; an authorized fast-forward introduces no manual main commit.

### Print next commands

After successful approval and any authorized merge, report the approval commit and its branch, plus whether the target was advanced. Approval and merge completes from one owner reply with no manual file edits. Approval-only leaves the commit on the plan branch; identify the checkout containing that commit and any target prerequisite that must be resolved before the printed commands can pass.

Use authoritative dispatch history to choose the run ID and replacement argument:

- Existing, undispatched run: select `--replace` only when authoritative history confirms no unit has ever dispatched. Retain that run ID.
- Dispatched run: if any unit has dispatched, preserve that run and select the next unused run ID, verified against the project's run store, without `--replace`.
- Fresh run: use the confirmed unused run ID and omit `--replace`.
- Unknown dispatch history: stop replacement until the history is resolved. Do not infer safety from missing records or print a replacement command while history is unknown.

Print one resolved command block containing the following commands in this order. This is a rendering template: replace every placeholder with actual paths and IDs, shell-quote values, and use only arguments confirmed by the installed CLI documentation. Replace `<replacement argument>` with `--replace` only for the verified existing-undispatched case; otherwise remove it. State the working directory and use the resolved generated ECC JSON path for `--plan`; do not pass the Markdown plan or invent a doc-map flag. If the installed CLI cannot express these operations, stop and report the unsupported command.

```sh
ecc lint-plan --plan <generated ECC JSON path> &&
ecc plan-check --plan <generated ECC JSON path> &&
ecc create-run --run-id <resolved run ID> --plan <generated ECC JSON path> <replacement argument> &&
ecc drive --run-id <resolved run ID>
```

Require stopping at the first failure; keep the `&&` chain in the resolved block. Print these commands for the owner to run. Do not execute the handoff commands or automatically dispatch work as part of approval. A failed generation or validation check produces a failure report instead of this block.

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
