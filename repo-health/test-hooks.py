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
HOOKS = os.path.join(REPO, "scripts", "hooks")
SAFE_READ = os.path.join(HOOKS, "keru-safe-read.py")
REQUIRE_SKILL = os.path.join(HOOKS, "keru-require-skill.py")
CHECK_OUTPUT = os.path.join(HOOKS, "keru-check-output.py")
JUDGE_OUTPUT = os.path.join(HOOKS, "keru-judge-output.py")
GATE = os.path.join(HOOKS, "keru-gate-deliverable.py")

results = []


def check(name, ok):
    results.append((name, bool(ok)))


# --- keru-safe-read ----------------------------------------------------------

def sr_decision(cmd):
    """Decision for a Bash command under safe-read, with the model slow-path
    neutralized (dp hidden via empty HOME/PATH) so the test is deterministic and
    offline: the fast static path still returns 'allow' for provably-safe
    commands, and anything else hits the slow path which fail-safes to 'ask'.
    Returns 'allow', 'ask', or 'NONE' (no output)."""
    env = dict(os.environ)
    env["HOME"] = "/nonexistent"
    env["PATH"] = "/usr/bin:/bin"   # no `dp` here -> slow path fail-safes to ask
    stdin = json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}})
    out = subprocess.run([sys.executable, SAFE_READ], input=stdin,
                         capture_output=True, text=True, env=env).stdout.strip()
    if not out:
        return "NONE"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "NONE"


def test_safe_read():
    # FAST PATH: provably read-only/local-reversible -> instant allow, no model.
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
        check("safe-read fast-allows: " + name, sr_decision(cmd) == "allow")

    # SLOW PATH (model hidden -> fail-safe ASK): not provably safe by static
    # parsing. With dp present these get a model verdict; with it absent they must
    # ASK, never silently allow. The key guarantee: an unknown command is never
    # auto-allowed without a positive judgment.
    ask = [
        ("git push", "git push origin main"),
        ("rm -rf outside", "rm -rf /tmp/whatever"),
        ("go run remote@version", "go run github.com/a/b@latest fmt ."),
        ("go tool <name>", "go tool templ fmt ."),
        ("pip install", "pip install requests"),
        ("python script", "python main.py"),
        ("python -m http.server", "python -m http.server"),
        ("docker ps (unknown to parser)", "docker ps -a"),
        ("py_compile && make", "python -m py_compile a.py && make build"),
        ("gh api POST", "gh api -X POST repos/o/r/issues"),
    ]
    for name, cmd in ask:
        check("safe-read slow-asks (model absent): " + name, sr_decision(cmd) == "ask")

    # Inline interpreters are NOT safe-read's job (a separate block hook denies
    # them); safe-read should not fast-allow `python -c`.
    check("safe-read does not fast-allow python -c", sr_decision('python -c "import os"') != "allow")


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


def co_block_noskill(user_text, assistant_msg):
    """Like co_block but the user prompt is plain text with NO /keru-* command and
    no Skill tool_use: exercises detection of a deliverable produced WITHOUT its
    skill ever being loaded (the audit case)."""
    recs = [
        {"type": "user", "message": {"content": user_text}},
        {"type": "assistant", "message": {"content":
            [{"type": "text", "text": assistant_msg}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    out = subprocess.run([sys.executable, CHECK_OUTPUT],
                         input=json.dumps({"transcript_path": path, "stop_hook_active": False}),
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

    # bot-triage: bold service header first passes; intro blocks. (Links use ':'
    # not an em dash, matching the no-em-dash rule the template now follows.)
    good_bot = "**xapi**\nPRs:\n- bump x: http://u\nSecurity (no fixing PR): none"
    check("bot-triage service-header-first -> no block", not co_block("keru-bot-triage", good_bot))
    check("bot-triage intro before service -> BLOCK",
          co_block("keru-bot-triage",
                   "I triaged all 3 repos. Here is the rundown.\n\n**xapi**\nPRs:\n- bump x: http://u"))

    # The loop cap holds for this hook too.
    check("check-output stop_hook_active cap",
          not co_block("keru-pr-review", "Prose intro that would otherwise block.\n### Blocking\n`a.go:1`",
                       stop_hook_active=True))

    # Em-dash rule (Playbook): a well-formed deliverable with an em dash in prose
    # is still blocked; em dashes inside code/diffs are allowed; clean passes.
    em_review = "Approve\n\n### Nits\n`a.go:1`\nWhy: this is fine — but the dash is not."
    check("em dash in deliverable prose -> BLOCK", co_block("keru-pr-review", em_review))
    em_in_code = ("Approve\n\n### Nits\n`a.go:1`\n```go\nx := a — b // pasted diff\n```\n"
                  "Why: the dash above is inside code, allowed.")
    check("em dash only inside code fence (```go) -> no block", not co_block("keru-pr-review", em_in_code))
    em_in_diff = ("Comment\n\n### Nits\n`a.go:1`\n```diff\n- old — value\n```\nWhy: nit.")
    check("em dash inside ```diff -> no block", not co_block("keru-pr-review", em_in_diff))
    em_ticket = "**Fix the thing**\n\nProblem — with a dash.\n\n### Acceptance Criteria\n- x"
    check("em dash in ticket prose -> BLOCK", co_block("keru-writing-tickets", em_ticket))
    # The audit's real case (caught live by /keru-pr-review): an em dash inside the
    # "Comment (paste into the PR)" block, which is FENCED PROSE that goes verbatim
    # to GitHub. A bare (no-language) fence is prose, so the rule applies there.
    em_paste = ("Verdict: Comment\n\n### Questions\n`config.go:55`\n\n"
                "Comment (paste into the PR):\n\n`````\n"
                "This drops the retry these writes rely on — the lag surfaces as NotFound.\n"
                "`````\n\nWhy: AC asks to confirm.")
    check("em dash inside paste-into-PR block (fenced prose) -> BLOCK",
          co_block("keru-pr-review", em_paste))
    # A malformed-opening message is still caught on the opening first, regardless.
    check("clean deliverable, no dash -> no block",
          not co_block("keru-pr-review", "Approve\n\n### Nits\n`a.go:1`\nWhy: clean, no dash here."))

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

    # Deliverable produced WITHOUT loading its skill (the audit case): a strong
    # structural fingerprint still gates it. No /keru-* command, no Skill tool.
    free = "Logan left a comment on config.go:55, validate again"
    # addressing: two bold path:line blocks with a prose intro -> caught.
    check("no-skill addressing (prose + 2 blocks) -> BLOCK",
          co_block_noskill(free, "Reviewed both.\n\n**a.go:55**\n\nApplied.\n\n**b.go:10**\n\nPushed back."))
    check("no-skill addressing well-formed (2 blocks) -> no block",
          not co_block_noskill(free, "**a.go:55**\n\nApplied.\n\n**b.go:10**\n\nPushed back."))
    # ticket WELL-FORMED but no skill loaded: bold title + AC fingerprints it, so
    # an em dash or other body issue would still be checked. (Opening is fine here.)
    check("no-skill ticket well-formed (title + ### AC) -> no block",
          not co_block_noskill(free, "**Fix the thing**\n\nProblem.\n\n### Acceptance Criteria\n- x"))
    # Accepted limit: a ticket that OPENS with prose and was produced with no
    # /keru-* command has no strong fingerprint (the title-first form is the
    # fingerprint), so it is not gated. Firing on a bare '### Acceptance Criteria'
    # in free chat would false-positive. With the slash command it IS caught
    # (see test_check_output's co_block cases).
    check("no-skill ticket prose-opening -> not gated (accepted limit)",
          not co_block_noskill(free, "Here is the ticket:\n\n**T**\n\n### Acceptance Criteria\n- x"))
    # Plain chat must NOT be gated even if it mentions a path:line or a heading.
    check("no-skill plain chat (one path mention) -> no block",
          not co_block_noskill(free, "The issue is in config.go:55, middleware.Timeout cancels context."))
    check("no-skill single bold block (too weak) -> no block",
          not co_block_noskill(free, "**a.go:55**\n\nJust one note, not the deliverable."))
    # Known limit (chosen): a review produced without its skill is only caught
    # when well-formed; a prose-opening review without a verdict is NOT gated,
    # because firing on a bare '### Questions' would false-positive in chat.
    check("no-skill review prose-opening -> not gated (accepted limit)",
          not co_block_noskill(free, "The change looks clean overall.\n\n### Questions\n`a.go:1`"))


def judge_blocks(slash_cmd, assistant_msg):
    """Run keru-judge-output with `dp` made unavailable (empty PATH) so no real
    model call happens. Tests the GATING logic only: the judge must exit silent
    (no block) for anything that should not reach the model, and fail-open when
    `dp` is missing. A live judgment test is too slow/costly for repo-health."""
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
    env = dict(os.environ)
    env["PATH"] = "/nonexistent"      # hide `dp`
    env["HOME"] = "/nonexistent"      # hide the mise fallback path too
    out = subprocess.run([sys.executable, JUDGE_OUTPUT],
                         input=json.dumps({"transcript_path": path, "stop_hook_active": False}),
                         capture_output=True, text=True, env=env).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_judge_gating():
    # Chat / non-deliverable turn must not reach the judge and must not block.
    check("judge: chat turn -> no block (no model call)",
          not judge_blocks("keru-pr-review", "Sure, I'll review the PR shortly."))
    check("judge: clarifying question -> no block",
          not judge_blocks("keru-pr-review", "Which PR should I review?"))
    # A deliverable-shaped turn would reach the model, but with `dp` hidden the
    # judge fails open (no block) rather than wedging the turn.
    check("judge: fail-open when dp unavailable -> no block",
          not judge_blocks("keru-pr-review", "Verdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # investigation is excluded from the judge (it has its own adversarial review),
    # so a well-formed investigation never reaches the judge: must not block even
    # though dp is hidden (proves it short-circuited before the model call).
    check("judge: investigation excluded -> no block",
          not judge_blocks("keru-investigation", "## Findings\n\nThe consumer registers via X.\n\n## Sources\n- a"))
    # The judged set must match the intended four-plus-bot-triage list exactly.
    import importlib.util as _ilu
    _s = _ilu.spec_from_file_location("kjo", JUDGE_OUTPUT)
    _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)
    check("judge: JUDGED_SKILLS is exactly the intended set",
          _m.JUDGED_SKILLS == {"pr-review", "writing-tickets", "pr-description",
                               "addressing-pr-comments", "bot-triage"})


def gate_denies(file_path, content, tool="Write"):
    """Run the PreToolUse Write/Edit gate; True if it denies the write."""
    key = "content" if tool == "Write" else "new_string"
    payload = {"tool_name": tool, "tool_input": {"file_path": file_path, key: content}}
    out = subprocess.run([sys.executable, GATE], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return False
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    except Exception:
        return False


def test_write_gate():
    P = "/tmp/keru-deliverable-pr-review.md"
    # Malformed deliverable to the gated path -> DENY (file never written).
    check("write-gate: malformed review -> deny",
          gate_denies(P, "Verified CI. Now:\n\nVerdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # Compliant deliverable -> allowed (no deny).
    check("write-gate: valid review -> allow",
          not gate_denies(P, "Verdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # Em dash in the gated file -> deny.
    check("write-gate: em-dash review -> deny",
          gate_denies(P, "Verdict: Comment\n\n### Nits\n`a.go:1`\nComment (paste into the PR):\n`````\nreuse it — please\n`````\nWhy: x."))
    # A NON-deliverable file (normal code) is never gated, even with an em dash.
    check("write-gate: normal code file -> allow",
          not gate_denies("/Users/x/main.go", "package main // a — b"))
    # Ticket path enforces the ticket contract.
    check("write-gate: malformed ticket -> deny",
          gate_denies("/tmp/keru-deliverable-writing-tickets.md",
                      "Here is the ticket:\n\n**T**\n\n### Acceptance Criteria\n- x"))
    check("write-gate: valid ticket -> allow",
          not gate_denies("/tmp/keru-deliverable-writing-tickets.md",
                          "**Fix it**\n\nProblem.\n\n### Acceptance Criteria\n- x"))
    # Edit tool on a deliverable file is gated too (new_string validated).
    check("write-gate: Edit malformed review -> deny",
          gate_denies(P, "Intro prose.\n\nVerdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok.", tool="Edit"))


def main():
    test_safe_read()
    test_require_skill()
    test_check_output()
    test_judge_gating()
    test_write_gate()
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
