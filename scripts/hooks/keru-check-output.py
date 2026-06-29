#!/usr/bin/env python3
"""Stop hook: enforce a skill's Output contract mechanically.

Text cannot force output format: the playbook rule and the skill's own "Output"
spec were both ignored across turns (see output-compliance-audit.md). A checklist
that says "verify your format before sending" is more of the same. This hook makes
the format a gate: it reads the delivered message and blocks once if it violates
the governing deliverable skill's machine-checkable opening invariant.

Every deliverable skill defines a concrete opening in its Output section, so all
are gated on that opening:
  - pr-review: first visible line is EXACTLY the verdict
    (`Approve` / `Request changes` / `Comment`), nothing appended.
  - writing-tickets: first visible line is the bold title `**...**`.
  - pr-description: opens with the bold title block `**...**`.
  - investigation: opens with a markdown heading (`#`/`##`), no generic intro.
  - addressing-pr-comments: opens with the first comment block (a `path:line`
    ref or a heading), not an intro/summary sentence.
The hook checks only the OPENING (the one part with a hard, machine-checkable
invariant) and only when the message clearly IS the deliverable, so trailing
content and genuine non-deliverable replies (a clarifying question) are left
alone.

Bounded and fail-open like keru-require-skill: honors stop_hook_active (caps at
one block per turn), and only blocks when the message clearly IS the deliverable
but malformed; a clarifying question or pushback (which does not look like the
deliverable) is left alone. Only the OPENING is checked, so legitimate trailing
content (an offer to post, a note) after a correct template is fine.
"""
import json
import re
import sys

# A verdict is the ENTIRE first line: the bare word, optionally backtick-wrapped,
# optionally with a leading `Verdict:` label (which reads better and is what good
# reviews use). Nothing else may follow on that line (no parenthetical decoration).
VERDICT_FULL = re.compile(r"^(?:#{1,6}\s*)?(?:\*{0,2}Verdict\*{0,2}:\s*)?`?(Approve|Request changes|Comment)`?$", re.I)
# "Starts like a verdict" (verdict word, or a `Verdict:` label, at the front),
# used to tell a malformed review opening ("Verdict: Comment (one question...)")
# from a non-review reply.
VERDICT_HEAD = re.compile(r"^(?:#{1,6}\s*)?(?:\*{0,2}Verdict\*{0,2}:\s*)?`?(Approve|Request changes|Comment)\b", re.I)
REVIEW_HEADING = re.compile(r"(?m)^###\s+(Blocking|Nits|Questions)\b")
TICKET_HEADING = re.compile(r"(?m)^###\s+Acceptance Criteria\b")


def first_visible_line(msg):
    for ln in msg.splitlines():
        if ln.strip():
            return ln.strip()
    return ""


def check_pr_review(msg):
    """('ok'|'violation'|'skip', reason)."""
    first = first_visible_line(msg)
    if not first:
        return "skip", ""
    looks_like_review = bool(REVIEW_HEADING.search(msg)) or bool(VERDICT_HEAD.match(first))
    if not looks_like_review:
        return "skip", ""  # not a review delivery (e.g. asking for the PR number)
    if VERDICT_FULL.match(first):
        return "ok", ""
    return ("violation",
            "the pr-review Output must OPEN with a one-line verdict that is exactly "
            "`Approve`, `Request changes`, or `Comment` (no parenthetical, no prose "
            "before or appended). Your first line was: %r" % first[:100])


HEADING = re.compile(r"^#{1,6}\s")
HEADING_ANY = re.compile(r"(?m)^#{1,6}\s")
# A bold comment header anywhere: `**a.go:55**` or any `**...**` line. Used to
# tell "this is the addressing deliverable" from a prose reply, regardless of
# whether that bold header sits on the first line or a later one.
BOLD_HEADER_ANY = re.compile(r"(?m)^\*\*.+\*\*\s*$")
PATHLINE_REF_ANY = re.compile(r"[\w./-]+\.\w+:\d+")  # a path:line ref anywhere


def opens_bold(first):
    """The shared invariant: the deliverable opens with a bold header `**...**`."""
    return first.startswith("**")


def check_bold_open(skill, msg, looks_like):
    """Shared checker for the deliverables whose Output is a list of blocks, each
    opening with a `**bold**` header: writing-tickets (title), pr-description
    (title), bot-triage (service), addressing-pr-comments (comment ref). They are
    the same contract, so they share one check. `looks_like` decides whether this
    message is that deliverable at all (vs a clarifying question), so a non-answer
    is left alone."""
    first = first_visible_line(msg)
    if not first or not looks_like(msg, first):
        return "skip", ""
    if opens_bold(first):
        return "ok", ""
    return ("violation",
            "the %s Output opens with a bold header line `**...**`, with nothing "
            "before it (no intro, recap, or summary sentence). Your first line "
            "was: %r" % (skill, first[:100]))


# Per-skill "is this actually the deliverable?" signals. Each looks for a
# structural marker the deliverable always has, so a clarifying question (which
# lacks it) is skipped rather than blocked.
TICKET_AC = re.compile(r"(?m)^###\s+Acceptance Criteria\b")
PRDESC_BODY = re.compile(r"(?m)^.*\b(What Changed|How to Test)\b")
# A PR-description title line: `<type>(<scope>): ...`, optionally bold or behind
# a markdown heading. Used to recognize the opening of a pr-description.
PRDESC_TITLE_HEAD = re.compile(r"^(?:#{1,6}\s*)?\**\s*`?(feat|fix|chore|docs|refactor|test|perf|build|ci)\(", re.I)


def check_pr_review(msg):
    """('ok'|'violation'|'skip', reason)."""
    first = first_visible_line(msg)
    if not first:
        return "skip", ""
    looks_like_review = bool(REVIEW_HEADING.search(msg)) or bool(VERDICT_HEAD.match(first))
    if not looks_like_review:
        return "skip", ""  # not a review delivery (e.g. asking for the PR number)
    if VERDICT_FULL.match(first):
        return "ok", ""
    return ("violation",
            "the pr-review Output must OPEN with a one-line verdict that is exactly "
            "`Approve`, `Request changes`, or `Comment` (no parenthetical, no prose "
            "before or appended). Your first line was: %r" % first[:100])


def check_investigation(msg):
    first = first_visible_line(msg)
    if not first:
        return "skip", ""
    # An investigation is a markdown doc; if there is no heading anywhere it is
    # not the deliverable (e.g. a status update), so skip.
    if not HEADING_ANY.search(msg):
        return "skip", ""
    if HEADING.match(first):
        return "ok", ""
    return ("violation",
            "the investigation Output must OPEN with a markdown heading (the first "
            "finding/question), no generic intro before it. Your first line was: "
            "%r" % first[:100])


# Keyed by normalized skill name (no keru- prefix, no namespace).
# The bold-header family shares check_bold_open; pr-review and investigation have
# their own opening invariant (a one-word verdict / a markdown heading).
CHECKERS = {
    "pr-review": check_pr_review,
    "investigation": check_investigation,
    "writing-tickets": lambda m: check_bold_open(
        "writing-tickets", m, lambda msg, first: bool(TICKET_AC.search(msg))),
    "pr-description": lambda m: check_bold_open(
        "pr-description", m, lambda msg, first: bool(PRDESC_BODY.search(msg)) or opens_bold(first)),
    "bot-triage": lambda m: check_bold_open(
        "bot-triage", m, lambda msg, first: ("PRs:" in msg) or ("Security" in msg) or opens_bold(first)),
    "addressing-pr-comments": lambda m: check_bold_open(
        "addressing-pr-comments", m,
        lambda msg, first: bool(BOLD_HEADER_ANY.search(msg)) or bool(PATHLINE_REF_ANY.search(msg)) or opens_bold(first)),
}


def _norm(name):
    base = re.split(r"[/:]", name)[-1]
    return base[len("keru-"):] if base.startswith("keru-") else base


def _records(transcript_path):
    try:
        lines = open(transcript_path, encoding="utf-8").read().splitlines()
    except OSError:
        return []
    out = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except ValueError:
            continue
    return out


def _text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text")
    return ""


def _strip_code(msg):
    """Remove only true CODE from the message before the em-dash check, so a dash
    in a pasted diff/snippet is excused but a dash in PROSE is not, even when that
    prose sits in a fence. The distinction matters: a pr-review's
    "Comment (paste into the PR)" block is fenced prose that goes verbatim to
    GitHub, so an em dash there is the real violation, not an exception.

    A fence is treated as code only when its opening line declares a language
    (```go, ```diff, ...). A bare fence of any length (```, `````) wraps prose
    whose content may contain backticks, like the paste block, so it is left in
    and its prose still checked. Parsed line by line to get fence lengths right
    (a 5-backtick close must not be matched by 3 backticks). Inline `spans` are
    always stripped (short, code)."""
    # Strip inline `spans` per line FIRST (they are short code), but never touch a
    # fence delimiter line (3+ backticks): doing the inline pass on the whole text
    # would treat the backticks that open/close a prose fence as a span and eat the
    # prose between them, which is exactly the paste block we must keep checking.
    def strip_inline(line):
        return line if re.match(r"\s*`{3,}", line) else re.sub(r"`[^`]*`", " ", line)

    out = []
    fence = None        # the exact opening fence string while inside a block
    drop = False        # whether the current block is code (drop) or prose (keep)
    for line in msg.splitlines():
        stripped = line.strip()
        m = re.match(r"(`{3,})(.*)$", stripped)
        if fence is None and m:
            fence = m.group(1)
            drop = bool(m.group(2).strip())   # language tag => code; bare => prose, keep
            continue                          # never keep the delimiter line itself
        if fence is not None:
            if stripped == fence:             # close only on a same-length fence
                fence = None
                drop = False
                continue
            if not drop:
                out.append(strip_inline(line))  # prose inside a bare fence: check it
            continue
        out.append(strip_inline(line))
    return "\n".join(out)


def check_no_em_dash(msg):
    """Playbook 'No em dashes' rule, applied to deliverable prose. Returns
    ('ok'|'violation', reason). Em dashes inside code are ignored."""
    prose = _strip_code(msg)
    if "—" not in prose:  # em dash —
        return "ok", ""
    # Show a little context around the first offending em dash.
    idx = prose.index("—")
    snippet = prose[max(0, idx - 30):idx + 30].replace("\n", " ").strip()
    return ("violation",
            "it uses an em dash (the Playbook forbids them: use commas, "
            "semicolons, colons, or parentheses). Near: %r." % snippet)


# Strong structural fingerprints: forms that ONLY a given deliverable produces,
# so finding one identifies the message as that deliverable from its shape alone.
# This is the PRIMARY way the gate decides what it is looking at: the deliverable
# is recognized by what was written, not by which /keru-* command was typed
# (which may be many turns back, with ordinary chat since). Each fingerprint is a
# multi-marker structure unlikely to appear in casual chat, to avoid false hits.
def _fingerprint_skill(msg):
    first = first_visible_line(msg)
    # pr-review: a verdict-like opening AND a findings heading.
    if REVIEW_HEADING.search(msg) and VERDICT_HEAD.match(first):
        return "pr-review"
    # writing-tickets: a bold title opening AND the AC heading.
    if TICKET_AC.search(msg) and first.startswith("**"):
        return "writing-tickets"
    # pr-description: a conventional-commit title (bold or bare) AND a template
    # section (What Changed / How to Test).
    if PRDESC_BODY.search(msg) and (first.startswith("**") or PRDESC_TITLE_HEAD.match(first)):
        return "pr-description"
    # bot-triage: a bold service header AND the per-service "PRs:" line.
    if first.startswith("**") and re.search(r"(?m)^PRs:", msg):
        return "bot-triage"
    # addressing-pr-comments: two or more bold path:line headers (one block per
    # comment). One alone is too weak; two distinct comment blocks is the form.
    pathheaders = re.findall(r"(?m)^\*\*[\w./-]+\.\w+:\d+\*\*", msg)
    if len(pathheaders) >= 2:
        return "addressing-pr-comments"
    return None


def _last_assistant_text(records):
    for r in reversed(records):
        if r.get("type") == "assistant":
            msg = _text_of((r.get("message") or {}).get("content"))
            if msg.strip():
                return msg
    return ""


def _skill_from_last_prompt(records):
    """The deliverable skill named in the current turn: a /keru-X slash command in
    the last human prompt, or a Skill tool_use after it. Catches a malformed
    deliverable produced THIS turn (which has no strong fingerprint to match)."""
    last_user_idx = None
    last_user_text = ""
    for i, r in enumerate(records):
        if r.get("type") != "user" or r.get("isMeta"):
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, list) and not any(
                isinstance(c, dict) and c.get("type") == "text" for c in content):
            continue
        text = _text_of(content)
        if text.strip():
            last_user_idx = i
            last_user_text = text
    if last_user_idx is None:
        return None
    candidates = set()
    for m in re.finditer(r"/(keru-[a-z-]+)", last_user_text):
        candidates.add(_norm(m.group(1)))
    for r in records[last_user_idx + 1:]:
        if r.get("type") != "assistant":
            continue
        for c in (r.get("message") or {}).get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                s = (c.get("input") or {}).get("skill", "")
                if s:
                    candidates.add(_norm(s))
    candidates.discard("gather-context")
    return next((c for c in candidates if c in CHECKERS), None)


def governing_skill_and_message(records):
    """Return (checker_skill_name, last_assistant_text) for this turn, or (None,'').

    Hybrid detection, so neither real-world shape slips through:
      1. By FORM: if the last assistant message structurally fingerprints a
         deliverable, that is what we check, regardless of how many turns back the
         /keru-* command was (a review is produced once and chat continues after,
         so keying only off the last prompt misses every later Stop).
      2. By COMMAND: else, if the current turn's prompt named a deliverable skill
         (slash command or Skill tool), check against that. This catches a
         malformed deliverable produced THIS turn, which has no strong fingerprint
         to match (e.g. a review that opens with prose instead of the verdict).
    """
    msg = _last_assistant_text(records)
    if not msg:
        return None, ""
    skill = _fingerprint_skill(msg)
    if not skill or skill not in CHECKERS:
        skill = _skill_from_last_prompt(records)
    if not skill or skill not in CHECKERS:
        return None, ""
    return skill, msg


def _diag(data, **fields):
    """Append one line to a diagnostic log proving this hook actually executed,
    and what it decided. This is the only way to tell, per session, whether Claude
    Code invoked the Stop hook at all (the stdout of a Stop hook does not land in
    the transcript). Best-effort; never raises into the hook."""
    try:
        import os
        path = os.path.expanduser("~/.claude/keru-check-output.log")
        parts = ["sid=%s" % str(data.get("session_id"))[:8],
                 "sha=%s" % data.get("stop_hook_active")]
        parts += ["%s=%s" % (k, v) for k, v in fields.items()]
        with open(path, "a", encoding="utf-8") as f:
            f.write(" ".join(parts) + "\n")
    except Exception:
        pass


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # Cap: never block twice in a row (breaks any loop, same as keru-require-skill).
    if data.get("stop_hook_active"):
        _diag(data, fired="yes", action="skip-cap")
        return
    tpath = data.get("transcript_path")
    if not tpath:
        _diag(data, fired="yes", action="no-transcript")
        return
    records = _records(tpath)
    if not records:
        _diag(data, fired="yes", action="no-records")
        return
    skill, msg = governing_skill_and_message(records)
    if not skill or not msg:
        _diag(data, fired="yes", action="no-deliverable")
        return
    verdict, reason = CHECKERS[skill](msg)
    # The opening check skips when the message is not actually the deliverable
    # (a clarifying question), and the em-dash check must not fire there either,
    # so only run it once we know this IS the deliverable (verdict == "ok").
    if verdict == "ok":
        em = check_no_em_dash(msg)
        if em[0] == "violation":
            verdict, reason = em
    if verdict != "violation":
        _diag(data, fired="yes", skill=skill, action="pass-" + verdict)
        return  # compliant, or does not look like the deliverable: leave it alone
    _diag(data, fired="yes", skill=skill, action="BLOCK")
    print(json.dumps({
        "decision": "block",
        "reason": (
            "Your response is governed by the `%s` skill's Output contract, and %s "
            "Re-send the response correctly: start on its first line with the exact "
            "Output template (no intro, recap, or scope line before it), and follow "
            "the Playbook's no-em-dash rule. If you have a meta-comment, put it AFTER "
            "the template. If this turn was not actually that deliverable (you were "
            "asking a question or pushing back), proceed as you were. You will not be "
            "blocked again this turn either way." % (skill, reason)
        ),
    }))


def check_file_cli():
    """CLI mode: `keru-check-output --check <skill> <file>`. Validates a drafted
    deliverable held in a FILE (not the transcript) against that skill's Output
    contract, so Claude can self-check a /tmp draft and fix it BEFORE pasting the
    clean version into chat. Prints 'OK' and exits 0 if it complies; prints the
    violations and exits 1 if not. Same checkers as the Stop hook: one source of
    truth, no second implementation to drift.

    This is the pre-display path the Stop hook cannot give: the draft never
    reaches the user until it passes here."""
    args = sys.argv[2:]
    if len(args) != 2:
        print("usage: keru-check-output --check <skill> <file>", file=sys.stderr)
        sys.exit(2)
    skill, path = _norm(args[0]), args[1]
    if skill not in CHECKERS:
        print("unknown skill %r; known: %s" % (skill, ", ".join(sorted(CHECKERS))),
              file=sys.stderr)
        sys.exit(2)
    try:
        msg = open(path, encoding="utf-8").read()
    except OSError as e:
        print("cannot read %s: %s" % (path, e), file=sys.stderr)
        sys.exit(2)
    problems = []
    verdict, reason = CHECKERS[skill](msg)
    if verdict == "violation":
        problems.append(reason)
    elif verdict == "skip":
        problems.append("this does not look like a %s deliverable (wrong opening "
                        "or structure)." % skill)
    em = check_no_em_dash(msg)
    if em[0] == "violation":
        problems.append(em[1])
    if problems:
        print("NOT COMPLIANT (%s):" % skill)
        for p in problems:
            print("  - " + p)
        sys.exit(1)
    print("OK: complies with the %s Output contract." % skill)
    sys.exit(0)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        check_file_cli()
    else:
        main()
