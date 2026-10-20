# ecc-customization

Everything built on top of ECC and OpenClaw that is not code in another repository: the project kit every new repository starts from, the shared skills, the pinned stack, a backup of this machine's agent settings, and the one command that rebuilds the whole setup on another Mac.

## Redeploy on a new Mac (one call)

```sh
git clone https://github.com/kennylhilljr/ecc-customization.git ~/Documents/GitHub/ecc-customization && ~/Documents/GitHub/ecc-customization/bootstrap.sh
```

To carry OpenClaw's sessions and devices over too, add `--openclaw-archive /path/to/openclaw-state.tar.gz` (made on the old Mac by `bin/ecc-snapshot --openclaw`).

`bootstrap.sh` runs these steps in order. Each checks before it changes anything, so it is safe to run again; it never overwrites an existing file or setting without asking.

| Step | What it does |
|---|---|
| prereqs | macOS and the Xcode command line tools |
| brew | Homebrew; git, gh, uv, jq, Python 3.13 |
| node | nvm; Node 24 as the default |
| clis | Claude Code, Codex, Gemini CLI, OpenClaw (versions in `stack.conf`); checks each is signed in |
| repos | clones or fast-forwards openclaw-ecc-orchestrator, agent-control-plane-infra and the projects in `stack.conf` |
| runtime | the orchestrator copy outside Documents that launchd runs from; the ECC state folder |
| ecc | the everything-claude-code plugin for Claude Code (user scope) and Codex |
| skills | links `skills/*` into `~/.claude/skills` and `~/.agents/skills` |
| shell | puts `bin/` (`ecc`, `ecc-kit`, `ecc-snapshot`) on PATH in `~/.zshrc` |
| machine | restores the settings, skills and plugins captured in `machine/` |
| openclaw | restores OpenClaw state from an archive, or runs `openclaw onboard`; registers the ECC orchestrator plugin |
| secrets | for each Keychain item named in `stack.conf` that is missing, opens macOS's hidden prompt so you can store it |
| launchd | the inbox processor and the weekly recertification agents |
| verify | runner certification, then `ecc doctor`, `catalog-refresh` and `preflight` for each project, and an inventory |

It ends with a summary: what was done, warnings, and the few things only you can do (sign-ins, trust prompts, Keychain values). Do those, run it again, and finished steps are skipped. Options: `--dry-run`, `--only a,b`, `--skip a,b`, `--yes`, `--no-launchd`, `--no-certify`, `--overwrite-config` (see `bootstrap.sh --help`).

## Keep the backup current

```sh
bin/ecc-snapshot              # capture settings, skills and plugin lists into machine/
bin/ecc-snapshot --openclaw   # also a full, verified OpenClaw state archive (local only)
git add machine && git commit -m "Snapshot" && git push
```

`ecc-snapshot` removes every secret-looking value before anything is written (keys named like tokens, keys and passwords, every `env` and header value, and anything shaped like a token), lists what it removed, and refuses the whole snapshot if anything secret-shaped is left. A pre-commit hook in this repository runs the same scan on every commit. The OpenClaw archive holds credentials, so it stays in `~/AgentPlatformBackups` and is never committed; carry it to the new Mac yourself.

## Start a new project

```sh
ecc-kit new ~/Documents/GitHub/my-project --name "My Project" \
  --spec docs/spec/SPEC-v1.md --prd docs/prd/PRD-v1.md --test-plan docs/test-plan/TEST-PLAN-v1.md \
  --setup "uv sync --frozen" --test-cmd "uv run pytest -q" --gate tools/ci.sh --fast-gate "tools/ci.sh --python-only"
```

It writes the kit (below) without touching files that already exist, links `.claude/skills` to `.agents/skills`, and lists what is left for you: high-risk paths, contract paths, milestone doc sections, the run skill's details, project rules and the milestone plan.

## The kit

`kit/` holds what every ECC project starts with, generalized from research-mcp:

- `AGENTS.md` (Documents, Branches, Repairs, Skills while building, Lessons, Rules, Commands), with `CLAUDE.md` and `GEMINI.md` pointing to it;
- `.agents/skills/`: run-*project*, simplify-change, verify-change, review-change, security-review, in the Agent Skills format Claude Code, Codex and Gemini all read;
- `.agents/LESSONS.md`, the ledger the delivery lead keeps as practices evolve (TEAM-DELIVERY v7);
- `.orchestration/`: `ecc.json`, `config.yaml` (providers, models, budgets), `team.json` (personas, panels, skills pass, learning loop), `RUN-GUIDE.md`.

Projects improve these files as they learn. Two commands move improvements in both directions:

```sh
ecc-kit diff ~/Documents/GitHub/research-mcp   # how the project's practices moved on from the kit
ecc-kit sync ~/Documents/GitHub/research-mcp   # kit improvements into files the project never changed
```

When a project's lesson generalizes, port it into `kit/` here and commit; every later project starts with it.

## Running ECC

From inside a project: `ecc catalog-refresh`, `ecc preflight`, `ecc create-run --run-id <id> --plan .orchestration/plan-m0.json`, `ecc drive --run-id <id>`. `bin/ecc` finds the project's `.orchestration/ecc.json`, puts nvm's Node first and loads provider keys from the Keychain itself. The shared `ecc-operator` skill teaches any agent the same.

## Layout

| Path | What |
|---|---|
| `bootstrap.sh` | the one call |
| `stack.conf` | pinned versions, repositories, locations, Keychain item names |
| `bin/` | `ecc`, `ecc-kit`, `ecc-snapshot` |
| `lib/ecctools.py` | kit, snapshot, restore, OpenClaw and secret-scan helpers (standard library only) |
| `kit/` | project templates |
| `skills/` | shared user-level skills |
| `machine/` | this machine's captured settings (no secrets) |
| `docs/REDEPLOY.md` | what is automatic, what is yours, and recovery notes |

Related repositories: [openclaw-ecc-orchestrator](https://github.com/kennylhilljr/openclaw-ecc-orchestrator) (the runtime and the OpenClaw plugin) and [agent-control-plane-infra](https://github.com/kennylhilljr/agent-control-plane-infra) (TEAM-DELIVERY specs, inventory, OpenClaw backups).
