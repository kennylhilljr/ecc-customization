# Redeploying the stack

## What the bootstrap does by itself

Installs and pins the toolchain, the runner CLIs, OpenClaw and ECC; clones the repositories; sets up the launchd runtime copy and agents; restores captured settings, skills and plugins; registers the OpenClaw plugin; certifies the runners; and checks every project with `ecc doctor`, `catalog-refresh` and `preflight`.

## What only you can do

These need a person at the keyboard. The bootstrap lists the ones still open in its summary; do them and run it again.

1. **Command line tools.** On a fresh Mac, `git` triggers the Xcode command line tools installer. Finish it, then rerun the clone line.
2. **Sign-ins.** `gh auth login` (so private repositories clone), `claude auth login`, `codex login`, and `gemini` once if you use a Gemini account rather than `GEMINI_API_KEY`.
3. **Keychain values.** For each missing item the bootstrap offers macOS's hidden prompt (`security add-generic-password ... -w`), which asks for the value twice and never echoes it. Values never pass through a file, an argument, a log or a model conversation.
4. **Trust prompts.** Claude Code and Codex may ask you to approve the ECC plugin; macOS may ask about background items for the launchd agents.
5. **OpenClaw.** Either restore the archive from the old Mac (`--openclaw-archive`), then run `openclaw doctor`; or answer `openclaw onboard`. Choose an API key provider, never the claude-cli (Claude subscription) provider.

## Moving from one Mac to another

On the old Mac:

```sh
cd ~/Documents/GitHub/ecc-customization
bin/ecc-snapshot --openclaw
git add machine && git commit -m "Snapshot before moving" && git push
```

Push every other repository too (`git -C <repo> push`). Copy the newest `~/AgentPlatformBackups/openclaw-*/` folder (the archive and its `manifest.json`) to the new Mac by a channel you trust.

On the new Mac:

```sh
git clone https://github.com/kennylhilljr/ecc-customization.git ~/Documents/GitHub/ecc-customization && \
  ~/Documents/GitHub/ecc-customization/bootstrap.sh --openclaw-archive ~/Downloads/openclaw-XXXX/openclaw-state.tar.gz
```

The restore checks the archive against its manifest, refuses unsafe paths, and never writes over an existing `~/.openclaw`.

## When a step fails

Run just that step again with `--only <step>`; add `--dry-run` to see what it would do. Machine configs that differ from the snapshot are left in place with the snapshot beside them as `<file>.ecc-snapshot`; compare and merge, or rerun with `--overwrite-config` (the current file is kept as `<file>.ecc-backup`). Logs of the verify step are in `~/.local/state/openclaw-ecc-orchestrator/logs/bootstrap-*.log`; the launchd agents log to `~/Library/Logs/openclaw-ecc-orchestrator/`.

## Changing the stack

Edit `stack.conf` (a version, a project, a Keychain item name), commit, push. Every machine picks it up on its next `bootstrap.sh`.
