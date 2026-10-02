#!/usr/bin/env python3
"""PreToolUse hook: deny a code edit whose added comments break the parser-checkable
part of keru-writing-code's comment rule. What it checks: docs/permissions.md,
"The code-comment gate"."""
import difflib
import json
import os
import re
import sys
from collections import Counter

MAX_BLOCK = 2
MAX_TOTAL = 5
MAX_LINE = 2000

SLASH = {".go", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".java", ".kt", ".kts",
         ".scala", ".rs", ".swift", ".c", ".h", ".cc", ".cpp", ".hpp", ".cs", ".proto",
         ".dart", ".php", ".vue", ".svelte"}
HASH = {".py", ".rb", ".sh", ".bash", ".zsh", ".yaml", ".yml", ".toml", ".pl", ".r",
        ".ex", ".exs", ".mk", ".dockerfile"}
SLASH_AND_HASH = {".tf", ".tfvars", ".hcl"}
DASH = {".sql"}
HASH_NAMES = {"makefile", "gnumakefile", "dockerfile", "containerfile", "gemfile",
              "rakefile", "justfile"}
BACKTICK = {".go", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"}
TRIPLE = {".py", ".toml", ".ex", ".exs"}
SHELL = {".sh", ".bash", ".zsh"}
YAML = {".yaml", ".yml"}

SKIP_SEGMENTS = ("/node_modules/", "/.git/", "/vendor/", "/.venv/", "/site-packages/",
                 "/third_party/", "/docs/")
GENERATED = re.compile(r"(\.pb\.go|\.gen\.go|_gen\.go|zz_generated[^/]*\.go|\.pb\.[a-z]+)$")

SWAG = ("Summary|Description|Tags|Accept|Produce|Param|Success|Failure|Router|Security|ID"
        "|Deprecated|title|version|host|BasePath|license|contact|securityDefinitions")
DIRECTIVE = re.compile(
    r"^(?:"
    r"//go:|//\s*\+[a-z]|//\s*nolint\b|//lint:|//revive:|//export\s|//line\s|//\s*#(?:include|cgo)\b"
    r"|//\s*clang-format\b|//\s*(?:eslint|prettier-ignore|@ts-|istanbul|c8\b|biome-ignore|tslint:)"
    r"|/\*\s*(?:eslint|istanbul|c8\b|prettier-ignore|@ts-|webpackChunkName)|/\*\*?\s*@[^*]*\*/"
    r"|///\s*<reference|//\s*Code generated .*DO NOT EDIT|//\s*@(?:" + SWAG + r")\b|//\s*swagger:"
    r"|(?://|#|--)\s*SPDX-License-Identifier"
    r"|#!|#\s*-\*-|#\s*(?:noqa\b|type:|pylint:|pragma\b|mypy:|fmt:|isort:|ruff:|pyright:|flake8:"
    r"|shellcheck\b|nosec\b|frozen_string_literal|rubocop:|tflint-ignore|tfsec:|checkov:|trivy:"
    r"|yamllint\b|yaml-language-server:|renovate:|hadolint\b|syntax=|escape=|region\b|endregion\b"
    r"|@(?:schema|default|ignore)\b|--\s)"
    r"|--\s*(?:name:|\+goose\b|\+migrate\b|migrate:|noqa\b|sqlfluff\b)"
    r")")
GO_OUTPUT = re.compile(r"(?i)^(?:unordered\s+)?output:")
VERSION_PIN = re.compile(r"\s*(?:v?\d+(?:\.\d+)*[\w.+-]{0,40}|tag=\S{1,80}|pin@\S{1,80})\s*")

# Same list as keru-context-snapshot's NOT_TICKETS_JQ; repo-health checks they match.
NOT_TICKETS = {"UTF", "SHA", "ISO", "IEC", "RFC", "AES", "RSA", "DSA", "TLS", "SSL", "HTTP",
               "MD", "CRC", "UUID", "IPV", "CVE", "CWE", "GHSA", "PYSEC", "RUSTSEC", "FIPS",
               "NIST", "PKCS", "CP", "ECDSA", "ED", "HS", "RS", "ES", "PS", "PEP", "KIP",
               "UTC", "GMT", "IEEE", "ANSI", "ECMA", "ASCII", "GPT", "AWS", "BSD", "MPL",
               "GPL", "LGPL", "AGPL", "MIT", "CC", "OWASP", "CIS", "SOC", "PCI", "ARM",
               "AVX", "INT", "UINT", "GO", "COVID", "HTML", "CSS", "SQL", "IE", "AMD", "BASE",
               "OAUTH", "TCP", "UDP", "DNS", "API", "JSON", "XML", "PDF", "JDK"}
TICKET = re.compile(r"\b([A-Z]{2,10})-\d+\b(?![.-][A-Za-z0-9])")
PR_REF = re.compile(
    r"(?i)\b(?:PR|MR|pull request|pull|issue)s?\s*#\s*\d+\b"
    r"|(?<![/\w.-])[\w.-]+/[\w.-]+#\d+\b"
    r"|\b[a-z0-9]+(?:-[a-z0-9]+)+\s+#\d{3,5}\b"
    r"|/pull/\d+|atlassian\.net/browse/")
STRING_SPAN = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')
SHELL_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(?:([\"'])([A-Za-z_]\w*)\1|\\?([A-Z_][A-Z0-9_]*)\b)")
RUBY_HEREDOC = re.compile(r"<<[-~]?([\"']?)([A-Z_][A-Z0-9_]*)\1")
YAML_BLOCK = re.compile(r"(?:^|[:\-])\s*(?:[&!]\S*\s+)*[|>][-+0-9]*\s*$")
PY_DOC = re.compile(r"^[rRuU]?(\"\"\"|''')")
MID_BLOCK = re.compile(r"^\*(?:\s|/|$)")


def _lang(path):
    low = os.path.basename(path).lower()
    ext = os.path.splitext(low)[1]
    docker = low in ("dockerfile", "containerfile") or low.startswith(("dockerfile.", "containerfile.")) \
        or ext == ".dockerfile"
    if ext in SLASH:
        line, block = ("//",), True
    elif ext in SLASH_AND_HASH:
        line, block = ("//", "#"), True
    elif ext in DASH:
        line, block = ("--",), True
    elif ext in HASH or low in HASH_NAMES or docker:
        line, block = ("#",), False
    else:
        return None
    return {"line": line, "block": block, "ext": ext, "test": low.endswith("_test.go"),
            "make": low in ("makefile", "gnumakefile") or ext == ".mk",
            "heredoc": ext in SHELL or ext in SLASH_AND_HASH or docker,
            "multiline_quotes": ext in SHELL or ext in YAML or docker}


def _in_skills_repo(path):
    d = os.path.dirname(os.path.abspath(path))
    while True:
        if (os.path.isfile(os.path.join(d, "playbook", "PLAYBOOK.md"))
                and os.path.isfile(os.path.join(d, "scripts", "hooks", "keru-gate-comments.py"))):
            return True
        parent = os.path.dirname(d)
        if parent == d:
            return False
        d = parent


def _opener_context(prefix):
    p = prefix.rstrip()
    return bool(p) and (p[-1] in "=(,[{:+" or p.endswith("return")
                        or re.search(r"(?:sql|html|css|gql|graphql)$", p) is not None)


def _scan_code(line, lang, opener_ok):
    """(trailing text, its marker, code before it, state left open at end of line)."""
    ext, n, i = lang["ext"], len(line), 0
    while i < n:
        c, two = line[i], line[i:i + 2]
        if c == "\\":
            i += 2
            continue
        if "//" in lang["line"] and two == "//" and not (i and line[i - 1] == ":"):
            return line[i + 2:], "//", line[:i], None
        if lang["block"] and two == "/*":
            end = line.find("*/", i + 2)
            if end == -1:
                return line[i + 2:], "/*", line[:i], ("block", False)
            return line[i + 2:end], "/*", line[:i] + line[end + 2:], None
        if "--" in lang["line"] and two == "--":
            return line[i + 2:], "--", line[:i], None
        if "#" in lang["line"] and c == "#" and (i == 0 or line[i - 1].isspace() or ext in (".py", ".toml")):
            return line[i + 1:], "#", line[:i], None
        if ext in TRIPLE and line.startswith(('"""', "'''"), i):
            d = line[i:i + 3]
            end = line.find(d, i + 3)
            if end == -1:
                return None, None, line[:i], (("str", d, False) if opener_ok(line[:i]) else None)
            i = end + 3
            continue
        if c in "\"'" or (c == "`" and ext in BACKTICK):
            if ext in YAML and line[:i].rstrip()[-1:] not in ("", ":", "-", "[", "{", ","):
                i += 1
                continue
            j = i + 1
            while j < n and line[j] != c:
                j += 2 if line[j] == "\\" else 1
            if j >= n:
                if (c == "`" or lang["multiline_quotes"]) and opener_ok(line[:i]):
                    return None, None, line[:i], ("str", c, False)
                return None, None, line, None
            i = j + 1
            continue
        i += 1
    return None, None, line, None


def _inner_comment(s, lang):
    """The free text after a second comment marker on a directive line."""
    for mk in lang["line"]:
        k = s.find(mk, len(mk))
        if k > 0 and s[k - 1].isspace():
            return s[k + len(mk):].strip() or None
    return None


def _clean_trailing(text, marker, lang):
    text = text.strip()
    if not text or VERSION_PIN.fullmatch(text) or (lang["make"] and text.startswith("#")):
        return None
    if DIRECTIVE.match(marker + text) or DIRECTIVE.match(marker + " " + text):
        return _inner_comment(marker + text, lang)
    return text


def _heredoc(code, lang):
    rx = RUBY_HEREDOC if lang["ext"] == ".rb" else SHELL_HEREDOC
    spans = [m.span() for m in STRING_SPAN.finditer(code)]
    for m in rx.finditer(code):
        if not any(a <= m.start() < b for a, b in spans):
            return m.group(2) or (m.group(3) if m.lastindex and m.lastindex >= 3 else None)
    return None


def _closes(line, d):
    if len(d) == 3:
        return line.count(d) % 2 == 1
    return len(re.findall(r"(?<!\\)" + re.escape(d), line)) % 2 == 1


def scan(lines, lang, fragment):
    """One (kind, comment text, trailing comment) per line; kind is comment, delim,
    directive, code, blank or string."""
    recs, state, output_run = [], None, False
    seen_code, prev_code = not fragment, None
    for raw in lines:
        line = raw[:MAX_LINE]
        s = line.strip()
        indent = len(line) - len(line.lstrip())
        if state and state[0] == "heredoc":
            recs.append(("string", None, None))
            if s == state[1]:
                state = None
            continue
        if state and state[0] == "yaml":
            base, content = state[1], state[2]
            if not s or (content is None and indent > base) or (content is not None and indent >= content):
                if s and content is None:
                    state = ("yaml", base, indent)
                recs.append(("string", None, None))
                continue
            state = None
        if state and state[0] == "str":
            d, doc = state[1], state[2]
            if doc:
                body = s.replace(d, "").strip()
                recs.append(("comment", body, None) if body else ("delim", None, None))
            else:
                recs.append(("string", None, None))
            if _closes(line, d):
                state = None
            continue
        if state and state[0] == "block":
            body = s.split("*/")[0].lstrip("*").strip()
            recs.append(("directive", None, None) if state[1]
                        else ("comment", body, None) if body else ("delim", None, None))
            if "*/" in s:
                state = None
            continue
        if not s:
            output_run = False
            recs.append(("blank", None, None))
            continue
        if DIRECTIVE.match(s):
            if lang["block"] and s.startswith("/*") and "*/" not in s[2:]:
                state = ("block", True)
            recs.append(("directive", None, _inner_comment(s, lang)))
            continue
        marker = next((mk for mk in lang["line"] if s.startswith(mk)), None)
        if marker:
            body = s[len(marker):].lstrip(marker[0]).strip()
            if lang["test"] and GO_OUTPUT.match(body):
                output_run = True
            if output_run:
                recs.append(("directive", None, None))
            else:
                recs.append(("comment", body, None) if body else ("delim", None, None))
            continue
        output_run = False
        if lang["block"] and (s.startswith("/*") or s.startswith("{/*")):
            inner = s.split("/*", 1)[1]
            body = inner.split("*/")[0].lstrip("*").strip()
            recs.append(("comment", body, None) if body else ("delim", None, None))
            if "*/" not in inner:
                state = ("block", False)
            continue
        if lang["block"] and not seen_code and MID_BLOCK.match(s):
            body = s.lstrip("*/").strip()
            recs.append(("comment", body, None) if body else ("delim", None, None))
            continue
        doc = PY_DOC.match(s) if lang["ext"] == ".py" else None
        if doc and ((prev_code or "").endswith(":") or (not fragment and prev_code is None)):
            d = doc.group(1)
            body = s[doc.end():].replace(d, "").strip()
            recs.append(("comment", body, None) if body else ("delim", None, None))
            if s.count(d) % 2 == 1:
                state = ("str", d, True)
            seen_code, prev_code = True, s
            continue

        trailing, tmark, code, new_state = _scan_code(line, lang, (lambda _prefix: True) if seen_code else _opener_context)
        trailing = _clean_trailing(trailing, tmark, lang) if trailing is not None else None
        if new_state:
            state = new_state
        elif lang["heredoc"] or lang["ext"] == ".rb":
            hd = _heredoc(code, lang)
            if hd:
                state = ("heredoc", hd)
        if not state and lang["ext"] in YAML and YAML_BLOCK.search(code):
            state = ("yaml", indent, None)
        recs.append(("code", None, trailing))
        seen_code, prev_code = True, code.strip()
    return recs


def _refs(text):
    text = text[:MAX_LINE * 4]
    hits = [m.group(0) for m in TICKET.finditer(text) if m.group(1) not in NOT_TICKETS]
    hits += [m.group(0).strip() for m in PR_REF.finditer(text)]
    return hits


def _norm(t):
    return " ".join(t.split())


def _opcodes(a, b):
    """difflib opcodes over stripped lines, after trimming the common head and tail so a
    small change to a large file stays fast."""
    head = 0
    while head < len(a) and head < len(b) and a[head] == b[head]:
        head += 1
    tail = 0
    while tail < len(a) - head and tail < len(b) - head and a[-1 - tail] == b[-1 - tail]:
        tail += 1
    sm = difflib.SequenceMatcher(None, a[head:len(a) - tail], b[head:len(b) - tail], autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        yield tag, i1 + head, i2 + head, j1 + head, j2 + head


def problems_for(path, old, new, multiplier=1, fragment=True):
    lang = _lang(path)
    if not lang or not new:
        return []
    old_lines, new_lines = (old or "").splitlines(), new.splitlines()
    orec, nrec = scan(old_lines, lang, fragment), scan(new_lines, lang, fragment)
    status = ["eq"] * len(nrec)
    trailing_new = [False] * len(nrec)
    refs_ok = [set() for _ in nrec]
    for tag, i1, i2, j1, j2 in _opcodes([l.strip() for l in old_lines], [l.strip() for l in new_lines]):
        if tag == "equal":
            continue
        olds = orec[i1:i2]
        old_texts = [r[1] for r in olds if r[0] == "comment"] + [r[2] for r in olds if r[2]]
        ok = set(_refs(" ".join(old_texts)))
        budget = sum(1 for r in olds if r[0] == "comment")
        old_tr = Counter(_norm(r[2]) for r in olds if r[2])
        for j in range(j1, j2):
            kind, _, tr = nrec[j]
            refs_ok[j] = ok
            if kind == "comment":
                if budget > 0:
                    budget -= 1
                    status[j] = "rew"
                else:
                    status[j] = "ins"
            if tr:
                if old_tr[_norm(tr)] > 0:
                    old_tr[_norm(tr)] -= 1
                else:
                    trailing_new[j] = True

    refs, blocks, added, run = set(), [], 0, None
    for j, (kind, text, tr) in enumerate(nrec):
        if kind == "comment" and status[j] != "eq":
            refs.update(r for r in _refs(text) if r not in refs_ok[j])
        if trailing_new[j]:
            refs.update(r for r in _refs(tr) if r not in refs_ok[j])
            added += 1
        if kind in ("comment", "delim"):
            run = run or {"pre": 0, "add": 0, "first": None}
            if kind == "comment":
                if status[j] == "ins":
                    run["add"] += 1
                    added += 1
                    run["first"] = run["first"] or text
                else:
                    run["pre"] += 1
            continue
        if run:
            blocks.append(run)
        run = None
    if run:
        blocks.append(run)

    out = []
    if refs:
        out.append("something shaped like a ticket or PR reference in a comment (%s)"
                   % ", ".join(sorted(refs)[:5]))
    for r in blocks:
        if r["add"] > MAX_BLOCK or (r["pre"] and r["add"] and r["pre"] <= MAX_BLOCK < r["pre"] + r["add"]):
            out.append("a comment block of %d lines (starting `%s`), over the %d-line limit"
                       % (r["pre"] + r["add"], (r["first"] or "")[:80], MAX_BLOCK))
            if len(out) > 3:
                break
    added *= max(1, multiplier)
    if added > MAX_TOTAL:
        out.append("%d new comment lines in one edit, over the %d-line limit" % (added, MAX_TOTAL))
    return out


def _deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        return
    ti = data.get("tool_input")
    if not isinstance(ti, dict) or not isinstance(ti.get("file_path"), str):
        return
    p = os.path.abspath(os.path.expanduser(ti["file_path"]))
    if (not _lang(p) or any(seg in p for seg in SKIP_SEGMENTS)
            or GENERATED.search(p) or _in_skills_repo(p)):
        return

    current = ""
    try:
        if os.path.isfile(p):
            with open(p, encoding="utf-8", errors="replace") as f:
                current = f.read()
    except Exception:
        current = ""
    if data["tool_name"] == "Write":
        old, new, mult, fragment = current, ti.get("content"), 1, False
    else:
        old, new, fragment = ti.get("old_string"), ti.get("new_string"), True
        mult = current.count(old) if ti.get("replace_all") and isinstance(old, str) and old else 1
    if not isinstance(new, str) or (old is not None and not isinstance(old, str)):
        return
    try:
        problems = problems_for(p, old or "", new, mult, fragment)
    except Exception:
        return
    if not problems:
        return
    detail = " ".join("(%d) %s." % (i + 1, x) for i, x in enumerate(problems))
    _deny("This edit to %s adds comments over keru-writing-code's limits, so it was not "
          "applied. %s Comments default to none: keep one only where a reviewer could not "
          "infer the why from the code, as one short line, with no ticket or PR reference "
          "(that context goes in the PR description and the commit). Cut them and retry; do "
          "not reword or split them to fit under the check. If the user explicitly asked for "
          "this comment, or a linter the repo runs requires it, tell the user the gate "
          "blocked it instead." % (os.path.basename(p), detail))


if __name__ == "__main__":
    main()
