#!/usr/bin/env bash
# Snapshot a Jira ticket and its chain to a reusable file, and verify later that the
# snapshot is still current. Walking the chain is mechanical (fetch the issue, read
# its parent/epic/links, fetch those, ask the dev panel for PRs), so it needs no
# model at all: this helper does it deterministically and hands back a file plus a
# small JSON summary, instead of 40K of ticket text landing in the conversation.
#
# Why a snapshot is legitimate here, when caching code is not: a ticket is treated
# as a contract that mostly stops moving once the work starts, while code moves
# under you constantly. But "should not change" is not "did not change", so the file
# carries a validation header (per key: updated, comment count, link count) and
# `check` re-reads those three from Jira before the copy is reused. What that does
# and does not prove, exactly: it catches a field or description edit (which moves
# `updated`), an added or deleted comment, and an added or removed link; it does NOT
# catch an edit to an existing comment that leaves both the count and `updated`
# untouched. The counts are stored rather than trusting `updated` alone because
# whether a new comment bumps `updated` was never confirmed on this Jira.
#
# Usage: keru-context-snapshot <mode> <ISSUE-KEY>
#   write <KEY>   walk the chain and write /tmp/keru-context-<KEY>.md (overwrites)
#   check <KEY>   re-read the validation triple for every key in that file and
#                 report `current` or which keys moved (exit 0 current, 3 stale)
#   path  <KEY>   print the snapshot path and whether it exists
#
# Both modes only read Jira; `write` writes exactly one file, under /tmp, keyed by
# the issue. Nothing else is created or removed, which is why the Bash gate can
# auto-approve every mode (local, reversible, bounded path).
#
# NOT in the snapshot, on purpose: PR diffs, file contents, CI logs. Those move
# under you, and a stale copy of a diff makes you review code that no longer
# exists. The snapshot carries the pointer (PR number, branch, url) and the content
# is read live.
set -uo pipefail

MODE="${1:-}"
KEY="${2:-}"
case "$MODE" in
  write|check|path) ;;
  -h|--help|help) sed -n '1,28p' "$0" | grep -E '^# (Usage|  )' | sed 's/^# //'; exit 0 ;;
  *) echo "usage: keru-context-snapshot <write|check|path> <ISSUE-KEY>" >&2; exit 2 ;;
esac
# Same key validation as keru-jira-dev: no flags, URLs or shell metacharacters
# reach a request or a filename.
if ! printf '%s' "$KEY" | grep -qE '^[A-Z][A-Z0-9]+-[0-9]+$'; then
  echo "error: '$KEY' is not a valid issue key (expected like DBI-1234)" >&2
  exit 2
fi

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }
command -v jira >/dev/null 2>&1 || { echo "error: jira CLI not found" >&2; exit 1; }

FILE="/tmp/keru-context-${KEY}.md"

if [ "$MODE" = "path" ]; then
  jq -n --arg f "$FILE" --argjson e "$([ -f "$FILE" ] && echo true || echo false)" \
    '{file: $f, exists: $e}'
  exit 0
fi

# The validation triple for one key: what can change on a ticket after work starts.
# `updated` alone is not enough: it is not confirmed that a new comment bumps it,
# so the counts are read directly rather than inferred from a timestamp.
triple() {  # triple KEY -> one JSON object, or empty when the fetch is unusable
  local raw out
  raw="$(jira issue view "$1" --raw 2>/dev/null)"
  # `jira` can print a banner or an error on stdout, which is not JSON: feeding that
  # to jq downstream produces garbage that then breaks --argjson at the caller.
  jq -e '.fields' >/dev/null 2>&1 <<<"$raw" || return 1
  out="$(jq -c --arg k "$1" \
    '{key: $k, updated: (.fields.updated // "unknown"),
      comments: ((.fields.comment.comments // []) | length),
      links: ((.fields.issuelinks // []) | length)}' <<<"$raw" 2>/dev/null)"
  jq -e . >/dev/null 2>&1 <<<"$out" || return 1
  printf '%s' "$out"
}

# ============================================================================
# CHECK: is the snapshot still a faithful copy of Jira?
# ============================================================================
if [ "$MODE" = "check" ]; then
  [ -f "$FILE" ] || { jq -n --arg f "$FILE" '{status:"missing", file:$f}'; exit 3; }
  # The header block is the machine-checkable part written by `write`. Read only the
  # FIRST block and stop: the file also carries raw ticket text further down, and a
  # ticket that happens to quote this marker (a ticket about this helper) would
  # otherwise re-open the range and corrupt the header.
  stored="$(awk '/^<!--keru-validate$/{f=1;next} /^keru-validate-->$/{if(f)exit} f' "$FILE")"
  [ -n "$stored" ] || { jq -n --arg f "$FILE" '{status:"unreadable", file:$f,
      reason:"no validation header; rewrite with: keru-context-snapshot write"}'; exit 3; }
  keys="$(jq -r 'if type == "array" then (.[] | .key | select(type == "string")) else empty end' <<<"$stored" 2>/dev/null)"
  [ -n "$keys" ] || { jq -n '{status:"unreadable", reason:"validation header is not the expected JSON array"}'; exit 3; }
  # A key that cannot be fetched is tracked separately from one that changed. They
  # are different facts: "the ticket moved" and "I could not tell" must not share an
  # answer, or an expired token reads as every ticket having been edited.
  live="[]"; unfetched="[]"
  while IFS= read -r k; do
    [ -n "$k" ] || continue
    if t="$(triple "$k")" && [ -n "$t" ]; then
      live="$(jq -c --argjson t "$t" '. + [$t]' <<<"$live")"
    else
      unfetched="$(jq -c --arg k "$k" '. + [$k]' <<<"$unfetched")"
    fi
  done <<<"$keys"
  # One evaluation produces both the report and the exit status, so the status
  # printed can never disagree with the code returned.
  report="$(jq -n --argjson stored "$stored" --argjson live "$live" \
                  --argjson unfetched "$unfetched" --arg f "$FILE" '
    [$live[] as $l | ($stored[] | select(.key == $l.key)) as $s
     | {key: $l.key,
        moved: (($s.updated != $l.updated) or ($s.comments != $l.comments) or ($s.links != $l.links)),
        was: {updated: $s.updated, comments: $s.comments, links: $s.links},
        now: {updated: $l.updated, comments: $l.comments, links: $l.links}}] as $cmp
    | [$cmp[] | select(.moved)] as $moved
    | {status: (if ($cmp | length) == 0 then "unreadable"
                elif ($moved | length) > 0 then "stale"
                elif ($unfetched | length) > 0 then "unverified"
                else "current" end),
       file: $f,
       checked: ($cmp | length),
       stale_keys: [$moved[] | .key],
       unfetched_keys: $unfetched,
       detail: $moved,
       note: "current means every key matched on updated + comment count + link count; the body itself was not re-read, and an edit to an existing comment that leaves the count and the timestamp unchanged would not be caught"}')"
  if [ -z "$report" ]; then
    jq -n '{status:"unreadable", reason:"could not compare the header against Jira"}'
    exit 3
  fi
  printf '%s\n' "$report"
  case "$(jq -r '.status' <<<"$report")" in
    current) exit 0 ;;
    unverified) exit 4 ;;
    *) exit 3 ;;
  esac
fi

# ============================================================================
# WRITE: walk the chain once, deterministically, and write the snapshot.
# ============================================================================
root_raw="$(jira issue view "$KEY" --raw 2>/dev/null)"
if [ -z "$root_raw" ] || ! jq -e '.fields' >/dev/null 2>&1 <<<"$root_raw"; then
  echo "error: could not read $KEY (is the key right and jira configured?)" >&2
  exit 1
fi

# Every key one hop out: parent, epic, and each side of every issue link.
chain_keys="$(jq -r '
  [ (.fields.parent.key // empty),
    (.fields.epic.key // empty),
    (.fields.customfield_10014 // empty),
    (.fields.issuelinks[]? | (.inwardIssue.key // .outwardIssue.key // empty)) ]
  | map(select(type == "string" and test("^[A-Z][A-Z0-9]+-[0-9]+$"))) | unique | .[]' <<<"$root_raw")"

# Fetch each linked issue once. These are independent, but a helper stays serial on
# purpose: it is bounded (one hop), and a background job per key would make the
# failure modes worse than the wait it saves.
linked_json="[]"; unfetched_json="[]"
while IFS= read -r k; do
  [ -n "$k" ] || continue
  raw="$(jira issue view "$k" --raw 2>/dev/null)"
  # Validated the same way as the root: a banner or an error message on stdout is
  # not JSON, and silently dropping the key would leave a snapshot that `check`
  # later calls `current` while a ticket of the chain is simply missing from it.
  if ! jq -e '.fields' >/dev/null 2>&1 <<<"$raw"; then
    unfetched_json="$(jq -c --arg k "$k" '. + [$k]' <<<"$unfetched_json")"
    continue
  fi
  linked_json="$(jq -c --argjson l "$linked_json" '
    $l + [{key: (.key // "?"),
           type: (.fields.issuetype.name // "?"),
           status: (.fields.status.name // "?"),
           summary: (.fields.summary // ""),
           updated: (.fields.updated // "unknown"),
           comments: ((.fields.comment.comments // []) | length),
           links: ((.fields.issuelinks // []) | length),
           description: ((.fields.description // "") | tostring)}]' <<<"$raw")"
done <<<"$chain_keys"

# The dev panel is the accurate source for linked PRs; it is not in the issue JSON.
prs_json='{"pullRequests":[],"branches":[]}'
if command -v keru-jira-dev >/dev/null 2>&1; then
  dev="$(keru-jira-dev "$KEY" 2>/dev/null)"
  if [ -n "$dev" ] && jq -e '.pullRequests' >/dev/null 2>&1 <<<"$dev"; then
    prs_json="$dev"
  fi
fi

# Validation header: the root plus every key in the chain.
validate="$(jq -c --argjson linked "$linked_json" '
  [{key: (.key // "?"), updated: (.fields.updated // "unknown"),
    comments: ((.fields.comment.comments // []) | length),
    links: ((.fields.issuelinks // []) | length)}]
  + [$linked[] | {key, updated, comments, links}]' <<<"$root_raw")"

{
  printf '# Context snapshot: %s\n\n' "$KEY"
  printf '<!--keru-validate\n%s\nkeru-validate-->\n\n' "$validate"
  printf 'Fetched: %s. This is a copy, not the source: run `keru-context-snapshot check %s`\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$KEY"
  printf 'before reusing it, and treat `current` as "these keys did not move", not as\n'
  printf '"nothing about the work changed". PR diffs and file contents are NOT here on\n'
  printf 'purpose (they move under you) and must be read live every time.\n\n'
  if [ "$(jq -r 'length' <<<"$unfetched_json")" != "0" ]; then
    printf 'INCOMPLETE: these linked keys could not be fetched and are missing from this\n'
    printf 'snapshot: %s. Read them from Jira directly.\n\n' "$(jq -r 'join(", ")' <<<"$unfetched_json")"
  fi

  jq -r '"## " + (.key // "?") + " (" + (.fields.issuetype.name // "?") + ", " + (.fields.status.name // "?") + ")\n\n"
    + "**" + (.fields.summary // "") + "**\n\n"
    + "- assignee: " + ((.fields.assignee.displayName) // "unassigned")
    + "\n- updated: " + (.fields.updated // "unknown")
    + (if (.fields.parent.key // "") != "" then "\n- parent: " + .fields.parent.key + " " + ((.fields.parent.fields.summary) // "") else "" end)
    + "\n\n### Description\n\n" + ((.fields.description // "(empty)") | tostring) + "\n"' <<<"$root_raw"

  echo
  echo "### Comments"
  echo
  jq -r 'if ((.fields.comment.comments // []) | length) == 0 then "(none)"
         else (.fields.comment.comments[] | "- **" + ((.author.displayName) // "?") + "** (" + (.created // "?") + "): " + ((.body // "") | tostring)) end' <<<"$root_raw"

  echo
  echo "## Chain (one hop out)"
  echo
  jq -r --argjson unfetched "$unfetched_json" 'if length == 0 then
           (if ($unfetched | length) > 0
            then "(the linked issues could not be fetched: " + ($unfetched | join(", ")) + ")"
            else "(no parent, epic or linked issues)" end)
         else (.[] | "### " + .key + " (" + .type + ", " + .status + ")\n\n**" + .summary + "**\n\n- updated: " + .updated + "\n\n" + (if .description == "" then "(no description)" else .description end) + "\n") end' <<<"$linked_json"

  echo
  echo "## Pull requests (Jira dev panel)"
  echo
  jq -r 'if ((.pullRequests // []) | length) == 0 then "(none linked in the panel; search GitHub by key instead)"
         else (.pullRequests[] | "- " + ((.status) // "?") + " " + ((.name) // "?") + " branch=" + ((.branch) // "?") + " " + ((.url) // "")) end' <<<"$prs_json"
} >"$FILE" || { echo "error: could not write $FILE" >&2; exit 1; }

# Nothing above uses `set -e`, so confirm the file actually landed rather than
# reporting success and letting an empty byte count break the summary itself.
bytes="$(wc -c <"$FILE" 2>/dev/null | tr -d ' ')"
case "${bytes:-}" in ''|*[!0-9]*) echo "error: $FILE was not written" >&2; exit 1 ;; esac

jq -n --arg f "$FILE" --arg root "$KEY" --argjson v "$validate" --argjson prs "$prs_json" \
  --argjson bytes "$bytes" --argjson unfetched "$unfetched_json" '
  {file: $f, root: $root, keys: [$v[].key], bytes: $bytes,
   unfetched_keys: $unfetched,
   pull_requests: [($prs.pullRequests // [])[] | {status, branch, url}],
   note: "chain written to the file; read the sections you need from it (Read with offset/limit) instead of pulling it all into context. Re-verify with: keru-context-snapshot check " + $root}'
