#!/usr/bin/env python3
"""PreToolUse hook: mechanically block writing a non-compliant deliverable.

This is the one enforcement point that does NOT depend on the model's discretion
and is NOT the unreliable Stop event. PreToolUse runs on the critical path of the
Write/Edit tool: the harness invokes it before the file is written, and a "deny"
decision actually prevents the write. So a malformed deliverable file cannot be
created, the model is shown why, and it retries until the content passes.

Scope: only files whose name marks them as a deliverable draft, by convention
  /tmp/keru-deliverable-<skill>.md   (e.g. /tmp/keru-deliverable-pr-review.md)
The <skill> in the name selects which Output contract to validate against. Any
other Write/Edit is ignored (the hook allows it by staying silent).

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

# Deliverable draft filename convention: keru-deliverable-<skill>.md
NAME_RE = re.compile(r"keru-deliverable-([a-z-]+)\.md$")


def _load_checkers():
    for path in (os.path.join(HERE, "keru-check-output.py"),
                 os.path.join(HERE, "keru-check-output"),
                 os.path.expanduser("~/.local/bin/keru-check-output")):
        if os.path.isfile(path):
            try:
                spec = importlib.util.spec_from_file_location("keru_check_output", path)
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
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
    m = NAME_RE.search(path)
    if not m:
        return  # not a deliverable draft file: not ours, allow

    co = _load_checkers()
    if co is None:
        return  # cannot validate: allow rather than wedge
    skill = co._norm(m.group(1))
    if skill not in co.CHECKERS:
        return  # unknown skill in the name: allow

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
