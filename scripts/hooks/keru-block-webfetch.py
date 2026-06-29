#!/usr/bin/env python3
"""PreToolUse hook: deny WebFetch to authenticated systems (Jira, GitHub).

Reads the tool-call JSON on stdin. If WebFetch targets a Jira or GitHub URL,
returns a PreToolUse "deny" decision telling Claude to use the `jira`/`gh` CLI
instead. WebFetch cannot read authenticated content anyway, and the CLI is the
right tool. Any other URL is left alone (no decision, normal flow).
"""
import json
import re
import sys

# Hosts that must go through a CLI, not WebFetch.
BLOCKED = re.compile(r"(^|\.)(atlassian\.net|jira\.[^/]+|github\.com)(/|$|:)", re.I)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    if data.get("tool_name") != "WebFetch":
        return
    url = (data.get("tool_input") or {}).get("url", "")
    if not isinstance(url, str) or not url:
        return
    # Match against the host portion of the URL.
    host = re.sub(r"^[a-z]+://", "", url, flags=re.I).split("/")[0].split("?")[0]
    if not BLOCKED.search(host):
        return
    tool = "jira (jira issue view <KEY>)" if "atlassian" in host.lower() or "jira" in host.lower() \
        else "gh (gh pr view / gh api)"
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "Do not WebFetch %s; it is authenticated and unreadable that way. "
                "Use the %s CLI instead: extract the id from the URL and run the command." % (host, tool)
            ),
        }
    }))


if __name__ == "__main__":
    main()
