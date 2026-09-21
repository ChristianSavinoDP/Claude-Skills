#!/usr/bin/env python3
"""PreToolUse hook: deny inline-interpreter one-liners, point to the right tool.

Reads the tool-call JSON on stdin. If a Bash command runs code inline via
`python3 -c`, `node -e`, `ruby -e`, `perl -e` (and common variants), it returns
a "deny" decision telling Claude to use the dedicated tool instead: `yq` for
YAML, `jq` for JSON, `actionlint` for GitHub workflows, a CLI's own flags
otherwise. Inline interpreters are arbitrary code and the wrong tool for
parsing/validation.

Running a script file (`python3 foo.py`, `node app.js`) is NOT blocked: only
the inline-code flags (-c / -e) are. Fail-open: on any doubt, prints nothing
and exits 0, deferring to the normal flow. It never approves.
"""
import json
import re
import sys

# interpreter -> the flag that means "run this inline code string".
INLINE = {
    "python": "-c", "python3": "-c", "py": "-c",
    "node": "-e", "nodejs": "-e", "deno": "-e", "bun": "-e",
    "ruby": "-e", "perl": "-e",
}

# Interpreter options that take a SEPARATE value token (so the next token is the
# option's argument, not a script and not the inline flag): `python -W ignore`,
# `python -X importtime`. Skip the value so a script's own later `-c` is not read
# as the interpreter's inline flag.
SEP_VALUE_OPTS = {
    "python": {"-W", "-X"}, "python3": {"-W", "-X"}, "py": {"-W", "-X"},
}

# Options that switch the interpreter to "run a module" (`python -m pytest`).
# Everything after is the module and its args, so there is no inline code to find.
MODULE_FLAGS = {
    "python": {"-m"}, "python3": {"-m"}, "py": {"-m"},
}

# Shell operators that end one command's arguments. Scanning stops here so a
# following command's flags are never attributed to this interpreter.
SHELL_OPS = {"|", "&&", "||", ";", "&", ">", ">>", "<", "2>", "2>>", "|&"}


# Interpreters whose short options may safely be read as a cluster: the python
# family only. Its value-taking single-dash options (-W/-X) are separate-value
# (consumed in _runs_inline), and it has no attached-value single-dash option
# ending in `c`, so a token like `-Ic` is unambiguously the cluster `-I -c`.
# perl/ruby are EXCLUDED: their `-M<module>`/`-I<dir>` attach a value, so
# `perl -Mautodie` / `ruby -Icode` (value ends in the `-e` flag letter) would
# otherwise be misread as an inline cluster and wrongly denied.
_CLUSTER_SAFE = {"python", "python3", "py"}


def _is_inline_flag(tok, flag, base):
    """Does this one token invoke the interpreter's inline-code flag?

    Matches the exact flag (`-c`), for the python family a short-option cluster
    ending in the flag letter (`-Ic`, `-uc`), or the attached form (`-c'code'`)
    where the char right after the flag is non-alphanumeric. So `-config`/`-env`/
    `-certificate` do NOT match (their char after the flag letter is alphanumeric),
    a perl/ruby attached-value option (`-Mautodie`/`-Icode`) is NOT misread as a
    cluster, while `python3 -Ic` and `node -e'...'` still do."""
    if tok == flag:
        return True
    flag_char = flag[1]
    if base in _CLUSTER_SAFE and re.fullmatch(r"-[A-Za-z]{2,}", tok) and tok[-1] == flag_char:
        return True
    if tok.startswith(flag) and len(tok) > len(flag) and not tok[len(flag)].isalnum():
        return True
    return False


def _runs_inline(args, base, flag):
    """True if the interpreter's inline-code flag appears before its script/module
    boundary. Stops (no inline) at the first bare token (the script path), at a
    module flag (`-m` for the python family), at `--` (end of options), or at a
    shell operator. Value-taking options consume their following token so a
    script's own `-c` after them is not misread."""
    sep_opts = SEP_VALUE_OPTS.get(base, set())
    mod_flags = MODULE_FLAGS.get(base, set())
    i = 0
    while i < len(args):
        t = args[i]
        if t in SHELL_OPS or t == "--" or t in mod_flags:
            return False
        if t in sep_opts:
            i += 2  # skip this option's separate value token
            continue
        if _is_inline_flag(t, flag, base):
            return True
        if t.startswith("-"):
            i += 1  # some other interpreter option; keep scanning
            continue
        return False  # a bare token: the script file; no inline flag can follow
    return False


def offending_interpreter(command: str):
    # Find `<interp>` as a command word, then decide (per _runs_inline) whether it
    # runs inline code. Token scan is quote-agnostic enough for a deny-vs-defer
    # decision. The outer loop re-checks every token, so a second interpreter after
    # a pipe (`python foo.py | python3 -c ...`) is still caught on its own turn.
    toks = command.replace("|", " | ").split()
    for idx, tok in enumerate(toks):
        base = tok.split("/")[-1]
        flag = INLINE.get(base)
        if not flag:
            continue
        if _runs_inline(toks[idx + 1:], base, flag):
            return base
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command", "")
    if not isinstance(command, str) or not command:
        return
    interp = offending_interpreter(command)
    if not interp:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Do not run inline code with %s -c/-e for parsing or validation. "
                "Use the dedicated tool: yq for YAML, jq for JSON, actionlint for "
                "GitHub workflows, or a CLI's own flags. Run a script file if you "
                "genuinely need %s." % (interp, interp)
            ),
        }
    }))


if __name__ == "__main__":
    main()
