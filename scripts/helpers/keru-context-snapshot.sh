#!/usr/bin/env bash
# Snapshot a Jira ticket and its chain to a reusable file, and verify later that the
# snapshot is still current. Walking the chain is mechanical (fetch the issue, read
# its parent/epic/links, fetch those, look up the keys their text mentions, ask the
# dev panel for PRs), so it needs no model at all: this helper does it
# deterministically and hands back a file plus a small JSON summary.
#
# Why a snapshot is legitimate here, when caching code is not: a ticket is treated
# as a contract that mostly stops moving once the work starts, while code moves
# under you constantly. But "should not change" is not "did not change", so the file
# carries a validation header (per key: updated, status, comment count, link count)
# and `check` re-reads those four from Jira before the copy is reused. What that does
# and does not prove, exactly: it catches a field or description edit (which moves
# `updated`), a workflow transition, an added or deleted comment, and an added or
# removed link; it does NOT catch an edit to an existing comment that leaves both the
# count and `updated` untouched. The counts and the status are stored rather than
# trusting `updated` alone because whether a new comment or a transition bumps
# `updated` was never confirmed on this Jira, and a dependency's workflow state
# (is the blocker closed yet?) is exactly what a reader acts on, so it must be
# validated rather than re-fetched by hand on the side.
#
# Usage: keru-context-snapshot <mode> <ISSUE-KEY>
#   write <KEY>   walk the chain and write <config>/keru-context/<KEY>.md (overwrites)
#   check <KEY>   re-read the validation fingerprint for every key in that file and
#                 report `current` or which keys moved (exit 0 current, 3 stale).
#                 On `current` it also touches the file, so its mtime records when
#                 the copy was last verified (keru-artifacts-prune reads that).
#   path  <KEY>   print the snapshot path and whether it exists
#
# Ticket text is rendered from ADF to markdown: read as one 15K line of JSON, it gets skimmed.
# Keys the text mentions without a link are listed as pointers, since an investigation is
# often only named in a sibling's description.
#
# Every mode only reads Jira; on disk, `write` writes exactly one file under the
# Claude config dir keyed by the issue, and `check` updates that same file's
# timestamp. Nothing else is created or removed, which is why the Bash gate can
# auto-approve every mode (local, reversible, bounded path).
#
# Why not /tmp, where this used to live: a snapshot there does not survive a
# reboot. Checked on 2026-09-22: DBI-1669 was snapshotted four times the previous
# afternoon and `check` reported `missing` the next morning, with nothing
# user-owned left in /private/tmp from before the 09:36 boot. The daily
# /usr/libexec/tmp_cleaner is not the cause (it only collects what has been
# untouched for 3 days), so the lifetime of /tmp here is one boot, which is
# shorter than the work it was meant to outlive. Nothing collects the new
# location, so `keru-artifacts-prune` does that on purpose, by hand.
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
  -h|--help|help) sed -n '1,40p' "$0" | grep -E '^# (Usage|  )' | sed 's/^# //'; exit 0 ;;
  *) echo "usage: keru-context-snapshot <write|check|path> <ISSUE-KEY>" >&2; exit 2 ;;
esac
# Same key validation as keru-jira-dev: no flags, URLs or shell metacharacters
# reach a request or a filename.
# Matched with bash's own operator rather than `grep -E`: grep applies `^...$` per
# LINE, so a key carrying an embedded newline ("DBI-1\n../x") passes a grep check
# while contributing a second path component to the filename below. `=~` anchors
# against the whole string, which is what "bounded path" has to mean.
if [[ ! "$KEY" =~ ^[A-Z][A-Z0-9]+-[0-9]+$ ]]; then
  echo "error: '$KEY' is not a valid issue key (expected like DBI-1234)" >&2
  exit 2
fi

command -v jq >/dev/null 2>&1 || { echo "error: jq not found" >&2; exit 1; }
command -v jira >/dev/null 2>&1 || { echo "error: jira CLI not found" >&2; exit 1; }

DIR="${CLAUDE_CONFIG_DIR:-${HOME:-/nonexistent}/.claude}/keru-context"
FILE="$DIR/${KEY}.md"
FORMAT_MARK='<!--keru-format: 2-->'

# Headings render bold, not `#`, so they cannot pose as one of the file's own sections.
ADF_JQ='
def adf:
  if type == "string" then .
  elif type == "array" then map(adf) | join("")
  elif type != "object" then ""
  elif .type == "text" then
    (.text // "") as $t | [.marks[]?.type] as $m
    | ([.marks[]? | select(.type == "link") | .attrs.href][0] // "") as $href
    | (if ($m | index("code")) then "`" + $t + "`" else $t end)
      + (if $href != "" then " <" + $href + ">" else "" end)
  elif .type == "hardBreak" then "\n"
  elif .type == "paragraph" then (.content | adf) + "\n\n"
  elif .type == "heading" then "**" + (.content | adf) + "**\n\n"
  elif .type == "expand" or .type == "nestedExpand" then "**" + (.attrs.title // "") + "**\n\n" + (.content | adf)
  elif .type == "bulletList" then
    ([.content[]? | "- " + ((.content | adf) | gsub("\n\n+"; "\n") | sub("\\s+$"; "") | gsub("\n"; "\n  "))] | join("\n")) + "\n\n"
  elif .type == "taskList" or .type == "decisionList" then
    ([.content[]? | select(type == "object")
      | (if .type == "decisionItem" then "- decision: " elif .attrs.state == "DONE" then "- [x] " else "- [ ] " end)
        + ((.content | adf) | gsub("\n\n+"; "\n") | sub("\\s+$"; "") | gsub("\n"; "\n  "))] | join("\n")) + "\n\n"
  elif .type == "orderedList" then
    ((.attrs.order // 1) | tonumber? // 1) as $start
    | ([.content[]? | (.content | adf) | gsub("\n\n+"; "\n") | sub("\\s+$"; "") | gsub("\n"; "\n   ")]
     | to_entries | map("\(.key + $start). " + .value) | join("\n")) + "\n\n"
  elif .type == "codeBlock" then "```" + (.attrs.language // "") + "\n" + (.content | adf) + "\n```\n\n"
  elif .type == "blockquote" then ((.content | adf) | sub("\\s+$"; "") | split("\n") | map("> " + .) | join("\n")) + "\n\n"
  elif .type == "rule" then "---\n\n"
  elif .type == "table" then
    [.content[]? | [.content[]? | (.content | adf) | sub("\\s+$"; "") | gsub("\n+"; " ") | gsub("\\|"; "\\|")]] as $rows
    | ([$rows[] | "| " + join(" | ") + " |"]
       | if length > 0 then .[:1] + ["|" + ($rows[0] | map(" --- |") | join(""))] + .[1:] else . end
       | join("\n")) + "\n\n"
  elif .type == "inlineCard" or .type == "blockCard" or .type == "embedCard" then (.attrs.url // "")
  elif .type == "mention" then (.attrs.text // "@someone")
  elif .type == "emoji" then (.attrs.text // .attrs.shortName // "")
  elif .type == "status" then "[" + (.attrs.text // "") + "]"
  elif .type == "date" then ((.attrs.timestamp // "") | (tonumber? / 1000 | strftime("%Y-%m-%d")) // .)
  elif .type == "media" or .type == "mediaSingle" or .type == "mediaGroup" then "[attachment]\n\n"
  elif (.content | type) == "array" and (.content | length) > 0 then (.content | adf) + "\n\n"
  else (.content | adf) end;
def adf_doc: try (adf | gsub("\n{3,}"; "\n\n") | sub("\\s+$"; ""))
  catch "(this text could not be rendered: read it with `jira issue view`)";
'
# Prefixes shaped like issue keys that are standards, encodings or licenses, not tickets.
NOT_TICKETS_JQ='["UTF","SHA","ISO","IEC","RFC","AES","RSA","DSA","TLS","SSL","HTTP","MD","CRC","UUID","IPV","CVE","CWE","GHSA","PYSEC","RUSTSEC","FIPS","NIST","PKCS","CP","ECDSA","ED","HS","RS","ES","PS","PEP","KIP","UTC","GMT","IEEE","ANSI","ECMA","ASCII","GPT","AWS","BSD","MPL","GPL","LGPL","AGPL","MIT","CC","OWASP","CIS","SOC","PCI","ARM","AVX","INT","UINT","GO","COVID","HTML","CSS","SQL","IE","AMD","BASE","OAUTH","TCP","UDP","DNS","API","JSON","XML","PDF","JDK"]'

if [ "$MODE" = "path" ]; then
  jq -n --arg f "$FILE" --argjson e "$([ -f "$FILE" ] && echo true || echo false)" \
    '{file: $f, exists: $e}'
  exit 0
fi

# The validation fingerprint for one key: what can change on a ticket after work
# starts. `updated` alone is not enough: it is not confirmed that a new comment or a
# transition bumps it, so the status and the counts are read directly rather than
# inferred from a timestamp.
fingerprint() {  # fingerprint KEY -> one JSON object, or empty when the fetch is unusable
  local raw out
  raw="$(jira issue view "$1" --raw 2>/dev/null)"
  # `jira` can print a banner or an error on stdout, which is not JSON: feeding that
  # to jq downstream produces garbage that then breaks --argjson at the caller.
  jq -e '.fields' >/dev/null 2>&1 <<<"$raw" || return 1
  out="$(jq -c --arg k "$1" \
    '{key: $k, updated: (.fields.updated // "unknown"),
      status: (.fields.status.name // "unknown"),
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
  # An older raw-JSON snapshot still matches Jira on every key, so it would read `current` forever.
  if [ "$(awk '/^keru-validate-->$/{getline; print; exit}' "$FILE")" != "$FORMAT_MARK" ]; then
    jq -n --arg f "$FILE" --arg k "$KEY" '{status:"stale", file:$f, stale_keys:[],
      reason:("older snapshot format (raw Jira JSON); rewrite with: keru-context-snapshot write " + $k)}'
    exit 3
  fi
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
    if t="$(fingerprint "$k")" && [ -n "$t" ]; then
      live="$(jq -c --argjson t "$t" '. + [$t]' <<<"$live")"
    else
      unfetched="$(jq -c --arg k "$k" '. + [$k]' <<<"$unfetched")"
    fi
  done <<<"$keys"
  # The same `investigations` list `write` returns, read back from the file's headings
  # and pointer lines, so a reused snapshot does not hide them.
  inv="$(grep -oE '^(### |- )[A-Z][A-Z0-9]+-[0-9]+ \(Investigation,' "$FILE" \
         | grep -oE '[A-Z][A-Z0-9]+-[0-9]+' | jq -Rsc 'split("\n") | map(select(length > 0)) | unique')"
  # One evaluation produces both the report and the exit status, so the status
  # printed can never disagree with the code returned.
  report="$(jq -n --argjson stored "$stored" --argjson live "$live" \
                  --argjson unfetched "$unfetched" --arg f "$FILE" --argjson inv "${inv:-[]}" '
    [$live[] as $l | ($stored[] | select(.key == $l.key)) as $s
     | ($s.status // "unknown") as $was_status
     | {key: $l.key,
        moved: (($s.updated != $l.updated) or ($was_status != $l.status)
                or ($s.comments != $l.comments) or ($s.links != $l.links)),
        was: {updated: $s.updated, status: $was_status, comments: $s.comments, links: $s.links},
        now: {updated: $l.updated, status: $l.status, comments: $l.comments, links: $l.links}}] as $cmp
    | [$cmp[] | select(.moved)] as $moved
    | {status: (if ($cmp | length) == 0 then "unreadable"
                elif ($moved | length) > 0 then "stale"
                elif ($unfetched | length) > 0 then "unverified"
                else "current" end),
       file: $f,
       checked: ($cmp | length),
       stale_keys: [$moved[] | .key],
       unfetched_keys: $unfetched,
       investigations: $inv,
       detail: $moved,
       note: "current means every key matched on updated + status + comment count + link count, so a dependency that has since been closed or reopened reads as stale and does not need a separate status re-fetch; the body itself was not re-read, and an edit to an existing comment that leaves the count and the timestamp unchanged would not be caught. A header written before status was validated shows was.status=unknown and reports stale once: rewrite it"}')"
  if [ -z "$report" ]; then
    jq -n '{status:"unreadable", reason:"could not compare the header against Jira"}'
    exit 3
  fi
  printf '%s\n' "$report"
  case "$(jq -r '.status' <<<"$report")" in
    current)
      # Touch it, so mtime means "last verified" and not "first written". That is
      # what keru-artifacts-prune measures, and atime cannot carry it: on this
      # volume a read refreshes atime only while atime is older than mtime, so
      # every read after the first leaves it frozen. Without this, a snapshot
      # verified daily on a long-running ticket would still age out by the
      # calendar. Timestamp only; the contents are untouched.
      touch "$FILE" 2>/dev/null || true
      exit 0 ;;
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

rels_json="$(jq -c '
  ([ (.fields.parent.key // empty | {key: ., rel: "parent of this ticket"}),
     (.fields.epic.key // .fields.customfield_10014 // empty | select(type == "string") | {key: ., rel: "epic of this ticket"}),
     (.fields.issuelinks[]? | if .inwardIssue then {key: .inwardIssue.key, rel: ("this ticket " + (.type.inward // "links to") + " it")}
                              else {key: .outwardIssue.key, rel: ("this ticket " + (.type.outward // "links to") + " it")} end) ]
   | group_by(.key) | map({key: .[0].key, value: (map(.rel) | unique | join(", "))}) | from_entries)' <<<"$root_raw" 2>/dev/null)"
[ -n "$rels_json" ] || rels_json='{}'

# Fetch each linked issue once. These are independent, but a helper stays serial on
# purpose: it is bounded (one hop, plus at most 25 mentioned keys below), and a
# background job per key would make the failure modes worse than the wait it saves.
# The linked items, with their rendered text, can pass the OS argument-size limit,
# so they travel as lines and through /dev/fd (--slurpfile), never as one argument.
linked_lines=""; unfetched_json="[]"
while IFS= read -r k; do
  [ -n "$k" ] || continue
  raw="$(jira issue view "$k" --raw 2>/dev/null)"
  # Validated the same way as the root: a banner or an error message on stdout is
  # not JSON. An unfetched key still goes in the validation header (below), so
  # `check` reads the snapshot as stale instead of `current` with a ticket missing.
  if ! jq -e '.fields' >/dev/null 2>&1 <<<"$raw"; then
    unfetched_json="$(jq -c --arg k "$k" '. + [$k]' <<<"$unfetched_json")"
    continue
  fi
  next="$(jq -c --argjson rels "$rels_json" "$ADF_JQ"'
    {key: (.key // "?"),
           rel: ($rels[.key // ""] // "linked"),
           type: (.fields.issuetype.name // "?"),
           status: (.fields.status.name // "?"),
           summary: (.fields.summary // ""),
           updated: (.fields.updated // "unknown"),
           comments: ((.fields.comment.comments // []) | length),
           links: ((.fields.issuelinks // []) | length),
           description: ((.fields.description // "") | adf_doc),
           comment_text: [(.fields.comment.comments // [])[]
                          | "#### " + ((.author.displayName) // "?") + " (" + (.created // "?") + ")\n\n"
                            + ((.body // "") | adf_doc)]}' <<<"$raw" 2>/dev/null)"
  if [ -n "$next" ]; then
    linked_lines+="$next"$'\n'
  else
    unfetched_json="$(jq -c --arg k "$k" '. + [$k]' <<<"$unfetched_json")"
  fi
done <<<"$chain_keys"
linked_json="$(jq -sc . <<<"$linked_lines")"
[ -n "$linked_json" ] || linked_json='[]'

# Root mentions sort first, so the cap drops the farthest ones; the dropped ones are named.
all_mentions="$(jq -c --arg root "$KEY" --slurpfile linked <(printf '%s' "$linked_json") \
    --argjson chain "$(jq -Rsc 'split("\n") | map(select(length > 0))' <<<"$chain_keys")" \
    --argjson skip "$NOT_TICKETS_JQ" "$ADF_JQ"'
  $linked[0] as $linked
  | ([{src: $root, text: (.fields.summary // "")}, {src: $root, text: ((.fields.description // "") | adf_doc)}]
   + [(.fields.comment.comments // [])[] | {src: $root, text: ((.body // "") | adf_doc)}]
   + [$linked[] | {src: .key, text: ([.description] + .comment_text | join("\n"))}]) as $texts
  | ([$root] + $chain) as $known
  | [$texts[] | .src as $s
     | (.text | [scan("\\b[A-Z]{2,10}-[0-9]+\\b(?![.-][A-Za-z0-9])")] | unique[]) | {k: ., src: $s}]
  | map(select((.k as $k | $known | index($k) | not) and ((.k | split("-")[0]) as $p | $skip | index($p) | not)))
  | group_by(.k) | map({key: .[0].k, from: (map(.src) | unique)})
  | sort_by([(.from | index($root) | not), .key])' <<<"$root_raw" 2>/dev/null)"
[ -n "$all_mentions" ] || all_mentions='[]'
mention_keys="$(jq -r '.[:25][] | .key + " " + (.from | join(","))' <<<"$all_mentions")"
mention_dropped="$(jq -c '[.[25:][] | .key]' <<<"$all_mentions")"

mentioned_json="[]"; mention_unreadable="[]"
while read -r k from; do
  [ -n "$k" ] || continue
  raw="$(jira issue view "$k" --raw 2>/dev/null)"
  if ! jq -e '.fields' >/dev/null 2>&1 <<<"$raw"; then
    mention_unreadable="$(jq -c --arg k "$k" '. + [$k]' <<<"$mention_unreadable")"
    continue
  fi
  mentioned_json="$(jq -c --argjson m "$mentioned_json" --arg from "$from" '
    $m + [{key: (.key // "?"), type: (.fields.issuetype.name // "?"),
           status: (.fields.status.name // "?"), summary: (.fields.summary // ""),
           from: ($from | split(","))}]' <<<"$raw")"
done <<<"$mention_keys"

# The dev panel is the accurate source for linked PRs; it is not in the issue JSON.
prs_json='{"pullRequests":[],"branches":[]}'
if command -v keru-jira-dev >/dev/null 2>&1; then
  dev="$(keru-jira-dev "$KEY" 2>/dev/null)"
  if [ -n "$dev" ] && jq -e '.pullRequests' >/dev/null 2>&1 <<<"$dev"; then
    prs_json="$dev"
  fi
fi

# Validation header: the root plus every key in the chain, an unfetched one with a
# fingerprint no live ticket can match.
validate="$(jq -c --slurpfile linked <(printf '%s' "$linked_json") --argjson unf "$unfetched_json" '
  [{key: (.key // "?"), updated: (.fields.updated // "unknown"),
    status: (.fields.status.name // "unknown"),
    comments: ((.fields.comment.comments // []) | length),
    links: ((.fields.issuelinks // []) | length)}]
  + [$linked[0][] | {key, updated, status, comments, links}]
  + [$unf[] | {key: ., updated: "unfetched", status: "unfetched", comments: -1, links: -1}]' <<<"$root_raw")"

# Created here rather than at install time so the helper also works when it is run
# from the repo, before any installer has touched this machine.
mkdir -p "$DIR" 2>/dev/null || { echo "error: could not create $DIR" >&2; exit 1; }

{
  printf '# Context snapshot: %s\n\n' "$KEY"
  printf '<!--keru-validate\n%s\nkeru-validate-->\n%s\n\n' "$validate" "$FORMAT_MARK"
  printf 'Fetched: %s. This is a copy, not the source: run `keru-context-snapshot check %s`\n' \
    "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$KEY"
  printf 'before reusing it, and treat `current` as "these keys did not move", not as\n'
  printf '"nothing about the work changed". PR diffs and file contents are NOT here on\n'
  printf 'purpose (they move under you) and must be read live every time.\n\n'
  if [ "$(jq -r 'length' <<<"$unfetched_json")" != "0" ]; then
    printf 'INCOMPLETE: these linked keys could not be fetched and are missing from this\n'
    printf 'snapshot: %s. Read them from Jira directly.\n\n' "$(jq -r 'join(", ")' <<<"$unfetched_json")"
  fi

  jq -r "$ADF_JQ"'"## " + (.key // "?") + " (" + (.fields.issuetype.name // "?") + ", " + (.fields.status.name // "?") + ")\n\n"
    + "**" + (.fields.summary // "") + "**\n\n"
    + "- assignee: " + ((.fields.assignee.displayName) // "unassigned")
    + "\n- updated: " + (.fields.updated // "unknown")
    + (if (.fields.parent.key // "") != "" then "\n- parent: " + .fields.parent.key + " " + ((.fields.parent.fields.summary) // "") else "" end)
    + "\n\n### Description\n\n" + ((.fields.description // "(empty)") | adf_doc) + "\n"' <<<"$root_raw"

  echo
  echo "### Comments"
  echo
  jq -r "$ADF_JQ"'if ((.fields.comment.comments // []) | length) == 0 then "(none)"
         else (.fields.comment.comments[] | "#### " + ((.author.displayName) // "?") + " (" + (.created // "?") + ")\n\n" + ((.body // "") | adf_doc) + "\n") end' <<<"$root_raw"

  echo
  echo "## Chain (one hop out)"
  echo
  jq -r --argjson unfetched "$unfetched_json" 'if length == 0 then
           (if ($unfetched | length) > 0
            then "(the linked issues could not be fetched: " + ($unfetched | join(", ")) + ")"
            else "(no parent, epic or linked issues)" end)
         else (.[] | "### " + .key + " (" + .type + ", " + .status + "), " + .rel + "\n\n**" + .summary + "**\n\n- updated: " + .updated + "\n\n"
               + (if .description == "" then "(no description)" else .description end) + "\n\n"
               + (if (.comment_text | length) == 0 then "(no comments)" else (.comment_text | join("\n\n")) end) + "\n") end' <<<"$linked_json"

  echo
  echo "## Mentioned in the chain's text, not linked"
  echo
  echo "Type, status and summary as of this write, not re-verified by \`check\`. Open live the ones that bear on the work."
  echo
  jq -r --argjson bad "$mention_unreadable" --argjson dropped "$mention_dropped" 'if length == 0 then "(none)"
         else (.[] | "- " + .key + " (" + .type + ", " + .status + "): " + .summary + " [mentioned in " + (.from | join(", ")) + "]") end,
         (if ($bad | length) > 0 then "\nNot readable as issues: " + ($bad | join(", ")) else empty end),
         (if ($dropped | length) > 0 then "\nOver the 25-key cap, not looked up: " + ($dropped | join(", ")) else empty end)' <<<"$mentioned_json"

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
  --argjson bytes "$bytes" --argjson unfetched "$unfetched_json" \
  --slurpfile linked <(printf '%s' "$linked_json") --argjson mentioned "$mentioned_json" --argjson dropped "$mention_dropped" '
  {file: $f, root: $root, keys: [$v[].key], bytes: $bytes,
   unfetched_keys: $unfetched,
   investigations: ([($linked[0] + $mentioned)[] | select(.type == "Investigation") | .key] | unique),
   mentioned_keys: [$mentioned[].key],
   mentioned_not_looked_up: $dropped,
   pull_requests: [($prs.pullRequests // [])[] | {status, branch, url}],
   note: ("read the whole file yourself: the root and every chain section. A linked investigation is read with its PR and doc; a mentioned one when it bears on the work. Re-verify with: keru-context-snapshot check " + $root)}'
