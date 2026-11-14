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
                  "until", "case", "esac", "for", "select", "in", "always", "end")
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
    pending, expect_delimiter, delimiter_after, strip_dash = [], False, -1, False
    parens, previous = [], None     # open ( kinds, and the last token for adjacency checks
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
                    if piece == "(":
                        # (( and $(( open arithmetic, where << is a shift, not a here-document.
                        if previous and previous[0] == "op" and previous[1] == "(" and \
                                previous[3] == piece_start and parens:
                            parens[-1] = "arith"
                            parens.append("arith")
                        else:
                            parens.append("paren")
                    elif piece == ")" and parens:
                        parens.pop()
                    token_out = ("op", piece, piece_start, offset)
                    yield token_out
                    if piece == "<<" and "arith" not in parens and not (
                            previous and previous[0] == "word" and previous[4] == piece_start
                            and "$[" in previous[2] and "]" not in previous[2].rsplit("$[", 1)[1]):
                        expect_delimiter, delimiter_after = True, offset
                    previous = token_out
                    if piece == "\n" and pending:
                        new_pos, bodies = _read_heredocs(text, offset, pending)
                        pending = []
                        if new_pos is not None:
                            for heredoc_body, quoted in bodies:
                                yield ("heredoc", heredoc_body, quoted)
                            restart = new_pos
                            break
                continue
            if expect_delimiter and body == "-" and body_start == delimiter_after:
                # <<- EOF: the dash belongs to the operator and the delimiter is the next word.
                strip_dash = True
                previous = ("word", token, body, body_start, body_start + len(body))
                continue
            if expect_delimiter:
                expect_delimiter = False
                strip_tabs = strip_dash or (body_start == delimiter_after and token.startswith("-"))
                delimiter = token[1:] if strip_tabs and not strip_dash else token
                strip_dash = False
                quoted = any(ch in body for ch in "'\"\\")
                pending.append((delimiter, quoted, strip_tabs))
            previous = ("word", token, body, body_start, body_start + len(body))
            yield previous
        pos = restart


def _continuations(text):
    """Offsets of the backslash-newline pairs bash removes: those in words, outside single
    quotes. Comments and quoted here-documents keep theirs."""
    offsets = []
    for token in _tokens(text):
        if token[0] != "word":
            continue
        body, start = token[2], token[3]
        index, state = 0, None
        while index < len(body):
            char = body[index]
            if state == "'":
                state = None if char == "'" else state
            elif state == "$'":
                if char == "\\":
                    index += 1
                elif char == "'":
                    state = None
            elif char == "\\":
                if body.startswith("\n", index + 1):
                    offsets.append(start + index)
                index += 1
            elif state == '"':
                state = None if char == '"' else state
            elif char == "'":
                state = "'"
            elif char == '"':
                state = '"'
            elif body.startswith("$'", index):
                state = "$'"
                index += 1
            index += 1
    return offsets


def join_continuations(text):
    """Remove line continuations the way bash does before it splits the command."""
    for _ in range(4):
        offsets = _continuations(text)
        if not offsets:
            break
        for offset in reversed(offsets):
            text = text[:offset] + text[offset + 2:]
    return text


class SimpleCommand:
    def __init__(self):
        self.words = []
        self.stdin = []          # here-document and here-string text fed to the command
        self.stdin_file = False  # input redirected from a file


PROCESS_SUBSTITUTION = "/dev/fd/63"


def split_commands(text):
    """Split a shell command into simple commands.

    The inside of an unquoted $(...), `...`, <(...), >(...) or zsh =(...) becomes
    commands of its own, and the command around it keeps going after it closes.
    """
    commands, owners = [], []
    current = SimpleCommand()
    ends, sources = [], []
    target, last = None, None
    stack = []      # (kind, outer command, its ends, its sources, its case depth)
    case_depth = 0  # open case ... esac at this level: a ) there ends a pattern

    def finish():
        if current.words or current.stdin:
            commands.append(current)

    def mark_dynamic(start):
        # The substitution's output is part of the outer command: mark the word it joins,
        # or add a word of its own, as an expansion the guard cannot read.
        if current.words and ends[-1] == start:
            current.words[-1] += "$"
        else:
            current.words.append("$")
            ends.append(start)
            sources.append("$")

    tokens = list(_tokens(text))
    arithmetic = 0  # open ( inside $((...)): scan_substitutions checks that text instead
    for index, token in enumerate(tokens):
        kind = token[0]
        if arithmetic:
            if kind == "op" and token[1] in ("(", ")"):
                arithmetic += 1 if token[1] == "(" else -1
            continue
        if kind == "heredoc":
            _, body, _ = token
            if owners:
                owners.pop(0).stdin.append(body)
            continue
        if kind == "word":
            _, value, source, start, end = token
            last = token
            if target is not None:
                if target == "<<<":
                    current.stdin.append(value)
                target = None
                continue
            if "$'" in source or '$"' in source:
                # ANSI-C or locale quoting: shlex does not decode $'\x2e'. A trailing $ marks
                # the word, its last path part included, as an expansion the guard cannot read.
                value = value + "$"
            leading = all(word in RESERVED_WORDS for word in current.words)
            if leading and source == "case":
                case_depth += 1
            elif leading and source == "esac" and case_depth:
                case_depth -= 1
            current.words.append(value)
            ends.append(end)
            sources.append(source)
            continue
        _, piece, start, end = token
        previous, last = last, token
        adjacent = previous is not None and previous[-1] == start
        if piece == "(" and adjacent and previous[0] == "word" and previous[2].endswith("$") \
                and index + 1 < len(tokens) and tokens[index + 1][:2] == ("op", "(") \
                and tokens[index + 1][2] == end:
            # $((...)) is arithmetic: the word already ends in $, so it reads as an
            # expansion, and check_command checks the inside as code on its own.
            arithmetic = 1
            continue
        if piece == "(" and adjacent and (
                (previous[0] == "op" and previous[1] in ("<", ">")) or
                (previous[0] == "word" and (previous[2].endswith("$") or previous[2] == "="))):
            if previous[0] == "op" or previous[2] == "=":
                # <(...), >(...) and zsh =(...) are a file name argument, not a redirection.
                target = None
                current.stdin_file = current.stdin_file and previous[1] != "<"
                if previous[0] == "word" and current.words and ends[-1] == start:
                    current.words.pop()     # the = of zsh =(...)
                    ends.pop()
                    sources.pop()
                current.words.append(PROCESS_SUBSTITUTION)
                ends.append(end)
                sources.append(PROCESS_SUBSTITUTION)
            stack.append(("sub", current, ends, sources, case_depth))
            current, ends, sources, case_depth = SimpleCommand(), [], [], 0
            continue
        if piece == "`":
            if stack and stack[-1][0] == "backtick":
                finish()
                _, current, ends, sources, case_depth = stack.pop()
            else:
                mark_dynamic(start)
                stack.append(("backtick", current, ends, sources, case_depth))
                current, ends, sources, case_depth = SimpleCommand(), [], [], 0
            continue
        if piece == ")" and case_depth and not (stack and stack[-1][0] == "group"):
            target = None       # the end of a case pattern: the commands follow
            finish()
            current, ends, sources = SimpleCommand(), [], []
            continue
        if piece == ")" and stack and stack[-1][0] == "sub":
            finish()
            _, current, ends, sources, case_depth = stack.pop()
            target = None
            continue
        if piece == "(":
            stack.append(("group", None, None, None, None))
        elif piece == ")" and stack and stack[-1][0] == "group":
            stack.pop()
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
        finish()
        current = SimpleCommand()
        ends, sources = [], []
    finish()
    while stack:
        outer = stack.pop()[1]
        if outer is not None and outer is not current:
            current = outer
            finish()
    return commands


def _skip_quoted(text, index):
    """index is just after an opening double quote; return the index after its close."""
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == '"':
            return index + 1
        elif text.startswith("$(", index):
            index = _substitution_end(text, index + 2) + 1
        elif char == "`":
            index = _backtick_end(text, index + 1) + 1
        else:
            index += 1
    return len(text)


def _backtick_end(text, index):
    """index is just after an opening backtick; return the index of the closing one."""
    while index < len(text) and text[index] != "`":
        index += 2 if text[index] == "\\" else 1
    return min(index, len(text))


HEREDOC_START = re.compile(
    r"<<(-?)[ \t]*(\\?)(?:'([^']*)'|\"([^\"]*)\"|([^\s;&|<>()'\"]+))")
CASE_WORD = re.compile(r"(?<![\w$-])(case|esac)(?![\w-])")


def _arithmetic_end(text, index):
    """index is just after "$(". Return the index of the closing ")" of $(( arithmetic )),
    or None when the text is not arithmetic.

    Like bash and zsh, the text is arithmetic only when the ( after $( closes just before
    the final ")", as in $((2*(3+4))). Otherwise, as in $(($X) | head), the ( opens a
    subshell inside a command substitution and the text is shell code.
    """
    if not text.startswith("(", index):
        return None
    depth = 2
    position = index + 1
    while position < len(text):
        depth += {"(": 1, ")": -1}.get(text[position], 0)
        if depth == 1 and text[position] == ")":
            return position + 1 if text.startswith(")", position + 1) else None
        position += 1
    return len(text)


def _substitution_end(text, index):
    """index is just after "$("; return the index of the matching ")" (or len(text)).

    Reads the inside as shell code: quotes, nested substitutions, comments,
    here-documents and case patterns, whose ) does not close the substitution.
    """
    arithmetic = _arithmetic_end(text, index)
    if arithmetic is not None:
        return arithmetic
    depth, cases, pending = 1, [], []
    word_start = True
    while index < len(text):
        char = text[index]
        if char == "\\":
            index, word_start = index + 2, False
            continue
        if char == "\n" and pending:
            index = _skip_heredoc_bodies(text, index + 1, pending)
            pending, word_start = [], True
            continue
        if char == "'":
            close = text.find("'", index + 1)
            index = len(text) if close < 0 else close + 1
        elif char == '"':
            index = _skip_quoted(text, index + 1)
        elif char == "`":
            index = _backtick_end(text, index + 1) + 1
        elif text.startswith("$(", index):
            index = _substitution_end(text, index + 2) + 1
        elif char == "#" and word_start:
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
            continue
        elif text.startswith("<<", index) and not text.startswith("<<<", index):
            match = HEREDOC_START.match(text, index)
            if match:
                delimiter = next(group for group in match.group(3, 4, 5) if group is not None)
                pending.append((delimiter, match.group(1) == "-"))
                index = match.end()
            else:
                index += 2
        elif word_start and CASE_WORD.match(text, index):
            word = CASE_WORD.match(text, index).group(1)
            if word == "case":
                cases.append(depth)
            elif cases:
                cases.pop()
            index += 4
        elif char == "(":
            depth += 1
            index += 1
        elif char == ")":
            if cases and cases[-1] == depth:
                index += 1      # the end of a case pattern
            else:
                depth -= 1
                if depth == 0:
                    return index
                index += 1
        else:
            index += 1
        word_start = char in " \t\n;&|()"
    return len(text)


def _skip_heredoc_bodies(text, index, pending):
    for delimiter, strip_tabs in pending:
        while index < len(text):
            newline = text.find("\n", index)
            line = text[index:] if newline < 0 else text[index:newline]
            index = len(text) if newline < 0 else newline + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                break
    return index


def _scan_double(text, index, found):
    """Scan a double-quoted string from just after its opening quote; collect the
    substitutions in it and return the index after the closing quote."""
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
        elif char == '"':
            return index + 1
        elif text.startswith("$(", index):
            index = _collect_substitution(text, index, found)
        elif char == "`":
            stop = _backtick_end(text, index + 1)
            found.append(text[index + 1:stop])
            index = stop + 1
        else:
            index += 1
    return len(text)


class MaybeArithmetic(str):
    """The inside of $(( ... )) that closes like arithmetic. Real arithmetic such as
    2*(3+4) reads as unchecked code, so only a rule match blocks it. A $((...)) whose
    first ( closes earlier, as in "$((cd x; $CMD) | head)", is a subshell and is checked
    like any other command substitution."""


def _collect_substitution(text, index, found):
    """index is at "$("; collect the inside and return the index after the closing ")"."""
    stop = _substitution_end(text, index + 2)
    if _arithmetic_end(text, index + 2) is not None:
        found.extend(scan_substitutions(text[index + 3:max(index + 3, stop - 1)], quoting=False))
        found.append(MaybeArithmetic(text[index + 2:stop]))
    else:
        found.append(text[index + 2:stop])
    return stop + 1


def scan_substitutions(text, quoting=True):
    """Return the inside of every command substitution in a command, read the way bash
    reads it: single quotes, $'...', double quotes, comments and here-documents.

    The command text is scanned as a whole because shlex ends a double-quoted word at
    the first inner quote, as in "$(echo "a b")". With quoting False (a here-document
    body, arithmetic), quote characters are plain text.
    """
    found, index, pending, word_start = [], 0, [], True
    while index < len(text):
        char = text[index]
        next_word_start = char in " \t\n;&|()"
        if char == "\\":
            index += 2
        elif char == "\n" and pending:
            index = _collect_heredocs(text, index + 1, pending, found)
            pending = []
        elif quoting and char == "'":
            if index > 0 and text[index - 1] == "$":
                close = index + 1
                while close < len(text) and text[close] != "'":
                    close += 2 if text[close] == "\\" else 1
            else:
                close = text.find("'", index + 1)
            index = len(text) if close < 0 else close + 1
        elif quoting and char == '"':
            index = _scan_double(text, index + 1, found)
        elif text.startswith("$(", index):
            index = _collect_substitution(text, index, found)
        elif char == "`":
            stop = _backtick_end(text, index + 1)
            found.append(text[index + 1:stop])
            index = stop + 1
        elif quoting and char == "#" and word_start:
            newline = text.find("\n", index)
            index = len(text) if newline < 0 else newline
        elif quoting and text.startswith("<<", index) and not text.startswith("<<<", index):
            match = HEREDOC_START.match(text, index)
            if match:
                quoted = bool(match.group(2) or match.group(3) is not None or
                              match.group(4) is not None)
                delimiter = next(group for group in match.group(3, 4, 5) if group is not None)
                pending.append((delimiter, match.group(1) == "-", quoted))
                index = match.end()
            else:
                index += 2
        else:
            index += 1
        word_start = next_word_start
    return found


def _collect_heredocs(text, index, pending, found):
    """Skip here-document bodies; collect the substitutions in the unquoted ones."""
    for delimiter, strip_tabs, quoted in pending:
        lines, closed = [], False
        while index < len(text):
            newline = text.find("\n", index)
            line = text[index:] if newline < 0 else text[index:newline]
            index = len(text) if newline < 0 else newline + 1
            if (line.lstrip("\t") if strip_tabs else line) == delimiter:
                closed = True
                break
            lines.append(line)
        if not quoted or not closed:
            # Quotes are plain text in a here-document body; $(...) and `...` still run.
            found.extend(scan_substitutions("\n".join(lines), quoting=False))
    return index


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


# The whole Bash command being checked: a temp path is only trusted when the same command
# does not create links or copy files that could turn it into the real home folder.
CURRENT = {"command": ""}
LINKING_WORDS = re.compile(r"(?<![\w.-])(ln|gln|link|symlink|cp|gcp|mv|rsync|ditto|tar|unzip|"
                           r"bsdtar|cpio|mount|bindfs)(?![\w-])", re.I)
TMPDIR_PREFIX = re.compile(r"^\$(TMPDIR|\{TMPDIR\})(?=/|$)")


def is_temp_path(value):
    """True when value is an absolute path inside /tmp or the system temp folder."""
    if not isinstance(value, str):
        return False
    if LINKING_WORDS.search(CURRENT["command"]):
        return False
    tmpdir = os.environ.get("TMPDIR")
    if TMPDIR_PREFIX.match(value) and tmpdir and "TMPDIR" not in TMPDIR_PREFIX.sub("", value) \
            and not re.search(r"TMPDIR\s*[=+]|-u\s*TMPDIR|unset", CURRENT["command"]):
        value = TMPDIR_PREFIX.sub(lambda _: tmpdir.rstrip("/"), value, count=1)
    if not os.path.isabs(value):
        return False
    if any(ch in value for ch in EXPANSION_CHARS + "~\n"):
        return False    # $X, $(...), globs and braces expand to paths the guard cannot see
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
    "expect": ("-c",), "lua": ("-e",), "vim": ("-c", "--cmd"), "nvim": ("-c", "--cmd"), "vi": ("-c", "--cmd"),
    "ex": ("-c", "--cmd"), "view": ("-c", "--cmd"),
}
EDITORS = ("vim", "nvim", "vi", "ex", "view")
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
    if program in EDITORS:
        codes.extend(arg[1:] for arg in args if arg.startswith("+"))   # vim +cmd
    for index, arg in enumerate(args):
        if arg in flags and index + 1 < len(args):
            codes.append(args[index + 1])
        elif any(arg.startswith(flag + "=") for flag in flags if flag.startswith("--")):
            codes.append(arg.split("=", 1)[1])
    return codes


def _is_python(name):
    if name in ("python", "python3", "pypy", "pypy3"):
        return True
    return name.startswith("python3.") and name[len("python3."):].isdigit()


SCRIPT_RUNNING_MODULES = ("runpy", "cProfile", "profile", "pdb", "trace")


def python_targets(args):
    """Return (scripts, codes) a python command runs: scripts are (path, args) pairs.

    A python that reads its program from stdin returns [("-", [])].
    """
    index = 0
    while index < len(args):
        arg = args[index]
        if arg in ("-V", "--version", "-h", "--help", "-?"):
            return [], []
        if arg == "--":
            return ([(args[index + 1], args[index + 2:])] if index + 1 < len(args)
                    else [("-", [])]), []
        if arg == "-":
            return [("-", [])], []
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
                        return [], [" ".join([value] + rest)]   # sys.argv follows the code
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
    return [("-", [])], []


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
    if ctx.via_xargs:
        return XARGS_MESSAGE.format("a shell")    # stdin words become its script or -c string
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
    r"^(core\.(pager|editor|sshcommand|fsmonitor|askpass|gitproxy)|sequence\.editor|diff\.external|"
    r"gpg(\.[^.]+)?\.program|credential(\..+)?\.helper|pager\..+|filter\..+\.(clean|smudge|process)|"
    r"merge\..+\.driver|diff\..+\.(command|textconv)|uploadpack\.packobjectshook|web\.browser|"
    r"browser\..+\.(cmd|path)|man\..+\.(cmd|path)|remote\..+\.(uploadpack|receivepack|vcs)|"
    r"sendemail\..*(cccmd|tocmd|sendmailcmd|smtpserver)|difftool\..+\.(cmd|path)|"
    r"mergetool\..+\.(cmd|path)|core\.hookspath)$")
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
ENV_COMMAND_VARIABLES = ("GIT_EDITOR", "GIT_SEQUENCE_EDITOR", "GIT_PAGER", "GIT_SSH_COMMAND", "GIT_SSH",
                         "GIT_EXTERNAL_DIFF", "GIT_ASKPASS", "SSH_ASKPASS", "GIT_PROXY_COMMAND",
                         "EDITOR", "VISUAL", "PAGER", "LESSOPEN", "LESSCLOSE")
# Variables naming a file the shell sources before running anything.
ENV_SOURCED_VARIABLES = ("BASH_ENV", "ENV")
HASH_MESSAGE = _message("hash", "hash maps a command name to a script the guard protects")


def check_git_c(value, ctx, from_env=False):
    key, _, setting = value.partition("=")
    key = key.lower()
    if key.startswith("alias."):
        return _message("unchecked-git-alias", "a git alias set with -c cannot be checked; "
                                               "run the git command it stands for")
    if GIT_COMMAND_KEYS.match(key):
        if from_env or key == "core.hookspath":
            return _message("unchecked-git-config", "git -c {} takes a command or hook folder "
                                                    "the guard cannot see".format(key))
        return check_command(setting.lstrip("!"), ctx.depth + 1)
    return None


# Options of git subcommands whose value is a command git runs, and short forms per subcommand.
GIT_COMMAND_OPTIONS = ("--upload-pack", "--receive-pack", "--exec", "--extcmd",
                       "--open-files-in-pager", "--setup")
GIT_SHORT_COMMAND_OPTIONS = {"rebase": "x", "difftool": "x", "clone": "u", "grep": "O"}


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
        elif name == "--config-env" and equals:
            value = inline
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
        elif name == "--config-env":
            message = check_git_c(value, ctx, from_env=True)
            if message:
                return message
    if index >= len(args):
        return None
    sub, rest = args[index], args[index + 1:]
    if sub == "config":
        if ctx.via_xargs:
            return XARGS_MESSAGE.format("git config")
        return check_git_config(rest)
    if any(arg.lower().startswith("ext::") or "=ext::" in arg.lower() for arg in rest) and \
            sub in ("clone", "fetch", "pull", "push", "ls-remote", "remote", "submodule", "archive"):
        return _message("unchecked-git-config", "an ext:: remote runs a command the guard "
                                                "cannot check")
    commands = []
    short = GIT_SHORT_COMMAND_OPTIONS.get(sub)
    for position, arg in enumerate(rest):
        following = rest[position + 1] if position + 1 < len(rest) else ""
        name, equals, value = arg.partition("=")
        if arg.startswith("--") and (name in GIT_COMMAND_OPTIONS or
                                     (sub == "filter-branch" and name.endswith("-filter"))):
            commands.append(value if equals else following)
        elif short and arg.startswith("-") and not arg.startswith("--") and short in arg[1:]:
            # -x CMD, -xCMD and bundles such as -ix CMD
            tail = arg[arg.index(short, 1) + 1:]
            if tail:
                commands.append(tail)
            elif short != "O":      # git grep -O alone uses the default pager
                commands.append(following)
    if sub == "bisect" and rest[:1] == ["run"]:
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


# Options whose value is a command line the program runs.
COMMAND_OPTIONS = {
    "rsync": ("-e", "--rsh", "--rsync-path"),
    "sort": ("--compress-program",),
    "tar": ("-I", "--use-compress-program", "--to-command", "--rsh-command"),
    "bsdtar": ("-I", "--use-compress-program"),
    "zip": ("-TT", "--unzip-command"),
    "scp": ("-S",),
    "sftp": ("-S",),
}
SSH_COMMAND_SETTINGS = ("proxycommand", "localcommand", "knownhostscommand", "remotecommand")
REMOTE_SHELLS = ("ssh", "tmux", "screen", "su", "sem", "launchctl")


def _command_option_values(program, args):
    values = []
    options = COMMAND_OPTIONS.get(program, ())
    for position, arg in enumerate(args):
        following = args[position + 1] if position + 1 < len(args) else ""
        name, equals, value = arg.partition("=")
        if arg in options:
            values.append(following)
        elif arg.startswith("--") and equals and name in options:
            values.append(value)
        elif arg.startswith("-") and not arg.startswith("--"):
            for option in options:
                if len(option) == 2 and option[1] in arg[1:]:
                    tail = arg[arg.index(option[1], 1) + 1:]
                    values.append(tail if tail else following)     # -e./x, -ave ./x
        if program in ("ssh", "scp", "sftp", "rsync") and (arg == "-o" or arg.startswith("-o")):
            setting = following if arg == "-o" else arg[2:]
            key, _, command_text = setting.replace(" ", "=", 1).partition("=")
            if key.strip().lower() in SSH_COMMAND_SETTINGS:
                values.append(command_text)
    return values


# Programs that run a command given in their arguments, after options and operands of their own.
LAUNCHERS = ("xcrun", "flock", "fakeroot", "chroot", "entr", "direnv", "npx", "bunx", "pnpx", "pnpm",
             "npm", "yarn", "uv", "uvx", "poetry", "pipenv", "pdm", "hatch", "rye", "conda", "mamba",
             "pixi", "mise", "asdf", "devbox", "ssh", "tmux", "screen", "launchctl", "su", "sem",
             "open", "firejail", "systemd-run", "strace", "ltrace", "dtruss", "valgrind", "gdb",
             "lldb", "nix-shell", "run-one", "unshare", "proxychains", "proxychains4", "tsp")
WRAPPERS = ("env", "time", "busybox", "noglob", "nocorrect", "-", "sandbox-exec", "sudo", "doas", "nohup", "command", "exec", "nice", "ionice", "caffeinate",
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
    "sandbox-exec": ("-f", "-n", "-p", "-D"),
}


def _check_assignment(word, env, ctx):
    """Record NAME=value in env and check variables whose value is a command or a script."""
    name, _, value = word.partition("=")
    name = name.rstrip("+")
    env[name] = value
    if name in ENV_COMMAND_VARIABLES or name.startswith("GIT_CONFIG_VALUE_") or \
            name.startswith("BASH_FUNC_"):
        return check_command(value.lstrip("|-"), ctx.depth + 1)
    if name in ENV_SOURCED_VARIABLES:
        return check_script(value, [], ctx)
    if name.startswith("GIT_CONFIG_KEY_") and (
            value.lower() == "core.hookspath" or value.lower().startswith("alias.")):
        return check_git_c(value + "=", ctx, from_env=True)
    if name == "GIT_CONFIG_PARAMETERS":
        for pair in re.findall(r"'([^']*)'", value) or [value]:
            message = check_git_c(pair.replace("'='", "="), ctx)
            if message:
                return message
    return None


def check_simple(command, depth):
    """Return a block message for one simple command, or None."""
    words = command.words
    index, wrapper, via_xargs, env, placeholder = 0, None, False, {}, None
    while index < len(words):
        word = words[index]
        base = _base(word).lower()      # macOS file systems ignore case: ENV is env
        if word in RESERVED_WORDS:
            index += 1
        elif word == "function":
            index += 2
        elif word == "repeat" and wrapper is None:
            index += 2      # zsh: repeat COUNT command
        elif _is_assignment(word) or (wrapper == "env" and "=" in word and not word.startswith("-")):
            message = _check_assignment(word, env, Context(env, via_xargs, depth))
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
            if wrapper == "xargs":
                # -I R / -J R / -i: xargs puts each input line where R appears.
                if word in ("-I", "-J") and index + 1 < len(words):
                    placeholder = words[index + 1]
                elif word[:2] in ("-I", "-J") and len(word) > 2:
                    placeholder = word[2:]
                    takes_value = False
                elif word == "-i" or word.startswith("--replace"):
                    placeholder = word.split("=", 1)[1] if "=" in word else "{}"
            index += 2 if takes_value else 1
        else:
            break
    words = words[index:]
    if not words:
        if via_xargs and wrapper != "xargs":
            # xargs env, xargs nohup: the program itself comes from stdin.
            return XARGS_MESSAGE.format("a command")
        return None
    ctx = Context(env, via_xargs, depth)
    program, args = words[0], words[1:]
    base = _base(program).lower()
    if placeholder and placeholder in program:
        return XARGS_MESSAGE.format("a program")
    if program in ("[", "[["):
        # zsh short forms can follow the test: if [[ -n x ]] ./script
        closer = "]" if program == "[" else "]]"
        if closer in args:
            rest = SimpleCommand()
            rest.words = args[args.index(closer) + 1:]
            return check_simple(rest, depth + 1) if rest.words else None
        return None
    if program == "test":
        return None
    if _is_dynamic(base):
        return DYNAMIC_MESSAGE
    if via_xargs and (base in ("eval", ".", "source", "trap", "alias", "hash")
                      or base in INLINE_FLAGS or base in AWKS):
        return XARGS_MESSAGE.format(base)
    if base == "hash":
        for position, arg in enumerate(args):
            target = None
            if arg == "-p" and position + 1 < len(args):
                target = args[position + 1]
            elif "=" in arg and not arg.startswith("-"):
                target = arg.split("=", 1)[1]       # zsh: hash name=path
            if target is not None and (_base(target).lower() in SCRIPT_RULES or
                                       _is_dynamic(_base(target))):
                return HASH_MESSAGE
        return None
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
        if not args:
            return STDIN_SHELL_MESSAGE
        return check_script(args[0], args[1:], ctx)
    if base == "trap":
        if args[:1] == ["--"]:
            args = args[1:]
        if args and not args[0].startswith("-"):
            return check_command(args[0], depth + 1)
        return None
    if base in ("export", "declare", "typeset", "local", "readonly"):
        for arg in args:
            if "=" in arg and not arg.startswith("-"):
                message = _check_assignment(arg, env, ctx)
                if message:
                    return message
        return None
    if base in ("mapfile", "readarray", "compgen", "complete"):
        for position, arg in enumerate(args):
            if arg == "-C" and position + 1 < len(args):
                return check_command(args[position + 1], depth + 1)
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
    if base == "su":
        for position, arg in enumerate(args):
            if arg in ("-c", "--command") and position + 1 < len(args):
                return check_command(args[position + 1], depth + 1)
            if arg.startswith("--command="):
                return check_command(arg.split("=", 1)[1], depth + 1)
    if base in ("rg", "ripgrep"):
        for position, arg in enumerate(args):
            runner = None
            if arg == "--pre" and position + 1 < len(args):
                runner = args[position + 1]
            elif arg.startswith("--pre="):
                runner = arg.split("=", 1)[1]
            if runner:
                message = check_script(runner, ["FILE"], ctx)
                if message:
                    return message
        return None
    for option_text in _command_option_values(base, args):
        message = check_command(option_text, depth + 1)
        if message:
            return message
    if base in ("at", "batch"):
        if command.stdin and not command.stdin_file:
            for text in command.stdin:
                message = check_command(text, depth + 1)
                if message:
                    return message
            return None
        if "-f" in args or not any(arg in ("-l", "-r", "-c", "-q") for arg in args):
            return STDIN_SHELL_MESSAGE
        return None
    if base in REMOTE_SHELLS:
        # The remote side joins the words into one shell command.
        for position in range(len(args)):
            if " " in args[position] or any(ch in args[position] for ch in ";&|"):
                message = check_command(" ".join(args[position:]), depth + 1)
                if message:
                    return message
    if base in LAUNCHERS:
        # Programs that run another command from their arguments: check every place one can start.
        for position in range(len(args)):
            inner = SimpleCommand()
            inner.words = args[position:]
            message = check_simple(inner, depth + 1)
            if message:
                return message
        return None
    if base == "parallel":
        # GNU parallel runs the words before ::: as a command; check every place one can start.
        stop = len(args)
        for marker in (":::", "::::", ":::+", "::::+"):
            if marker in args:
                stop = min(stop, args.index(marker))
        if stop == len(args) and not any(not arg.startswith("-") for arg in args):
            return XARGS_MESSAGE.format("parallel")     # commands come from stdin
        for position in range(stop):
            inner = SimpleCommand()
            inner.words = args[position:stop]
            message = check_simple(inner, depth + 1)
            if message:
                return message
        return None
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
        if via_xargs and (scripts or codes):
            return XARGS_MESSAGE.format(base)       # python -m MODULE with stdin words is fine
        if any(script == "-" or STDIN_PATHS.match(script) for script, _ in scripts):
            if not command.stdin or command.stdin_file:
                return _message("unchecked-python", "a python that reads its program from a "
                                                    "pipe or a file redirect cannot be checked; "
                                                    "pass the code with -c or run a script")
            scripts, codes = [], list(command.stdin)
        for script, rest in scripts:
            message = check_script(script, rest, ctx)
            if message:
                return message
    elif base in INLINE_FLAGS or base in AWKS:
        codes = _inline_codes(base, args)
        if codes:
            codes.append(" ".join(args))    # the code can read its arguments
        codes += list(command.stdin)
    for code in codes:
        message = check_inline_code(code)
        if message:
            return message
    if _is_python(base) or base in INLINE_FLAGS or base in AWKS:
        return None
    return check_script(program, args, ctx)


ANSI_C_ESCAPED_QUOTE = re.compile(r"\$'(?:[^'\\]|\\.)*\\'")


UNCHECKED_RULE = re.compile(r"\((unchecked-[a-z-]+|unparsable)\)")


def check_command(command, depth=0, arithmetic=False):
    """Return a block message for a Bash command string, or None to allow it.

    With arithmetic=True the text is the inside of a $(( ... )) that closes like arithmetic
    (see _arithmetic_end); bash reports an error for it rather than running it when it is
    not valid arithmetic. Real arithmetic such as 2*(3+4) gives "unchecked" or
    "unparsable" verdicts, so those are ignored, but every part is still checked so a
    later rule match is not hidden behind them.
    """
    if ANSI_C_ESCAPED_QUOTE.search(command):
        # shlex reads $'\'' as an open quote, so everything after it would be misread.
        return _message("unparsable", "$'...' quoting with an escaped quote cannot be read "
                                      "reliably, so the command is not allowed")
    if depth > MAX_DEPTH:
        return _message("unparsable", "the command nests shells or substitutions too deeply to check")
    try:
        command = join_continuations(command)
        commands = split_commands(command)
    except Unparsable as error:
        return _message("unparsable", "the command could not be parsed ({}), so it is not "
                                      "allowed".format(error))
    verdicts = [check_command(inner, depth + 1, isinstance(inner, MaybeArithmetic))
                for inner in scan_substitutions(command)]
    verdicts += [check_simple(simple, depth) for simple in commands]
    for message in verdicts:
        if message and not (arithmetic and UNCHECKED_RULE.search(message)):
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
    CURRENT["command"] = command
    try:
        message = check_command(command)
    finally:
        CURRENT["command"] = ""
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
