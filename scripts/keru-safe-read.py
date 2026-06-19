#!/usr/bin/env python3
"""PreToolUse hook: auto-approve read-only Bash pipelines.

Reads the tool-call JSON on stdin. If the Bash command is composed entirely of
known read-only commands (grep, find, sed, awk, cat, ls, git log/diff, ...) with
no dangerous flags, no redirection, and no command substitution, it returns a
PreToolUse "allow" decision so compound read-only pipelines do not prompt.

Fail-open: on any doubt it prints nothing and exits 0, deferring to the normal
permission flow (allow/ask/defaultMode). It never blocks anything.
"""
import json
import re
import shlex
import sys

# Commands that only read. A pipeline made solely of these (with safe flags) is
# safe to auto-approve.
READ_ONLY = {
    "grep", "egrep", "fgrep", "rg", "find", "sed", "awk", "cat", "ls", "cd",
    "pwd", "echo", "printf", "head", "tail", "which", "wc", "sort", "uniq",
    "cut", "tr", "jq", "yq", "basename", "dirname", "realpath", "true", "test",
    "[", "[[", "read", "seq", "column",
}

# Shell control keywords. Loops/conditionals whose body is read-only are safe.
NOOP_KW = {"do", "done", "then", "fi", "else", "{", "}", "(", ")", "!", ":"}
HEADER_KW = {"for", "select"}    # `for VAR in WORDS` — WORDS are operands, not run
COND_KW = {"while", "until", "if", "elif"}  # followed by a condition command
DEFER_KW = {"case", "esac", "function"}      # too messy to parse: defer

# git subcommands that only read.
GIT_READONLY_SUB = {"log", "diff", "status", "show", "branch", "blame",
                    "rev-parse", "ls-files", "describe", "remote", "config"}

# go subcommands that only read (go env writes only with -w/-u, handled below).
GO_READONLY_SUB = {"env", "version", "list", "vet", "doc"}

# Dangerous flags (as whole tokens) that mean a segment can change state.
DANGEROUS_FLAGS = {
    "-i", "--in-place", "-exec", "-execdir", "-delete", "-fprint", "-fprintf",
    "-fprint0",
}

# Shell operators that separate or redirect. Redirection means a write target.
SEPARATORS = {"|", "||", "&&", ";", "&", "|&", "\n"}
REDIRECTS = {">", ">>", "<", "<<", "<<<", "&>", ">|"}


def tokens_are_safe(tokens) -> bool:
    """tokens is one segment's argv (no operators). True if it only reads."""
    # Strip env-var prefixes like FOO=bar.
    while tokens and "=" in tokens[0] and not tokens[0].startswith("-"):
        tokens = tokens[1:]
    if not tokens:
        return True
    # A `for VAR in W1 W2 ...` header: the words are operands, not executed.
    # Approve the header outright; the loop body is its own segment(s).
    if tokens[0] in HEADER_KW:
        return True
    base = tokens[0].split("/")[-1]
    if base == "git":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in GIT_READONLY_SUB:
            return False
    elif base == "go":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in GO_READONLY_SUB:
            return False
        # `go env -w` / `-u` mutate the env; defer those.
        if sub == "env" and any(a in ("-w", "-u") for a in tokens[2:]):
            return False
    elif base not in READ_ONLY:
        return False
    for t in tokens[1:]:
        if t in DANGEROUS_FLAGS:
            return False
    return True


def command_is_safe(command: str) -> bool:
    # Reject command/process substitution outright (cheap string check; these
    # never appear as bare tokens shlex would split).
    if "$(" in command or "`" in command or "<(" in command or ">(" in command:
        return False
    # Strip safe redirections before parsing: fd duplications (2>&1, >&2) and
    # redirects to /dev/null. These do not write real files. Any other < or >
    # that survives is a real file redirect and will cause a reject below.
    command = re.sub(r"[0-9&]*>>?\s*&[0-9]", " ", command)        # 2>&1, >&2
    command = re.sub(r"[0-9&]*>>?\s*/dev/null", " ", command)     # 2>/dev/null
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        toks = list(lexer)
    except ValueError:
        return False  # unbalanced quotes etc: defer

    segment = []

    def flush():
        if not tokens_are_safe(segment):
            return False
        segment.clear()
        return True

    for t in toks:
        if t in DEFER_KW:
            return False  # case/function: do not try to parse
        if t in REDIRECTS or any(c in t for c in "<>"):
            return False  # redirection to/from a file
        if t in SEPARATORS:
            if not flush():
                return False
        elif t in NOOP_KW or t in COND_KW:
            # Keyword boundary: the accumulated segment ends here. The keyword
            # itself executes nothing (while/if are followed by a command that
            # forms its own segment).
            if not flush():
                return False
        else:
            segment.append(t)
    return tokens_are_safe(segment)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input: defer
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command", "")
    if not command or not isinstance(command, str):
        return
    if not command_is_safe(command):
        return  # not provably safe: defer to normal permissions
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": "read-only command pipeline",
        }
    }))


if __name__ == "__main__":
    main()
