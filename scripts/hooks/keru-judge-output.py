#!/usr/bin/env python3
"""Stop hook: an LLM judge reviews a finished skill deliverable for the rules a
regex cannot check (tone, unverified/uncited claims, gist-substituted shape),
and blocks the turn once if it does not comply.

Why this exists: across a long session, rules that depend on Claude *recalling*
and self-applying them (tone, "verify before asserting", "open with the
template") failed repeatedly, because generation emits the gist of a rule, not
its literal text. The deterministic gates (keru-check-output) catch the
machine-checkable part (opening shape, em dashes). This judge is the second
layer: a fresh model, with no stake in the output, reads the deliverable against
the skill's rules and catches what only judgment can.

Design:
  - Cheap first: reuse the same "did this turn produce a skill deliverable?"
    detection as keru-check-output. If not, exit silent (no model call). So the
    judge only spends tokens on actual deliverables, never on chat.
  - stop_hook_active cap: never block twice in a row (no loops).
  - The judge is `dp ai claude -p --bare` (headless Claude on Bedrock, minimal
    mode: no hooks, so it cannot recurse into this gate). It returns strict JSON.
  - Fail-open: any error talking to the judge (missing CLI, timeout, unparseable
    output) exits silent. A flaky judge must never wedge the turn; the
    deterministic gates still ran.
"""
import json
import os
import re
import shutil
import subprocess
import sys

# Reuse the deterministic detector from the regex gate: same notion of "which
# deliverable skill governs this turn", so the judge fires on exactly the same
# turns the regex gate inspects (and nothing else).
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Load keru-check-output's checkers. The installed copy has NO .py extension, so
# spec_from_file_location would return a loaderless spec and fail silently; use an
# explicit SourceFileLoader and try the extensionless installed name too.
_co = None
try:
    import importlib.util
    from importlib.machinery import SourceFileLoader
    for _p in (os.path.join(HERE, "keru-check-output.py"),
               os.path.join(HERE, "keru-check-output"),
               os.path.expanduser("~/.local/bin/keru-check-output")):
        if os.path.isfile(_p):
            _loader = SourceFileLoader("keru_check_output", _p)
            _spec = importlib.util.spec_from_loader("keru_check_output", _loader)
            _co = importlib.util.module_from_spec(_spec)
            _loader.exec_module(_co)
            break
except Exception:
    _co = None

# Where to find the skill bodies, to feed the judge the rules it must enforce.
# This file lives in scripts/hooks/, so the repo root is two levels up.
REPO_ROOT = os.path.dirname(os.path.dirname(HERE))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")

# Deliverable skills the LLM judge reviews (tone, unverified claims, shape drift).
# A subset of keru-check-output's CHECKERS on purpose: `investigation` is NOT
# here because that skill already runs its own adversarial-review subagent over
# the document, so judging it again would be redundant. The regex gate still
# checks investigation's opening; only the LLM judge skips it.
JUDGED_SKILLS = {
    "pr-review",
    "writing-tickets",
    "pr-description",
    "addressing-pr-comments",
    "bot-triage",
}

# What the judge checks. Deliberately NOT the machine-checkable things the regex
# gate already enforces (opening line, em dashes); those are handled. This is the
# judgment-only layer.
JUDGE_CRITERIA = """You are a strict compliance reviewer for a deliverable produced under a skill's rules. You did NOT write it; your job is to catch where it violates the skill, the way a careful reviewer would. Judge ONLY these, which a regex cannot:

1. TONE: if the skill requires a peer/suggesting register (e.g. pr-review: findings on someone else's PR are questions or suggestions, not flat verdicts or imperatives), does the delivered text actually read that way? A Nit/Question written as "this is broken, do X" violates it; "does this still hold when X?" complies.
2. UNVERIFIED / UNCITED CLAIMS: does it state how a library, API, field, or external system behaves as fact without either naming a verified source or marking it "not verified"? Asserting behavior from apparent memory is a violation.
3. INVENTED RULES / FABRICATION: does it assert a rule, constraint, or fact that it does not actually support? (Stating a violation without quoting the rule, claiming something was verified that was not.)
4. SHAPE DRIFT: beyond the first line (already checked), does the body follow the skill's required structure, or did it substitute a remembered-but-wrong shape (prose essay where structured findings are required, etc.)?

Be precise and conservative: only flag a CLEAR violation you can point to. A judgment call that is defensible is NOT a violation. If it complies, say so."""

JUDGE_PROMPT = """%s

## The skill's rules (the contract this deliverable must follow)

%s

## The delivered text to review

<<<DELIVERABLE
%s
DELIVERABLE

Return ONLY this JSON, nothing else:
{"complies": true|false, "violation": "<one concise sentence naming the specific violation and where, or empty if it complies>"}"""


def _read_skill(skill):
    """Load the skill body for the judge. skill is e.g. 'pr-review'."""
    for name in (skill, "keru-" + skill):
        p = os.path.join(SKILLS_DIR, name, "SKILL.md")
        if os.path.isfile(p):
            try:
                return open(p, encoding="utf-8").read()
            except OSError:
                return None
    return None


def _dp_bin():
    """Locate the dp CLI (it provides `dp ai claude`, headless Claude on Bedrock).
    It is under mise and may not be on the hook's PATH, so search known spots."""
    found = shutil.which("dp")
    if found:
        return found
    base = os.path.expanduser("~/.local/share/mise/installs/dailypay-dp")
    if os.path.isdir(base):
        # Pick any installed version's bin/dp.
        for ver in sorted(os.listdir(base), reverse=True):
            cand = os.path.join(base, ver, "bin", "dp")
            if os.path.isfile(cand) and os.access(cand, os.X_OK):
                return cand
    return None


def _ask_judge(prompt):
    """Run the headless judge. Returns parsed JSON dict, or None on any failure
    (fail-open: a broken judge must never block the turn)."""
    dp = _dp_bin()
    if not dp:
        return None
    try:
        proc = subprocess.run(
            [dp, "ai", "claude", "-p", "--bare", prompt],
            capture_output=True, text=True, timeout=55)
    except Exception:
        return None
    out = (proc.stdout or "").strip()
    if not out:
        return None
    # The model may wrap the JSON in prose or a fence; extract the first object.
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # Cap: never block twice in a row (same loop-break as the other Stop hooks).
    if data.get("stop_hook_active"):
        return
    tpath = data.get("transcript_path")
    if not tpath or _co is None:
        return
    records = _co._records(tpath)
    if not records:
        return
    # Cheap gate, two stages, before spending any model call:
    # 1. Which deliverable skill governs this turn (slash command / Skill tool /
    #    fingerprint). No skill => chat, exit.
    skill, msg = _co.governing_skill_and_message(records)
    if not skill or not msg:
        return
    # Only judge the skills whose deliverable benefits from an LLM review of tone/
    # verification/shape. investigation is excluded (it has its own adversarial
    # reviewer); anything else the judge has no business on.
    if skill not in JUDGED_SKILLS:
        return
    # 2. Does the message actually LOOK like that deliverable? The regex checker
    #    returns 'skip' for a turn that is not the deliverable (a clarifying reply
    #    like "I'll review it in a moment"), and 'violation' when the regex gate
    #    will already block it. Only run the judge when the form is right ('ok'),
    #    so we neither judge chat nor double-up on what keru-check-output caught.
    checker = _co.CHECKERS.get(skill)
    if checker is not None:
        status = checker(msg)[0]
        if status != "ok":
            return
    skill_body = _read_skill(skill)
    if not skill_body:
        return
    verdict = _ask_judge(JUDGE_PROMPT % (JUDGE_CRITERIA, skill_body, msg))
    if not verdict or verdict.get("complies") is not False:
        return  # complies, or judge unavailable/unsure: fail-open, do not block
    reason = (verdict.get("violation") or "").strip() or \
        "the deliverable does not comply with the skill's tone/verification/shape rules"
    print(json.dumps({
        "decision": "block",
        "reason": (
            "A compliance review of your `%s` deliverable found: %s "
            "Re-send it fixed, following the skill's rules (re-read them; do not "
            "work from memory of them). If you judge this a false positive and the "
            "deliverable does comply, say briefly why and proceed; you will not be "
            "blocked again this turn." % (skill, reason)
        ),
    }))


if __name__ == "__main__":
    main()
