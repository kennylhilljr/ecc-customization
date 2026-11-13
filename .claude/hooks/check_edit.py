#!/usr/bin/env python3
"""Project Claude Code hooks for this repository (Python 3.9, standard library only).

    check_edit.py pre-bash    PreToolUse, matcher Bash
    check_edit.py post-edit   PostToolUse, matcher Write|Edit|MultiEdit

Both read the hook payload Claude Code writes to stdin as JSON.

pre-bash blocks a Bash command that runs something the "Do not run" section of
AGENTS.md forbids. It exits 2 and names the rule on stderr, which is how a
PreToolUse hook stops a tool call. It splits the command the way the shell
does (quotes, ;, &&, ||, |, &, newlines, subshells, $(...), backticks,
here-documents, comments) and looks at the program each part runs, after
wrappers such as env, nohup, timeout and xargs and through sh/bash -c, sh
SCRIPT, source, eval and python SCRIPT. A name inside a grep pattern or an echo
string is an argument, not a program, so it does not trigger a rule. A command
it cannot parse, or whose program name comes from a shell expansion, is
blocked.

This is a guardrail against mistakes, not a security boundary. A determined
agent can still get around it, for example by copying a script under another
name, writing a script and running that, or building the command at run time
inside another program.

post-edit runs the quick checks for the file that was just edited (syntax,
the matching test module, the secret scan) and reports failures to Claude as
additional context. It never blocks: it always exits 0.
"""
import argparse
import io
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath

AGENTS_HINT = "see the \"Do not run\" section of AGENTS.md"

# ---------------------------------------------------------------- shell splitting

PUNCTUATION = ";&|<>()`\n"
BLANKS = " \t\r"
MAX_DEPTH = 6
REDIRECTIONS = ("&>>", "<<<", "&>", ">>", ">&", "<&", "<>", "<<", ">|", ">", "<")
SEPARATORS = (";;&", "&&", "||", ";;", ";&", "|&", ";", "&", "|", "(", ")", "`", "\n")
OPERATORS = sorted(REDIRECTIONS + SEPARATORS, key=len, reverse=True)
# Shell keywords that can start a simple command once ; and newlines have split it.
RESERVED_WORDS = ("{", "}", "!", "if", "then", "elif", "else", "fi", "do", "done", "while",
                  "until", "case", "esac", "for", "select", "in")
# Characters that make a program name depend on an expansion the hook cannot see.
EXPANSION_CHARS = "$`*?[{}"


class Unparsable(Exception):
    """The command cannot be split reliably; the hook fails closed."""


def _split_operator(run):
    """Split a run of punctuation into shell operators, longest match first."""
    pieces, pos = [], 0
    while pos < len(run):
        for op in OPERATORS:
            if run.startswith(op, pos):
                pieces.append(op)
                pos += len(op)
                break
        else:   # unreachable: every punctuation character starts an operator
            pieces.append(run[pos])
            pos += 1
    return pieces


def _read_heredocs(text, pos, pending):
    """Consume the bodies of pending here-documents starting at pos.

    Returns (new position, [(body, quoted), ...]), or (None, None) when a
    delimiter line is missing; the caller then lexes the text as commands.
    """
    bodies = []
    for delimiter, quoted, strip_tabs in pending:
        lines, found = [], False
        while pos < len(text):
            newline = text.find("\n", pos)
            line_end = len(text) if newline < 0 else newline
            line = text[pos:line_end]
            pos = len(text) if newline < 0 else newline + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                found = True
                break
            lines.append(line)
        if not found:
            return None, None
        bodies.append(("\n".join(lines), quoted))
    return pos, bodies


def _tokens(text):
    """Yield ('word', value, source, start, end), ('op', operator, start, end) and
    ('heredoc', body, quoted) tokens for a shell command."""
    pos = 0
    pending, expect_delimiter, delimiter_after = [], False, -1
    while pos is not None and pos < len(text):
        stream = io.StringIO(text)
        stream.seek(pos)
        lexer = shlex.shlex(stream, posix=True, punctuation_chars=PUNCTUATION)
        lexer.whitespace = BLANKS
        lexer.whitespace_split = True
        lexer.commenters = ""
        restart = None
        while restart is None:
            start = stream.tell() - len(lexer._pushback_chars)
            peek = start
            while peek < len(text) and text[peek] in BLANKS:
                peek += 1
            if peek < len(text) and text[peek] == "#":
                # A comment runs to the end of the line; the newline still separates.
                newline = text.find("\n", peek)
                if newline < 0:
                    return
                restart = newline
                break
            try:
                token = lexer.get_token()
            except ValueError as error:
                raise Unparsable(str(error)) from None
            if token is None:
                return
            end = stream.tell() - len(lexer._pushback_chars)
            raw = text[start:end]
            body_start = start + len(raw) - len(raw.lstrip(BLANKS))
            body = raw.strip(BLANKS)
            if body and body == token and all(ch in PUNCTUATION for ch in token):
                offset = body_start
                for piece in _split_operator(token):
                    piece_start, offset = offset, offset + len(piece)
                    yield ("op", piece, piece_start, offset)
                    if piece == "<<":
                        expect_delimiter, delimiter_after = True, offset
                    elif piece == "\n" and pending:
                        new_pos, bodies = _read_heredocs(text, offset, pending)
                        pending = []
                        if new_pos is not None:
                            for heredoc_body, quoted in bodies:
                                yield ("heredoc", heredoc_body, quoted)
                            restart = new_pos
                            break
                continue
            if expect_delimiter:
                expect_delimiter = False
                strip_tabs = body_start == delimiter_after and token.startswith("-")
                delimiter = token[1:] if strip_tabs else token
                quoted = any(ch in body for ch in "'\"\\")
                pending.append((delimiter, quoted, strip_tabs))
            yield ("word", token, body, body_start, body_start + len(body))
        pos = restart


class SimpleCommand:
    def __init__(self):
        self.words = []
        self.stdin = []          # here-document and here-string text fed to the command
        self.stdin_file = False  # input redirected from a file


def split_commands(text):
    """Split a shell command into simple commands.

    Returns (commands, texts): texts are every word value and unquoted
    here-document body, where a command substitution can hide.
    """
    commands, texts, owners = [], [], []
    current = SimpleCommand()
    ends, sources = [], []
    target = None
    for token in _tokens(text):
        kind = token[0]
        if kind == "heredoc":
            _, body, quoted = token
            if owners:
                owners.pop(0).stdin.append(body)
            if not quoted:
                texts.append(body)
            continue
        if kind == "word":
            _, value, source, start, end = token
            texts.append(value)
            if target is not None:
                if target == "<<<":
                    current.stdin.append(value)
                target = None
                continue
            if "$'" in source or '$"' in source:
                # ANSI-C or locale quoting: shlex does not decode $'\x2e'. A trailing $ marks
                # the word, its last path part included, as an expansion the guard cannot read.
                value = value + "$"
            current.words.append(value)
            ends.append(end)
            sources.append(source)
            continue
        _, piece, start, end = token
        if piece in REDIRECTIONS:
            if current.words and ends[-1] == start and sources[-1].isdigit():
                current.words.pop()     # a file descriptor, as in 2>&1
                ends.pop()
                sources.pop()
            if piece == "<<":
                owners.append(current)
            elif piece in ("<", "<>"):
                current.stdin_file = True
            target = piece
            continue
        target = None
        if current.words or current.stdin:
            commands.append(current)
        current = SimpleCommand()
        ends, sources = [], []
    if current.words or current.stdin:
        commands.append(current)
    return commands, texts


def _substitutions(text):
    """Return the text of each $(...) and `...` in a word or here-document body."""
    found, index = [], 0
    while index < len(text):
        if text.startswith("$(", index):
            depth, stop = 0, index + 1
            while stop < len(text):
                if text[stop] == "(":
                    depth += 1
                elif text[stop] == ")":
                    depth -= 1
                    if depth == 0:
                        break
                stop += 1
            found.append(text[index + 2:stop])
            index = stop + 1
        elif text[index] == "`":
            stop = text.find("`", index + 1)
            stop = len(text) if stop < 0 else stop
            found.append(text[index + 1:stop])
            index = stop + 1
        elif text[index] == "\\":
            index += 2
        else:
            index += 1
    return found


# ---------------------------------------------------------------- paths

def _temp_roots():
    roots = set()
    home = os.path.realpath(os.path.expanduser("~"))
    for candidate in ("/tmp", tempfile.gettempdir()):
        real = os.path.realpath(candidate)
        # A TMPDIR of / or of a folder holding the home folder would allow everything.
        if real == os.sep or home == real or home.startswith(real.rstrip(os.sep) + os.sep):
            continue
        roots.add(real)
    return roots


def is_temp_path(value):
    """True when value is an absolute path inside /tmp or the system temp folder."""
    if not isinstance(value, str) or not os.path.isabs(value):
        return False
    real = os.path.realpath(value)
    return any(real == root or real.startswith(root.rstrip(os.sep) + os.sep)
               for root in _temp_roots())


def _base(word):
    return os.path.basename(word.rstrip("/")) if word else ""


def _is_dynamic(name):
    return any(ch in name for ch in EXPANSION_CHARS)


def _is_assignment(word):
    name, equals, _ = word.partition("=")
    if name.endswith("+"):
        name = name[:-1]    # NAME+=value appends
    return bool(equals) and name.isidentifier()


# ---------------------------------------------------------------- rules

class Context:
    def __init__(self, env, via_xargs, depth):
        self.env = env
        self.via_xargs = via_xargs
        self.depth = depth


def _message(rule, text):
    return "blocked by .claude/hooks/check_edit.py ({}): {}; {}.".format(rule, text, AGENTS_HINT)


DYNAMIC_MESSAGE = _message(
    "unchecked-program",
    "the program or script name uses a shell expansion ($VAR, $(...), a glob or braces), "
    "so the guard cannot tell whether it is a command AGENTS.md forbids. Spell the name out")
STDIN_SHELL_MESSAGE = _message(
    "unchecked-shell",
    "a shell that reads its commands from a pipe, a file redirect or -s cannot be checked. "
    "Pass the commands with -c or run them directly")
XARGS_MESSAGE = _message(
    "unchecked-xargs",
    "{} run through xargs takes arguments from stdin, so they cannot be checked")


def rule_bootstrap(args, ctx):
    if not ctx.via_xargs and args in (["--help"], ["-h"]):
        return None
    return _message("bootstrap", "./bootstrap.sh may only be run with --help or -h. Even --dry-run "
                                 "probes the real machine and the Keychain")


def rule_snapshot(args, ctx):
    return _message("ecc-snapshot", "bin/ecc-snapshot has no help switch and always rewrites "
                                    "machine/ from your home folder")


def rule_drain(args, ctx):
    options = args[:args.index("--")] if "--" in args else args
    if "--dry-run" in options:
        return None
    return _message("command-drain", "openclaw-gh-command-drain (lib/gh_command_drain.py) needs "
                                     "--dry-run; without it, it moves real queue files and runs "
                                     "openclaw agent (--retry-pending is not enough)")


def rule_app_token(args, ctx):
    return _message("app-token", "openclaw-gh-app-token talks to the real GitHub App with the "
                                 "Keychain key; use the fakes in tests/")


def rule_ecc(args, ctx):
    return _message("ecc", "bin/ecc runs the external ECC orchestrator with Keychain secrets "
                           "against real projects; test with temporary folders and fakes")


ECCTOOLS_GUARDED = {
    # subcommand: options that must all point under a temp folder
    "snapshot": ("--root", "--home"),
    "restore": ("--home",),
    "openclaw-restore": ("--dest",),
    "openclaw-plugin": ("--state-dir",),
}
ECCTOOLS_OTHER = ("kit-new", "kit-diff", "kit-sync", "plan-json", "scan", "merge-settings")


def _option_values(args, option):
    """Values given for a long option, accepting --opt V, --opt=V and argparse abbreviations."""
    values = []
    for index, arg in enumerate(args):
        if not arg.startswith("--") or len(arg) < 3:
            continue
        name, equals, value = arg.partition("=")
        if not option.startswith(name):
            continue
        if equals:
            values.append(value)
        else:
            values.append(args[index + 1] if index + 1 < len(args) else "")
    return values


def rule_ecctools(args, ctx):
    index = 0
    while index < len(args) and args[index].startswith("-"):
        if args[index] in ("-h", "--help"):
            return None
        index += 1
    if index >= len(args):
        return None
    sub = args[index]
    guarded = [name for name in ECCTOOLS_GUARDED if name == sub or
               (sub not in ECCTOOLS_OTHER and name.startswith(sub))]
    if not guarded:
        return None
    sub = guarded[0]
    rest = args[index + 1:]
    if ctx.via_xargs:
        return XARGS_MESSAGE.format("lib/ecctools.py " + sub)
    if "-h" in rest or "--help" in rest:
        return None
    for option in ECCTOOLS_GUARDED[sub]:
        values = _option_values(rest, option)
        if not values and option == "--home" and "HOME" in ctx.env:
            values = [ctx.env["HOME"]]      # --home defaults to ~
        if not values or not all(is_temp_path(value) for value in values):
            wanted = " and ".join(ECCTOOLS_GUARDED[sub])
            return _message("ecctools", "lib/ecctools.py {} must not touch the real home folder or "
                                        "OpenClaw state: give {} as absolute paths under /tmp or "
                                        "the system temp folder".format(sub, wanted))
    return None


SCRIPT_RULES = {
    "bootstrap.sh": rule_bootstrap,
    "ecc-snapshot": rule_snapshot,
    "openclaw-gh-command-drain": rule_drain,
    "gh_command_drain.py": rule_drain,
    "openclaw-gh-app-token": rule_app_token,
    "ecctools.py": rule_ecctools,
    "ecc": rule_ecc,
}
ALWAYS_BLOCKED = ("ecc-snapshot", "openclaw-gh-app-token", "ecc")


def check_script(word, args, ctx):
    """Apply the script rules to a program or script path and its arguments."""
    name = _base(word).lower()      # macOS file systems ignore case
    if _is_dynamic(name):
        return DYNAMIC_MESSAGE
    rule = SCRIPT_RULES.get(name)
    if rule is None:
        return None
    if ctx.via_xargs and name not in ALWAYS_BLOCKED and name != "ecctools.py":
        if not (rule is rule_drain and "--dry-run" in args):
            return XARGS_MESSAGE.format(name)
    return rule(args, ctx)


# Inline code: a guarded name in python -c, perl -e, node -e and the like.
INLINE_MARKERS = ("bootstrap.sh", "ecc-snapshot", "openclaw-gh-command-drain", "gh_command_drain",
                  "openclaw-gh-app-token")
INLINE_FLAGS = {
    "perl": ("-e", "-E"), "ruby": ("-e",), "node": ("-e", "--eval", "-p", "--print"),
    "bun": ("-e", "--eval", "-p", "--print"), "osascript": ("-e",), "php": ("-r",),
}
AWKS = ("awk", "gawk", "mawk", "nawk")


def check_inline_code(code):
    lowered = code.lower()
    hit = next((marker for marker in INLINE_MARKERS if marker in lowered), None)
    if hit is None and re.search(r"bin/ecc(?![\w-])", lowered):
        hit = "bin/ecc"
    if hit is None and "ecctools" in lowered and re.search(
            r"snapshot|restore|openclaw[-_]plugin", lowered):
        hit = "lib/ecctools.py snapshot/restore/openclaw-plugin"
    if hit is None:
        return None
    return _message("inline-code", "inline code mentions {}, which the guard cannot check "
                                   "inside another language".format(hit))


def _inline_codes(program, args):
    codes = []
    if program in AWKS:
        index = 0
        while index < len(args) and args[index].startswith("-") and args[index] != "--":
            if args[index] in ("-f", "--file"):
                return []
            index += 2 if args[index] in ("-F", "-v") else 1
        if index < len(args) and args[index] == "--":
            index += 1
        return args[index:index + 1]
    flags = INLINE_FLAGS.get(program, ())
    for index, arg in enumerate(args):
        if arg in flags and index + 1 < len(args):
            codes.append(args[index + 1])
        elif any(arg.startswith(flag + "=") for flag in flags if flag.startswith("--")):
            codes.append(arg.split("=", 1)[1])
    return codes


def _is_python(name):
    if name in ("python", "python3"):
        return True
    return name.startswith("python3.") and name[len("python3."):].isdigit()


SCRIPT_RUNNING_MODULES = ("runpy", "cProfile", "profile", "pdb", "trace")


def python_targets(args):
    """Return (scripts, codes) a python command runs: scripts are (path, args) pairs."""
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            return ([(args[index + 1], args[index + 2:])] if index + 1 < len(args) else []), []
        if arg == "-":
            return [], []
        if arg.startswith("--"):
            index += 2 if arg == "--check-hash-based-pycs" else 1
            continue
        if arg.startswith("-") and len(arg) > 1:
            takes_value = False
            for position, flag in enumerate(arg[1:], start=1):
                inline = arg[position + 1:]
                if flag in "mc":
                    value = inline or (args[index + 1] if index + 1 < len(args) else "")
                    rest = args[index + 1:] if inline else args[index + 2:]
                    if flag == "c":
                        return [], [value]
                    leaf = value.rsplit(".", 1)[-1] + ".py"
                    if leaf in SCRIPT_RULES:
                        return [(leaf, rest)], []
                    if value in SCRIPT_RUNNING_MODULES:
                        return [(rest[k], rest[k + 1:]) for k in range(len(rest))
                                if not rest[k].startswith("-")], []
                    return [], []
                if flag in "WX":
                    takes_value = not inline
                    break
            index += 2 if takes_value else 1
            continue
        return [(arg, args[index + 1:])], []
    return [], []


SHELLS = ("sh", "bash", "rbash", "zsh", "dash", "ash", "ksh", "mksh", "oksh", "pdksh", "yash",
          "posh", "fish", "csh", "tcsh")
# Operands that name the command's own stdin or an open file descriptor.
STDIN_PATHS = re.compile(r"^/(dev/stdin|dev/fd/\d+|proc/self/fd/\d+|dev/fd/?)$")


def check_shell(args, command, ctx):
    """sh/bash/zsh: check -c strings, scripts and here-documents."""
    index, has_c, reads_stdin = 0, False, False
    while index < len(args):
        arg = args[index]
        if arg in ("--version", "--help"):
            return None
        if arg in ("-o", "+o", "-O", "+O", "--rcfile", "--init-file"):
            index += 2
            continue
        if arg == "--":
            index += 1
            break
        if arg.startswith("--"):
            index += 1
            continue
        if arg[:1] in ("-", "+") and len(arg) > 1:
            if arg[0] == "-" and "n" in arg[1:]:
                return None     # -n reads without running anything
            if arg[0] == "-" and "c" in arg[1:]:
                has_c = True
            if arg[0] == "-" and "s" in arg[1:]:
                reads_stdin = True
            index += 2 if arg[-1] in "oO" else 1    # -euo pipefail
            continue
        break
    if has_c:
        if index >= len(args):
            return None
        return check_command(args[index], ctx.depth + 1)
    if reads_stdin or index >= len(args) or args[index] == "-" or STDIN_PATHS.match(args[index]):
        if command.stdin and not command.stdin_file:
            for text in command.stdin:
                message = check_command(text, ctx.depth + 1)
                if message:
                    return message
            return None
        return STDIN_SHELL_MESSAGE
    return check_script(args[index], args[index + 1:], ctx)


GIT_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
                     "--config-env", "--attr-source", "--list-cmds")
# git config keys whose value is a command git runs.
GIT_COMMAND_KEYS = re.compile(
    r"^(core\.(pager|editor|sshcommand|fsmonitor)|sequence\.editor|diff\.external|"
    r"gpg(\.[^.]+)?\.program|credential(\..+)?\.helper|pager\..+|filter\..+\.(clean|smudge|process)|"
    r"merge\..+\.driver|diff\..+\.(command|textconv))$")
GIT_CONFIG_READ_ACTIONS = ("--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color",
                           "--get-colorbool", "-l", "--list")
GIT_CONFIG_SAFE_FLAGS = ("--global", "--system", "--local", "--worktree", "--show-origin",
                         "--show-scope", "--name-only", "-z", "--null", "--includes",
                         "--no-includes", "--bool", "--int", "--bool-or-int", "--path",
                         "--expiry-date", "--fixed-value", "--all", "--regexp", "--no-type")
GIT_CONFIG_VALUE_OPTIONS = ("--blob", "--type", "--default", "--value", "--url", "--comment")
GIT_CONFIG_MESSAGE = _message(
    "git-config", "git config may not write the repository config: every worktree of this clone "
                  "shares one .git/config and the orchestrator stops the unit when it changes. "
                  "Read with --get or --list, or write a scratch file under /tmp with --file")
ENV_COMMAND_VARIABLES = ("GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_SSH_COMMAND",
                         "GIT_EXTERNAL_DIFF", "EDITOR", "VISUAL", "PAGER")


def check_git_c(value, ctx):
    key, _, setting = value.partition("=")
    key = key.lower()
    if key.startswith("alias."):
        return _message("unchecked-git-alias", "a git alias set with -c cannot be checked; "
                                               "run the git command it stands for")
    if GIT_COMMAND_KEYS.match(key):
        return check_command(setting.lstrip("!"), ctx.depth + 1)
    return None


def _is_scratch_config(path):
    """True for a config file under a temp folder that is not inside a .git folder."""
    return is_temp_path(path) and ".git" not in os.path.realpath(path).split(os.sep)


def check_git_config(args):
    files, write, read, positionals, other_scope = [], False, False, [], False
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "--":
            positionals.extend(args[index + 1:])
            break
        name, equals, value = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        if name in ("--file", "-f"):
            if not equals:
                index += 1
                value = args[index] if index < len(args) else ""
            files.append(value)
        elif arg.startswith("-f") and len(arg) > 2:
            files.append(arg[2:])
        elif name in GIT_CONFIG_VALUE_OPTIONS:
            if not equals:
                index += 1
        elif name in GIT_CONFIG_READ_ACTIONS:
            read = True
        elif name in GIT_CONFIG_SAFE_FLAGS:
            other_scope = other_scope or name in ("--global", "--system")
        elif arg.startswith("-") and len(arg) > 1:
            write = True    # an action that writes, or an option the guard does not know
        else:
            positionals.append(arg)
        index += 1
    if not write and not read:
        first = positionals[0] if positionals else ""
        if first in ("set", "unset", "rename-section", "remove-section", "edit"):
            write = True
        elif first not in ("get", "list") and len(positionals) >= 2:
            write = True
    if not write:
        return None
    # Only a scratch file is safe: -C or --git-dir under /tmp can still be a worktree of this
    # clone, and --global or --system writes the user's or the machine's config.
    if files and not other_scope and all(_is_scratch_config(path) for path in files):
        return None
    return GIT_CONFIG_MESSAGE


def check_git(args, ctx):
    index = 0
    while index < len(args):
        arg = args[index]
        name, equals, inline = arg.partition("=") if arg.startswith("--") else (arg, "", "")
        if name in ("-C", "-c") or (name in GIT_VALUE_OPTIONS and not equals):
            value = args[index + 1] if index + 1 < len(args) else ""
            index += 2
        elif arg.startswith("-C") or arg.startswith("-c"):
            name, value = arg[:2], arg[2:]
            index += 1
        elif arg.startswith("-"):
            index += 1
            continue
        else:
            break
        if name == "-c":
            message = check_git_c(value, ctx)
            if message:
                return message
    if index >= len(args):
        return None
    sub, rest = args[index], args[index + 1:]
    if sub == "config":
        if ctx.via_xargs:
            return XARGS_MESSAGE.format("git config")
        return check_git_config(rest)
    commands = []
    if sub in ("rebase", "difftool"):
        flags = ("-x", "--exec") if sub == "rebase" else ("-x", "--extcmd")
        for position, arg in enumerate(rest):
            if arg in flags and position + 1 < len(rest):
                commands.append(rest[position + 1])
            elif arg.startswith(flags[1] + "="):
                commands.append(arg.split("=", 1)[1])
            elif arg.startswith("-x") and len(arg) > 2:
                commands.append(arg[2:])
    elif sub == "filter-branch":
        for position, arg in enumerate(rest):
            if arg.endswith("-filter") and arg.startswith("--") and position + 1 < len(rest):
                commands.append(rest[position + 1])
    elif sub == "bisect" and rest[:1] == ["run"]:
        commands.append(" ".join(shlex.quote(word) for word in rest[1:]))
    elif sub == "submodule" and "foreach" in rest:
        tail = rest[rest.index("foreach") + 1:]
        while tail and tail[0] in ("--recursive", "-q", "--quiet"):
            tail = tail[1:]
        commands.append(" ".join(tail))
    for text in commands:
        message = check_command(text, ctx.depth + 1)
        if message:
            return message
    return None


WRAPPERS = ("env", "time", "busybox", "sudo", "doas", "nohup", "command", "exec", "nice", "ionice", "caffeinate",
            "xargs", "timeout", "gtimeout", "watch", "arch", "setsid", "stdbuf", "taskpolicy",
            "unbuffer", "builtin", "script", "coproc", "chronic")
WRAPPER_VALUE_OPTIONS = {
    "env": ("-u", "-C", "-P", "--unset", "--chdir"),
    "time": ("-o", "-f", "--output", "--format"),
    "sudo": ("-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T", "--user", "--group",
             "--host", "--prompt", "--chdir", "--close-from", "--role", "--type", "--other-user"),
    "doas": ("-u", "-C"),
    "stdbuf": ("-i", "-o", "-e", "--input", "--output", "--error"),
    "taskpolicy": ("-c", "-t", "-l", "-p", "-g"),
    "nice": ("-n", "--adjustment"),
    "ionice": ("-c", "-n", "-p", "--class", "--classdata"),
    "caffeinate": ("-t", "-w"),
    "exec": ("-a",),
    "xargs": ("-I", "-J", "-L", "-n", "-P", "-s", "-E", "-d", "-a", "-R", "-S"),
    "timeout": ("-s", "-k", "--signal", "--kill-after"),
    "gtimeout": ("-s", "-k", "--signal", "--kill-after"),
    "watch": ("-n", "--interval", "-d", "--differences"),
    "arch": ("-e",),
    "script": ("-t", "-T", "-F"),
}


def check_simple(command, depth):
    """Return a block message for one simple command, or None."""
    words = command.words
    index, wrapper, via_xargs, env = 0, None, False, {}
    while index < len(words):
        word = words[index]
        base = _base(word).lower()      # macOS file systems ignore case: ENV is env
        if word in RESERVED_WORDS:
            index += 1
        elif word == "function":
            index += 2
        elif _is_assignment(word):
            name, _, value = word.partition("=")
            name = name.rstrip("+")
            env[name] = value
            if name in ENV_COMMAND_VARIABLES:
                message = check_command(value, depth + 1)
                if message:
                    return message
            index += 1
        elif base in WRAPPERS and (wrapper is None or not word.startswith("-")):
            if base in ("sudo", "doas"):
                env = {}        # sudo resets the environment
            if base == "command" and index + 1 < len(words) and words[index + 1] in ("-v", "-V"):
                return None     # only looks the name up
            if base == "coproc" and index + 2 < len(words) and words[index + 2] == "{":
                index += 1      # coproc NAME { ...; }
            wrapper = base
            via_xargs = via_xargs or base == "xargs"
            index += 1
            if base in ("timeout", "gtimeout", "script"):
                while index < len(words) and words[index].startswith("-"):
                    index += 2 if words[index] in WRAPPER_VALUE_OPTIONS[base] else 1
                index += 1      # timeout's duration, script's output file
            elif base == "watch":
                while index < len(words) and words[index].startswith("-"):
                    index += 2 if words[index] in WRAPPER_VALUE_OPTIONS[base] else 1
                return check_command(" ".join(words[index:]), depth + 1)  # watch runs sh -c
        elif wrapper == "env" and word in ("-", "-i", "--ignore-environment"):
            env = {}
            index += 1
        elif wrapper == "env" and (word.startswith("-S") or word.startswith("--split-string")
                                   or (not word.startswith("--") and word.startswith("-")
                                       and "S" in word)):
            # env -S runs its value as a command line, followed by the remaining words.
            if word in ("-S", "--split-string"):
                rest = words[index + 1:]
            elif word.startswith("--"):
                rest = [word.split("=", 1)[1]] + words[index + 1:]
            else:
                value = word[word.index("S") + 1:]
                rest = ([value] if value else []) + words[index + 1:]
            return check_command(" ".join(rest), depth + 1)
        elif wrapper == "env" and word in ("-u", "--unset") and index + 1 < len(words):
            env.pop(words[index + 1], None)
            index += 2
        elif wrapper == "env" and word.startswith("--unset="):
            env.pop(word.split("=", 1)[1], None)
            index += 1
        elif wrapper is not None and word.startswith("-") and len(word) > 1:
            values = WRAPPER_VALUE_OPTIONS.get(wrapper, ())
            takes_value = word in values or (
                not word.startswith("--") and len(word) > 2 and "-" + word[-1] in values)
            index += 2 if takes_value else 1
        else:
            break
    words = words[index:]
    if not words:
        return None
    ctx = Context(env, via_xargs, depth)
    program, args = words[0], words[1:]
    base = _base(program).lower()
    if program in ("[", "[[", "test"):
        return None
    if _is_dynamic(base):
        return DYNAMIC_MESSAGE
    if base in SHELLS:
        return check_shell(args, command, ctx)
    if base == "eval":
        return check_command(" ".join(args), depth + 1)
    if base in (".", "source"):
        if args and STDIN_PATHS.match(args[0]):
            if command.stdin and not command.stdin_file:
                for text in command.stdin:
                    message = check_command(text, depth + 1)
                    if message:
                        return message
                return None
            return STDIN_SHELL_MESSAGE
        return check_script(args[0], args[1:], ctx) if args else None
    if base == "trap":
        if args[:1] == ["--"]:
            args = args[1:]
        if args and not args[0].startswith("-"):
            return check_command(args[0], depth + 1)
        return None
    if base == "alias":
        # shopt -s expand_aliases makes a later line run the alias.
        for arg in args:
            if "=" in arg:
                message = check_command(arg.split("=", 1)[1], depth + 1)
                if message:
                    return message
        return None
    if base == "git":
        return check_git(args, ctx)
    if base == "find":
        for position, arg in enumerate(args):
            if arg in ("-exec", "-execdir", "-ok", "-okdir"):
                stop = position + 1
                while stop < len(args) and args[stop] not in (";", "+"):
                    stop += 1
                inner = SimpleCommand()
                inner.words = args[position + 1:stop]
                message = check_simple(inner, depth + 1)
                if message:
                    return message
        return None
    codes = []
    if _is_python(base):
        scripts, codes = python_targets(args)
        if any(STDIN_PATHS.match(script) for script, _ in scripts):
            scripts, codes = [], list(command.stdin)
        for script, rest in scripts:
            message = check_script(script, rest, ctx)
            if message:
                return message
        if not scripts and not codes:
            codes = list(command.stdin)     # python reading a here-document
    elif base in INLINE_FLAGS or base in AWKS:
        codes = _inline_codes(base, args) + list(command.stdin)
    for code in codes:
        message = check_inline_code(code)
        if message:
            return message
    if _is_python(base) or base in INLINE_FLAGS or base in AWKS:
        return None
    return check_script(program, args, ctx)


def check_command(command, depth=0):
    """Return a block message for a Bash command string, or None to allow it."""
    if depth > MAX_DEPTH:
        return _message("unparsable", "the command nests shells or substitutions too deeply to check")
    command = command.replace("\\\n", "")
    try:
        commands, texts = split_commands(command)
    except Unparsable as error:
        return _message("unparsable", "the command could not be parsed ({}), so it is not "
                                      "allowed".format(error))
    for text in texts:
        for inner in _substitutions(text):
            message = check_command(inner, depth + 1)
            if message:
                return message
    for simple in commands:
        message = check_simple(simple, depth)
        if message:
            return message
    return None


def pre_bash(payload):
    """Return (exit code, stderr text) for a PreToolUse payload."""
    if not isinstance(payload, dict):
        return 0, ""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0, ""
    command = tool_input.get("command")
    if not isinstance(command, str):
        return 0, ""
    message = check_command(command)
    return (2, message) if message else (0, "")


# ---------------------------------------------------------------- post-edit

CHECK_TIMEOUT = 240
OUTPUT_TAIL = 1500
BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".pdf", ".tar", ".gz", ".tgz", ".zip", ".ico")


def find_root(start):
    directory = os.path.dirname(os.path.abspath(start))
    while True:
        if os.path.isfile(os.path.join(directory, "AGENTS.md")):
            return directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return None
        directory = parent


def relative_path(file_path, root):
    """file_path relative to root (POSIX form), or None when it is outside root."""
    if not isinstance(file_path, str) or not file_path:
        return None
    absolute = file_path if os.path.isabs(file_path) else os.path.join(root, file_path)
    real_root = os.path.realpath(root)
    real = os.path.realpath(absolute)
    if real != real_root and not real.startswith(real_root.rstrip(os.sep) + os.sep):
        return None
    relative = os.path.relpath(real, real_root)
    return PurePosixPath(*relative.split(os.sep)).as_posix()


def _test_modules(relative, root):
    tests = os.path.join(root, "tests")
    names = []
    path = PurePosixPath(relative)
    if relative == "lib/gh_command_drain.py":
        names = ["test_gh_command_drain"]
    elif relative == "lib/ecctools.py" and os.path.isdir(tests):
        for name in sorted(os.listdir(tests)):
            if name.startswith("test_") and name.endswith(".py"):
                try:
                    with open(os.path.join(tests, name), encoding="utf-8") as handle:
                        text = handle.read()
                    # A test that loads or runs the helper names its file; "ecctools-help"
                    # in the check runner tests is only a check name.
                    if "ecctools.py" in text or '"ecctools"' in text:
                        names.append(name[:-3])
                except (OSError, UnicodeDecodeError):
                    continue
    elif path.parts[0] == "tests" and len(path.parts) == 2 and path.name.startswith("test_"):
        names = [path.stem]
    elif path.parts[:2] == (".claude", "hooks") or relative == ".claude/settings.json":
        names = ["test_claude_hooks"]
    return [name for name in names if os.path.isfile(os.path.join(tests, name + ".py"))]


def _is_text(path):
    if path.lower().endswith(BINARY_SUFFIXES):
        return False
    try:
        with open(path, "rb") as handle:
            return b"\0" not in handle.read(8192)
    except OSError:
        return False


def plan_checks(relative, root):
    """Return [(label, argv, cwd)] for the edited file."""
    python = sys.executable or "python3"
    path = PurePosixPath(relative)
    parts, name = path.parts, path.name
    checks = []
    if relative in ("bootstrap.sh", "stack.conf", "bin/openclaw-gh-app-token"):
        checks.append(("bash -n", ["bash", "-n", relative], root))
    elif relative == ".githooks/pre-commit" or (parts[0] == "bin" and len(parts) == 2) or \
            (parts[0] == "scripts" and name.endswith(".sh")):
        checks.append(("sh -n", ["sh", "-n", relative], root))
    elif name.endswith(".py") and (parts[0] in ("lib", "tests") or parts[:2] == (".claude", "hooks")):
        checks.append(("py_compile", [python, "-m", "py_compile", relative], root))
    elif name.endswith(".plist"):
        if shutil.which("plutil"):
            checks.append(("plutil -lint", ["plutil", "-lint", relative], root))
    elif relative.startswith("openclaw-plugins/github-event-router/") and "node_modules" not in parts:
        checks.append(("npm test", ["npm", "test"],
                       os.path.join(root, "openclaw-plugins", "github-event-router")))
    elif name.endswith(".json"):
        checks.append(("json.tool", [python, "-m", "json.tool", relative], root))
    modules = _test_modules(relative, root)
    if modules:
        checks.append(("unittest " + " ".join(modules), [python, "-m", "unittest"] + modules, root))
    if _is_text(os.path.join(root, relative)) and \
            os.path.isfile(os.path.join(root, "lib", "ecctools.py")):
        checks.append(("secret scan", [python, os.path.join("lib", "ecctools.py"), "scan", relative],
                       root))
    return checks


def run_check(argv, cwd, env):
    """Run one check; return (exit code, combined output)."""
    try:
        process = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   start_new_session=True)
    except OSError as error:
        return 127, str(error)
    try:
        output, _ = process.communicate(timeout=CHECK_TIMEOUT)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        output, _ = process.communicate()
        return 124, output.decode("utf-8", "replace") + \
            "\n(timed out after {} seconds)".format(CHECK_TIMEOUT)
    return process.returncode, output.decode("utf-8", "replace")


def post_edit(payload, root):
    """Return the report lines and whether any check failed."""
    if not isinstance(payload, dict) or not root:
        return [], False
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return [], False
    relative = relative_path(tool_input.get("file_path"), root)
    if relative is None or not os.path.isfile(os.path.join(root, relative)):
        return [], False
    checks = plan_checks(relative, root)
    if not checks:
        return [], False
    scratch = tempfile.mkdtemp(prefix="ecc-hook-", dir="/tmp")
    lines, failed = [], False
    try:
        env = dict(os.environ)
        env.update({
            "TMPDIR": scratch,
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": os.path.join(scratch, "pycache"),
            "PYTHONPATH": os.path.join(root, "tests"),
            "npm_config_cache": os.path.join(scratch, "npm-cache"),
        })
        for label, argv, cwd in checks:
            code, output = run_check(argv, cwd, env)
            if code == 0:
                lines.append("PASS {} ({})".format(label, relative))
            else:
                failed = True
                tail = output.strip()[-OUTPUT_TAIL:]
                lines.append("FAIL: {} for {} (exit {})\n{}".format(label, relative, code, tail))
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    return lines, failed


# ---------------------------------------------------------------- main

def main(argv=None):
    parser = argparse.ArgumentParser(description="Project Claude Code hooks for ecc-customization")
    parser.add_argument("event", choices=["pre-bash", "post-edit"])
    parser.add_argument("--root", help="repository root (default: the folder above holding AGENTS.md)")
    args = parser.parse_args(argv)
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        payload = None
    if args.event == "pre-bash":
        try:
            code, message = pre_bash(payload)
        except Exception as error:   # fail closed: a crash must not let the command through
            code, message = 2, _message("hook-error", "the guard failed ({}: {}), so the command "
                                                      "was not checked".format(type(error).__name__,
                                                                               error))
        if message:
            print(message, file=sys.stderr)
        return code
    root = os.path.abspath(args.root) if args.root else find_root(__file__)
    try:
        lines, failed = post_edit(payload, root)
    except Exception as error:      # report, never block
        lines, failed = ["FAIL: the post-edit hook itself failed: {}: {}".format(
            type(error).__name__, error)], True
    if lines:
        print("\n".join(lines), file=sys.stderr)
    if failed:
        text = "check_edit.py found problems in the file you just edited:\n" + "\n".join(lines)
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                 "additionalContext": text}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
