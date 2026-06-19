#!/usr/bin/env python3
"""PreToolUse hook: auto-approve read-only Bash pipelines.

Reads the tool-call JSON on stdin. If the Bash command is composed entirely of
known read-only commands (grep, find, sed, awk, cat, ls, git log/diff, gh read
subcommands, ...) with no dangerous flags and no file redirection, it returns a
PreToolUse "allow" decision so compound read-only pipelines do not prompt. It
parses pipelines, loops, conditionals, safe redirections (2>/dev/null, 2>&1),
and command substitution whose contents are themselves read-only.

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
    "[", "[[", "read", "seq", "column", "actionlint",
    "stat", "file", "diff", "comm", "base64", "xxd",
}
# Deliberately excluded from READ_ONLY: `command`, `type`, `xargs`, `env`, `sh`,
# `bash`, etc. run their argument as another command, which would bypass this
# allowlist (e.g. `command rm x`). They must defer.

# Shell control keywords. Loops/conditionals whose body is read-only are safe.
NOOP_KW = {"do", "done", "then", "fi", "else", "{", "}", "(", ")", "!", ":"}
HEADER_KW = {"for", "select"}    # `for VAR in WORDS`: WORDS are operands, not run
COND_KW = {"while", "until", "if", "elif"}  # followed by a condition command
DEFER_KW = {"case", "esac", "function"}      # too messy to parse: defer

# git subcommands that only read. Excludes `config`/`remote` (mutate config),
# `fetch` (network + writes .git). `checkout`/`switch` are here but the
# discard forms (`checkout -- <file>`, `checkout .`) are rejected below.
GIT_READONLY_SUB = {"log", "diff", "status", "show", "branch", "blame",
                    "rev-parse", "ls-files", "describe", "checkout", "switch"}

# go subcommands that only read (go env writes only with -w/-u, handled below).
GO_READONLY_SUB = {"env", "version", "list", "vet", "doc"}

# gh: only read subcommands. Writes (pr create/merge/comment, run rerun, etc.)
# are deliberately excluded so they fall through to the ask rules.
GH_READONLY = {
    ("pr", "view"), ("pr", "diff"), ("pr", "list"), ("pr", "checks"),
    ("issue", "view"), ("issue", "list"),
    ("run", "view"), ("run", "list"),
    ("workflow", "view"), ("workflow", "list"),
    ("repo", "view"), ("release", "view"), ("release", "list"),
    ("search",),  # gh search code/prs/...
}

# Flags that mean a segment can change state. Matched as whole tokens AND as
# prefixes for the in-place forms, so `sed -i`, `sed -i.bak`, and
# `sed --in-place=.x` all count. `find` write actions are exact tokens.
DANGEROUS_FLAG_TOKENS = {"-exec", "-execdir", "-delete", "-fprint", "-fprintf",
                        "-fprint0"}


def _is_dangerous_flag(tok: str) -> bool:
    if tok in DANGEROUS_FLAG_TOKENS:
        return True
    # In-place edit: exactly -i, or -i<suffix> like -i.bak, or --in-place[=...].
    if tok == "-i" or tok == "--in-place":
        return True
    if tok.startswith("-i") and len(tok) > 2 and tok[2] in ".=":
        return True
    if tok.startswith("--in-place="):
        return True
    return False

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
        # `git checkout`/`switch` changing a branch is safe, but `checkout --`,
        # `checkout .`, or `checkout <x> -- <files>` discards changes: defer it.
        if sub in ("checkout", "switch") and ("--" in tokens[2:] or "." in tokens[2:]):
            return False
    elif base == "go":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in GO_READONLY_SUB:
            return False
        # `go env -w` / `-u` mutate the env; defer those.
        if sub == "env" and any(a in ("-w", "-u") for a in tokens[2:]):
            return False
    elif base == "gh":
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        sub1 = rest[0] if rest else ""
        sub2 = rest[1] if len(rest) > 1 else ""
        if sub1 == "api":
            # gh api is read-only only as a GET: no method override, no field data.
            bad = {"-X", "--method", "-f", "-F", "--field", "--raw-field", "--input"}
            for t in tokens[2:]:
                # Catch -X POST, --method=POST, and the glued -XPOST form.
                if t in bad or t.split("=")[0] in bad or t.startswith("-X"):
                    return False
        elif (sub1, sub2) not in GH_READONLY and (sub1,) not in GH_READONLY:
            return False
    elif base not in READ_ONLY:
        return False
    for t in tokens[1:]:
        if _is_dangerous_flag(t):
            return False
    return True


def _resolve_substitutions(command: str):
    """Replace $(...) and `...` with a placeholder, but only if the substituted
    command is itself read-only. Returns (new_command, ok). ok is False if any
    substitution contains something not provably safe, or process substitution
    <(...) >(...) is present. Handles nested $(...) innermost-first."""
    # Process substitution is too rare/risky to bother with: defer.
    if "<(" in command or ">(" in command:
        return command, False
    # Resolve $(...) innermost-first.
    pat = re.compile(r"\$\(([^()]*)\)")
    for _ in range(20):  # bounded against pathological nesting
        m = pat.search(command)
        if not m:
            break
        inner = m.group(1)
        if not command_is_safe(inner):
            return command, False
        command = command[:m.start()] + "SUBST" + command[m.end():]
    if "$(" in command:  # leftover unbalanced/odd substitution: defer
        return command, False
    # Backtick substitution.
    if "`" in command:
        parts = command.split("`")
        if len(parts) % 2 == 0:  # unbalanced backticks
            return command, False
        for i in range(1, len(parts), 2):
            if not command_is_safe(parts[i]):
                return command, False
            parts[i] = "SUBST"
        command = "".join(p for i, p in enumerate(parts))
    return command, True


def command_is_safe(command: str) -> bool:
    # Resolve command substitutions: safe only if their contents are read-only.
    command, ok = _resolve_substitutions(command)
    if not ok:
        return False
    # Strip safe redirections before parsing: fd duplications (2>&1, >&2) and
    # redirects to /dev/null. These do not write real files. Any other < or >
    # that survives is a real file redirect and will cause a reject below.
    command = re.sub(r"[0-9&]*>>?\s*&\s*[0-9]", " ", command)     # 2>&1, >&2
    command = re.sub(r"[0-9&]*>>?\s*/dev/null", " ", command)     # 2>/dev/null, 2> /dev/null
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
