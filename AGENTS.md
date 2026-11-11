# Agent instructions for ecc-customization

This file is for agents changing this repository. The files in `kit/` (`kit/AGENTS.md`, `kit/CLAUDE.md`, `kit/GEMINI.md` and the rest) are templates that `bin/ecc-kit new` renders into other projects. They do not apply here.

## Layout

- `bootstrap.sh`: the macOS install steps, run in the order listed in `ALL_STEPS`.
- `stack.conf`: versions, repository names, paths and Keychain item names. `bootstrap.sh`, `bin/ecc` and `bin/ecc-snapshot` source it as shell; `lib/ecctools.py` reads `ECC_RUNTIME_DIR` and `ECC_STATE_DIR` from it.
- `bin/`: POSIX `sh` wrappers. `ecc` delegates to the external orchestrator, `ecc-kit` calls `lib/ecctools.py kit-*`, `ecc-snapshot` calls `lib/ecctools.py snapshot`, `openclaw-gh-command-drain` calls `lib/gh_command_drain.py`. `openclaw-gh-app-token` is bash (it uses process substitution to keep the private key off disk); the `ops` step installs it into `~/.local/bin` with the App ids from `stack.conf` filled in.
- `lib/ecctools.py`: every helper (kit, snapshot, restore, OpenClaw restore and plugin, settings merge, secret scan).
- `lib/gh_command_drain.py`: the verified-command drain. It reads `command` events from `~/.local/state/github-events/ops/`, checks the comment author with the GitHub API, wakes the ops agent with `openclaw agent`, and moves failures to `ops-deferred/` or `ops-rejected/`. State lives in `~/.local/state/openclaw-gh-command-drain/state.json`. Never run it against the real queue except with `--dry-run`.
- `kit/`: project templates. Every file under `kit/` except `kit/gitignore` is copied into the destination project, and `{{NAME}}`-style placeholders are filled from `KIT_VARS` in `lib/ecctools.py`. An unknown placeholder makes rendering fail. A new file in `kit/` reaches every project on its next `ecc-kit sync`.
- `skills/`: user-level skills. `bootstrap.sh` links each folder that has a `SKILL.md` into `~/.claude/skills` and `~/.agents/skills`. Keep the list in `skills/README.md` current.
- `machine/`: snapshot output (`manifest.json`, `home/`), written only by `bin/ecc-snapshot`. The exception is `machine/ops/workspace-ops.settings.json`, which is edited by hand and merged into the OpenClaw ops agent's `.claude/settings.json` by the `ops` step, and `machine/launchd/`, which holds hand-maintained launchd plists installed by hand (see README).
- `openclaw-plugins/`: OpenClaw plugins kept here and installed by hand with `openclaw plugins install --link`. `github-event-router` is plain ES module JavaScript with no dependencies and `node --test` tests; see its README for install and rollback. `bootstrap.sh` does not install it.
- `tests/`: `unittest` tests. They use temporary home folders and fake `security`, `curl`, token and `openclaw` commands; `test_gh_command_drain.py` also fakes the GitHub API.
- `.githooks/pre-commit`: runs `lib/ecctools.py scan` on staged files. It runs only when `git config core.hooksPath` prints `.githooks`. `bootstrap.sh` sets that unless `ECC_BOOTSTRAP_NO_HOOKS=1`, which the tests set.

## Checks

There is no CI workflow, bats setup or shellcheck config. Run these from the repository root after a change. None of them modify the machine:

```sh
python3 -m unittest discover -s tests
bash -n bootstrap.sh stack.conf bin/openclaw-gh-app-token
sh -n bin/ecc bin/ecc-kit bin/ecc-snapshot bin/openclaw-gh-command-drain .githooks/pre-commit
python3 -c "import ast; ast.parse(open('lib/ecctools.py').read()); ast.parse(open('lib/gh_command_drain.py').read())"
python3 lib/ecctools.py --help
bin/ecc-kit new --help
./bootstrap.sh --help
python3 lib/ecctools.py scan README.md AGENTS.md stack.conf docs kit skills machine openclaw-plugins lib bin tests
plutil -lint machine/launchd/*.plist
(cd openclaw-plugins/github-event-router && npm test)
git diff --check
```

The scan prints nothing and exits 0 when clean, or exits 1 and names file, line and kind. If you run `shellcheck`, the current scripts already report SC1007 warnings and SC1091, SC2015 and SC2016 notes; do not add new findings. To try a `kit/` change, run `bin/ecc-kit new` against an empty temporary folder, never a real project.

## Do not run

- `./bootstrap.sh` with anything but `--help` (the tests run `--only ops` with a temporary `HOME`; never with your own). Even `--dry-run` probes the real machine, for example `security find-generic-password` for each Keychain name in the `secrets` step.
- `git config` that writes the repository config (for example `git config core.hooksPath .githooks`). Agent worktrees share one `.git/config` with every other worktree of the clone, and the orchestrator stops the unit when it changes. Leave the hook off; the checks above cover the scan.
- `bin/ecc-snapshot`. It has no help switch and always rewrites `machine/` from your home folder.
- `bin/openclaw-gh-command-drain` without `--dry-run`: it moves real queue files and runs `openclaw agent`. Do not run `bin/openclaw-gh-app-token` for real either.
- `bin/ecc`, `lib/ecctools.py restore`, `openclaw-restore` or `openclaw-plugin` against the real home folder or OpenClaw state. Use temporary folders and fake data.

## Conventions

- `bootstrap.sh` and `stack.conf` must work in Bash 3.2. Scripts in `bin/` and `.githooks/` are POSIX `sh`, except `bin/openclaw-gh-app-token`, which is Bash 3.2.
- `lib/ecctools.py` uses Python 3.9 or newer and the standard library only. Output names the file, line and kind of a finding, never the matched value.
- `stack.conf` holds plain `KEY="value"` lines and no secret values. `KEYCHAIN_SECRETS` lists names only.
- When behavior changes, update the `README.md` section that describes it in the same change.
- Prose in this repository uses no em dashes or en dashes.
