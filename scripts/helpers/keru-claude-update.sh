#!/usr/bin/env bash
# Keep the Claude toolchain current on this machine: update the Claude Code CLI
# through the dp `ai` plugin, and refresh which Claude models the CLI offers,
# so the newest model per family (and its 1M-context spelling) is selectable
# from /model and one of them can be pinned as the resting model.
#
# scripts/hooks/keru-safe-read.py auto-approves `audit` (read-only) but not
# `cli` / `models`, keying on the mode being positional arg 1. Keep `audit`
# read-only and the mode as arg 1, or the gate will mis-classify.
#
# Usage: keru-claude-update <mode> [options]
#   audit    read-only: installed CLI version, the newest model per family on
#            this Bedrock account, what settings.json pins today, and the exact
#            writes `models` would make (its `plan`)
#   cli      update the CLI: `dp up`, `dp plug up ai`, then `dp ai claude
#            --version`. The plugin is a launcher that installs claude@latest
#            before exec'ing it, so `--version` is what triggers the install and
#            exits, instead of opening a nested interactive session.
#   models [--pin <choice>] [--no-1m]
#            write the model env slots into <config>/settings.json, and with
#            --pin also the resting `model`
#     --pin opus|sonnet|haiku|fable|custom|<full model id>|none   (default none)
#     --no-1m  pin the plain spelling instead of <id>[1m]
#
# No model id is hardcoded. The catalogue is the newest ACTIVE inference profile
# per family from `aws bedrock list-inference-profiles` (id prefix from
# KERU_MODEL_PREFIX, default `us.`), so a model added to the account shows up
# here without editing this file. What each family maps to:
#
#   ANTHROPIC_DEFAULT_{OPUS,SONNET,HAIKU,FABLE}_MODEL   newest of that family,
#                                                       plain (no [1m])
#   ANTHROPIC_CUSTOM_MODEL_OPTION                       runner-up Opus in its
#                                                       [1m] spelling, so the
#                                                       picker holds a plain
#                                                       entry per family and one
#                                                       explicit 1M entry
#                                                       (--no-1m makes it plain)
#   ANTHROPIC_SMALL_FAST_MODEL                          newest Haiku (this
#                                                       legacy var is read
#                                                       BEFORE the Haiku slot,
#                                                       so leaving it stale
#                                                       would silently win)
#
# Two things are deliberate:
#
#   1. ANTHROPIC_MODEL is never written, and is REMOVED when present: it
#      overrides the `model` setting, which is where /model persists a choice,
#      so a leftover copy (the dp `ai` plugin writes one) silently pins a model
#      the picker does not show. The resting model belongs in `model`.
#   2. *_SUPPORTED_CAPABILITIES is written only for an id the installed CLI
#      does NOT recognize. For a known id the build already knows its
#      capabilities, and an override could only contradict it; for an unknown
#      one (a model newer than the CLI) the build assumes nothing, so thinking
#      and effort need declaring or they are simply unavailable.
#
# Secrets live in the same settings file (API tokens, OTEL headers), so this
# only ever adds/removes the keys listed above and never prints the file.
set -euo pipefail

MODE="${1:-}"
shift || true
PIN="none"
WANT_1M=1

case "$MODE" in
  audit|cli|models) ;;
  *) echo "usage: keru-claude-update <audit|cli|models> [--pin <choice>] [--no-1m]" >&2; exit 2 ;;
esac

while [ $# -gt 0 ]; do
  case "$1" in
    --pin)     PIN="${2:-}"
               [ -n "$PIN" ] || { echo "error: --pin needs a value" >&2; exit 2; }
               shift 2 ;;
    --pin=*)   PIN="${1#--pin=}"; shift ;;
    --no-1m)   WANT_1M=0; shift ;;
    --1m)      WANT_1M=1; shift ;;
    *) echo "error: unknown option '$1'" >&2; exit 2 ;;
  esac
done

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }

CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
SETTINGS="$CLAUDE_DIR/settings.json"
PREFIX="${KERU_MODEL_PREFIX:-us.}"

# Families that map to a picker slot. A family outside this list (a preview
# model, say) is reported in the catalogue but never written: there is no env
# var to put it in, and inventing one would be a guess.
SLOT_FAMILIES='["opus","sonnet","haiku","fable"]'

# Two different builds can run on this machine, and they update independently:
#
#   - the IDE extension's bundled binary, which is what a VSCode session runs
#     (and the extension updater, not dp, decides its version)
#   - the mise install tree, which is what `claude` in a terminal runs (that is
#     the one `dp ai claude` installs and points `latest` at)
#
# Both are reported, and a model counts as recognized only when EVERY build in
# play knows it: the capability override is written for the oldest build that
# could serve the next session, and it is a no-op on a build that already knows
# the model. Reading one build only was the earlier mistake here: it reported a
# model as known while the IDE session was still on a build that had never
# heard of it.
claude_bins() {
  if [ -n "${KERU_CLAUDE_BIN:-}" ]; then
    [ -x "$KERU_CLAUDE_BIN" ] && echo "$KERU_CLAUDE_BIN"
    return
  fi
  local d newest candidates=()

  # IDE extension: several versions can sit side by side, and the newest is the
  # one VSCode loads, so only that one is in play.
  candidates=()
  for d in "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude \
           "$HOME"/.vscode-insiders/extensions/anthropic.claude-code-*/resources/native-binary/claude; do
    [ -x "$d" ] && candidates+=("$d")
  done
  if [ "${#candidates[@]}" -gt 0 ]; then
    newest="$(printf '%s\n' "${candidates[@]}" | sort -V | tail -1)"
    echo "$newest"
  fi

  # mise tree: `latest` is the symlink the dp plugin moves. Without it, the
  # highest version dir, sorted with -V because the names are lexically
  # misleading (2.1.9 sorts after 2.1.278).
  local root="$HOME/.local/share/mise/installs/claude"
  if [ -x "$root/latest/claude" ]; then
    echo "$root/latest/claude"
    return
  fi
  candidates=()
  for d in "$root"/*/claude; do
    [ -x "$d" ] && candidates+=("$d")
  done
  [ "${#candidates[@]}" -gt 0 ] || return 0
  printf '%s\n' "${candidates[@]}" | sort -V | tail -1
}

# Where a binary came from, for the report: the two launchers keep their own
# copies, and knowing which one is behind is the whole point of listing both.
bin_source() {
  case "$1" in
    *"/.vscode/extensions/"*|*"/.vscode-insiders/extensions/"*) echo "vscode-extension" ;;
    *"/mise/installs/claude/"*) echo "mise" ;;
    *) echo "other" ;;
  esac
}

claude_version() {
  local bin="$1"
  [ -n "$bin" ] && [ -x "$bin" ] || return 0
  "$bin" --version 2>/dev/null | awk '{print $1}'
}

# The mise copy alone, which is the one `dp ai claude` installs and the only one
# `cli` mode can move. The IDE extension updates itself and is out of scope
# here, so reporting its version as the update's before/after would be a lie.
mise_claude_bin() {
  claude_bins 2>/dev/null | grep "/mise/installs/claude/" | tail -1
}

# ---------------------------------------------------------------- cli mode ---
# The three steps the dp toolchain needs, in order: dp itself, then the `ai`
# plugin, then the CLI the plugin installs. Each is run separately so a failure
# names the step that failed instead of collapsing into one exit code.
if [ "$MODE" = "cli" ]; then
  command -v dp >/dev/null 2>&1 || { echo "error: dp not found" >&2; exit 1; }
  before="$(claude_version "$(mise_claude_bin || true)" || true)"
  status=0
  for step in "dp up" "dp plug up ai" "dp ai claude --version"; do
    echo "--- $step ---"
    # shellcheck disable=SC2086
    if ! $step; then
      echo "failed: $step" >&2
      status=1
      break
    fi
  done
  after="$(claude_version "$(mise_claude_bin || true)" || true)"
  jq -n --arg before "${before:-unknown}" --arg after "${after:-unknown}" \
        --argjson ok "$([ "$status" -eq 0 ] && echo true || echo false)" \
    '{mode:"cli", ok:$ok, scope:"the mise CLI (a terminal `claude`); the IDE extension ships its own build and updates itself",
      claude_version:{before:$before, after:$after},
      note:(if $before == $after
            then "already on the newest version the plugin installs"
            else "CLI updated; re-run `keru-claude-update audit`, a newer build may recognize more models" end)}'
  exit "$status"
fi

# ------------------------------------------------------------ shared reads ---
# Every build in play, and the model spellings they all agree on. KNOWN is the
# intersection, so `recognized` answers "known to whichever build serves the
# next session", not "known to the newest copy on disk".
BUILDS='[]'
KNOWN=''
while IFS= read -r bin; do
  [ -n "$bin" ] && [ -r "$bin" ] || continue
  spellings="$(LC_ALL=C grep -ao "claude-\(opus\|sonnet\|haiku\|fable\|mythos\)-[0-9][0-9-]*" "$bin" 2>/dev/null \
    | sed 's/-*$//' | LC_ALL=C sort -u | jq -R . | jq -s .)"
  [ -n "$spellings" ] || spellings='[]'
  if [ -z "$KNOWN" ]; then
    KNOWN="$spellings"
  else
    KNOWN="$(jq -n --argjson a "$KNOWN" --argjson b "$spellings" '$a - ($a - $b)')"
  fi
  BUILDS="$(jq -c --arg src "$(bin_source "$bin")" --arg bin "$bin" \
    --arg version "$(claude_version "$bin" || true)" \
    '. + [{source: $src, version: (if $version == "" then null else $version end), binary: $bin}]' \
    <<<"$BUILDS")"
done <<<"$(claude_bins || true)"
[ -n "$KNOWN" ] || KNOWN='[]'

command -v aws >/dev/null 2>&1 || { echo "error: aws not found, cannot read the model list" >&2; exit 1; }
PROFILES="$(aws bedrock list-inference-profiles --output json 2>/dev/null)" || {
  echo "error: 'aws bedrock list-inference-profiles' failed (expired credentials? run: dp awsso login)" >&2
  exit 1
}

# Catalogue: one entry per ACTIVE Anthropic profile under $PREFIX, newest first
# within each family. Version comes from the numeric segments of the id (two at
# most: `opus-5-5` is 5.5, `opus-5` is 5.0); an 8-digit segment is the snapshot
# date, kept only as a tiebreak. `canonical` is the id with the prefix, date and
# `-v1:0` suffix stripped, which is the spelling the CLI build uses internally.
CATALOGUE="$(jq --arg prefix "$PREFIX" --argjson known "$KNOWN" '
  [ .inferenceProfileSummaries[]
    | select(.status == "ACTIVE")
    | select(.inferenceProfileId | startswith($prefix + "anthropic.claude-"))
    | .inferenceProfileId as $id
    | ($id | ltrimstr($prefix + "anthropic.claude-") | split("-")) as $seg
    | ($seg[1:] | map(select(test("^[0-9]+$")))) as $nums
    | ($nums | map(select(length <= 2)) | map(tonumber)) as $ver
    | ($nums | map(select(length == 8)) | map(tonumber) | first // 0) as $date
    | select($ver | length > 0)
    | { id: $id,
        family: $seg[0],
        version: (($ver[0] | tostring) + (if ($ver[1] // 0) > 0 then "." + ($ver[1] | tostring) else "" end)),
        sort_key: [($ver[0] // 0), ($ver[1] // 0), $date],
        canonical: ("claude-" + $seg[0] + "-" + ($ver | map(tostring) | join("-"))),
        # 1M context is a capability assertion about the deployment, not
        # something the profile list reports: every current family but Haiku
        # (a 200K model) is offered with a [1m] spelling, and --no-1m opts out.
        supports_1m: ($seg[0] != "haiku") }
    | . as $m
    | . + { label: (($m.family | .[0:1] | ascii_upcase) + ($m.family | .[1:]) + " " + $m.version),
            recognized: (if ($known | length) == 0 then null else ($known | index($m.canonical)) != null end) } ]
  | sort_by(.family, .sort_key) | reverse' <<<"$PROFILES")"

# Newest per family, plus the runner-up Opus for the extra picker slot.
NEWEST="$(jq --argjson fams "$SLOT_FAMILIES" \
  '[ group_by(.family)[] | (sort_by(.sort_key) | reverse | .[0]) ]
   | map(select(.family as $f | $fams | index($f))) ' <<<"$CATALOGUE")"
RUNNER_UP="$(jq '[ .[] | select(.family == "opus") ] | sort_by(.sort_key) | reverse | .[1] // null' <<<"$CATALOGUE")"

# Desired env block. The capability list is the 4.6-and-later request surface
# (adaptive thinking, effort with xhigh/max, mid-conversation system messages);
# `temperature` is absent because those models reject it. It is attached only
# to an unrecognized id, and only for a generation that has that surface, so an
# unknown older model gets no invented capabilities.
DESIRED="$(jq -n --argjson newest "$NEWEST" --argjson runner "$RUNNER_UP" \
  --argjson want1m "$([ "$WANT_1M" -eq 1 ] && echo true || echo false)" '
  def caps($m):
    if $m.recognized == false
       and (($m.family == "opus" or $m.family == "fable" or $m.family == "mythos"
             or ($m.family == "sonnet" and ($m.sort_key[0] >= 5))))
    then "thinking,adaptive_thinking,interleaved_thinking,effort,xhigh_effort,max_effort,mid_conversation_system"
    else null end;
  def slot($m):
    ("ANTHROPIC_DEFAULT_" + ($m.family | ascii_upcase) + "_MODEL") as $k
    | { ($k): $m.id,
        ($k + "_NAME"): $m.label,
        ($k + "_DESCRIPTION"): ("Newest " + $m.label + " inference profile on this Bedrock account") }
      + (if caps($m) then { ($k + "_SUPPORTED_CAPABILITIES"): caps($m) } else {} end);
  ([ $newest[] | slot(.) ] | add // {})
  # The legacy small/fast var is read before the Haiku slot, so it has to agree.
  + ([ $newest[] | select(.family == "haiku") | { ANTHROPIC_SMALL_FAST_MODEL: .id } ] | add // {})
  # One extra picker entry, the previous Opus, and this is the one that carries
  # the [1m] spelling: the family slots stay bare, so the picker ends up with a
  # plain entry per family plus one explicit 1M entry to switch to, rather than
  # leaving the 1M form to whatever the build decides to offer per slot.
  + (if $runner then
       (($want1m and $runner.supports_1m) as $on
        | (if $on then $runner.id + "[1m]" else $runner.id end) as $cid
        | (if $on then $runner.label + " (1M)" else $runner.label end) as $clabel
        | { ANTHROPIC_CUSTOM_MODEL_OPTION: $cid,
            ANTHROPIC_CUSTOM_MODEL_OPTION_NAME: $clabel,
            ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION:
              ("Previous Opus generation" + (if $on then " with the 1M context window" else "" end) + ", kept selectable") }
          + (if caps($runner) then { ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES: caps($runner) } else {} end))
     else {} end)')"

# Every key this helper owns. A managed key present in settings but absent from
# DESIRED is removed, which is what makes the write idempotent and what strips
# ANTHROPIC_MODEL (never desired, and it would override the `model` pin).
MANAGED='["ANTHROPIC_MODEL","ANTHROPIC_DEFAULT_MODEL","ANTHROPIC_SMALL_FAST_MODEL",
  "ANTHROPIC_DEFAULT_OPUS_MODEL","ANTHROPIC_DEFAULT_OPUS_MODEL_NAME","ANTHROPIC_DEFAULT_OPUS_MODEL_DESCRIPTION","ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES",
  "ANTHROPIC_DEFAULT_SONNET_MODEL","ANTHROPIC_DEFAULT_SONNET_MODEL_NAME","ANTHROPIC_DEFAULT_SONNET_MODEL_DESCRIPTION","ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES",
  "ANTHROPIC_DEFAULT_HAIKU_MODEL","ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME","ANTHROPIC_DEFAULT_HAIKU_MODEL_DESCRIPTION","ANTHROPIC_DEFAULT_HAIKU_MODEL_SUPPORTED_CAPABILITIES",
  "ANTHROPIC_DEFAULT_FABLE_MODEL","ANTHROPIC_DEFAULT_FABLE_MODEL_NAME","ANTHROPIC_DEFAULT_FABLE_MODEL_DESCRIPTION","ANTHROPIC_DEFAULT_FABLE_MODEL_SUPPORTED_CAPABILITIES",
  "ANTHROPIC_CUSTOM_MODEL_OPTION","ANTHROPIC_CUSTOM_MODEL_OPTION_NAME","ANTHROPIC_CUSTOM_MODEL_OPTION_DESCRIPTION","ANTHROPIC_CUSTOM_MODEL_OPTION_SUPPORTED_CAPABILITIES"]'

CURRENT_ENV='{}'
CURRENT_MODEL=''
if [ -f "$SETTINGS" ]; then
  CURRENT_ENV="$(jq '.env // {}' "$SETTINGS" 2>/dev/null || echo '{}')"
  CURRENT_MODEL="$(jq -r '.model // ""' "$SETTINGS" 2>/dev/null || echo '')"
fi

# Resolve --pin to a model id. A family name takes the newest of that family,
# `custom` the runner-up, anything else is used verbatim (so a specific profile
# id, or a `[1m]` spelling, can be pinned without this helper knowing it).
resolve_pin() {
  case "$PIN" in
    none|"") echo ""; return ;;
    opus|sonnet|haiku|fable)
      jq -r --arg f "$PIN" '(.[] | select(.family == $f) | .id) // ""' <<<"$NEWEST" ;;
    custom) jq -r '.id // ""' <<<"$RUNNER_UP" ;;
    *) echo "$PIN" ;;
  esac
}
PIN_ID="$(resolve_pin)"
if [ "$PIN" != "none" ] && [ -z "$PIN_ID" ]; then
  echo "error: --pin '$PIN' matched no model in the catalogue" >&2
  exit 2
fi

# The pinned spelling. [1m] is appended only when asked for AND the family
# carries the 1M assertion, and never twice (a pin that already ends in [1m]
# stays as-is).
PIN_SPELLING=""
if [ -n "$PIN_ID" ]; then
  PIN_SPELLING="$PIN_ID"
  # `// true` would be wrong here: jq's alternative operator also fires on
  # false, which is exactly the Haiku case this has to respect. An id absent
  # from the catalogue (a literal --pin) is assumed to take the suffix.
  pin_1m_ok="$(jq -r --arg id "$PIN_ID" \
    '[ .[] | select(.id == $id) | .supports_1m ] | if length == 0 then true else .[0] end' <<<"$CATALOGUE")"
  case "$PIN_ID" in
    *"[1m]") ;;
    *) [ "$WANT_1M" -eq 1 ] && [ "$pin_1m_ok" = "true" ] && PIN_SPELLING="${PIN_ID}[1m]" ;;
  esac
fi

# The plan: one entry per key that would change, plus the model pin. Computed
# the same way in `audit` and `models`, so what the audit shows is what the
# write applies.
PLAN="$(jq -n --argjson desired "$DESIRED" --argjson current "$CURRENT_ENV" --argjson managed "$MANAGED" \
  --arg pin "$PIN_SPELLING" --arg model "$CURRENT_MODEL" '
  [ ($desired | to_entries[] | select(.value != ($current[.key] // null))
     | {key: .key, from: ($current[.key] // null), to: .value}),
    ($managed[] as $k | select(($current | has($k)) and (($desired | has($k)) | not))
     | {key: $k, from: $current[$k], to: null}) ]
  | { env: ., model: (if $pin == "" or $pin == $model then null
                      else {from: (if $model == "" then null else $model end), to: $pin} end) }')"

# ------------------------------------------------------------- audit mode ----
if [ "$MODE" = "audit" ]; then
  jq -n --argjson builds "$BUILDS" \
        --arg settings "$SETTINGS" --arg model "$CURRENT_MODEL" --arg prefix "$PREFIX" \
        --argjson catalogue "$CATALOGUE" --argjson newest "$NEWEST" --argjson runner "$RUNNER_UP" \
        --argjson plan "$PLAN" --argjson current "$CURRENT_ENV" --argjson managed "$MANAGED" \
        --argjson desired "$DESIRED" '
    { mode: "audit",
      # One row per build that can serve a session: the bundled IDE binary and
      # the mise CLI update on separate schedules, so a model can be known to
      # one and unknown to the other.
      claude_builds: $builds,
      settings: $settings,
      prefix: $prefix,
      pinned_model: (if $model == "" then null else $model end),
      # A pin that no longer matches any catalogue id (a retired profile, or a
      # model the account lost access to) is the thing worth seeing first. Null
      # when nothing is pinned, which is not the same as a pin gone missing.
      pinned_model_in_catalogue: (if $model == "" then null
        else ($catalogue | map(.id) | index($model | sub("\\[1m\\]$"; ""))) != null end),
      overridden_by_env: ($current.ANTHROPIC_MODEL // null),
      newest_per_family: ($newest | map({family, label, id, recognized, supports_1m})),
      # Reported as it will be written (the [1m] spelling), not as the bare
      # catalogue row, so the audit and the write cannot read differently.
      extra_picker_entry: (if $runner then
        { label: $desired.ANTHROPIC_CUSTOM_MODEL_OPTION_NAME,
          id: $desired.ANTHROPIC_CUSTOM_MODEL_OPTION,
          recognized: $runner.recognized } else null end),
      catalogue: ($catalogue | map({family, label, id, recognized, supports_1m})),
      current_env: ($current | with_entries(select(.key as $k | $managed | index($k)))),
      plan: $plan }'
  exit 0
fi

# ------------------------------------------------------------ models mode ----
[ -f "$SETTINGS" ] || { echo "error: $SETTINGS not found" >&2; exit 1; }

BACKUP="$SETTINGS.keru-claude-update.bak"
cp "$SETTINGS" "$BACKUP"

# Beside the settings file, not in TMPDIR: same filesystem means the `mv` below
# is an atomic rename, so an interrupted write cannot leave a half-written
# settings file (the one holding the secrets) behind.
TMP="$(mktemp "$SETTINGS.XXXXXX")"
trap 'rm -f "$TMP"' EXIT

jq --argjson desired "$DESIRED" --argjson managed "$MANAGED" --arg pin "$PIN_SPELLING" '
  .env = (((.env // {}) + $desired)
          | with_entries(. as $e | select((($managed | index($e.key)) == null)
                                          or ($desired | has($e.key)))))
  | if $pin == "" then . else .model = $pin end' "$SETTINGS" > "$TMP"

# A malformed write must never replace a settings file that holds secrets, so
# the result is parsed (and checked for the env block) before it is moved in.
jq -e '.env | type == "object"' "$TMP" >/dev/null 2>&1 || {
  echo "error: refusing to write, the merged settings did not parse as expected (kept $BACKUP)" >&2
  exit 1
}
mv "$TMP" "$SETTINGS"
trap - EXIT

jq -n --argjson plan "$PLAN" --arg settings "$SETTINGS" --arg backup "$BACKUP" \
      --arg pin "$PIN_SPELLING" --argjson newest "$NEWEST" '
  { mode: "models", settings: $settings, backup: $backup,
    applied: $plan,
    pinned_model: (if $pin == "" then null else $pin end),
    newest_per_family: ($newest | map({family, label, id, recognized})),
    note: "restart the Claude Code session to pick this up; settings env is read at startup" }'
