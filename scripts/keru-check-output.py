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
VERDICT_FULL = re.compile(r"^(?:\*{0,2}Verdict\*{0,2}:\s*)?`?(Approve|Request changes|Comment)`?$", re.I)
# "Starts like a verdict" (verdict word, or a `Verdict:` label, at the front),
# used to tell a malformed review opening ("Verdict: Comment (one question...)")
# from a non-review reply.
VERDICT_HEAD = re.compile(r"^(?:\*{0,2}Verdict\*{0,2}:\s*)?`?(Approve|Request changes|Comment)\b", re.I)
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
PRDESC_BODY = re.compile(r"(?m)^(#{1,6}\s|.*\b(What Changed|How to Test)\b)")


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
    """Remove fenced code blocks (``` ... ```) and inline `code` spans, so an
    em dash that legitimately appears in a pasted diff/snippet is not flagged.
    Only prose em dashes violate the Playbook rule."""
    # Drop fenced blocks first (any fence length >= 3 backticks), non-greedy.
    no_fences = re.sub(r"`{3,}.*?`{3,}", " ", msg, flags=re.S)
    # Then inline spans.
    return re.sub(r"`[^`]*`", " ", no_fences)


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
# so finding one proves the message is that deliverable even when its skill was
# never loaded (the "produced the deliverable without the skill" case). These are
# intentionally stricter than the opening check's "looks_like" signals: each must
# be a multi-marker structure unlikely to appear in ordinary chat.
def _fingerprint_skill(msg):
    # pr-review: a verdict-like opening AND a findings heading.
    if REVIEW_HEADING.search(msg) and VERDICT_HEAD.match(first_visible_line(msg)):
        return "pr-review"
    # writing-tickets: the AC heading is unique to a drafted ticket.
    if TICKET_AC.search(msg):
        return "writing-tickets"
    # addressing-pr-comments: two or more bold path:line headers (one block per
    # comment). One alone is too weak; two distinct comment blocks is the form.
    pathheaders = re.findall(r"(?m)^\*\*[\w./-]+\.\w+:\d+\*\*", msg)
    if len(pathheaders) >= 2:
        return "addressing-pr-comments"
    return None


def governing_skill_and_message(records):
    """Return (checker_skill_name, last_assistant_text) for this turn, or (None, '').

    The governing deliverable skill is found two ways, in order:
      1. It was loaded: a `/keru-X` slash command in the last human prompt or a
         Skill tool_use after it (gather-context, a prerequisite, is ignored).
      2. It was NOT loaded but the message has an unmistakable deliverable
         fingerprint (a strong structural form only that deliverable produces).
         This catches producing the deliverable without ever loading its skill.
    The message is the last assistant text in the file (what Stop fires on).
    """
    # Last human prompt (isMeta records are injected, not the user; skip them).
    last_user_idx = None
    last_user_text = ""
    for i, r in enumerate(records):
        if r.get("type") != "user" or r.get("isMeta"):
            continue
        content = (r.get("message") or {}).get("content")
        if isinstance(content, list) and not any(
                isinstance(c, dict) and c.get("type") == "text" for c in content):
            continue  # tool_result only
        text = _text_of(content)
        if text.strip():
            last_user_idx = i
            last_user_text = text
    if last_user_idx is None:
        return None, ""

    candidates = set()
    # Slash command in the prompt: <command-name>/keru-X</command-name> or /keru-X.
    for m in re.finditer(r"/(keru-[a-z-]+)", last_user_text):
        candidates.add(_norm(m.group(1)))
    # Skill tool_uses after the prompt.
    for r in records[last_user_idx + 1:]:
        if r.get("type") != "assistant":
            continue
        for c in (r.get("message") or {}).get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                s = (c.get("input") or {}).get("skill", "")
                if s:
                    candidates.add(_norm(s))
    candidates.discard("gather-context")

    # Last assistant message text in the file.
    msg = ""
    for r in reversed(records):
        if r.get("type") == "assistant":
            msg = _text_of((r.get("message") or {}).get("content"))
            if msg.strip():
                break

    skill = next((c for c in candidates if c in CHECKERS), None)
    if not skill and msg:
        # No deliverable skill was loaded; fall back to the message's own form.
        skill = _fingerprint_skill(msg)
    if not skill:
        return None, ""
    return skill, msg


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # Cap: never block twice in a row (breaks any loop, same as keru-require-skill).
    if data.get("stop_hook_active"):
        return
    tpath = data.get("transcript_path")
    if not tpath:
        return
    records = _records(tpath)
    if not records:
        return
    skill, msg = governing_skill_and_message(records)
    if not skill or not msg:
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
        return  # compliant, or does not look like the deliverable: leave it alone
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


if __name__ == "__main__":
    main()
