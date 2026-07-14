#!/usr/bin/env python3
"""PreToolUse hook: the single Bash command gate (fast static path + model fallback).

Two paths, one hook:

  FAST (instant, deterministic): if the command parses as entirely read-only or
  local-reversible (grep, find, git log/diff, gh/jira read subcommands, go
  build/test/fmt, etc., with no dangerous flags or file redirection), it returns
  "allow" immediately. Most commands hit this path and never touch a model.

  SLOW (only for the rest): a command not provably safe used to fall to a
  separate, always-running agent hook, which added latency to everything. Now
  this one hook makes a single model call (`dp ai claude`) to judge impact, and
  fail-safe to "ask" on any failure. So the model is consulted only for genuinely
  unknown commands, not for the read-only majority, and there is ONE Bash hook
  instead of a fast one plus an always-slow agent.

The slow-path judgment is the old impact-judge criterion: only remote/infra
mutation or irreversible destruction is "ask"; everything local and reversible is
"allow". On the fast path it never blocks; on the slow path it returns allow or
ask, never deny.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
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

# go subcommands that are read-only or local-reversible (fmt reformats files,
# build/test/vet are safe). `go env -w/-u` is rejected below. `go tool` is here
# only for the bare list form (`go tool` with no tool name); `go tool <name>`
# runs the tool and is rejected below. `go get` fetches deps and rewrites
# go.mod/go.sum: a network read that only writes local, git-reversible files and
# does NOT execute the fetched code (module-aware mode), so it is local-
# reversible, same category as `go mod download`/`tidy` already here. Excludes
# `go run` (executes arbitrary code) and `go install` (network + installs
# binaries onto PATH).
GO_READONLY_SUB = {"env", "version", "list", "vet", "doc", "fmt", "build",
                   "test", "mod", "tool", "get"}

# terraform subcommands that only read or stay local. apply/destroy/import/state
# (mutations) are NOT here; they fall through to the ask rules.
TF_READONLY_SUB = {"fmt", "validate", "plan", "version", "show", "output",
                   "providers", "graph", "init"}

# mise subcommands that only read. Excludes run/install/use/exec/uninstall/
# prune (those execute or mutate; they stay with the mise guard hook).
MISE_READONLY_SUB = {"registry", "ls", "list", "current", "which", "where",
                     "ls-remote", "version", "doctor", "env"}

# pip subcommands that only inspect the environment. install/uninstall/download
# (mutate the venv or fetch from the network) are NOT here and fall through to
# the ask rules. `pip` may also be invoked as `pip3` or `python -m pip`.
PIP_READONLY_SUB = {"list", "show", "freeze", "check", "config", "debug",
                    "inspect", "help", "cache"}

# `python -m <module>` modules that only PARSE the target without importing or
# executing it: byte-compile and static analyzers/linters/type-checkers. They
# read source and report, so they are read-only. Deliberately excluded: `pylint`
# (imports the target module to analyze it, executing module-level code) and any
# formatter that rewrites files (black/isort); those defer to the impact judge.
PYTHON_M_READONLY = {"py_compile", "pyflakes", "pycodestyle", "pydocstyle",
                     "flake8", "mccabe", "mypy", "ruff"}

# jira: read-only commands. `me`, `version`, `open` are single-word; the rest
# are `<group> <verb>` pairs. Writes (issue create/move/comment/edit/assign,
# epic add/create, sprint add) are NOT here and fall through to the ask rules.
JIRA_READONLY_SOLO = {"me", "version", "open"}
JIRA_READONLY_PAIR = {
    ("issue", "view"), ("issue", "list"),
    ("epic", "list"),
    ("sprint", "list"),
    ("board", "list"),
}

# pup (DataDog CLI): only the read command paths keru-datadog-audit uses. `pup`
# tags every command with a `read_only` flag in its own --help; this is an
# explicit allowlist (like GH_READONLY), so any path not listed (every write:
# `cases create/jira`, `metrics submit`, `logs archives/metrics delete`,
# `metrics metadata update`, and the interactive `auth login/logout/refresh`)
# falls through to the model judge and prompts. Matched as an anchored prefix of
# the positional tokens, so a flag VALUE that follows the verb can never make a
# write path look like a read.
PUP_READONLY = {
    ("error-tracking", "issues", "search"), ("error-tracking", "issues", "get"),
    ("logs", "search"), ("logs", "aggregate"), ("logs", "list"), ("logs", "query"),
    ("events", "search"), ("events", "list"), ("events", "get"),
    ("metrics", "query"), ("metrics", "search"), ("metrics", "list"),
    ("auth", "status"), ("auth", "test"), ("auth", "list"),
    ("version",),
}

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

# Project helpers installed on PATH by the installer (scripts/helpers/). These
# are read-only by construction: keru-jira-dev does authenticated GETs against
# Jira's dev-status endpoint, keru-bot-triage does only gh reads (no merges or
# comments). keru-branch-cleanup is NOT here: it is read-only only in `audit`
# mode, so it is handled separately below (`clean` deletes branches and defers).
KERU_READONLY_HELPERS = {"keru-jira-dev", "keru-bot-triage"}

# find write actions: unambiguous, only find uses them, so they are dangerous
# on any command that bears them.
DANGEROUS_FLAG_TOKENS = {"-exec", "-execdir", "-delete", "-fprint", "-fprintf",
                        "-fprint0"}
# Commands where `-i` / `--in-place` means edit-the-file-in-place. For other
# commands `-i` is harmless (e.g. grep -i is case-insensitive), so the in-place
# check must be scoped to these, not applied globally.
INPLACE_COMMANDS = {"sed", "gsed", "perl"}


def _is_inplace_flag(tok: str) -> bool:
    # exactly -i, or -i<suffix> like -i.bak, or --in-place[=...].
    if tok == "-i" or tok == "--in-place":
        return True
    if tok.startswith("-i") and len(tok) > 2 and tok[2] in ".=":
        return True
    if tok.startswith("--in-place="):
        return True
    return False

# `gh api graphql` carries its GraphQL operation in a `query=` field, which the
# REST `gh api` rule rejects as field data. Judge it by operation instead: a
# read (`query`/introspection) has no `mutation`. `mutation` is a lowercase,
# case-sensitive GraphQL reserved word, so a real mutation always contains it
# while a type named "Mutation" (capitalized) does not, making this precise.
GQL_MUTATION_RE = re.compile(r"\bmutation\b")


def _gh_graphql_is_read(tokens) -> bool:
    """True only if `gh api graphql ...` carries an inline, mutation-free query.
    A query loaded from a file (`query=@...`) or absent cannot be proven read-
    only, so it returns False (defer to the impact judge)."""
    for t in tokens:
        if t.startswith("query="):
            value = t[len("query="):]
            if value.startswith("@"):
                return False  # loaded from a file/stdin: cannot inspect
            return GQL_MUTATION_RE.search(value) is None
    return False  # no inline query field found: cannot prove it is a read

# Shell operators that separate commands.
SEPARATORS = {"|", "||", "&&", ";", "&", "|&", "\n"}
_REDIR_CHARS = set("<>&|")


def _is_redirect_token(tok: str) -> bool:
    """True if a token IS a redirection operator (>, >>, <, <>, >&, &>>, ...);
    redirection means a write target. The punctuation_chars lexer isolates every
    real redirect as a standalone token made only of redirect chars (and
    optional fd digits), so checking the token's shape is precise. A quoted
    string like 'a -> b' arrives as one token with letters/spaces, so it is NOT
    flagged: this is the bug the shape check fixes versus scanning for any
    '<'/'>' character anywhere in the token."""
    if not tok or not any(c in "<>" for c in tok):
        return False
    return all(c in _REDIR_CHARS or c.isdigit() for c in tok)


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
        # Skip safe global options that can precede the subcommand (e.g.
        # `git --no-pager diff`, `git --paginate log`). Defer on global options
        # that can change target or inject config (-C, -c, --git-dir, --work-tree).
        rest = tokens[1:]
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            if rest[i] in ("--no-pager", "--paginate", "--literal-pathspecs"):
                i += 1
            else:
                return False  # -C, -c, --git-dir, etc: not provably safe
        after = rest[i:]
        sub = after[0] if after else ""
        if sub not in GIT_READONLY_SUB:
            return False
        # `git checkout`/`switch` changing a branch is safe, but `checkout --`,
        # `checkout .`, or `checkout <x> -- <files>` discards changes: defer it.
        if sub in ("checkout", "switch") and ("--" in after[1:] or "." in after[1:]):
            return False
    elif base == "go":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in GO_READONLY_SUB:
            return False
        # `go env -w` / `-u` mutate the env; defer those.
        if sub == "env" and any(a in ("-w", "-u") for a in tokens[2:]):
            return False
        # `go mod` is read-only only for tidy/download/verify/graph/why.
        if sub == "mod":
            modsub = tokens[2] if len(tokens) > 2 else ""
            # tidy/download/verify/graph/why are safe; edit rewrites go.mod but
            # is local and reversible. Anything else (e.g. unknown) defers.
            if modsub not in ("tidy", "download", "verify", "graph", "why", "edit"):
                return False
        # `go tool` with no tool name just lists declared tools (read-only); but
        # `go tool <name>` runs the tool (arbitrary). Approve only the bare form;
        # the rest defers to the `Bash(go tool *)` impact-judge hook.
        if sub == "tool":
            if any(not a.startswith("-") for a in tokens[2:]):
                return False
    elif base in ("python", "python3", "py"):
        # Only `python -m <module>` for a parse-only module (PYTHON_M_READONLY:
        # py_compile and the static analyzers/linters/type-checkers) is read-
        # only: it reads source and reports without importing or executing the
        # target (py_compile's .pyc is a local, git-ignorable cache). Every other
        # python invocation runs arbitrary code (a script, `-c`, another module),
        # so it defers to the impact-judge agent.
        if not (len(tokens) > 2 and tokens[1] == "-m"
                and tokens[2] in PYTHON_M_READONLY):
            return False
    elif base == "terraform":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub not in TF_READONLY_SUB:
            return False
    elif base in ("command", "type", "hash"):
        # Only the lookup forms are safe (`command -v x`, `type x`). `command x`
        # would run x, bypassing this allowlist, so require a lookup flag for
        # `command`. `type`/`hash` only print, never execute.
        if base == "command" and not any(t in ("-v", "-V") for t in tokens[1:]):
            return False
    elif base == "mise":
        sub = tokens[1] if len(tokens) > 1 else ""
        # `mise exec [opts] -- <cmd>` runs <cmd> with mise's tools on PATH; it is
        # safe iff <cmd> is. Recurse on the part after `--`.
        if sub == "exec":
            if "--" in tokens:
                inner = tokens[tokens.index("--") + 1:]
                return tokens_are_safe(inner)
            return False  # `mise exec` without `--` is ambiguous: defer
        if sub not in MISE_READONLY_SUB:
            return False
    elif base in ("pip", "pip3"):
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        sub = rest[0] if rest else ""
        if sub not in PIP_READONLY_SUB:
            return False
        # `pip config set/unset/edit` writes config; `pip cache purge/remove`
        # deletes the wheel cache. Those mutate, so defer them.
        if sub == "config" and any(a in ("set", "unset", "edit") for a in rest[1:]):
            return False
        if sub == "cache" and any(a in ("purge", "remove") for a in rest[1:]):
            return False
    elif base == "gh":
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        sub1 = rest[0] if rest else ""
        sub2 = rest[1] if len(rest) > 1 else ""
        if sub1 == "api" and sub2 == "graphql":
            # `gh api graphql` passes its operation via `-f query='...'`, which
            # the REST rule below would reject. Allow only an inline, mutation-
            # free query; a mutation or a file-loaded query defers to the judge.
            return _gh_graphql_is_read(tokens[2:])
        if sub1 == "api":
            # gh api defaults to GET, but field flags (-f/-F) auto-switch it to
            # POST. So a GET is read-only when EITHER the method is pinned to GET
            # (`-X GET`/`--method GET`: field flags then become query-string
            # params) OR there is no method and no field flags. An explicit
            # non-GET method mutates; field flags with no explicit method imply a
            # POST. Parse the method (`-X V`, `-XV`, `--method V`, `--method=V`).
            api_args = tokens[2:]
            method = None
            i = 0
            while i < len(api_args):
                t = api_args[i]
                if t in ("-X", "--method"):
                    method = api_args[i + 1] if i + 1 < len(api_args) else ""
                    i += 2
                    continue
                if t.startswith("-X") and len(t) > 2:
                    method = t[2:]
                elif t.startswith("--method="):
                    method = t[len("--method="):]
                i += 1
            if method is not None:
                if method.upper() != "GET":
                    return False  # explicit mutating method
            else:
                # No explicit method: field/input flags would switch GET to POST.
                bad = {"-f", "-F", "--field", "--raw-field", "--input"}
                for t in api_args:
                    if t in bad or t.split("=")[0] in bad:
                        return False
        elif (sub1, sub2) not in GH_READONLY and (sub1,) not in GH_READONLY:
            return False
    elif base == "jira":
        rest = [t for t in tokens[1:] if not t.startswith("-")]
        sub1 = rest[0] if rest else ""
        sub2 = rest[1] if len(rest) > 1 else ""
        if sub1 not in JIRA_READONLY_SOLO and (sub1, sub2) not in JIRA_READONLY_PAIR:
            return False
    elif base == "pup":
        # Skip pup's global flags first (they precede the domain), so a value-
        # taking global (`--org X`, `--output X`) does not turn its value into a
        # false leading positional and break the prefix match. Same idea as the
        # git global-option skip above.
        rest = tokens[1:]
        i = 0
        while i < len(rest) and rest[i].startswith("-"):
            # --org/--output take a separate value token unless given as =VALUE.
            if rest[i] in ("--org", "--output"):
                i += 2
            else:  # --agent/--no-agent/--yes/--org=.../--output=...: no separate value
                i += 1
        # Match the read command as an anchored prefix of the positional (non-
        # flag) tokens after the globals: the first positional must be the read
        # domain, so a write domain (`cases`, `metrics submit`) can never be
        # promoted to a read, and a flag VALUE after the verb (a --query or
        # --compute argument) cannot shift the prefix. Anything not listed defers.
        pos = tuple(t for t in rest[i:] if not t.startswith("-"))
        if not any(len(pos) >= len(p) and pos[:len(p)] == p for p in PUP_READONLY):
            return False
    elif base in KERU_READONLY_HELPERS:
        return True  # read-only project helpers; their args are issue keys/repos
    elif base == "keru-branch-cleanup":
        # Read-only only in `audit` mode; `clean` deletes branches, so defer it.
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub != "audit":
            return False
    elif base == "keru-repo-update":
        # Read-only only in `audit` mode; `update` switches branches and
        # fast-forwards (mutates the working tree), so defer it.
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub != "audit":
            return False
    elif base not in READ_ONLY:
        return False
    inplace_risky = base in INPLACE_COMMANDS
    for t in tokens[1:]:
        if t in DANGEROUS_FLAG_TOKENS:
            return False
        if inplace_risky and _is_inplace_flag(t):
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
        if _is_redirect_token(t):
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


def _emit(decision, reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


# The single judgment the slow path applies, ported verbatim in spirit from the
# old impact-judge agent: only remote/infra mutation or irreversible destruction
# is "ask"; everything local and reversible (including reads over the network and
# dependency fetches) is "allow". A recognized local-effect dev tool run through
# a fetch-wrapper (npx/go run/uvx) is allow; an unrecognized remote payload
# executed as code is ask.
JUDGE_SYSTEM = (
    "You decide if a shell command is safe to auto-approve in a dev repo. "
    "Answer with ONLY one word: ALLOW or ASK.\n"
    "ALLOW when every part only reads or is LOCAL and REVERSIBLE: reads (local or "
    "a read-only remote query like `gh ... view/list`, `aws ... describe/list`, a "
    "GET), analyzes, builds, tests, lints, formats, generates, or writes/deletes "
    "files in the repo or /tmp (git reverts those); dependency fetches (`go get`, "
    "`npm/pnpm/yarn install`, `pip install`) that only write local lockfiles/deps; "
    "a recognized linter/formatter/test tool even via `npx`/`go run <tool>@v`/`uvx`; "
    "`brew install`. \n"
    "ASK only when a part: changes remote state or infra (git push, deploy, "
    "terraform/tofu apply/destroy, kubectl/helm/aws/gcloud/az mutations, docker "
    "push, a network call that writes to a remote, DB changes even local); OR "
    "destroys beyond git's reach (`rm -rf` of untracked/outside-repo paths, `git "
    "reset --hard`, `git checkout -- <files>`, `git restore`, `git clean`); OR "
    "executes an unrecognized remote payload as code (`curl ... | sh`, `go install` "
    "of an unfamiliar package). For a compound command, if ANY part is ASK, answer "
    "ASK. If unsure, answer ASK."
)


def _dp_bin():
    found = shutil.which("dp")
    if found:
        return found
    base = os.path.expanduser("~/.local/share/mise/installs/dailypay-dp")
    if os.path.isdir(base):
        for ver in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, ver, "bin", "dp")
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def judge_with_model(command):
    """Slow path: ask the model once whether the command is safe. Returns
    'allow' or 'ask'. Fail-safe: any failure (no dp, timeout, junk) returns
    'ask', never 'allow', so an unevaluated unknown command always prompts."""
    dp = _dp_bin()
    if not dp:
        return "ask"
    prompt = JUDGE_SYSTEM + "\n\nCommand:\n" + command
    try:
        proc = subprocess.run([dp, "ai", "claude", "-p", "--bare", prompt],
                              capture_output=True, text=True, timeout=25)
    except Exception:
        return "ask"
    out = (proc.stdout or "").strip().upper()
    if out.startswith("ALLOW"):
        return "allow"
    return "ask"  # ASK, junk, or empty: fail safe


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # malformed input: defer to normal permission flow
    if data.get("tool_name") != "Bash":
        return
    command = (data.get("tool_input") or {}).get("command", "")
    if not command or not isinstance(command, str):
        return

    # FAST PATH: provably read-only/local-reversible by static parsing. Instant.
    if command_is_safe(command):
        _emit("allow", "read-only command pipeline")
        return

    # The user's own allow-list (rules they approved with "allow always") is
    # consulted by Claude Code's permission layer separately; we do not duplicate
    # it here. Anything not provably safe goes to the single slow judgment.

    # SLOW PATH: one model call decides. Fail-safe to ASK. This replaces the old
    # separate agent hooks (make/mise/go-tool/catch-all), so there is ONE hook,
    # fast for known-safe commands and model-judged only for the unknowns.
    decision = judge_with_model(command)
    if decision == "allow":
        _emit("allow", "model-judged local/reversible")
    else:
        _emit("ask", "not provably safe; model judgment deferred to you")


if __name__ == "__main__":
    main()
