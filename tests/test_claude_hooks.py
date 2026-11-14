"""Tests for the project Claude Code hooks: .claude/settings.json and .claude/hooks/check_edit.py.

Every case feeds a JSON payload shaped like Claude Code's to the hook in a subprocess and
checks the exit code and message. Nothing here runs a guarded command: the hook only parses
the command text. The post-edit cases use a temporary repository root.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOK = os.path.join(ROOT, ".claude", "hooks", "check_edit.py")
SETTINGS = os.path.join(ROOT, ".claude", "settings.json")
HINT = "\"Do not run\" section of AGENTS.md"


def run_hook(event, payload, *extra, env=None):
    data = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run([sys.executable, "-B", HOOK, event, *extra], input=data,
                          capture_output=True, text=True, timeout=120, env=env)


def bash_payload(command):
    return {"session_id": "test", "hook_event_name": "PreToolUse", "tool_name": "Bash",
            "tool_input": {"command": command, "description": "test"}, "cwd": ROOT}


# (command, rule named in the message)
BLOCKED = [
    # bootstrap.sh with anything but --help or -h
    ("./bootstrap.sh", "bootstrap"),
    ("./bootstrap.sh --dry-run", "bootstrap"),
    ("./bootstrap.sh --only ops", "bootstrap"),
    ("./bootstrap.sh --help --only ops", "bootstrap"),
    ("bash bootstrap.sh", "bootstrap"),
    ("sh ./bootstrap.sh -h --only ops", "bootstrap"),
    ("bash -x bootstrap.sh", "bootstrap"),
    ("source bootstrap.sh", "bootstrap"),
    (". ./bootstrap.sh", "bootstrap"),
    ("/Users/me/ecc-customization/bootstrap.sh", "bootstrap"),
    ("./Bootstrap.SH", "bootstrap"),
    ("x=1 ./bootstrap.sh --only ops", "bootstrap"),
    # bin/ecc-snapshot in any form
    ("bin/ecc-snapshot", "ecc-snapshot"),
    ("./bin/ecc-snapshot --anything", "ecc-snapshot"),
    ("bin/ecc-snapshot --help", "ecc-snapshot"),
    ("sh bin/ecc-snapshot", "ecc-snapshot"),
    ("cd bin && ./ecc-snapshot", "ecc-snapshot"),
    # the command drain without --dry-run
    ("bin/openclaw-gh-command-drain", "command-drain"),
    ("bin/openclaw-gh-command-drain --retry-pending", "command-drain"),
    ("bin/openclaw-gh-command-drain --queue /tmp/q", "command-drain"),
    ("openclaw-gh-command-drain", "command-drain"),
    ("sh bin/openclaw-gh-command-drain", "command-drain"),
    ("python3 lib/gh_command_drain.py", "command-drain"),
    ("python3 lib/gh_command_drain.py --retry-pending", "command-drain"),
    ("python3 lib/gh_command_drain.py --queue x -- --dry-run", "command-drain"),
    ("python3 -m gh_command_drain", "command-drain"),
    ("python3 -m runpy lib/gh_command_drain.py", "command-drain"),
    # the App token helper
    ("bin/openclaw-gh-app-token", "app-token"),
    ("openclaw-gh-app-token", "app-token"),
    ("bash bin/openclaw-gh-app-token --help", "app-token"),
    # bin/ecc runs the real orchestrator
    ("bin/ecc status --run-id x", "ecc"),
    ("ecc --project /tmp/x status", "ecc"),
    # lib/ecctools.py against the real home folder or OpenClaw state
    ("python3 lib/ecctools.py restore --root /Users/me", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine", "ecctools"),
    ("python3 lib/ecctools.py snapshot", "ecctools"),
    ("python3 lib/ecctools.py snapshot --root machine --home /tmp/x", "ecctools"),
    ("python3 lib/ecctools.py snapshot --root /tmp/r", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine --home /tmp/x --home /Users/me", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine --home /tmp/../Users/me", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine --home /tmp/x --ho=/Users/me", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine --home tmp/x", "ecctools"),
    ("python3 lib/ecctools.py restore --root machine --home ~", "ecctools"),
    ("python3 lib/ecctools.py rest --root machine --home ~", "ecctools"),
    ("python3 lib/ecctools.py openclaw-restore --archive a.tgz --dest /Users/me/.openclaw", "ecctools"),
    ("python3 lib/ecctools.py openclaw-plugin --plugin-dir x --state-dir ~/.openclaw", "ecctools"),
    ("python3 -m ecctools restore --root machine --home ~", "ecctools"),
    ("./lib/ecctools.py restore --root machine", "ecctools"),
    ("HOME=/tmp/h env -u HOME python3 lib/ecctools.py restore --root machine", "ecctools"),
    ("HOME=/tmp/h env -i python3 lib/ecctools.py restore --root machine", "ecctools"),
    ("sudo HOME=/tmp/x python3 lib/ecctools.py restore --root m --home ~", "ecctools"),
    # git config writes to the repository config
    ("git config core.hooksPath .githooks", "git-config"),
    ("git config --unset core.hooksPath", "git-config"),
    ("git config --add core.hooksPath x", "git-config"),
    ("git config set core.hooksPath x", "git-config"),
    ("git config --replace-all core.hooksPath x", "git-config"),
    ("git -C /tmp/x config core.hooksPath .githooks", "git-config"),
    ("git --git-dir=/tmp/x/.git config a.b c", "git-config"),
    ("git config --global user.name x", "git-config"),
    ("git config --file /tmp/x/.git/config a.b c", "git-config"),
    ("git config --global --file /tmp/x/cfg a.b c", "git-config"),
    ("git config core.hooksPath \"|\" .githooks", "git-config"),
    ("git config --repl core.hooksPath x", "git-config"),
    # control operators with and without spaces
    ("echo first;./bootstrap.sh", "bootstrap"),
    ("echo first|bin/ecc-snapshot", "ecc-snapshot"),
    ("echo first&&./bootstrap.sh", "bootstrap"),
    ("false||./bootstrap.sh", "bootstrap"),
    ("echo first&./bootstrap.sh", "bootstrap"),
    ("echo first\n./bootstrap.sh", "bootstrap"),
    ("echo a # it's a comment\n./bootstrap.sh", "bootstrap"),
    ("if true; then ./bootstrap.sh; fi", "bootstrap"),
    ("while true; do bin/ecc-snapshot; done", "ecc-snapshot"),
    ("! ./bootstrap.sh", "bootstrap"),
    # grouping and substitutions
    ("{ ./bootstrap.sh; }", "bootstrap"),
    ("(./bootstrap.sh)", "bootstrap"),
    ("echo \"$(./bootstrap.sh)\"", "bootstrap"),
    ("echo $(bin/ecc-snapshot)", "ecc-snapshot"),
    ("echo `bin/ecc-snapshot`", "ecc-snapshot"),
    ("echo \"`bin/ecc-snapshot`\"", "ecc-snapshot"),
    ("echo x > >(./bootstrap.sh)", "bootstrap"),
    ("diff <(bin/ecc-snapshot) x", "ecc-snapshot"),
    ("cat <<EOF\n$(./bootstrap.sh)\nEOF", "bootstrap"),
    ("coproc X { ./bootstrap.sh; }", "bootstrap"),
    ("f() { ./bootstrap.sh; }; f", "bootstrap"),
    # wrappers
    ("env FOO=1 ./bootstrap.sh", "bootstrap"),
    ("env -S './bootstrap.sh'", "bootstrap"),
    ("env -iS'bin/ecc-snapshot'", "ecc-snapshot"),
    ("time -p ./bootstrap.sh", "bootstrap"),
    ("nohup bin/ecc-snapshot &", "ecc-snapshot"),
    ("timeout 5 ./bootstrap.sh", "bootstrap"),
    ("nice -n 5 bin/ecc-snapshot", "ecc-snapshot"),
    ("command ./bootstrap.sh", "bootstrap"),
    ("exec ./bootstrap.sh", "bootstrap"),
    ("caffeinate -i bin/ecc-snapshot", "ecc-snapshot"),
    ("watch -n 1 ./bootstrap.sh", "bootstrap"),
    ("eval ./bootstrap.sh", "bootstrap"),
    ("trap './bootstrap.sh' EXIT", "bootstrap"),
    ("find . -name x -exec bin/ecc-snapshot {} \\;", "ecc-snapshot"),
    ("xargs ./bootstrap.sh", "unchecked-xargs"),
    ("xargs python3 lib/ecctools.py restore --home /tmp/x", "unchecked-xargs"),
    # shells and interpreters
    ("bash -c './bootstrap.sh'", "bootstrap"),
    ("bash -euo pipefail -c './bootstrap.sh'", "bootstrap"),
    ("bash -lc 'bin/ecc-snapshot'", "ecc-snapshot"),
    ("zsh -c ./bootstrap.sh", "bootstrap"),
    ("sh -c \"echo ok; bin/openclaw-gh-command-drain\"", "command-drain"),
    ("bash -c 'bash -c \"./bootstrap.sh\"'", "bootstrap"),
    ("echo ./bootstrap.sh | bash", "unchecked-shell"),
    ("cat x | sh", "unchecked-shell"),
    ("bash -s < script.sh", "unchecked-shell"),
    ("bash <<'EOF'\n./bootstrap.sh\nEOF", "bootstrap"),
    ("bash <<< './bootstrap.sh'", "bootstrap"),
    ("python3 -c \"import subprocess; subprocess.run(['./bootstrap.sh'])\"", "inline-code"),
    ("python3 - <<'EOF'\nimport os; os.system('bin/ecc-snapshot')\nEOF", "inline-code"),
    ("node -e \"require('child_process').execSync('./bootstrap.sh')\"", "inline-code"),
    ("awk 'BEGIN{system(\"./bootstrap.sh\")}'", "inline-code"),
    ("csh -c ./bootstrap.sh", "bootstrap"),
    ("busybox sh -c ./bootstrap.sh", "bootstrap"),
    ("bash /dev/stdin <<EOF\n./bootstrap.sh\nEOF", "bootstrap"),
    ("source /dev/stdin <<EOF\n./bootstrap.sh\nEOF", "bootstrap"),
    ("bash /dev/fd/3", "unchecked-shell"),
    ("python3 /dev/stdin <<EOF\nimport os; os.system('./bootstrap.sh')\nEOF", "inline-code"),
    ("shopt -s expand_aliases; alias b=./bootstrap.sh\nb", "bootstrap"),
    ("trap -- ./bootstrap.sh EXIT", "bootstrap"),
    ("X+=1 ./bootstrap.sh", "bootstrap"),
    ("echo ./bootstrap.sh | xargs -I % sh -c %", "unchecked-xargs"),
    ("echo ./bootstrap.sh | xargs env", "unchecked-xargs"),
    ("xargs -I% %", "unchecked-xargs"),
    ("hash -p ./bootstrap.sh ls; ls", "hash"),
    ("hash ls=./bootstrap.sh", "hash"),
    ("BASH_ENV=bootstrap.sh bash -c true", "bootstrap"),
    ("env 'BASH_FUNC_ls%%=() { bootstrap.sh; }' bash -c ls", "bootstrap"),
    ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.pager GIT_CONFIG_VALUE_0=./bootstrap.sh git log",
     "bootstrap"),
    # zsh precommand modifiers and short forms
    ("noglob ./bootstrap.sh", "bootstrap"),
    ("nocorrect bin/ecc-snapshot", "ecc-snapshot"),
    ("- ./bootstrap.sh", "bootstrap"),
    ("repeat 2 ./bootstrap.sh", "bootstrap"),
    ("if [[ -n x ]] ./bootstrap.sh", "bootstrap"),
    # line continuations, arithmetic and substitutions the way bash reads them
    ("echo \\\\\n./bootstrap.sh", "bootstrap"),
    ("# c \\\n./bootstrap.sh", "bootstrap"),
    ("echo a &\\\n& ./bootstrap.sh", "bootstrap"),
    ("cat <<EOF\nline \\\n$(./bootstrap.sh)\nEOF", "bootstrap"),
    ("echo $((1<<X))\n./bootstrap.sh\nX", "bootstrap"),
    ("echo \"$(case x in x) ./bootstrap.sh;; esac)\"", "bootstrap"),
    ("echo \"$(echo ')'; ./bootstrap.sh)\"", "bootstrap"),
    ("source <(echo ./bootstrap.sh)", "unchecked-shell"),
    (". <(printf x)", "unchecked-shell"),
    ("python3 <(echo hi)", "unchecked-python"),
    ("echo hi | python3", "unchecked-python"),
    ("X=../Users/me; python3 lib/ecctools.py restore --root /tmp/r --home /tmp/$X", "ecctools"),
    ("python3 lib/ecctools.py restore --root /tmp/r --home \"/tmp/$(echo ../Users/x)\"",
     "ecctools"),
    ("python3 lib/ecctools.py restore --root /tmp/r --home /tmp/*", "ecctools"),
    # programs that run a command from their arguments
    ("expect -c \"spawn ./bootstrap.sh\"", "inline-code"),
    ("sandbox-exec -n x ./bootstrap.sh", "bootstrap"),
    ("su -c ./bootstrap.sh", "bootstrap"),
    ("parallel ./bootstrap.sh ::: a", "bootstrap"),
    ("vim -es -c \"!./bootstrap.sh\"", "inline-code"),
    ("vim '+!bin/ecc-snapshot' x", "inline-code"),
    ("rg --pre ./bootstrap.sh x .", "bootstrap"),
    ("GIT_SSH=bin/ecc-snapshot git fetch", "ecc-snapshot"),
    # review round 2
    ("cat <<- EOF\nx\nEOF\n./bootstrap.sh\n\necho done", "bootstrap"),
    ("cat <<- 'EOF'\nx\nEOF\n./bootstrap.sh\n\necho done", "bootstrap"),
    ("bash <<- EOF\n\t./bootstrap.sh\n\tEOF\n\necho done", "bootstrap"),
    ("echo $'\\'' ; ./bootstrap.sh ; echo $'\\'' #'", "unparsable"),
    ("git fetch --upload-pack=./bootstrap.sh /tmp/r", "bootstrap"),
    ("git ls-remote --upload-pack=bin/ecc-snapshot .", "ecc-snapshot"),
    ("git clone -u ./bootstrap.sh /tmp/r /tmp/q", "bootstrap"),
    ("git push --receive-pack=./bootstrap.sh", "bootstrap"),
    ("git archive --remote=/tmp/r --exec=./bootstrap.sh", "bootstrap"),
    ("git grep -O./bootstrap.sh x", "bootstrap"),
    ("git rebase -ix ./bootstrap.sh HEAD~1", "bootstrap"),
    ("git filter-branch --setup ./bootstrap.sh", "bootstrap"),
    ("git -c core.askPass=./bootstrap.sh fetch", "bootstrap"),
    ("git --config-env=core.sshCommand=VAR fetch", "unchecked-git-config"),
    ("GIT_CONFIG_PARAMETERS=\"'core.pager=./bootstrap.sh'\" git log", "bootstrap"),
    ("xcrun ./bootstrap.sh", "bootstrap"),
    ("flock /tmp/l ./bootstrap.sh", "bootstrap"),
    ("ssh localhost ./bootstrap.sh", "bootstrap"),
    ("npx ./bootstrap.sh", "bootstrap"),
    ("su root ./bootstrap.sh", "bootstrap"),
    ("open bin/ecc-snapshot", "ecc-snapshot"),
    ("uv run python3 lib/ecctools.py snapshot --root /Users/x", "ecctools"),
    ("pypy3 lib/gh_command_drain.py", "command-drain"),
    ("python3 -c 'import runpy; runpy.run_path(\"lib/ecctools.py\", run_name=\"__main__\")' "
     "snapshot --root /Users/x", "inline-code"),
    ("perl -e 'exec @ARGV' ./bootstrap.sh", "inline-code"),
    ("ln -s /Users/me /tmp/h && python3 lib/ecctools.py snapshot --root /tmp/r --home /tmp/h",
     "ecctools"),
    ("export GIT_SSH_COMMAND=./bootstrap.sh; git fetch", "bootstrap"),
    ("export BASH_ENV=./bootstrap.sh; bash -c true", "bootstrap"),
    ("LESSOPEN='|./bootstrap.sh %s' less x", "bootstrap"),
    ("mapfile -C ./bootstrap.sh -c 1 < x", "bootstrap"),
    ("TMPDIR=/Users/me python3 lib/ecctools.py restore --root machine --home $TMPDIR/h",
     "ecctools"),
    # review round 3
    ("`echo ./bootstrap.sh`", "unchecked-program"),
    ("sudo `echo ./bootstrap.sh`", "unchecked-program"),
    ("sh -c `echo ./bootstrap.sh`", "unchecked-program"),
    ("bash =(echo ./bootstrap.sh)", "unchecked-shell"),
    ("source =(echo ./bootstrap.sh)", "unchecked-shell"),
    ("echo $(case x in x) ./bootstrap.sh;; esac)", "bootstrap"),
    ("echo $(case x in x) echo;; y) ./bootstrap.sh;; esac)", "bootstrap"),
    ("ssh localhost './bootstrap.sh && echo a/b'", "bootstrap"),
    ("ssh -o ProxyCommand=./bootstrap.sh h", "bootstrap"),
    ("rsync -e ./bootstrap.sh a b:c", "bootstrap"),
    ("tar --use-compress-program=./bootstrap.sh -cf x y", "bootstrap"),
    ("echo ./bootstrap.sh | at now", "unchecked-shell"),
    ("git -c protocol.ext.allow=always clone 'ext::./bootstrap.sh' /tmp/x", "unchecked-git-config"),
    ("GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=d git status",
     "unchecked-git-config"),
    ("echo ./bootstrap.sh | xargs sh", "unchecked-xargs"),
    ("echo \"it's $(./bootstrap.sh)\"", "bootstrap"),
    # substitutions read from the full command text
    ("echo \"$(echo \"a b\"; ./bootstrap.sh)\"", "bootstrap"),
    ("echo \"$(basename \"$(./bootstrap.sh)\")\"", "bootstrap"),
    ("echo \"$(cat <<'EOF'\nit's )\nEOF\n./bootstrap.sh)\"", "bootstrap"),
    ("echo \"$(date)\" \"$(./bootstrap.sh)\"", "bootstrap"),
    ("echo \"$(date) `./bootstrap.sh`\"", "bootstrap"),
    ("echo \"$(echo \"'\")$(./bootstrap.sh)\" \"$(echo \"'\")\"", "bootstrap"),
    ("echo \"$(echo \"'\")\" \"$(./bootstrap.sh)\" \"$(echo \"'\")\"", "bootstrap"),
    ("echo \"$(cat <<'A B'\n)\nA B\n; ./bootstrap.sh)\"", "bootstrap"),
    ("cat <<EOF\nit's $(./bootstrap.sh)\nEOF", "bootstrap"),
    ("echo $(( $(./bootstrap.sh) + 1 ))", "bootstrap"),
    ("echo \"$((cd /tmp && ./bootstrap.sh) | head)\"", "bootstrap"),
    ("x=\"$((cd /tmp; ./bootstrap.sh))\"", "bootstrap"),
    ("echo \"$((true); bin/ecc-snapshot)\"", "ecc-snapshot"),
    ("echo \"$((cd x; $CMD; ./bootstrap.sh) | head)\"", "unchecked-program"),
    ("echo \"$((cd x; eval \"$X\"; ./bootstrap.sh) | head)\"", "unchecked-program"),
    ("echo $((cd x; $CMD; bin/ecc-snapshot) | head)", "unchecked-program"),
    ("echo $((2*3)) && bin/ecc-snapshot", "ecc-snapshot"),
    ("echo \"$((cd x; $CMD; ./bootstrap.sh))\"", "bootstrap"),
    # $((...)) whose first ( closes before the end is a subshell, not arithmetic
    ("X=./bootstrap.sh; echo \"$(($X) | head)\"", "unchecked-program"),
    ("echo \"$((cd x; sh -c \"$X\") | head)\"", "unchecked-program"),
    ("echo $(($CMD) | head)", "unchecked-program"),
    ("echo \"$((cd x; $CMD) )\"", "unchecked-program"),
    ("echo \"$((echo \")\") | ./bootstrap.sh)\"", "bootstrap"),
    ("echo \"$((echo \\(; $CMD); echo \\))\"", "unchecked-program"),
    ("echo \"$((echo ${v:-))}; ./bootstrap.sh) | head)\"", "bootstrap"),
    ("git archive --remote=ext::sh HEAD", "unchecked-git-config"),
    ("*a(<=(sh $((*xargs &bash -c \nin", "unchecked-program"),
    ("rsync -e./bootstrap.sh a host:b", "bootstrap"),
    ("rsync -ave ./bootstrap.sh a host:b", "bootstrap"),
    ("tar -I./bootstrap.sh -cf a b", "bootstrap"),
    ("git clone EXT::sh x", "unchecked-git-config"),
    # case-insensitive file systems
    ("ENV ./bootstrap.sh", "bootstrap"),
    ("NOHUP bin/ecc-snapshot", "ecc-snapshot"),
    ("GIT config core.hooksPath x", "git-config"),
    # git running other commands
    ("git rebase --exec ./bootstrap.sh main", "bootstrap"),
    ("git -c core.pager=./bootstrap.sh log", "bootstrap"),
    ("git -c alias.x=config x core.hooksPath y", "unchecked-git-alias"),
    ("git submodule foreach ./bootstrap.sh", "bootstrap"),
    ("git bisect run bin/ecc-snapshot", "ecc-snapshot"),
    ("GIT_EDITOR=./bootstrap.sh git commit", "bootstrap"),
    # names the guard cannot see
    ("$X --help", "unchecked-program"),
    ("\"$PROGRAM\" ./bootstrap.sh", "unchecked-program"),
    ("./boot*.sh --dry-run", "unchecked-program"),
    ("{./bootstrap.sh,}", "unchecked-program"),
    ("$'./bootstrap.sh'", "unchecked-program"),
    ("$'boot\\x73trap.sh'", "unchecked-program"),
    ("bash $'boot\\x73trap.sh'", "unchecked-program"),
    ("bash -c '\"$0\"' ./bootstrap.sh", "unchecked-program"),
    ("echo \"unclosed", "unparsable"),
    ("./boot\\\nstrap.sh", "bootstrap"),
]

ALLOWED = [
    "./bootstrap.sh --help",
    "./bootstrap.sh -h",
    "bin/openclaw-gh-command-drain --dry-run",
    "bin/openclaw-gh-command-drain --dry-run --retry-pending",
    "python3 lib/gh_command_drain.py --dry-run --queue /tmp/q",
    "grep -n ecc-snapshot README.md",
    "echo \"bootstrap.sh\"",
    "echo 'a;./bootstrap.sh'",
    "printf '%s\\n' \"bin/ecc-snapshot\"",
    "rg \"bin/ecc-snapshot|openclaw-gh-app-token\" -n .",
    "grep -n bootstrap.sh README.md && echo done",
    "python3 lib/ecctools.py restore --root machine --home /tmp/x --dry-run",
    "HOME=/tmp/h python3 lib/ecctools.py restore --root machine",
    "python3 lib/ecctools.py snapshot --root /tmp/r --home /tmp/h",
    "python3 lib/ecctools.py openclaw-restore --archive a.tgz --dest /tmp/x",
    "python3 lib/ecctools.py openclaw-plugin --plugin-dir openclaw-plugins/github-event-router "
    "--state-dir /tmp/s",
    "python3 lib/ecctools.py --help",
    "python3 lib/ecctools.py restore --help",
    "python3 lib/ecctools.py scan README.md AGENTS.md",
    "python3 lib/ecctools.py kit-new /tmp/x --name demo",
    "bash -n bootstrap.sh",
    "sh -n bin/ecc-snapshot",
    "/bin/bash -n bin/openclaw-gh-app-token",
    "bash --version",
    "sh scripts/check.sh",
    "python3 -m unittest discover -s tests",
    "/usr/bin/python3 -B -m unittest discover -s tests",
    "python3 -m json.tool .claude/settings.json",
    "python3 -c \"print(1)\"",
    "git config --get core.hooksPath",
    "git config core.hooksPath",
    "git config get core.hooksPath",
    "git -C /tmp/x config --get core.hooksPath",
    "git config --list --show-origin",
    "git config --file /tmp/x/cfg a.b c",
    "git -c user.name=x commit -m 'it is'",
    "git status && git diff origin/main...HEAD",
    "git log --oneline -5 | cat",
    "git commit -m \"$(cat <<'EOF'\nDon't run bootstrap.sh (it's bad)\n1) first\nEOF\n)\"",
    "cat > /tmp/x.txt <<'EOF'\nit's ./bootstrap.sh text\nEOF",
    "cat <<EOF > /tmp/a\nhello $(date)\nEOF",
    "echo hi # don't",
    "echo ${#x} $# done",
    "ls -la 2>&1 | head",
    "command -v bootstrap.sh",
    "[ -x ./bootstrap.sh ] && echo yes",
    "for f in a b; do echo $f; done",
    "sed -n 1,5p bootstrap.sh",
    "cat bin/openclaw-gh-app-token",
    "npm test --prefix openclaw-plugins/github-event-router",
    "bin/ecc-kit --help",
    "bash /dev/stdin <<EOF\necho hi\nEOF",
    "alias ll='ls -la'",
    "echo x | xargs",
    "git ls-files | xargs grep -n foo",
    "find . -name '*.pyc' -print0 | xargs -0 rm -f",
    "git ls-files | xargs -I{} wc -l {}",
    "env FOO=bar BAR=baz ls",
    "[[ -f x ]] && echo y",
    "python3 --version",
    "diff <(git show HEAD:README.md) README.md",
    "echo $(date) bootstrap.sh",
    "echo \"$(date) it's\"",
    "x=$(git rev-parse HEAD) && echo $x",
    "echo $((1<<2))",
    "echo `date` ok",
    "echo one \\\n  two",
    "<(echo) >out",
    "git fetch origin",
    "git rebase -i origin/main",
    "git push -u origin HEAD",
    "open https://example.com",
    "uv run pytest -q",
    "export FOO=bar",
    "python3 -c 'import sys; print(sys.argv)' a b",
    "IFS=$'\\n' read -r x <<< y",
    "cat <<- EOF\n\tit's\n\tEOF\necho ok",
    "echo 'use `bin/ecc-snapshot` here'",
    "git commit -m 'fix `bin/ecc-snapshot` docs'",
    "gh pr create --body 'Mentions `./bootstrap.sh` and `bin/ecc`'",
    "git commit -m \"$(cat <<'EOF'\nDocs: don't run `./bootstrap.sh`\nEOF\n)\"",
    "git ls-files '*.py' | xargs python3 -m py_compile",
    "x=`date`",
    "case x in a) echo a;; esac",
    "ssh host uptime",
    "rsync -a src/ /tmp/dst/",
    "x=(a b c)",
    "git commit -m \"$(echo \"a b\")\"",
    "echo \"$(basename \"$(pwd)\")\"",
    "x=\"$(echo \"a b\")\"",
    "git commit -m \"$(cat <<'EOF'\nDocs: don't run `./bootstrap.sh` (really)\n1) item\nEOF\n)\"",
    "echo \"$((1<<2))\"",
    "git commit -m 'ext::x'",
    "tar -xvf x.tar",
    "cat > /tmp/x <<'EOF'\nit's `./bootstrap.sh` $(./bootstrap.sh)\nEOF",
    "echo hi # it's `./bootstrap.sh`",
    "echo \"$((2*(3+4)))\"",
    "n=\"$((n+1))\"",
    "echo $((2*3))",
    "echo $((2*(3+4)))",
    "x=$((n*(m+1))); echo $x",
    "for i in $(seq 3); do echo $((i*2)); done",
    "echo \"$((X+1))\"",
    "echo $(( (i+1) % (n) ))",
    "echo \"$(( a ? (b) : (c) ))\"",
    "echo $(((1+2)*3))",
    "echo $(( $(printf %s \")\" >/dev/null; printf 1) + 1 ))",
    "x=1; echo $(( ${x:-)} + 1 ))",
    "X=3; echo \"$(($X*2))\" \"$(( ($X) ))\"",
    "printf '%s\\n' \"$(git log -1 --format='%H (%s)')\"",
]


class PreBashTmpdir(unittest.TestCase):
    def test_tmpdir_paths_follow_the_hook_environment(self):
        env = dict(os.environ, TMPDIR=tempfile.gettempdir())
        command = "python3 lib/ecctools.py restore --root machine --home $TMPDIR/h"
        self.assertEqual(run_hook("pre-bash", bash_payload(command), env=env).returncode, 0)
        # Climb to / however deep TMPDIR is, so the path really is /Users/me.
        depth = len(os.path.realpath(env["TMPDIR"]).strip(os.sep).split(os.sep))
        escape = "python3 lib/ecctools.py restore --root machine --home $TMPDIR" + \
            "/.." * (depth + 1) + "/Users/me"
        self.assertEqual(run_hook("pre-bash", bash_payload(escape), env=env).returncode, 2)

    def test_a_disposable_home_under_tmp_keeps_tmp_paths_but_not_the_home(self):
        # scripts/check.sh runs the suite with HOME and TMPDIR inside /tmp/ecc-check.XXXXXX.
        with tempfile.TemporaryDirectory(dir="/tmp") as base:
            home = os.path.join(base, "home")
            os.makedirs(home)
            env = dict(os.environ, HOME=home, TMPDIR=base)
            for command in [c for c in ALLOWED if "/tmp/" in c]:
                with self.subTest(command=command):
                    result = run_hook("pre-bash", bash_payload(command), env=env)
                    self.assertEqual(result.returncode, 0, result.stderr)
            for target in (home, os.path.join(home, ".openclaw"), base, "/tmp",
                           os.path.join(base, "x", "..", "home"), "$TMPDIR/home"):
                command = "python3 lib/ecctools.py restore --root machine --home " + target
                with self.subTest(command=command):
                    result = run_hook("pre-bash", bash_payload(command), env=env)
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("(ecctools)", result.stderr)

    def test_a_tmpdir_holding_the_home_outside_tmp_is_still_not_a_temp_root(self):
        if not os.access("/var/tmp", os.W_OK) or \
                os.path.realpath("/var/tmp").startswith(os.path.realpath("/tmp") + os.sep):
            self.skipTest("needs a writable /var/tmp outside /tmp")
        with tempfile.TemporaryDirectory(dir="/var/tmp") as base:
            home = os.path.join(base, "home")
            os.makedirs(home)
            env = dict(os.environ, HOME=home, TMPDIR=base)
            for target in (os.path.join(base, "other"), "$TMPDIR/other"):
                command = "python3 lib/ecctools.py restore --root machine --home " + target
                with self.subTest(command=command):
                    result = run_hook("pre-bash", bash_payload(command), env=env)
                    self.assertEqual(result.returncode, 2, result.stderr)
            command = "python3 lib/ecctools.py restore --root machine --home /tmp/x --dry-run"
            self.assertEqual(run_hook("pre-bash", bash_payload(command), env=env).returncode, 0)


class PreBashBlocks(unittest.TestCase):
    def test_each_forbidden_command_exits_2_and_names_its_rule(self):
        for command, rule in BLOCKED:
            with self.subTest(command=command):
                result = run_hook("pre-bash", bash_payload(command))
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("({})".format(rule), result.stderr)
                self.assertIn(HINT, result.stderr)
                self.assertEqual(result.stdout, "")


class PreBashAllows(unittest.TestCase):
    def test_each_allowed_command_exits_0_silently(self):
        for command in ALLOWED:
            with self.subTest(command=command):
                result = run_hook("pre-bash", bash_payload(command))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, "")

    def test_payloads_without_a_command_are_ignored(self):
        for payload in ({}, {"tool_name": "Bash"}, {"tool_name": "Bash", "tool_input": {}},
                        {"tool_name": "Bash", "tool_input": {"command": 5}}, [], "not json"):
            with self.subTest(payload=payload):
                result = run_hook("pre-bash", payload)
                self.assertEqual(result.returncode, 0, result.stderr)


class PreBashChains(unittest.TestCase):
    def test_a_mention_is_allowed_but_a_chained_run_is_not(self):
        self.assertEqual(run_hook("pre-bash", bash_payload(
            "grep -n bootstrap.sh README.md && echo done")).returncode, 0)
        for command in ("echo first && ./bootstrap.sh", "echo first;./bootstrap.sh",
                        "echo first|bin/ecc-snapshot"):
            with self.subTest(command=command):
                self.assertEqual(run_hook("pre-bash", bash_payload(command)).returncode, 2)


class Settings(unittest.TestCase):
    EXPECTED = {
        "PreToolUse": ("Bash", "pre-bash"),
        "PostToolUse": ("Write|Edit|MultiEdit", "post-edit"),
    }

    def setUp(self):
        with open(SETTINGS, encoding="utf-8") as handle:
            self.settings = json.load(handle)

    def test_only_two_hooks_and_both_call_check_edit(self):
        self.assertEqual(set(self.settings), {"hooks"})
        hooks = self.settings["hooks"]
        self.assertEqual(set(hooks), set(self.EXPECTED))
        for event, (matcher, subcommand) in self.EXPECTED.items():
            with self.subTest(event=event):
                groups = hooks[event]
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0]["matcher"], matcher)
                self.assertEqual(set(groups[0]), {"matcher", "hooks"})
                handlers = groups[0]["hooks"]
                self.assertEqual(len(handlers), 1)
                self.assertEqual(handlers[0]["type"], "command")
                self.assertNotIn("args", handlers[0])
                self.assertEqual(shlex.split(handlers[0]["command"]),
                                 ["python3", "$CLAUDE_PROJECT_DIR/.claude/hooks/check_edit.py",
                                  subcommand])

    def test_the_guard_blocks_the_call_when_it_fails(self):
        handler = self.settings["hooks"]["PreToolUse"][0]["hooks"][0]
        self.assertEqual(handler.get("onFailure"), "block")

    def test_the_configured_command_runs_the_hook(self):
        handler = self.settings["hooks"]["PreToolUse"][0]["hooks"][0]
        env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT, PYTHONDONTWRITEBYTECODE="1")
        for command, code in (("./bootstrap.sh", 2), ("./bootstrap.sh --help", 0)):
            with self.subTest(command=command):
                result = subprocess.run(["sh", "-c", handler["command"]],
                                        input=json.dumps(bash_payload(command)),
                                        capture_output=True, text=True, timeout=60, env=env)
                self.assertEqual(result.returncode, code, result.stderr)

    def test_the_hook_is_executable(self):
        self.assertTrue(os.access(HOOK, os.X_OK))


class PostEditReports(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="ecc-hook-test-", dir="/tmp")
        self.addCleanup(shutil.rmtree, self.root, True)
        for folder in ("bin", "lib", "tests"):
            os.mkdir(os.path.join(self.root, folder))
        with open(os.path.join(self.root, "AGENTS.md"), "w", encoding="utf-8") as handle:
            handle.write("# test root\n")
        shutil.copy(os.path.join(ROOT, "lib", "ecctools.py"), os.path.join(self.root, "lib"))

    def write(self, relative, text):
        path = os.path.join(self.root, relative)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)
        return path

    def edit(self, path, tool="Edit"):
        payload = {"hook_event_name": "PostToolUse", "tool_name": tool,
                   "tool_input": {"file_path": path}, "tool_response": {"success": True}}
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
        return run_hook("post-edit", payload, "--root", self.root, env=env)

    def assert_reported(self, result, *needles):
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]
        self.assertEqual(context["hookEventName"], "PostToolUse")
        for needle in needles:
            self.assertIn(needle, context["additionalContext"])

    def test_broken_shell_script_is_reported_without_blocking(self):
        path = self.write("bin/broken.sh", "#!/bin/sh\nif then\n")
        self.assert_reported(self.edit(path, "Write"), "FAIL: sh -n for bin/broken.sh")

    def test_broken_python_file_is_reported_without_blocking(self):
        path = self.write("lib/broken.py", "def broken(:\n    pass\n")
        self.assert_reported(self.edit(path), "FAIL: py_compile for lib/broken.py", "SyntaxError")

    def test_a_failing_test_module_runs_itself(self):
        path = self.write("tests/test_fake.py", "import unittest\n\n\nclass T(unittest.TestCase):\n"
                                                "    def test_fails(self):\n"
                                                "        self.assertEqual(1, 2)\n")
        self.assert_reported(self.edit(path, "MultiEdit"), "FAIL: unittest test_fake")

    def test_a_secret_shaped_value_is_reported(self):
        token = "gh" + "p_" + "Q" * 24
        path = self.write("lib/notes.txt", "token = {}\n".format(token))
        result = self.edit(path)
        self.assert_reported(result, "FAIL: secret scan for lib/notes.txt", "github token")
        self.assertNotIn(token, result.stdout + result.stderr)

    def test_a_healthy_file_reports_nothing(self):
        path = self.write("lib/good.py", "VALUE = 1\n")
        result = self.edit(path)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "")
        self.assertIn("PASS py_compile (lib/good.py)", result.stderr)
        self.assertNotIn("FAIL", result.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.root, "lib", "__pycache__")))

    def test_files_outside_the_root_and_missing_files_are_ignored(self):
        outside = tempfile.NamedTemporaryFile("w", suffix=".py", dir="/tmp", delete=False)
        outside.write("def broken(:\n")
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        for payload_path in (outside.name, os.path.join(self.root, "lib", "missing.py"), None):
            with self.subTest(path=payload_path):
                result = self.edit(payload_path)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
