#!/bin/bash
# Deploy the whole ECC + OpenClaw stack on a Mac with one call.
#
#   git clone https://github.com/kennylhilljr/ecc-customization.git \
#     ~/Documents/GitHub/ecc-customization && ~/Documents/GitHub/ecc-customization/bootstrap.sh
#
# Safe to run again: every step checks before it changes anything, and an
# existing file or setting is never overwritten without asking. Versions come
# from stack.conf. Secrets are never read, printed or stored here: Keychain
# values are typed by the owner into macOS's own hidden prompt.
#
# Options:
#   --yes                    accept every confirmation (the Keychain prompts
#                            still ask for values; skip them with --skip secrets)
#   --dry-run                print what would run, change nothing
#   --only a,b  --skip a,b   choose steps (names below)
#   --openclaw-archive PATH  restore OpenClaw state from an agent-platform
#                            backup (openclaw-state.tar.gz) when ~/.openclaw is absent
#   --no-launchd             do not install the launchd agents
#   --no-certify             do not run the first runner certification
#   --overwrite-config       replace differing machine configs from machine/
#                            (the current file is kept as <file>.ecc-backup)
#   --help
#
# Steps, in order:
#   prereqs brew node clis repos runtime ecc skills shell machine openclaw
#   secrets launchd verify
set -u

HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=stack.conf
. "$HERE/stack.conf"
LIB="$HERE/lib/ecctools.py"

ALL_STEPS="prereqs brew node clis repos runtime ecc skills shell machine openclaw secrets launchd verify"
DRY=0; YES=0; ONLY=""; SKIP=""; OC_ARCHIVE=""; LAUNCHD=1; CERTIFY=1; OVERWRITE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --yes) YES=1 ;;
    --dry-run) DRY=1 ;;
    --only) ONLY=",$2,"; shift ;;
    --skip) SKIP=",$2,"; shift ;;
    --openclaw-archive) OC_ARCHIVE="$2"; shift ;;
    --no-launchd) LAUNCHD=0 ;;
    --no-certify) CERTIFY=0 ;;
    --overwrite-config) OVERWRITE=1 ;;
    --help|-h) sed -n '2,30p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "bootstrap: unknown option $1 (see --help)" >&2; exit 2 ;;
  esac
  shift
done

# ---------------------------------------------------------------- helpers
DONE=""; WARNINGS=""; OWNER=""
say()   { printf '%s\n' "$*"; }
step()  { printf '\n== %s\n' "$*"; }
ok()    { printf '   ok: %s\n' "$*"; DONE="$DONE
   $*"; }
warn()  { printf '   warning: %s\n' "$*"; WARNINGS="$WARNINGS
   $*"; }
owner() { printf '   for you: %s\n' "$*"; OWNER="$OWNER
   $*"; }
die()   { printf 'bootstrap: %s\n' "$*" >&2; exit 1; }
run()   {
  if [ $DRY -eq 1 ]; then printf '   + %s\n' "$*"; return 0; fi
  "$@"
}
runq()  {
  if [ $DRY -eq 1 ]; then printf '   + %s\n' "$*"; return 0; fi
  "$@" >/dev/null 2>&1
}
have()  { command -v "$1" >/dev/null 2>&1; }
want()  {
  if [ -n "$ONLY" ]; then case "$ONLY" in *",$1,"*) ;; *) return 1 ;; esac; fi
  case "$SKIP" in *",$1,"*) return 1 ;; esac
  return 0
}
confirm() {
  [ $YES -eq 1 ] && return 0
  [ $DRY -eq 1 ] && return 0
  [ -t 0 ] || return 1
  printf '   %s [y/N] ' "$1"; read -r reply
  case "$reply" in y|Y|yes|YES) return 0 ;; esac
  return 1
}
py() {
  for cand in /opt/homebrew/bin/python3 /usr/local/bin/python3 python3; do
    if have "$cand" && "$cand" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' 2>/dev/null; then
      "$cand" "$@"; return $?
    fi
  done
  die "no python3 3.9 or newer"
}
load_brew() {
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do
    [ -x "$b" ] && { eval "$("$b" shellenv)"; return 0; }
  done
  return 1
}
load_node() {
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  # shellcheck disable=SC1091
  [ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh" >/dev/null 2>&1 && nvm use default >/dev/null 2>&1
  return 0
}
ORCH="$GITHUB_DIR/$ORCH_REPO"
INFRA="$GITHUB_DIR/$INFRA_REPO"

# ------------------------------------------------------------------ steps
s_prereqs() {
  step "prereqs: macOS and the command line tools"
  if [ "$(uname -s)" != "Darwin" ] && [ "${ECC_BOOTSTRAP_ANY_OS:-0}" != "1" ]; then
    die "this bootstrap targets macOS (set ECC_BOOTSTRAP_ANY_OS=1 to try anyway)"
  fi
  say "   host: $(uname -s) $(uname -m)"
  if [ "$(uname -s)" = "Darwin" ] && ! xcode-select -p >/dev/null 2>&1; then
    run xcode-select --install
    owner "finish the Xcode command line tools install, then run bootstrap.sh again"
    summary; exit 0
  fi
  ok "command line tools present"
}

s_brew() {
  step "brew: Homebrew and $BREW_FORMULAS"
  if ! load_brew; then
    confirm "Install Homebrew (official installer)?" || { owner "install Homebrew, then rerun"; return; }
    # shellcheck disable=SC2016
    run /bin/bash -c '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
    load_brew || [ $DRY -eq 1 ] || die "Homebrew did not install"
  fi
  for f in $BREW_FORMULAS; do
    if [ $DRY -eq 0 ] && brew list --formula "$f" >/dev/null 2>&1; then continue; fi
    run brew install "$f" || warn "brew install $f failed"
  done
  ok "Homebrew formulas"
}

s_node() {
  step "node: nvm and Node $NODE_VERSION as the default"
  export NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
  if [ ! -s "$NVM_DIR/nvm.sh" ]; then
    run /bin/bash -c "curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/$NVM_VERSION/install.sh | bash" \
      || die "nvm install failed"
  fi
  load_node
  if [ $DRY -eq 0 ]; then
    nvm install "$NODE_VERSION" >/dev/null || die "nvm install $NODE_VERSION failed"
    nvm alias default "$NODE_VERSION" >/dev/null
    nvm use default >/dev/null
    ok "node $(node --version) (nvm default)"
  else
    run nvm install "$NODE_VERSION"; run nvm alias default "$NODE_VERSION"
  fi
}

s_clis() {
  step "clis: Claude Code, Codex, Gemini CLI, OpenClaw"
  load_node
  for pkg in "$CLAUDE_CODE_PKG" "$CODEX_PKG" "$GEMINI_PKG" "$OPENCLAW_PKG"; do
    runq npm install -g --no-fund --no-audit "$pkg" || warn "npm install -g $pkg failed"
  done
  [ $DRY -eq 1 ] && return
  for t in claude codex gemini openclaw; do
    have "$t" && say "   $t: $("$t" --version 2>/dev/null | head -1)" || warn "$t not on PATH after install"
  done
  if have gh; then
    if gh auth status >/dev/null 2>&1; then gh auth setup-git >/dev/null 2>&1; ok "gh signed in"
    else owner "gh auth login   (then rerun, so private repos clone)"; fi
  fi
  if have claude && ! claude auth status >/dev/null 2>&1; then owner "claude auth login"; fi
  if have codex && ! codex login status >/dev/null 2>&1; then owner "codex login"; fi
  owner "gemini: run 'gemini' once to sign in, or rely on GEMINI_API_KEY from the Keychain"
}

clone_or_update() {
  repo="$1"; dir="$GITHUB_DIR/$repo"
  if [ ! -d "$dir/.git" ]; then
    run git clone "https://github.com/$GITHUB_OWNER/$repo.git" "$dir" || { warn "clone $repo failed"; return; }
    ok "cloned $repo"; return
  fi
  [ $DRY -eq 1 ] && { say "   $repo: present"; return; }
  branch=$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null)
  if [ -n "$(git -C "$dir" status --porcelain 2>/dev/null)" ] || [ "$branch" != "main" ]; then
    say "   $repo: left as is (on $branch or has local changes)"; return
  fi
  if git -C "$dir" pull --ff-only --quiet 2>/dev/null; then ok "$repo up to date"
  else say "   $repo: not fast-forwarded (local commits or offline); left as is"; fi
}

s_repos() {
  step "repos: platform and projects under $GITHUB_DIR"
  run mkdir -p "$GITHUB_DIR"
  for r in "$ORCH_REPO" "$INFRA_REPO" $PROJECT_REPOS; do clone_or_update "$r"; done
}

s_runtime() {
  step "runtime: orchestrator copy outside Documents for launchd, and state folders"
  [ -d "$ORCH/.git" ] || [ $DRY -eq 1 ] || { warn "$ORCH missing; run the repos step"; return; }
  run mkdir -p "$ECC_STATE_DIR" "$(dirname "$ECC_RUNTIME_DIR")"
  if [ ! -e "$ECC_RUNTIME_DIR" ]; then
    run git -C "$ORCH" worktree add --detach "$ECC_RUNTIME_DIR" main && ok "runtime worktree at $ECC_RUNTIME_DIR"
  else
    run git -C "$ECC_RUNTIME_DIR" checkout --quiet --detach main && ok "runtime moved to main"
  fi
}

s_ecc() {
  step "ecc: everything-claude-code plugin for Claude Code and Codex"
  load_node
  if have claude; then
    if [ $DRY -eq 0 ] && claude plugin list --json 2>/dev/null | grep -q "\"$ECC_PLUGIN\""; then
      ok "Claude Code has $ECC_PLUGIN"
    else
      runq claude plugin marketplace add "$ECC_MARKETPLACE"
      run claude plugin install "$ECC_PLUGIN" --scope "$ECC_CLAUDE_SCOPE" \
        && ok "Claude Code: $ECC_PLUGIN installed ($ECC_CLAUDE_SCOPE)" \
        || owner "claude plugin install $ECC_PLUGIN --scope $ECC_CLAUDE_SCOPE (approve the trust prompt)"
    fi
  fi
  if have codex; then
    if [ $DRY -eq 0 ] && codex plugin list --json 2>/dev/null | grep -q '"ecc'; then
      ok "Codex has $ECC_PLUGIN"
    else
      runq codex plugin marketplace add "$ECC_MARKETPLACE"
      run codex plugin add "$ECC_PLUGIN" \
        && ok "Codex: $ECC_PLUGIN installed" \
        || owner "codex plugin add $ECC_PLUGIN (approve the trust prompt)"
    fi
  fi
  say "   Gemini has no ECC plugin; it uses the repository skills (.agents/skills)."
}

s_skills() {
  step "skills: shared user-level skills from this repository"
  for target in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
    run mkdir -p "$target"
    for s in "$HERE"/skills/*/; do
      [ -f "$s/SKILL.md" ] || continue
      name=$(basename "$s"); link="$target/$name"
      if [ -L "$link" ] || [ ! -e "$link" ]; then run ln -sfn "${s%/}" "$link"
      else warn "$link exists and is not a link; left as is"; fi
    done
  done
  ok "linked into ~/.claude/skills (Claude Code) and ~/.agents/skills (Codex, Gemini CLI)"
}

s_shell() {
  step "shell: put ecc, ecc-kit and ecc-snapshot on PATH (zsh)"
  rc="$HOME/.zshrc"; mark="# ecc-customization"
  if [ -f "$rc" ] && grep -q "$mark" "$rc"; then say "   already in $rc"; return; fi
  confirm "Add $HERE/bin to PATH in $rc?" || { owner "add $HERE/bin to PATH"; return; }
  if [ $DRY -eq 1 ]; then say "   + append PATH line to $rc"; return; fi
  printf '\n%s\nexport PATH="%s/bin:$PATH"\n' "$mark" "$HERE" >> "$rc"
  ok "PATH line added to $rc (open a new terminal)"
}

s_machine() {
  step "machine: restore captured settings and plugins from machine/"
  if [ ! -f "$HERE/machine/manifest.json" ]; then
    say "   nothing captured yet (run bin/ecc-snapshot on the source machine)"; return
  fi
  args="restore --root $HERE/machine --home $HOME"
  [ $OVERWRITE -eq 1 ] && args="$args --overwrite"
  [ $DRY -eq 1 ] && args="$args --dry-run"
  load_node
  # shellcheck disable=SC2086
  py "$LIB" $args || warn "machine restore reported problems (see above)"
}

s_openclaw() {
  step "openclaw: state and the ECC orchestrator plugin"
  load_node
  have openclaw || [ $DRY -eq 1 ] || { warn "openclaw not installed; run the clis step"; return; }
  oc_dir="${OPENCLAW_STATE_DIR:-$HOME/.openclaw}"
  if [ ! -d "$oc_dir" ]; then
    if [ -n "$OC_ARCHIVE" ]; then
      run py "$LIB" openclaw-restore --archive "$OC_ARCHIVE" --dest "$oc_dir" \
        && ok "OpenClaw state restored from the archive" || die "OpenClaw restore failed"
      owner "openclaw doctor   (reinstalls the gateway service and checks the restored state)"
    elif [ -t 0 ] && confirm "No OpenClaw state. Run 'openclaw onboard --install-daemon' now?"; then
      say "   Choose an API key provider. Never the claude-cli (Claude subscription) provider."
      run openclaw onboard --install-daemon || warn "openclaw onboard did not finish"
    else
      owner "openclaw onboard --install-daemon   (API key provider, never claude-cli), or rerun with --openclaw-archive"
      return
    fi
  fi
  plugin="$ECC_RUNTIME_DIR/integrations/openclaw-plugin"
  run py "$LIB" openclaw-plugin --plugin-dir "$plugin" --state-dir "$ECC_STATE_DIR" \
    && ok "ecc-orchestrator plugin registered" \
    || owner "register the plugin by hand: $ORCH_REPO/integrations/openclaw-plugin/README.md"
}

s_secrets() {
  step "secrets: Keychain items (names only; values go into macOS's hidden prompt)"
  if [ "$(uname -s)" != "Darwin" ]; then warn "no macOS Keychain on this host"; return; fi
  for name in $KEYCHAIN_SECRETS; do
    if security find-generic-password -a "$USER" -s "$name" >/dev/null 2>&1; then
      say "   $name: present"; continue
    fi
    if [ $DRY -eq 0 ] && [ -t 0 ]; then
      printf '   %s is missing. Store it now? [y/N] ' "$name"; read -r reply
      case "$reply" in
        y|Y|yes)
          say "   macOS will ask for the value twice; it is not echoed."
          security add-generic-password -a "$USER" -s "$name" -U -w \
            && ok "$name stored" || warn "$name not stored" ;;
        *) owner "security add-generic-password -a \"\$USER\" -s $name -U -w" ;;
      esac
    else
      owner "security add-generic-password -a \"\$USER\" -s $name -U -w"
    fi
  done
}

s_launchd() {
  step "launchd: inbox processor and weekly recertification"
  [ "$(uname -s)" = "Darwin" ] || { warn "launchd is macOS only"; return; }
  [ $LAUNCHD -eq 1 ] || { say "   skipped (--no-launchd)"; return; }
  confirm "Install or refresh the two launchd agents?" || { owner "launchd agents: $ORCH_REPO/integrations/launchd/README.md"; return; }
  run mkdir -p "$HOME/Library/Logs/openclaw-ecc-orchestrator" "$HOME/Library/LaunchAgents"
  for job in inbox-processor recertify; do
    label="local.openclaw-ecc-orchestrator.$job"
    plist="$HOME/Library/LaunchAgents/$label.plist"
    tmpl="$ECC_RUNTIME_DIR/integrations/launchd/$job.plist.template"
    [ -f "$tmpl" ] || [ $DRY -eq 1 ] || { warn "missing $tmpl"; continue; }
    runq launchctl bootout "gui/$(id -u)/$label"
    if [ $DRY -eq 0 ]; then
      sed -e "s#__REPO__#$ECC_RUNTIME_DIR#g" -e "s#__HOME__#$HOME#g" -e "s#__USER__#$USER#g" "$tmpl" > "$plist"
      [ "$job" = "recertify" ] && /usr/libexec/PlistBuddy \
        -c "Add :EnvironmentVariables:ECC_RECERT_RUNNERS string $ECC_RUNNERS" "$plist" >/dev/null 2>&1
      plutil -lint "$plist" >/dev/null || { warn "$plist did not lint"; continue; }
    fi
    run launchctl bootstrap "gui/$(id -u)" "$plist" && ok "$label loaded"
  done
}

s_verify() {
  step "verify: doctor, certification, catalog and preflight per project"
  load_node
  [ $DRY -eq 1 ] && { say "   (dry run: nothing checked)"; return; }
  if [ -x "$ECC_RUNTIME_DIR/bin/recertify-weekly" ]; then
    "$ECC_RUNTIME_DIR/bin/recertify-weekly" check | sed 's/^/   /'
    cert="$ECC_RUNTIME_DIR/.orchestration/runtime/cert-latest.json"
    if [ $CERTIFY -eq 1 ] && [ ! -s "$cert" ]; then
      say "   first certification of $ECC_RUNNERS (one to three minutes)"
      ECC_RECERT_RUNNERS="$ECC_RUNNERS" "$ECC_RUNTIME_DIR/bin/recertify-weekly" \
        && ok "runners certified" || warn "certification gate not met; see $ECC_RUNTIME_DIR/.orchestration/runtime/"
    fi
  fi
  logs="$ECC_STATE_DIR/logs"; mkdir -p "$logs"
  for p in $PROJECT_REPOS; do
    [ -f "$GITHUB_DIR/$p/.orchestration/ecc.json" ] || continue
    for c in doctor catalog-refresh preflight; do
      log="$logs/bootstrap-$p-$c.log"
      if "$HERE/bin/ecc" --project "$GITHUB_DIR/$p" "$c" >"$log" 2>&1; then
        ok "$p: ecc $c"
      else
        warn "$p: ecc $c failed (log: $log)"
      fi
    done
  done
  if [ -x "$INFRA/bin/agent-platform" ]; then
    run mkdir -p "$INFRA/inventories"
    "$INFRA/bin/agent-platform" inventory --output "$INFRA/inventories/latest.json" >/dev/null 2>&1 \
      && ok "inventory written to $INFRA_REPO/inventories/latest.json" || warn "inventory failed"
  fi
}

summary() {
  printf '\n== summary\n'
  if [ $DRY -eq 1 ]; then label="would do"; else label="done"; fi
  [ -n "$DONE" ] && printf '%s:%s\n' "$label" "$DONE"
  [ -n "$WARNINGS" ] && printf 'warnings:%s\n' "$WARNINGS"
  [ -n "$OWNER" ] && printf 'for you (then rerun bootstrap.sh; finished steps are skipped):%s\n' "$OWNER"
  [ -z "$OWNER$WARNINGS" ] && printf 'everything is in place. Next: ecc --project <repo> status\n'
  return 0
}

[ $DRY -eq 1 ] && say "dry run: nothing will change"
# This repository's own guard: refuse commits that stage anything secret-shaped.
[ $DRY -eq 1 ] || git -C "$HERE" config core.hooksPath .githooks 2>/dev/null
for s in $ALL_STEPS; do
  want "$s" || continue
  load_brew >/dev/null 2>&1
  "s_$s"
done
summary
