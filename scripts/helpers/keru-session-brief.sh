#!/usr/bin/env bash
# Re-entry state for a session, read from the local Claude Code transcripts. Two
# modes, both read-only and both deliberately model-free: everything here is
# extracted mechanically, so it costs zero tokens to produce.
#
# Why it exists: a `/clear` is the only thing that shrinks a fat context, and the
# reason not to clear is losing where you were. This makes clearing cheap, which is
# what actually saves money (requests above 100K of context are a minority of calls
# and most of the cache bill). It does NOT try to save tokens by injecting context,
# which would add to every turn what it claims to save.
#
# What it deliberately does NOT do: summarize decisions or rationale. That needs a
# model, and a per-turn model call to save cache reads spends more than it saves.
# This is mechanical state only, and it says so, so nothing here is mistaken for a
# verified account of what was decided.
#
# Usage: keru-session-brief <mode>
#   brief   the previous session in this project: when, context size, files
#           touched, tickets seen (and whether a snapshot exists), last asks.
#           For SessionStart. Silent unless the event warrants it (see below).
#   nudge   one line, ONLY when the current session is both fat and idle, i.e.
#           the prompt cache has likely expired and the next turn rewrites the
#           prefix. For UserPromptSubmit, which runs on the critical path of every
#           prompt, so this mode checks the cheap signal first and prints nothing
#           the rest of the time.
#
# Both modes read the hook JSON on stdin when stdin is not a TTY (to honor
# `source` and `transcript_path`), and work standalone from a terminal without it.
#
# Thresholds (env-overridable, no edit needed): KERU_BRIEF_CTX_TOKENS (default
# 150000), KERU_BRIEF_IDLE_SECONDS (default 300, the prompt cache TTL),
# KERU_BRIEF_MAX_AGE_HOURS (default 24; an older session is a different task).
#
# Never exits non-zero in hook context: a UserPromptSubmit hook exiting 2 would
# block the prompt, so even an unknown mode fails open when stdin is not a TTY.
set -uo pipefail

# stdin is read before anything else so an unknown mode can tell hook context from
# a terminal. Hooks close stdin, so a plain `cat` returns immediately; bash 3.2 (what
# `env bash` resolves to on macOS) DISCARDS input on a `read -t` timeout, so the
# read-with-timeout form would silently drop the JSON and disable both the source
# gate and the current-transcript exclusion below.
HOOK_JSON=""
if [ ! -t 0 ]; then
  HOOK_JSON="$(cat 2>/dev/null || true)"
  command -v jq >/dev/null 2>&1 && { jq -e . >/dev/null 2>&1 <<<"$HOOK_JSON" || HOOK_JSON=""; }
fi
IN_HOOK=0
[ -t 0 ] || IN_HOOK=1

MODE="${1:-}"
case "$MODE" in
  brief|nudge) ;;
  -h|--help|help) echo "usage: keru-session-brief <brief|nudge>"; exit 0 ;;
  *) echo "usage: keru-session-brief <brief|nudge>" >&2
     [ "$IN_HOOK" -eq 1 ] && exit 0 || exit 2 ;;
esac

command -v jq >/dev/null 2>&1 || exit 0  # fail-open: a hook must never break the turn

CTX_LIMIT="${KERU_BRIEF_CTX_TOKENS:-150000}"
IDLE_LIMIT="${KERU_BRIEF_IDLE_SECONDS:-300}"
MAX_AGE_H="${KERU_BRIEF_MAX_AGE_HOURS:-24}"
# A bad env value must not leak a shell error out of a hook.
case "$CTX_LIMIT$IDLE_LIMIT$MAX_AGE_H" in *[!0-9]*) exit 0 ;; esac

hook_field() { [ -n "$HOOK_JSON" ] && jq -r --arg k "$1" '.[$k] // empty' <<<"$HOOK_JSON" 2>/dev/null || true; }
SOURCE="$(hook_field source)"
CUR_TRANSCRIPT="$(hook_field transcript_path)"
HOOK_CWD="$(hook_field cwd)"
[ -n "$HOOK_CWD" ] || HOOK_CWD="${PWD:-.}"

# SessionStart fires with source startup|resume|clear|compact|fork. Only two of
# those want this: `clear` (the context was dropped on purpose, which is exactly
# when re-entry state is the point) and `startup` (opening the project fresh).
# `resume` still has the history, `compact` just produced a summary, and `fork`
# inherits its parent, so injecting there is pure noise.
if [ "$MODE" = "brief" ] && [ -n "$SOURCE" ]; then
  case "$SOURCE" in
    startup|clear) ;;
    *) exit 0 ;;
  esac
fi

# --- locating the project's transcripts -------------------------------------
# In hook context the transcript path is given, and its parent IS the project
# directory, so it needs no guessing. Only a manual run has to derive the name,
# and Claude Code derives it by replacing EVERY non-alphanumeric character (not
# just the slashes) and truncating very long paths, so a computed name is
# best-effort: if it does not exist, stay silent rather than report another
# project as this one.
DIR=""
if [ -n "$CUR_TRANSCRIPT" ]; then
  DIR="$(dirname "$CUR_TRANSCRIPT")"
else
  slug="$(printf '%s' "$HOOK_CWD" | sed 's/[^a-zA-Z0-9]/-/g')"
  DIR="${CLAUDE_CONFIG_DIR:-${HOME:-/nonexistent}/.claude}/projects/$slug"
fi
[ -d "$DIR" ] || exit 0

# Records whose model is `<synthetic>` are Claude Code placeholders (an interrupt,
# an API error) carrying zero usage. They are frequently the LAST assistant records
# in a transcript, so taking the last record without this filter reports a 355K
# session as 0K and never fires the nudge on the sessions it exists for.
REAL_REQ='select(.type == "assistant" and .message.usage != null
                 and (((.message.model // "") | tostring) | test("claude")))'

# --- nudge: cheap, tail-only ------------------------------------------------
if [ "$MODE" = "nudge" ]; then
  T="$CUR_TRANSCRIPT"
  if [ -z "$T" ] || [ ! -f "$T" ]; then
    T="$(ls -t "$DIR"/*.jsonl 2>/dev/null | head -1)"
  fi
  [ -n "$T" ] && [ -f "$T" ] || exit 0
  # Idleness comes from the file mtime, not from the last record's timestamp: the
  # transcript is appended to continuously, so mtime is the last time anything
  # happened, while the newest *record* can read minutes old mid-turn (a long
  # generation is written when it completes) and produce a false idle gap.
  mtime="$(date -r "$T" +%s 2>/dev/null || echo 0)"
  case "$mtime" in ''|*[!0-9]*) exit 0 ;; esac
  idle=$(( $(date +%s) - mtime ))
  [ "$idle" -ge "$IDLE_LIMIT" ] || exit 0
  # Only the tail: this runs before every prompt, so it must not parse a 30MB file.
  read -r ctx model < <(tail -n 400 "$T" 2>/dev/null | jq -sr "
    [.[] | $REAL_REQ] | last as \$l
    | if \$l == null then \"0 unknown\"
      else (((\$l.message.usage.cache_read_input_tokens // 0)
            + (\$l.message.usage.cache_creation_input_tokens // 0)) | tostring)
           + \" \" + ((\$l.message.model // \"unknown\") | tostring) end" 2>/dev/null)
  ctx="${ctx:-0}"
  case "$ctx" in ''|*[!0-9]*) exit 0 ;; esac
  [ "$ctx" -ge "$CTX_LIMIT" ] || exit 0
  # Rate is per model, from the model that actually served the last request: a
  # hardcoded Opus rate would overstate a Sonnet or Haiku session about twofold.
  rate="$(jq -nr --arg m "${model:-unknown}" '
    if ($m | test("opus")) then 6.25
    elif ($m | test("fable|mythos")) then 12.5
    elif ($m | test("sonnet-5")) then 2.5
    elif ($m | test("sonnet")) then 3.75
    elif ($m | test("haiku")) then 1.25
    else 0 end')"
  cost="$(jq -nr --argjson c "$ctx" --argjson r "${rate:-0}" '($c / 1000000 * $r * 100 | round / 100)')"
  # Stated as a likelihood, not a fact: the TTL is server-side and refreshes on
  # every hit, so an idle gap past it makes expiry likely, not certain, and the
  # figure is what rewriting a prefix of this size would cost, not a charge.
  if [ "${rate:-0}" = "0" ]; then
    printf 'Context is %dK tokens and nothing has happened for %d min, so the prompt cache has likely expired and the next turn rewrites the prefix. If the next task is unrelated, /clear now: `keru-session-brief brief` reprints where you were.\n' \
      "$((ctx / 1000))" "$((idle / 60))"
  else
    printf 'Context is %dK tokens and nothing has happened for %d min, so the prompt cache has likely expired: rewriting a prefix this size runs about $%s at %s cache-write rates. If the next task is unrelated, /clear now: `keru-session-brief brief` reprints where you were.\n' \
      "$((ctx / 1000))" "$((idle / 60))" "$cost" "$model"
  fi
  exit 0
fi

# --- brief: the previous session -------------------------------------------
# Newest transcript with real activity, never the one this session is writing.
# `grep -a` because the grep on PATH may be ugrep, which prints nothing at all for
# a file it judges binary (one stray byte in a 30MB transcript is enough).
PREV=""
while IFS= read -r f; do
  [ -n "$f" ] || continue
  [ "$f" = "$CUR_TRANSCRIPT" ] && continue
  n="$(grep -a -c '"type":"assistant"' "$f" 2>/dev/null | head -1)"
  case "${n:-0}" in ''|*[!0-9]*) continue ;; esac
  [ "$n" -ge 3 ] || continue
  PREV="$f"
  break
done < <(ls -t "$DIR"/*.jsonl 2>/dev/null)
[ -n "$PREV" ] || exit 0

# An old session is a different task; saying nothing beats guessing it is relevant.
end_epoch="$(date -r "$PREV" +%s 2>/dev/null || echo 0)"
case "$end_epoch" in ''|*[!0-9]*) exit 0 ;; esac
age=$(( $(date +%s) - end_epoch ))
[ "$age" -le $((MAX_AGE_H * 3600)) ] || exit 0

# Keys come from command strings only, never from prose: scanning prose turns
# "UTF-8" and "GPT-4" into ticket keys, and those then look like real keys to
# every reader of this output. Two or more digits for the same reason.
KEYS="$(jq -sr '[.[] | select(.type == "assistant") | .message.content[]?
   | select(.type == "tool_use") | (.input.command // "") | tostring] | join(" ")
   | [match("[A-Z][A-Z0-9]+-[0-9][0-9]+"; "g").string] | unique | .[]' "$PREV" 2>/dev/null)"

BODY="$(jq -sr --arg cwd "$HOOK_CWD" --arg home "${HOME:-/nonexistent}" "
  def txt(\$c): if (\$c | type) == \"string\" then \$c
               else ([\$c[]? | select(.type == \"text\") | .text] | join(\"\n\")) end;
  # The gates inject their own text as user records, and this script's own output
  # can come back the same way, so neither is mistaken for something the user asked.
  def MARK: \"Stop hook feedback|Your response is governed by the|A compliance review of your|You were explicitly asked to use the|Previous session in this project|the prompt cache has likely expired\";
  . as \$all
  | ([.[] | $REAL_REQ] | unique_by(.requestId // .message.id)) as \$reqs
  | ([.[] | $REAL_REQ] | last) as \$lastreq
  | ([\$all[] | select(.type == \"assistant\") | .message.content[]?
      | select(.type == \"tool_use\" and (.name == \"Edit\" or .name == \"Write\" or .name == \"NotebookEdit\"))
      | .input.file_path // empty]) as \$paths
  | ([\$all[] | select(.type == \"user\" and ((.isMeta // false) | not)) | txt(.message.content)
      | select(. != \"\") | select((. | test(MARK)) | not)
      | gsub(\"<[^>]*>\"; \" \") | gsub(\"\\\\s+\"; \" \") | ltrimstr(\" \") | .[0:200]] | .[-3:]) as \$asks
  | {ctx: (((\$lastreq.message.usage.cache_read_input_tokens // 0)
           + (\$lastreq.message.usage.cache_creation_input_tokens // 0)) / 1000 | round),
     requests: (\$reqs | length),
     files: ([\$paths[] | select(test(\"keru-deliverable-\") | not)
              | ltrimstr(\$cwd + \"/\") | ltrimstr(\$home + \"/\")] | unique),
     asks: \$asks}
  | \"- context when it ended: \(.ctx)K tokens over \(.requests) requests\n\"
    + (if (.files | length) > 0 then \"- files edited: \" + (.files | .[0:8] | join(\", \"))
         + (if (.files | length) > 8 then \" (+\(.files | length - 8) more)\" else \"\" end) + \"\n\" else \"\" end)
    + (if (.asks | length) > 0 then \"- last asks:\n\" + (.asks | to_entries | map(\"  \(.key + 1). \(.value)\") | join(\"\n\")) + \"\n\" else \"\" end)
" "$PREV" 2>/dev/null)"
[ -n "$BODY" ] || exit 0

# The user records only prove a write was REQUESTED. The deliverable gate denies a
# non-compliant write, so a requested path that does not exist was never written and
# must not be reported as one.
DELIVERABLES=""
while IFS= read -r p; do
  [ -n "$p" ] || continue
  [ -f "$p" ] && DELIVERABLES="${DELIVERABLES}${DELIVERABLES:+, }$p"
done < <(jq -sr '[.[] | select(.type == "assistant") | .message.content[]?
   | select(.type == "tool_use") | .input.file_path // empty
   | select(test("keru-deliverable-"))] | unique | .[]' "$PREV" 2>/dev/null)

branch="$(git -C "$HOOK_CWD" branch --show-current 2>/dev/null || true)"
printf '## Previous session in this project (%s ago%s)\n\n' \
  "$(if [ "$age" -lt 3600 ]; then echo "$((age / 60)) min"; else echo "$((age / 3600))h"; fi)" \
  "$([ -n "$branch" ] && printf ', branch %s' "$branch")"
# Command substitution strips the trailing newline, so restore it: without this the
# lines below run into the last ask.
printf '%s\n' "$BODY"
[ -n "$KEYS" ] && printf -- '- keys seen in commands: %s\n' "$(printf '%s' "$KEYS" | tr '\n' ' ')"
[ -n "$DELIVERABLES" ] && printf -- '- deliverables still on disk: %s\n' "$DELIVERABLES"
# Anything a snapshot exists for can be re-verified instead of re-walked.
while IFS= read -r k; do
  [ -n "$k" ] || continue
  [ -f "/tmp/keru-context-${k}.md" ] && printf -- '- snapshot on disk for %s: verify with `keru-context-snapshot check %s`\n' "$k" "$k"
done <<<"$KEYS"
printf '\nMechanical state from the transcript, not an account of what was decided: treat it as pointers to re-read, not as facts.\n'
exit 0
