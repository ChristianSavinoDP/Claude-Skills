#!/usr/bin/env bash
# Report Claude Code token usage and estimated USD cost from the local session
# transcripts. Read-only: it reads ~/.claude/projects/**/*.jsonl and nothing else,
# so every mode is safe to run at any time (permissions.json allows it outright).
#
# Why this exists: `/usage` (aliases `/cost`, `/stats`) only covers the session you
# are in, and Claude Code does NOT persist cost anywhere. The transcripts do keep
# per-request `message.usage` (input, cache write, cache read, output), so spend
# across sessions, days and months is recoverable by pricing those token counts.
#
# Usage: keru-usage <mode> [args] [--table]
#   month  [YYYY-MM]        one month (default: the current one): totals, by model,
#                           by working directory, by day
#   months                  one row per month, all history
#   sessions [N] [YYYY-MM]  the N most expensive sessions (default 10), optionally
#                           restricted to one month
#   blocks [YYYY-MM]        how often each Stop gate (keru-check-output, the LLM
#                           judge, keru-require-skill) blocked a turn, and what the
#                           rework it forced cost. This is the other half of a
#                           model/effort decision: a cheaper setting that gets
#                           kicked back by the gates pays for the rework, so weigh
#                           the saving against this number, measured, not guessed.
#   --table                 human-readable columns instead of JSON
#
# Two things to know about the numbers:
#
#   1. COST IS AN ESTIMATE, not a bill. It applies Anthropic first-party list
#      prices (the RATES table below) to the recorded token counts, which is what
#      Claude Code itself does. On Bedrock or Vertex the provider's rates apply
#      instead, so the real invoice differs. Models that match no rate are counted
#      in tokens, priced at 0, and reported under `unpriced_models`.
#   2. Requests are de-duplicated by `requestId`. The same `usage` object appears
#      more than once per request in a transcript; summing it raw inflates spend.
#
# Days and months are bucketed in LOCAL time (transcripts store UTC), so the
# boundaries match what the working day felt like.
set -uo pipefail

usage() {
  cat <<'EOF'
usage: keru-usage <mode> [args] [--table]
  month  [YYYY-MM]        one month (default: current): totals, by model, by dir, by day
  months                  one row per month, all history
  sessions [N] [YYYY-MM]  the N most expensive sessions (default 10), optional month
  blocks [YYYY-MM]        Stop-gate blocks per hook and what the rework cost
  --table                 human-readable columns instead of JSON
EOF
}

MODE="${1:-}"
case "$MODE" in
  month|months|sessions|blocks) shift ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

TABLE=0
MONTH=""
LIMIT=10
for arg in "$@"; do
  case "$arg" in
    --table) TABLE=1 ;;
    [0-9][0-9][0-9][0-9]-[0-9][0-9]) MONTH="$arg" ;;
    [0-9]|[0-9][0-9]|[0-9][0-9][0-9]) LIMIT="$arg" ;;
    *) echo "unknown argument: $arg" >&2; usage >&2; exit 2 ;;
  esac
done
# `month` with no argument means the month in progress.
[ "$MODE" = "month" ] && [ -z "$MONTH" ] && MONTH="$(date +%Y-%m)"

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }
# Day and month buckets are local-time, which needs strflocaltime (absent or
# non-functional on some old jq builds). Fail here with a clear reason rather than
# halfway through the report.
jq -n '0 | strflocaltime("%Y")' >/dev/null 2>&1 \
  || { echo "error: this jq lacks strflocaltime (needs jq 1.7+ or a build with local time support)" >&2; exit 1; }

ROOT="${CLAUDE_CONFIG_DIR:-$HOME/.claude}/projects"
[ -d "$ROOT" ] || { echo "error: no transcript directory at $ROOT" >&2; exit 1; }

# Transcript paths are absolute, so they can never be mistaken for jq options
# (the per-project directory names start with a dash, a relative glob cannot).
FILES=()
while IFS= read -r f; do FILES+=("$f"); done < <(find "$ROOT" -type f -name '*.jsonl' | sort)
[ "${#FILES[@]}" -gt 0 ] || { echo "error: no .jsonl transcripts under $ROOT" >&2; exit 1; }

# Explicit template: GNU mktemp rejects a `-t prefix` without trailing X's.
TMP="$(mktemp "${TMPDIR:-/tmp}/keru-usage.XXXXXX")" || exit 1
trap 'rm -f "$TMP"' EXIT

# --- pass 1: one normalized record per billable request ---------------------
# Prices are USD per million tokens. 1h cache writes are billed at their own
# (higher) rate, which is why cache_creation is split. Sources: Anthropic's public
# price list, cross-checked against the pricing table embedded in the Claude Code
# binary (Opus: 5 / 25 / 6.25 write / 10 write-1h / 0.5 read, web search 0.01).
PASS1='
  def rates($m):
    if   ($m|test("opus"))          then {i:5,  o:25, w:6.25, w1h:10, r:0.5}
    elif ($m|test("fable|mythos"))  then {i:10, o:50, w:12.5, w1h:20, r:1}
    elif ($m|test("sonnet-5"))      then {i:2,  o:10, w:2.5,  w1h:4,  r:0.2}
    elif ($m|test("sonnet"))        then {i:3,  o:15, w:3.75, w1h:6,  r:0.3}
    elif ($m|test("haiku"))         then {i:1,  o:5,  w:1.25, w1h:2,  r:0.1}
    else null end;
  def usd($m; $u):
    rates($m) as $p
    | if $p == null then 0 else
        ($u.cache_creation_input_tokens // 0) as $w
        | ([$u.cache_creation.ephemeral_1h_input_tokens // 0, $w] | min) as $w1h
        | ($u.input_tokens // 0) / 1e6 * $p.i
        + ($u.output_tokens // 0) / 1e6 * $p.o
        + ($u.cache_read_input_tokens // 0) / 1e6 * $p.r
        + $w1h / 1e6 * $p.w1h + ($w - $w1h) / 1e6 * $p.w
        + ($u.server_tool_use.web_search_requests // 0) * 0.01
      end;
  # Transcripts write UTC as `...T15:14:40.147Z`; fromdate needs the fraction gone.
  # A timestamp in any other shape falls back to its own date part rather than
  # aborting the whole report.
  def localday($ts):
    try ($ts | sub("\\.[0-9]+Z$"; "Z") | fromdate | strflocaltime("%Y-%m-%d"))
    catch $ts[0:10];
  # Epoch seconds, to order records inside a session. -1 when unparseable, which
  # only excludes that record from a window, never aborts the report.
  def ep($ts): try ($ts | sub("\\.[0-9]+Z$"; "Z") | fromdate) catch -1;
  # A Stop gate blocking the turn is injected back into the conversation as a user
  # record carrying the reason the hook returned. These markers are those reasons
  # (the wrapper Claude Code adds, plus the opening line each gate writes), which is
  # what makes a block countable after the fact.
  def MARK: "Stop hook feedback|Your response is governed by the|A compliance review of your|You were explicitly asked to use the";
  def txt($c): if ($c | type) == "string" then $c
               else ([$c[]? | select(.type == "text") | .text] | join("\n")) end;
  # One pass, three kinds of record. Requests are de-duplicated by requestId (the
  # same request is written to the transcript more than once, so pricing every line
  # would multiply the bill); blocks and human turns are keyed by uuid, and are
  # needed to bound "the rework one block caused" (from the block to the next thing
  # the human actually said).
  reduce inputs as $l ({req: {}, ev: {}};
    if ($l.type == "assistant")
       and ($l.message.usage != null)
       and ((($l.message.model // "") | tostring) | test("claude"))
       and (($l.timestamp // "") != "")
    then .req[($l.requestId // $l.message.id // ($l.timestamp + ($l.uuid // "")))] = $l
    elif ($l.type == "user") and (($l.timestamp // "") != "") and (txt($l.message.content) != "")
    then (txt($l.message.content)) as $t
      | if ($t | test(MARK))
        then .ev[($l.uuid // $l.timestamp)] = {kind: "block", session: ($l.sessionId // "?"),
               t: ep($l.timestamp), day: localday($l.timestamp), month: (localday($l.timestamp)[0:7]),
               gate: (if ($t | test("A compliance review of your")) then "judge-output (LLM)"
                      elif ($t | test("Your response is governed by the")) then "check-output (regex)"
                      elif ($t | test("You were explicitly asked to use the")) then "require-skill"
                      else "other" end)}
        elif ($l.isMeta | not)
        then .ev[($l.uuid // $l.timestamp)] = {kind: "human", session: ($l.sessionId // "?"), t: ep($l.timestamp)}
        else . end
    else . end)
  | (.ev | .[]), (.req | .[] | . as $l
  | ($l.message.model | tostring) as $m
  | ($l.message.usage) as $u
  | localday($l.timestamp) as $day
  | {kind: "req",
     session: ($l.sessionId // "unknown"),
     t: ep($l.timestamp),
     day: $day,
     month: $day[0:7],
     model: $m,
     priced: (rates($m) != null),
     # Never an empty string: `column -t` on macOS collapses an empty cell and
     # shifts every later column left, so a blank dir would file numbers under the
     # wrong header instead of looking wrong.
     dir: ((($l.cwd // "?") | sub(".*/"; "")) | if . == "" then "?" else . end),
     input: ($u.input_tokens // 0),
     cache_write: ($u.cache_creation_input_tokens // 0),
     cache_read: ($u.cache_read_input_tokens // 0),
     output: ($u.output_tokens // 0),
     tokens: (($u.input_tokens // 0) + ($u.cache_creation_input_tokens // 0)
              + ($u.cache_read_input_tokens // 0) + ($u.output_tokens // 0)),
     usd: usd($m; $u)})
'
jq -n "$PASS1" "${FILES[@]}" >"$TMP" 2>/dev/null || {
  # `jq -n 'reduce inputs'` is all-or-nothing: one transcript with a truncated last
  # line (a session killed mid-append) would otherwise brick every mode. Retry file
  # by file, skip the unreadable ones, and say which, rather than reporting nothing.
  : >"$TMP"
  skipped=0
  for f in "${FILES[@]}"; do
    if ! jq -n "$PASS1" "$f" >>"$TMP" 2>/dev/null; then
      skipped=$((skipped + 1))
      echo "warning: skipped unreadable transcript $f" >&2
    fi
  done
  [ "$skipped" -gt 0 ] || { echo "error: could not read transcripts" >&2; exit 1; }
}

# --- pass 2: aggregate per mode --------------------------------------------
REPORT="$(jq -s --arg mode "$MODE" --arg month "$MONTH" --argjson limit "$LIMIT" '
  def r2: . * 100 | round / 100;
  def totals: {requests: length,
               tokens: (map(.tokens) | add // 0),
               input: (map(.input) | add // 0),
               cache_write: (map(.cache_write) | add // 0),
               cache_read: (map(.cache_read) | add // 0),
               output: (map(.output) | add // 0),
               usd: ((map(.usd) | add // 0) | r2)};
  # `f` is a filter parameter (not $f): group_by needs the path expression itself,
  # and a $-bound parameter would collapse everything into a single group.
  def group(f): group_by(f) | map({key: (.[0] | f)} + totals) | sort_by(-.usd);
  # Requests carry the spend; blocks and human turns only bound the rework windows,
  # so every mode but `blocks` works off the priced requests alone.
  ([.[] | select(.kind == "req")]) as $all_reqs
  | ([.[] | select(.kind == "block")]) as $all_blocks
  | ([.[] | select(.kind == "human")]) as $all_humans
  | (if $month == "" then $all_reqs else ($all_reqs | map(select(.month == $month))) end) as $rows
  | ($rows | map(select(.priced == false) | .model) | unique) as $unpriced
  | {scope: (if $month == "" then "all history" else $month end),
     estimate: "first-party list prices applied to recorded tokens; a Bedrock or Vertex invoice will differ",
     unpriced_models: $unpriced}
  + (if $mode == "months" then
       {months: ($rows | group(.month) | sort_by(.key))}
     elif $mode == "blocks" then
       # What one block cost: every priced request from the block until the next
       # thing the human said in that session. That window is the rework the gate
       # forced, and nothing else (a window with no following human turn runs to the
       # end of the session).
       ((if $month == "" then $all_blocks else ($all_blocks | map(select(.month == $month))) end)
        | map(. as $b
              | ([$all_humans[] | select(.session == $b.session and .t > $b.t) | .t] | min // 9e18) as $end
              | ([$all_reqs[] | select(.session == $b.session and .t > $b.t and .t < $end)]) as $redo
              | {gate: $b.gate, day: $b.day, session: ($b.session[0:8]),
                 redo_requests: ($redo | length),
                 redo_usd: (($redo | map(.usd) | add // 0) | r2)})) as $ev
       | {blocks: {events: ($ev | length),
                   rework_requests: ($ev | map(.redo_requests) | add // 0),
                   rework_usd: (($ev | map(.redo_usd) | add // 0) | r2),
                   rework_usd_median: (($ev | map(.redo_usd) | sort | .[(($ev|length)/2)|floor]) // 0),
                   share_of_scope_usd: (if ($rows | length) == 0 then 0
                     else ((($ev | map(.redo_usd) | add // 0) / (($rows | map(.usd) | add) + 1e-9) * 100) | r2) end)},
          by_gate: ($ev | group_by(.gate)
            | map({key: .[0].gate, events: length,
                   sessions: ([.[].session] | unique | length),
                   rework_requests: (map(.redo_requests) | add),
                   rework_usd: ((map(.redo_usd) | add) | r2)})
            | sort_by(-.rework_usd)),
          events: ($ev | sort_by(-.redo_usd))}
     elif $mode == "sessions" then
       {sessions: ($rows | group_by(.session)
         | map({session: (.[0].session[0:8]),
                started: (map(.day) | min),
                dirs: (map(.dir) | unique | join(",")),
                models: (map(.model) | unique | join(","))} + totals)
         | sort_by(-.usd) | .[0:$limit])}
     else
       ($rows | totals) as $t
       | {total: $t,
          by_model: ($rows | group(.model)),
          by_dir: ($rows | group(.dir)),
          by_day: ($rows | group(.day) | sort_by(.key))}
     end)
' "$TMP")" || exit 1

if [ "$TABLE" -eq 0 ]; then
  printf '%s\n' "$REPORT"
  exit 0
fi

# --table: the same report as aligned columns. Each section is rendered on its own
# so `column` can size it independently.
section() {  # section HEADING JQ-PATH LABEL
  local heading="$1" path="$2" label="$3" body
  body="$(jq -r --arg label "$label" "
    ($path) // [] | if length == 0 then empty else
      ([\$label,\"REQS\",\"TOKENS\",\"CACHE_READ\",\"OUTPUT\",\"USD\"] | @tsv),
      (.[] | [(.key // .session), .requests, .tokens, .cache_read, .output, .usd] | @tsv)
    end" <<<"$REPORT")"
  [ -n "$body" ] || return 0
  printf '\n%s\n' "$heading"
  column -t -s "$(printf '\t')" <<<"$body"
}

jq -r '"scope: \(.scope)"
  + (if .total then "\ntotal: $\(.total.usd)  |  \(.total.tokens) tokens  |  \(.total.requests) requests" else "" end)
  + (if (.unpriced_models | length) > 0 then "\nunpriced models (counted in tokens, 0 USD): \(.unpriced_models | join(", "))" else "" end)' <<<"$REPORT"

# Sessions get their own columns: which day and directory a session belongs to is
# what makes it identifiable, and the cache/output split is noise at that level.
sessions_section() {
  local body
  body="$(jq -r '.sessions // [] | if length == 0 then empty else
      (["SESSION","STARTED","DIRS","MODELS","REQS","TOKENS","USD"] | @tsv),
      (.[] | [.session, .started, .dirs, .models, .requests, .tokens, .usd] | @tsv)
    end' <<<"$REPORT")"
  [ -n "$body" ] || return 0
  printf '\nTOP SESSIONS BY COST\n'
  column -t -s "$(printf '\t')" <<<"$body"
}

blocks_section() {
  local body
  body="$(jq -r '.by_gate // [] | if length == 0 then empty else
      (["GATE","BLOCKS","SESSIONS","REWORK_REQS","REWORK_USD"] | @tsv),
      (.[] | [.key, .events, .sessions, .rework_requests, .rework_usd] | @tsv)
    end' <<<"$REPORT")"
  jq -r '.blocks | "blocks: \(.events)  |  rework: \(.rework_requests) requests, $\(.rework_usd) (median $\(.rework_usd_median) per block)  |  \(.share_of_scope_usd)% of the scope'"'"'s spend"' <<<"$REPORT"
  [ -n "$body" ] || return 0
  printf '\nBY GATE\n'
  column -t -s "$(printf '\t')" <<<"$body"
}

case "$MODE" in
  months)   section "BY MONTH" ".months" "MONTH" ;;
  blocks)   blocks_section ;;
  sessions) sessions_section ;;
  month)    section "BY MODEL" ".by_model" "MODEL"
            section "BY DIRECTORY" ".by_dir" "DIR"
            section "BY DAY" ".by_day" "DAY" ;;
esac
