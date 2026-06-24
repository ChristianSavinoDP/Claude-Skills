#!/usr/bin/env python3
"""Stop hook: if the user explicitly asked to use a skill this turn and it was
never invoked, block the turn end and tell Claude to invoke it.

This is a safeguard for the one verifiable case: a direct "use the X skill"
instruction. It does NOT police automatic skill triggering (too heuristic, and
minor work should not be forced through a skill). Fail-open: if it cannot
confidently tell which skill was requested, it stays silent.

Stop hook input (stdin JSON) includes `transcript_path`. We read the transcript,
find the last user prompt, check whether it explicitly requests a known skill,
and whether a `Skill` tool call for that skill appears after it in this turn.
"""
import json
import re
import sys

# Known skills and the phrases (English + Spanish) that name them. Order matters:
# more specific names first so "writing tickets" is not shadowed by "writing".
# Each entry's first element is the canonical skill id (skills are named keru-*,
# so it is the real skill/command name); the phrases are what the user might type.
SKILLS = [
    ("keru-addressing-pr-comments", ["addressing-pr-comments", "addressing pr comments",
                                "address pr comments", "pr comments",
                                "comentarios de pr", "responder comentarios"]),
    ("keru-pr-description", ["pr-description", "pr description", "descripcion de pr",
                        "descripcion del pr", "describir el pr"]),
    # Bare "review"/"revisar" deliberately excluded: they match casual mentions
    # ("...and then we review", "revisar el codigo") and a misnamed request (the
    # user says "revisar PRs" when the task is actually resolving review comments).
    # Require a phrase that genuinely names the PR-review skill.
    ("keru-pr-review", ["pr-review", "pr review", "revisar pr", "revisar el pr",
                   "revisar prs", "revisar el pull request", "revision de pr"]),
    ("keru-writing-tickets", ["writing-tickets", "writing tickets", "write ticket",
                         "escribir ticket", "escribir tickets", "redactar ticket",
                         "ticket skill", "skill de ticket", "skill de escribir ticket"]),
    ("keru-writing-code", ["writing-code", "writing code", "escribir codigo",
                      "code skill", "skill de codigo", "skill de escribir codigo"]),
    ("keru-investigation", ["investigation", "investigacion",
                       "investigation skill", "skill de investigacion"]),
    ("keru-gather-context", ["gather-context", "gather context",
                        "context skill", "skill de contexto"]),
]

# The user is explicitly asking to USE a skill only if the prompt has a "use" verb
# near the word "skill". This keeps it to direct instructions, not casual mentions.
USE_SKILL = re.compile(r"(use|uses|using|us[aáeo]\w*|invoc\w*|corr[eé]\w*|run)\b[^.\n]{0,40}\bskill\b", re.I)


def load_turn(transcript_path):
    """Return (last_user_text, skills_invoked_after) for the current turn.

    The 'turn' is everything from the last user prompt to the end of file.
    """
    try:
        lines = open(transcript_path, encoding="utf-8").read().splitlines()
    except OSError:
        return None, []
    records = []
    for ln in lines:
        ln = ln.strip()
        if not ln:
            continue
        try:
            records.append(json.loads(ln))
        except ValueError:
            continue
    # Find the index of the last real user prompt (text, not a tool_result).
    last_user_idx = None
    last_user_text = ""
    for i, r in enumerate(records):
        if r.get("type") != "user":
            continue
        content = (r.get("message") or {}).get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            parts = [c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"]
            # Skip turns that are only tool_result (no human text).
            if not any(c.get("type") == "text" for c in content if isinstance(c, dict)):
                continue
            text = "\n".join(parts)
        if text.strip():
            last_user_idx = i
            last_user_text = text
    if last_user_idx is None:
        return None, []
    # Skill tool calls after that prompt.
    invoked = []
    for r in records[last_user_idx + 1:]:
        if r.get("type") != "assistant":
            continue
        for c in (r.get("message") or {}).get("content", []) or []:
            if isinstance(c, dict) and c.get("type") == "tool_use" and c.get("name") == "Skill":
                s = (c.get("input") or {}).get("skill", "")
                if s:
                    invoked.append(s)
    return last_user_text, invoked


def _norm(name):
    """Normalize a skill name for comparison: drop any plugin namespace
    (`plugin:name`, `path/name`) and the `keru-` command-wrapper prefix, so an
    invoked `keru-pr-review` and a requested `pr-review` compare equal."""
    base = re.split(r"[/:]", name)[-1]
    return base[len("keru-"):] if base.startswith("keru-") else base


def invoked_via_slash_command(text):
    """A known skill the user invoked through its own slash command this turn.

    Each skill IS its own `/keru-*` slash command (there is no wrapper layer), so
    `/keru-pr-description` loads and runs that skill directly without emitting a
    `Skill` tool_use. The slash command appears in the prompt as a
    `<command-name>/keru-pr-description</command-name>` tag (or a bare
    `/keru-pr-description` line). That invocation already satisfies the request:
    the skill is running. Return its canonical id, or None."""
    m = re.search(r"<command-name>\s*/?(keru-[a-z-]+)\s*</command-name>", text, re.I)
    if not m:
        m = re.search(r"(?m)^\s*/(keru-[a-z-]+)\b", text)
    if not m:
        return None
    name = _norm(m.group(1))
    for skill, _ in SKILLS:
        if _norm(skill) == name:
            return skill
    return None


def requested_skill(text):
    """Which known skill the user explicitly asked to use, or None."""
    # Strip IDE-injected tags so they do not create false matches.
    text = re.sub(r"<ide_[^>]*>.*?</ide_[^>]*>", " ", text, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    if not USE_SKILL.search(text):
        return None
    low = text.lower()
    for skill, phrases in SKILLS:
        for p in phrases:
            if p in low:
                return skill
    return None


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    # Never block twice in a row. Claude Code sets stop_hook_active=true on the
    # Stop that follows a hook block; honoring it caps this hook at ONE block per
    # turn, so a wrong or stale match can never produce an infinite loop. The one
    # block carries an escape hatch (below), so that single block is harmless.
    if data.get("stop_hook_active"):
        return
    tpath = data.get("transcript_path")
    if not tpath:
        return
    text, invoked = load_turn(tpath)
    if not text:
        return
    skill = requested_skill(text)
    if not skill:
        return  # no explicit skill request: nothing to enforce
    # If the user ran the skill's own `/keru-*` slash command, the skill is
    # already loaded and running this turn; that satisfies the request without a
    # `Skill` tool_use. Enforcing one here would block a correct deliverable and
    # force a needless re-invocation (the observed double-run). Check on the raw
    # text, before requested_skill() strips the <command-name> tag.
    if invoked_via_slash_command(text) == skill:
        return  # invoked through its slash command: the skill is running
    # The requested skill counts as invoked if any invoked skill matches it after
    # normalizing away a plugin namespace (`plugin:name`, `path/name`) and the
    # `keru-` command-wrapper prefix on either side. So an invoked `keru-pr-review`
    # satisfies a requested `pr-review`, and vice versa.
    if any(_norm(s) == _norm(skill) for s in invoked):
        return  # the requested skill (or its keru- wrapper) was invoked: all good
    print(json.dumps({
        "decision": "block",
        "reason": (
            "You were explicitly asked to use the `%s` skill this turn and did not "
            "invoke the Skill tool for it. Having its instructions in context is not "
            "the same as invoking it. If `%s` is genuinely the right skill, call the "
            "Skill tool for it now and do the work from it. BUT if the user named the "
            "skill loosely and a different skill actually fits the task (e.g. they "
            "said \"review the PR\" but the work is resolving review comments, which "
            "is `addressing-pr-comments`), use the skill that fits and proceed; do "
            "not re-invoke the wrong one. You will not be blocked again this turn "
            "either way." % (skill, skill)
        ),
    }))


if __name__ == "__main__":
    main()
