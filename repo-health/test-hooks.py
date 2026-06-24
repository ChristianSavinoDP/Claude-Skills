#!/usr/bin/env python3
"""Behavioral tests for the repo's Bash/Stop hooks, run by repo-health.

These guard the hooks' LOGIC, not just their existence: the kind of regression
docs/permissions/installer checks cannot see. A hook can be installed, named
right, and documented, yet reason about a stale assumption (e.g. that a
`/keru-*` slash command emits a `Skill` tool_use). That class of bug shows up
only by exercising the hook on real inputs, which is what this does.

Tests target the scripts in scripts/ (the source of truth), not the installed
~/.local/bin copies. Exit 0 if all pass, 1 otherwise.
"""
import json
import os
import subprocess
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SAFE_READ = os.path.join(REPO, "scripts", "keru-safe-read.py")
REQUIRE_SKILL = os.path.join(REPO, "scripts", "keru-require-skill.py")
CHECK_OUTPUT = os.path.join(REPO, "scripts", "keru-check-output.py")

results = []


def check(name, ok):
    results.append((name, bool(ok)))


# --- keru-safe-read ----------------------------------------------------------

def sr_decision(cmd):
    """Return 'allow' or 'DEFER' for a Bash command under safe-read."""
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    out = subprocess.run([sys.executable, SAFE_READ], input=stdin,
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "DEFER"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "DEFER"


def test_safe_read():
    allow = [
        ("grep pipeline", 'grep -rn "foo" . | head'),
        ("git --no-pager diff", "git --no-pager diff --stat"),
        ("gh pr view", "gh pr view 123 --repo o/r --json title"),
        ("gh api GET", "gh api repos/o/r/rulesets --jq '.[].name'"),
        ("jira issue view", "jira issue view DBI-1 --plain"),
        ("go tool bare", "go tool | grep templ"),
        ("go get", "go get -tool github.com/a/b@v1"),
        ("pip list piped", "pip list | grep -i boto"),
        ("python -m py_compile", "python -m py_compile src/x.py"),
        (".venv python py_compile", ".venv/bin/python -m py_compile a.py"),
    ]
    for name, cmd in allow:
        check("safe-read allows: " + name, sr_decision(cmd) == "allow")

    defer = [
        ("git push", "git push origin main"),
        ("rm -rf outside", "rm -rf /tmp/whatever"),
        ("go run remote@version", "go run github.com/a/b@latest fmt ."),
        ("go tool <name>", "go tool templ fmt ."),
        ("pip install", "pip install requests"),
        ("python -c arbitrary", 'python -c "import os"'),
        ("python script", "python main.py"),
        ("python -m http.server", "python -m http.server"),
        ("py_compile && make", "python -m py_compile a.py && make build"),
        ("gh api POST", "gh api -X POST repos/o/r/issues"),
    ]
    for name, cmd in defer:
        check("safe-read defers: " + name, sr_decision(cmd) == "DEFER")


# --- keru-require-skill ------------------------------------------------------

def rs_block(user_text, invoked, stop_hook_active=False, trailing=None):
    """True if the Stop hook blocks for this turn.

    `trailing` is an optional list of extra raw records appended AFTER the human
    prompt and the Skill invocations, to simulate injected isMeta/non-human user
    records (skill body, hook feedback) that must NOT be read as the prompt."""
    recs = [{"type": "user", "message": {"content": user_text}}]
    for s in invoked:
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": s}}]}})
    for extra in (trailing or []):
        recs.append(extra)
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    stdin = json.dumps({"transcript_path": path,
                        "stop_hook_active": stop_hook_active})
    out = subprocess.run([sys.executable, REQUIRE_SKILL], input=stdin,
                         capture_output=True, text=True).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_require_skill():
    slash = ("<command-name>/keru-pr-description</command-name>\n"
             "Write the PR description.\n"
             "Use the keru-gather-context skill to gather the ticket.")
    # The core regression (DBI-1470): a slash-command skill needs no Skill tool.
    check("slash command satisfies (no Skill tool, no block)",
          not rs_block(slash, []))
    check("slash command satisfies even if only gather-context invoked",
          not rs_block(slash, ["keru-gather-context"]))
    check("bare /keru-* line satisfies",
          not rs_block("/keru-addressing-pr-comments\nhandle these", []))
    # Namespace: invoked keru-pr-review satisfies a requested pr-review.
    check("keru- wrapper invocation satisfies bare request",
          not rs_block("use the pr review skill", ["keru-pr-review"]))
    # The value case: a prose request ignored entirely still blocks once.
    check("prose 'use the X skill' not invoked -> blocks once",
          rs_block("recorda usar el skill de escribir ticket", []))
    # ...but never twice (loop cap).
    check("stop_hook_active caps at one block",
          not rs_block("recorda usar el skill de escribir ticket", [],
                       stop_hook_active=True))
    # No skill mentioned -> never blocks.
    check("no skill request -> no block",
          not rs_block("just summarize the diff", []))

    # isMeta records must NOT be read as the user's prompt. These are the
    # false-positive sources: the injected SKILL.md body, the "Base directory"
    # preamble, and the hook's own re-injected feedback. A plain human prompt
    # ("gracias, listo") with any of these trailing must NOT block.
    skill_body = {"type": "user", "isMeta": True, "message": {"content":
        "Implement: \n\nUse the `gather-context` skill to gather it and its chain."}}
    base_dir = {"type": "user", "isMeta": True, "message": {"content":
        "Base directory for this skill: /x/skills/keru-writing-code\n# Writing Code"}}
    hook_fb = {"type": "user", "isMeta": True, "message": {"content":
        "Stop hook feedback:\nYou were explicitly asked to use the `writing-code` skill this turn"}}
    check("isMeta skill-body not read as prompt -> no block",
          not rs_block("gracias, listo", [], trailing=[skill_body]))
    check("isMeta base-directory not read as prompt -> no block",
          not rs_block("gracias, listo", [], trailing=[base_dir]))
    check("isMeta hook-feedback does not re-trigger the hook -> no block",
          not rs_block("gracias, listo", [], trailing=[hook_fb]))
    # Defense in depth: even if the feedback text arrived as a real (non-meta)
    # prompt, requested_skill ignores its own feedback string.
    check("hook feedback text as non-meta prompt still does not block",
          not rs_block("Stop hook feedback:\nYou were explicitly asked to use "
                       "the `writing-code` skill this turn", []))

    # Every skill id in the hook's SKILLS table must exist on disk.
    check("hook skill ids match skills/ on disk", _skill_ids_exist())


def _skill_ids_exist():
    """The canonical ids in keru-require-skill's SKILLS must be real skill dirs."""
    import re
    src = open(REQUIRE_SKILL, encoding="utf-8").read()
    # Grab the first string in each ("id", [..]) tuple of the SKILLS list.
    ids = re.findall(r'\(\s*"(keru-[a-z-]+)"\s*,\s*\[', src)
    skills_dir = os.path.join(REPO, "skills")
    if not ids:
        return False
    return all(os.path.isdir(os.path.join(skills_dir, i)) for i in ids)


# --- keru-check-output -------------------------------------------------------

def co_block(slash_cmd, assistant_msg, stop_hook_active=False):
    """True if the output gate blocks. Simulates a turn: a /keru-* prompt, then
    an assistant message (the delivered text)."""
    recs = [
        {"type": "user", "message": {"content":
            "<command-name>/%s</command-name>\ndo it" % slash_cmd}},
        {"type": "assistant", "message": {"content":
            [{"type": "text", "text": assistant_msg}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    stdin = json.dumps({"transcript_path": path,
                        "stop_hook_active": stop_hook_active})
    out = subprocess.run([sys.executable, CHECK_OUTPUT], input=stdin,
                         capture_output=True, text=True).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_check_output():
    # pr-review: compliant verdict-first opening passes; decorated/prose opening blocks.
    good_review = "Approve\n\n### Nits\n`a.go:1`\n```go\nx\n```\nWhy: nit."
    check("pr-review verdict-first -> no block", not co_block("keru-pr-review", good_review))
    # The canonical "Verdict: <word>" label opens cleanly (the real review of DBI today).
    check("pr-review 'Verdict: Comment' label -> no block",
          not co_block("keru-pr-review", "Verdict: Comment\n\n### Questions\n`a.go:1`\nComment (paste into the PR):\ntext\nWhy: y."))
    check("pr-review bare 'Comment' still ok -> no block",
          not co_block("keru-pr-review", "Comment\n\n### Questions\n`a.go:1`\nWhy: y."))
    # But the label must not carry decoration after the word.
    check("pr-review 'Verdict: Comment (decorated)' -> BLOCK",
          co_block("keru-pr-review", "Verdict: Comment (one question on paging)\n\n### Questions\n`a.go:1`"))
    check("pr-review decorated verdict -> BLOCK",
          co_block("keru-pr-review", "`Request changes` (one blocking question)\n\n### Blocking\n`a.go:1`"))
    check("pr-review prose intro before heading -> BLOCK",
          co_block("keru-pr-review",
                   "The find-and-replace is clean. The one issue is behavioral.\n\n### Blocking\n`a.go:1`"))
    # A clarifying question (not the deliverable) must NOT block.
    check("pr-review: asking for the PR number -> no block",
          not co_block("keru-pr-review", "What PR number should I review?"))

    # writing-tickets: title-first passes; prose intro blocks.
    good_ticket = "**Fix the thing**\n\nProblem.\n\n### Acceptance Criteria\n- x"
    check("ticket title-first -> no block", not co_block("keru-writing-tickets", good_ticket))
    check("ticket prose intro -> BLOCK",
          co_block("keru-writing-tickets",
                   "Here is the ticket you asked for:\n\n**Fix it**\n\n### Acceptance Criteria\n- x"))
    check("ticket: asking which type -> no block",
          not co_block("keru-writing-tickets", "Is this a bug or a feature ticket?"))

    # pr-description: title block first passes; recap intro blocks.
    good_desc = "**feat(<scope>): [DBI-1] do x**\n\n````\n## What Changed\nstuff\n````"
    check("pr-desc title-first -> no block", not co_block("keru-pr-description", good_desc))
    check("pr-desc prose intro -> BLOCK",
          co_block("keru-pr-description",
                   "Based on the branch work, here is the description.\n\n## What Changed\nstuff"))

    # investigation: heading-first passes; generic intro blocks.
    good_inv = "## How onboarding works\n\nThe consumer registers via...\n\n## Sources\n- x"
    check("investigation heading-first -> no block", not co_block("keru-investigation", good_inv))
    check("investigation generic intro -> BLOCK",
          co_block("keru-investigation",
                   "I investigated the Kafka onboarding. Here is what I found.\n\n## Findings\ntext"))

    # addressing-pr-comments: bold-header block-first passes; summary intro blocks.
    good_addr = "**a.go:55**\n\nValid; applied a root-cause rewrite.\n\n**b.md:10**\n\nPushed back."
    check("addressing bold-block-first -> no block", not co_block("keru-addressing-pr-comments", good_addr))
    check("addressing bare path:line (not bold) -> BLOCK",
          co_block("keru-addressing-pr-comments", "`a.go:55`\n\nApplied a rewrite."))
    check("addressing summary intro -> BLOCK",
          co_block("keru-addressing-pr-comments",
                   "I reviewed both Copilot comments. Here is how I handled them.\n\n**a.go:55**\nApplied."))

    # bot-triage: bold service header first passes; intro blocks.
    good_bot = "**xapi**\nPRs:\n- bump x — http://u\nSecurity (no fixing PR): none"
    check("bot-triage service-header-first -> no block", not co_block("keru-bot-triage", good_bot))
    check("bot-triage intro before service -> BLOCK",
          co_block("keru-bot-triage",
                   "I triaged all 3 repos. Here is the rundown.\n\n**xapi**\nPRs:\n- bump x — http://u"))

    # The loop cap holds for this hook too.
    check("check-output stop_hook_active cap",
          not co_block("keru-pr-review", "Prose intro that would otherwise block.\n### Blocking\n`a.go:1`",
                       stop_hook_active=True))

    # NON-DELIVERABLE turns must never be gated: a turn that asks for missing
    # context or waits on a design decision is not the deliverable, so the gate
    # must stay silent. These are the false-positives the gate must not produce.
    missing_context = [
        ("keru-pr-review", "I need the PR number or link to review. Which PR is this?"),
        ("keru-pr-description", "I can't write this without the ticket. What's the Jira key?"),
        ("keru-writing-tickets", "Before I draft: is this a bug, feature, or investigation ticket?"),
        ("keru-investigation", "I couldn't find the investigation doc referenced in DBI-1. Point me to it?"),
        ("keru-bot-triage", "No repo list is saved. Which repos should I triage?"),
        ("keru-addressing-pr-comments", "Which PR are these comments on? I need the link first."),
    ]
    for slash, msg in missing_context:
        check("non-deliverable (missing context) not gated: " + slash,
              not co_block(slash, msg))

    design_decision = [
        ("keru-pr-description",
         "There are two ways to frame this PR depending on whether the opsgenie "
         "removal is intentional. Can you confirm before I write it?"),
        ("keru-addressing-pr-comments",
         "One comment hinges on whether the tier is critical. How do you want me to respond?"),
        ("keru-writing-tickets",
         "This could be one ticket or split into three. Which scope do you want?"),
    ]
    for slash, msg in design_decision:
        check("non-deliverable (design decision pending) not gated: " + slash,
              not co_block(slash, msg))


def main():
    test_safe_read()
    test_require_skill()
    test_check_output()
    failed = [n for n, ok in results if not ok]
    print("=== hook tests: %d run, %d failed ===" % (len(results), len(failed)))
    for n, ok in results:
        if not ok:
            print("  FAIL: " + n)
    if failed:
        sys.exit(1)
    print("ok: all hook behavioral tests pass")


if __name__ == "__main__":
    main()
