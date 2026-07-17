---
name: keru-datadog-audit
description: Audit DataDog errors and error logs for a set of services: surface what is failing (volume, spikes, top issues), group by recurrence, and judge attribution (ours vs downstream/client/noise). Use whenever the user asks what is failing in DataDog, to audit/triage service errors, check error volume or spikes, or review DataDog error-tracking, with or without a slash command. Read-only via `pup`; routes to keru-debugging when a cause is in doubt and feeds keru-writing-tickets for a recurring, attributable error, both as separate user-triggered steps.
---

# DataDog Error Audit

Reads DataDog error-tracking and error logs for a set of services through the `pup` CLI, analyzes the errors (group repeats, judge whether each is our failure or an external one), and writes a diagnostic report per service. The Playbook's always-on rules apply (verify never assume, read-only for external systems unless asked, concise); this skill adds the audit procedure.

This skill surfaces, groups, and attributes what is failing, then stops. It diagnoses only; it never writes a fix (that is `keru-writing-code`, out of scope). The chain out of it, both the user's to trigger:

- When an error's cause is genuinely in doubt after the attribution pass (the logs and a quick local code read still do not settle whether it is ours), hand THAT error to `keru-debugging` for the root-cause work. That skill owns the reproduce -> isolate -> hypothesis+verify method; do NOT restate or re-derive it here (DRY). This skill does the surface grouping and a first attribution, not the deep root cause.
- For a recurring error judged attributable to us, the report marks it a ticket candidate and, at the end, offers to open the ticket. On the user's yes, chain to `keru-writing-tickets` (which produces the ticket; the actual `jira issue create` still prompts separately). Do not draft the ticket inside this skill and do not file one without that yes. Errors judged external (a downstream/partner 500 we merely surface, expected client noise) are reported as such, not ticketed.

## Tool: `pup` (read-only)

Queries run through `pup`, DataDog's CLI (see [external-tools.md](../../docs/external-tools.md) for install and auth). It emits JSON by default; parse with `jq`. Only its read subcommands are used, and only those are allowlisted; every `pup` write (`cases create`, `cases jira`, `metrics submit`, ...) is in `ask` and out of scope for this audit.

If `pup auth status` reports not authenticated, stop and tell the user to run `pup auth login` (an interactive browser OAuth flow they run themselves); do not attempt the audit against an unauthenticated CLI.

Follow `pup`'s own usage guidance: always pass `--from` on a query; count with `logs aggregate --compute=count`, never by fetching raw logs to count them; start with a small `--limit` and refine; APM durations are in nanoseconds. When a report cites a `pup` command for the user to rerun themselves, append `--no-agent` (outside this session `pup` emits raw JSON, not the agent envelope, so the citation matches what they will see).

Command shapes verified against `pup` 1.6.0 (the `--help` JSON is wrong on some of these; these are what the CLI actually enforces):

- **Time format** is bare relative (`1h`, `30m`, `7d`), an RFC3339 stamp, or a Unix timestamp. `now-7d` is rejected.
- **`error-tracking issues search`** requires `--state`, `--from`, `--limit`, and exactly one of `--track` (`trace`|`logs`|`rum`) or `--persona` (they are mutually exclusive; passing both errors). Use `--track trace` for backend services. It returns only issue `id` + `total_count`; there is no title in the search result.
- **`error-tracking issues get <id>`** resolves an id to its attributes: `error_type`, `error_message`, `service`, `file_path`, `function_name`, `state`, `first_seen`/`last_seen`. There is no `title` field; identify an issue by `error_type` + `error_message`.
- **`logs aggregate`** output is at `.data.buckets[].computes.c0` (the compute is keyed `c0`), with the group value under `.by`. A `--group-by <facet>` only returns buckets when that facet is actually emitted by the service: many backend services log plain `msg`/`stacktrace` and have no `@error.type`, so grouping on it yields zero buckets. Confirm the facet exists (probe with a small query) before relying on a group-by; do not report "no exceptions" when the facet simply is not populated.
- **An empty result is data, not an error.** A `count` aggregate returns `.data.buckets: []` (no `[0]`) when nothing matches, e.g. a service that emitted only `info`/`warn` in the window. Read that as 0 errors (the service is not failing), not as a failed query. The `-status:(...)` exclusion and quoted parentheses pass through the shell inside `--query "..."` as-is.

## Service set

The services to audit are a personal choice, like bot-triage's repo list. There is NO default in the repo: the list lives only in memory (see [[datadog-services]]), and only once the user has chosen to save one. It is not project config.

1. Resolve the list, in order: services named in this invocation win for this run; else the saved memory list if one exists; else ask the user, because nothing is seeded by default. Never guess service names.
2. Persist only on request: if the user asks to remember the list, write/update the `[[datadog-services]]` memory file. Do not create it unprompted.

## Procedure

Work through the audit over a time window that defaults to the **last 24h** unless the user specifies a date/range (state the window you used). The services are independent, so run the per-service gather concurrently (issue the `pup` reads for all services together and collect the results, Playbook "Parallelize the work", the I/O-concurrency shape); then analyze and attribute each yourself. This keeps a many-service audit fast without changing what is gathered.

**The error filter (the base query):** `env:production -status:(info OR warn OR notice OR debug OR ok) service:<svc>`. Exclude the non-error levels rather than matching `status:error`, so any error severity is caught, not only the literal `error` label. The ONLY part that changes per service is `service:<svc>`; keep the rest verbatim. Pass it to `pup` as `--query "<that>"` (the parenthesized `-status:(...)` passes through the shell fine inside the quoted string). Add `env:<other>` only if the user audits a non-production env.

### Gather (per service)

- **Error volume:** `pup logs aggregate --query "<base query>" --from "24h" --compute "count"`, reading `.data.buckets[0].computes.c0`. Count via aggregate, not by listing logs. A count of 0 (the service emitted only info/warn/etc. in the window) is a real, reportable "not failing", not an error.
- **By HTTP status (the default breakdown):** `pup logs aggregate --query "<base query>" --from "24h" --compute "count" --group-by "@httpResponse.status" --sort count --limit 10`. This is the top-N-status view the reference dashboard uses (500s vs 4xx tells attribution apart at a glance). Only relied on when the facet returns buckets; a service that does not emit `@httpResponse.status` needs a different grouping.
- **Open error issues (the exception view):** `pup error-tracking issues search --state OPEN --from "24h" --limit 10 --track trace --query "service:<svc>" --order-by TOTAL_COUNT`, then resolve the top few ids with `pup error-tracking issues get <id>` for `error_type` + `error_message`. These are already grouped by exception, useful when raw logs lack an `@error.type` facet.
- **Spikes:** compare the window's count against a prior equal window (last 24h vs the 24h before, via `--from "48h" --to "24h"`), or an obvious jump in a status/issue count. State it as a comparison you actually ran, not an impression.
- **A specific slice** (an endpoint, a client, an operation): use the user's own log query verbatim in `--query` (e.g. adding `@httpRequest.header.x-jwt-claim-client-id:<client> @operationID:<op>` to the base), grouping by a facet that slice emits.
- **The actual error logs to analyze:** pull the recurring error's own log lines (`pup logs search --query "<base query> <narrowing>" --from "24h" --limit 20 --sort desc`) and read their `msg`, `stacktrace`, `@error`, and any `@http*` fields. Attribution is judged from these, so you need the real lines, not just the count. Keep `--limit` small (a sample is enough to see the shape); do not dump the whole set.

Verify, do not assume: every count, spike, and top issue you report comes from a `pup` result you actually ran this session, not from memory or inference. If a service returns nothing (no errors, or no access), say so for that service rather than omitting it.

### Analyze (per service): recurrence, then attribution

The raw count is not the finding. For each service, two questions decide what (if anything) is worth acting on:

1. **Is it the same error, or many?** Group before concluding: N occurrences of one identical error (same `error_type` + `error_message`, or one error-tracking issue with a high `total_count`) is ONE problem, not N. Say "one recurring error, X times" rather than "X errors". A high count of a single issue and a scatter of distinct issues are very different situations; distinguish them. Attribute only the recurring ones; a one-off is noise unless the user asks.
2. **Is it ours, or an external service's?** Judge from the actual error lines, and say which and why. Read the `stacktrace`/`@error`/message: a stack in our code, a validation we raise, a panic we own points to us; a non-2xx from a downstream or partner call, a client sending malformed input, a dependency timeout points elsewhere. When the log is opaque (no stacktrace, no `@error`, just a generic "500 Server Error", as extend-api's CreateTransfer 500s are), the log alone does not settle it: confirm which code path emits it by reading the owning service's repo **locally**.
   - Prefer the local clones under [[projects-root]] (`~/Documents/GitHub`), grepping the message/endpoint there, over more `pup`/API calls: the goal is to attribute without hammering the API, and the same service often spans multiple repos. If the repo is not cloned, note that rather than guessing.
   - This is a light attribution read (which side raises the error), not a root-cause investigation. If a local read still does not settle it, mark it "cause not established" and route that error to `keru-debugging`; do not do the deep reproduce/isolate here (DRY, that is debugging's method).
   - Never assert a cause the evidence does not support. "Ours" and "external" are both claims you must be able to point at (a stack frame, a downstream status, a repo line).

A ticket candidate is an error that is both **recurring** and **attributable to us** (or otherwise needs our action). Mark those in the report; external and unestablished errors are reported with their tag but are not candidates.

## Output

Write the report to `/tmp/keru-deliverable-datadog-audit.md` first (the Playbook's gated-deliverable rule; a PreToolUse gate validates it before the file is written). Your chat reply is a link to that file plus at most one line, not its pasted contents. (The audit spans a service set, not one ticket, so no `<id>` suffix; a new audit replaces the last.)

Lead with substance. Order services worst-first (highest volume or a real spike at the top). Open with the first service's bold header, nothing before it. Use this shape per service:

```text
**<service>**
Volume: <count> errors over <window><, spiking vs <baseline> | , flat>
- <error_type>: <short error_message>, one recurring error x<count> [OURS: <the stack frame / repo line that shows it> | EXTERNAL: <the downstream status / client cause> | UNESTABLISHED: cause not settled from logs, route to keru-debugging]
- <next issue...>
Ticket candidates: <error_type> (recurring + ours) | none
```

Keep it scannable: counts, issue identifiers, and the attribution tag with its one-line evidence, no per-line prose. If a service returned nothing or was inaccessible, keep its header with that one line so the gap is obvious. End with one line stating the window audited. If nothing is failing across all services, say that plainly.

After the file is delivered, if there is at least one ticket candidate, offer in the chat line to open a ticket for it. Only on the user's yes, chain to `keru-writing-tickets` (a separate turn/skill); do not draft or file it otherwise. If a candidate is UNESTABLISHED instead, offer to route it to `keru-debugging`.

## Scope and safety

Read-only on DataDog, always. Never create a case, submit a metric, or run any `pup` write; those are remote mutations in `ask` and are not part of this audit. The local repo reads for attribution are read-only greps of existing clones, not clones or writes. Filing a ticket is a separate step via `keru-writing-tickets` on the user's yes (and `jira issue create` still prompts on its own); this skill produces the report and the offer, not the ticket.

## Before delivering

Confirm every service in the resolved list was audited (or its no-data / access error reported), the window is stated, every count and spike came from a `pup` result run this session (not memory, Playbook "verify"), and each recurring error carries a recurrence count and an attribution tag whose one-line evidence you can point at (a stack frame, a downstream status, or a repo line; no asserted cause the evidence does not support). Then stop; do not root-cause an UNESTABLISHED error yourself (that is `keru-debugging`), do not write a fix (`keru-writing-code`), and do not draft or file the ticket without the user's yes.
