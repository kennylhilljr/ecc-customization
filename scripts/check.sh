#!/bin/sh

fail_setup() {
    printf 'check: %s\n' "$1" >&2
    exit 2
}

script_dir=$(CDPATH= cd -P "$(dirname "$0")" 2>/dev/null && pwd -P) ||
    fail_setup "cannot resolve the script directory"
repo_root=$(CDPATH= cd -P "$script_dir/.." 2>/dev/null && pwd -P) ||
    fail_setup "cannot resolve the repository root"
CDPATH= cd "$repo_root" 2>/dev/null ||
    fail_setup "cannot change to the repository root: $repo_root"

check_tmp=$(mktemp -d /tmp/ecc-check.XXXXXX) ||
    fail_setup "cannot create temporary storage under /tmp"
if [ ! -d "$check_tmp" ]; then
    fail_setup "mktemp did not create temporary storage"
fi

cleanup() {
    status=$?
    trap - 0 1 2 3 15
    if [ -n "${check_tmp:-}" ] && [ -d "$check_tmp" ]; then
        if ! rm -rf "$check_tmp"; then
            printf 'check: cannot remove temporary storage: %s\n' "$check_tmp" >&2
            if [ "$status" -eq 0 ]; then
                status=2
            fi
        fi
    fi
    exit "$status"
}

trap cleanup 0
trap 'exit 129' 1
trap 'exit 130' 2
trap 'exit 131' 3
trap 'exit 143' 15

mkdir "$check_tmp/npm-cache" ||
    fail_setup "cannot create the npm cache directory"
TMPDIR=$check_tmp
PYTHONDONTWRITEBYTECODE=1
npm_config_cache=$check_tmp/npm-cache
export TMPDIR PYTHONDONTWRITEBYTECODE npm_config_cache

failed=0

run_check() {
    label=$1
    shift
    if "$@"; then
        printf 'PASS %s\n' "$label"
    else
        printf 'FAIL %s\n' "$label"
        failed=1
    fi
}

bash_syntax() {
    result=0
    for path in bootstrap.sh stack.conf bin/openclaw-gh-app-token; do
        /bin/bash -n "$path" || result=1
    done
    return "$result"
}

sh_syntax() {
    result=0
    for path in \
        bin/ecc \
        bin/ecc-kit \
        bin/ecc-snapshot \
        bin/openclaw-gh-command-drain \
        .githooks/pre-commit \
        scripts/check.sh
    do
        sh -n "$path" || result=1
    done
    return "$result"
}

python_syntax() {
    python3 -c "import ast; ast.parse(open('lib/ecctools.py').read()); ast.parse(open('lib/gh_command_drain.py').read())"
}

plugin_tests() {
    (CDPATH= cd openclaw-plugins/github-event-router && npm test)
}

run_check unit-tests python3 -m unittest discover -s tests
run_check bash-syntax bash_syntax
run_check sh-syntax sh_syntax
run_check python-syntax python_syntax
run_check ecctools-help python3 lib/ecctools.py --help
run_check kit-help bin/ecc-kit new --help
run_check bootstrap-help ./bootstrap.sh --help
run_check secret-scan python3 lib/ecctools.py scan \
    README.md AGENTS.md stack.conf docs kit skills machine openclaw-plugins lib bin tests

if command -v plutil >/dev/null 2>&1; then
    run_check plist-lint plutil -lint machine/launchd/*.plist
else
    printf 'SKIP plist-lint (plutil is not available)\n'
fi

run_check plugin-tests plugin_tests
run_check diff-check git diff --check

if [ "$failed" -ne 0 ]; then
    exit 1
fi
exit 0
