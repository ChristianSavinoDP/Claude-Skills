#!/usr/bin/env python3
"""PreToolUse hook: mechanically block writing a non-compliant deliverable.

This is the one enforcement point that does NOT depend on the model's discretion
and is NOT the unreliable Stop event. PreToolUse runs on the critical path of the
Write/Edit tool: the harness invokes it before the file is written, and a "deny"
decision actually prevents the write. So a malformed deliverable file cannot be
created, the model is shown why, and it retries until the content passes.

Scope: only files whose name marks them as a deliverable draft, by convention
  /tmp/keru-deliverable-<skill>.md            (e.g. keru-deliverable-pr-review.md)
  /tmp/keru-deliverable-<skill>-<id>.md       (e.g. keru-deliverable-pr-review-3254.md)
The optional <id> (a Jira key or PR number) keeps concurrent or sequential
deliverables of the same skill from overwriting each other. The <skill> selects
which Output contract to validate against; since skill names contain hyphens
(pr-review, addressing-pr-comments), the skill is resolved against the known set,
not split on a hyphen. Any other Write/Edit is ignored (the hook stays silent).

Validation reuses keru-check-output's checkers (one source of truth). Fail-open
on anything it cannot parse, so it never wedges a normal write: it only ever
denies a deliverable file it can positively prove is non-compliant.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Deliverable draft filename convention: keru-deliverable-<skill>[-<id>].md
# The suffix may carry a Jira key or PR number (uppercase, digits) to keep
# deliverables from overwriting each other, so it is NOT restricted to [a-z-].
# The skill is resolved from the captured stem against the known checker set.
NAME_RE = re.compile(r"keru-deliverable-(.+)\.md$")


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


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return  # unparseable input: allow (fail-open)
    if data.get("tool_name") not in ("Write", "Edit"):
        return
    tool_input = data.get("tool_input") or {}
    path = tool_input.get("file_path") or ""
    m = NAME_RE.search(os.path.basename(path))
    if not m:
        return  # not a deliverable draft file: not ours, allow

    co = _load_checkers()
    if co is None:
        return  # cannot validate: allow rather than wedge
    skill = _resolve_skill(m.group(1), co.CHECKERS)
    if skill is None:
        return  # stem names no known skill: allow

    # The content being written. Write gives the full content; Edit gives the
    # post-edit string. For Edit we only have new_string (the inserted text), not
    # the whole file, so we validate that; for a deliverable the model should
    # Write the whole file, which is the gated path.
    content = tool_input.get("content")
    if content is None:
        content = tool_input.get("new_string")
    if not isinstance(content, str) or not content.strip():
        return  # nothing to check

    problems = []
    verdict, reason = co.CHECKERS[skill](content)
    if verdict == "violation":
        problems.append(reason)
    elif verdict == "skip":
        problems.append("this does not read as a %s deliverable (its opening or "
                        "structure does not match the skill's Output)." % skill)
    em = co.check_no_em_dash(content)
    if em[0] == "violation":
        problems.append(em[1])
    lang = co.check_english(content)
    if lang[0] == "violation":
        problems.append(lang[1])

    if not problems:
        return  # compliant: allow the write

    detail = " ".join("(%d) %s" % (i + 1, p) for i, p in enumerate(problems))
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "This %s deliverable does not comply, so it was not written. %s "
                "Fix the content and Write it again: open exactly with the skill's "
                "Output template (no preamble, recap, or intro before it), keep the "
                "verified-context as internal working (a `Why:` line, never visible "
                "preamble), and use no em dashes. The file is only created once it "
                "passes." % (skill, detail)
            ),
        }
    }))


if __name__ == "__main__":
    main()
