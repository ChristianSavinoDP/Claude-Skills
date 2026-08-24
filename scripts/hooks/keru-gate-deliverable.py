#!/usr/bin/env python3
"""PreToolUse hook: mechanically block writing a non-compliant deliverable.

This is the one enforcement point that does NOT depend on the model's discretion
and is NOT the unreliable Stop event. PreToolUse runs on the critical path of the
Write/Edit tool: the harness invokes it before the file is written, and a "deny"
decision actually prevents the write. So a malformed deliverable file cannot be
created, the model is shown why, and it retries until the content passes.

Two scopes, so no deliverable can skip the form gate:

  1. A gated DRAFT under /tmp, by convention
       /tmp/keru-deliverable-<skill>.md         (e.g. keru-deliverable-pr-review.md)
       /tmp/keru-deliverable-<skill>-<id>.md     (e.g. keru-deliverable-pr-review-3254.md)
     The optional <id> (a Jira key or PR number) keeps concurrent or sequential
     deliverables of the same skill from overwriting each other. The <skill>
     selects which Output contract to validate against (the skill-specific opening
     invariant PLUS the shared form rules); since skill names contain hyphens
     (pr-review, addressing-pr-comments), the skill is resolved against the known
     set, not split on a hyphen.

  2. Any MARKDOWN file written straight into a repo (not a temp scratch dir): a
     doc that lands in a repo IS a deliverable, so it must clear the shared form
     rules (no em dashes, English only, well-formed markdown) even when it never
     went through a /tmp draft. This closes the bypass a skill created by handing
     the write off to another skill (e.g. keru-investigation -> keru-writing-docs)
     with nothing mechanically forcing that handoff: previously such a doc could
     be written directly to `docs/investigations/.../investigation.md` and skip
     the gate entirely (see audit/audit.md). The skill-specific OPENING invariant
     is not imposed here (the placed doc's shape is the caller's, not a /tmp draft
     contract); only the shared form rules apply.

Validation reuses keru-check-output's checkers (one source of truth). Fail-open
on anything it cannot parse, so it never wedges a normal write: it only ever
denies content it can positively prove is non-compliant.
"""
import importlib.util
import json
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))

# Deliverable draft filename convention: keru-deliverable-<skill>[-<id>].md
# The suffix may carry a Jira key or PR number (uppercase, digits) to keep
# deliverables from overwriting each other, so it is NOT restricted to [a-z-].
# The skill is resolved from the captured stem against the known checker set.
NAME_RE = re.compile(r"keru-deliverable-(.+)\.md$")

# Temp roots: a .md here is scratch, not a repo deliverable, so scope 2 skips it.
# tempfile.gettempdir() covers the platform default; the literals cover the macOS
# /private symlink and the additional working dirs the harness may expose.
TEMP_ROOTS = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
# Never form-gate a .md under these: not authored prose we own (vendored deps, git
# internals, third-party trees), so the house style rules do not apply.
SKIP_SEGMENTS = ("/node_modules/", "/.git/", "/vendor/", "/.venv/", "/site-packages/")


def _resolve_skill(stem, known):
    """Given the filename stem after 'keru-deliverable-' (e.g. 'pr-review' or
    'pr-review-3254' or 'addressing-pr-comments-DBI-1'), return the skill it
    names, or None. Skill names contain hyphens and an optional id suffix
    follows another hyphen, so match the longest known skill that the stem
    equals or starts with (followed by '-'). Longest-first avoids a shorter
    skill shadowing a longer one; no known skill is a hyphen-prefix of another
    today, but this stays correct if that changes."""
    for skill in sorted(known, key=len, reverse=True):
        if stem == skill or stem.startswith(skill + "-"):
            return skill
    return None


def _is_temp(path):
    p = os.path.abspath(path)
    if any(p.startswith(r) for r in TEMP_ROOTS):
        return True
    try:
        return p.startswith(os.path.realpath(tempfile.gettempdir()) + os.sep)
    except Exception:
        return False


def _skip_md(path):
    p = os.path.abspath(path)
    return any(seg in p for seg in SKIP_SEGMENTS)


def _load_checkers():
    # The installed copies have NO .py extension, and spec_from_file_location
    # infers the loader from the extension, so it returns a spec with loader=None
    # for an extensionless file and the import fails silently (which made the
    # installed gate fail-open and let em dashes through). Pass an explicit
    # SourceFileLoader so the file loads as Python regardless of its name.
    from importlib.machinery import SourceFileLoader
    for path in (os.path.join(HERE, "keru-check-output.py"),
                 os.path.join(HERE, "keru-check-output"),
                 os.path.expanduser("~/.local/bin/keru-check-output")):
        if os.path.isfile(path):
            try:
                loader = SourceFileLoader("keru_check_output", path)
                spec = importlib.util.spec_from_loader("keru_check_output", loader)
                mod = importlib.util.module_from_spec(spec)
                loader.exec_module(mod)
                return mod
            except Exception:
                continue
    return None


def _form_problems(co, content, full_write):
    """The shared, skill-agnostic form rules every deliverable must clear: no em
    dashes, English only, and (for a whole-file Write) well-formed markdown. The
    markdown render check is skipped for an Edit, whose new_string is a fragment
    that can legitimately look unbalanced on its own (an inserted list item, half
    a fence); em-dash and English are safe on a fragment."""
    problems = []
    em = co.check_no_em_dash(content)
    if em[0] == "violation":
        problems.append(em[1])
    lang = co.check_english(content)
    if lang[0] == "violation":
        problems.append(lang[1])
    if full_write:
        md = co.check_markdown(content)
        if md[0] == "violation":
            problems.append(md[1])
    return problems


def _deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # unparseable input: allow (fail-open)
    if data.get("tool_name") not in ("Write", "Edit"):
        return
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or ""

    # Write gives the full content; Edit gives only the inserted post-edit string.
    content = tool_input.get("content")
    full_write = content is not None
    if content is None:
        content = tool_input.get("new_string")
    if not isinstance(content, str) or not content.strip():
        return  # nothing to check

    co = _load_checkers()
    if co is None:
        return  # cannot validate: allow rather than wedge

    m = NAME_RE.search(os.path.basename(path))
    if m:
        # Scope 1: a /tmp gated draft. Skill-specific opening invariant PLUS the
        # shared form rules. The stem selects the Output contract.
        skill = _resolve_skill(m.group(1), co.CHECKERS)
        if skill is None:
            return  # stem names no known skill: allow
        problems = []
        verdict, reason = co.CHECKERS[skill](content)
        if verdict == "violation":
            problems.append(reason)
        elif verdict == "skip":
            problems.append("this does not read as a %s deliverable (its opening or "
                            "structure does not match the skill's Output)." % skill)
        # A gated draft is written whole, so run the full form set (incl. markdown).
        problems += _form_problems(co, content, full_write=True)
        if not problems:
            return  # compliant: allow the write
        detail = " ".join("(%d) %s" % (i + 1, p) for i, p in enumerate(problems))
        _deny("This %s deliverable does not comply, so it was not written. %s "
              "Fix the content and Write it again: open exactly with the skill's "
              "Output template (no preamble, recap, or intro before it), keep the "
              "verified-context as internal working (a `Why:` line, never visible "
              "preamble), and use no em dashes. The file is only created once it "
              "passes." % (skill, detail))
        return

    # Scope 2: any markdown file landing in a repo (not a temp scratch, not a
    # vendored/third-party tree). It IS a deliverable, so it must clear the shared
    # form rules even though it skipped the /tmp draft path.
    if path.endswith(".md") and not _is_temp(path) and not _skip_md(path):
        problems = _form_problems(co, content, full_write)
        if not problems:
            return
        detail = " ".join("(%d) %s" % (i + 1, p) for i, p in enumerate(problems))
        _deny("This markdown file lands in a repo, so it is a deliverable and must "
              "clear the form gate before it is written; it does not, so it was not "
              "written. %s Fix it and Write again: no em dashes, English only, "
              "well-formed markdown. Every deliverable passes this gate, whether it "
              "goes through the /tmp draft or straight to the repo." % detail)
        return


if __name__ == "__main__":
    main()
