---
description: Create one or more tickets in Jira from within Claude, typed-only. Drafts each ticket with keru-writing-tickets, confirms it, then creates it via the jira CLI. Asks the board, type, and service first; adds the BAU label when there is no epic; links to an epic or related tickets when the context has them. Explicit call only; never auto-fires.
disable-model-invocation: true
---

# Create Ticket

Create tickets in Jira, one at a time, from a draft you confirm. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-create-ticket`, which is the intent to write to Jira. Creating is a remote state change, so it is confirmed against a concrete draft, never a blind batch. The Playbook's always-on rules apply (verify never assume, never fabricate, Jira through the `jira` CLI never WebFetch); this command adds the create-specific procedure.

This command orchestrates; it does not draft. `keru-writing-tickets` writes each ticket in its existing single-ticket gated form and never touches Jira (that boundary stays); this command reads that draft and creates it. For several tickets it loops the same one-at-a-time flow, it does not invent a batch format.

## What maps to what in Jira (project `DBI`)

Verified against the live config and a real ticket; do not assume other values without checking `jira` first.

- **Board** = the Jira project (`-p`, default `DBI`).
- **Type** (`-t`, required) is one of `Epic`, `Investigation`, `Task`, `Bug`. There is no `Story` in `DBI`. The type also tells `keru-writing-tickets` which ticket shape to draft (bug -> observed/expected, investigation -> questions).
- **Service** = a native Jira **Component**, not a label and not the "Modules or Component" custom field. Component names are the repos, but not always verbatim (`xapi` is the component `XAPI BFF`). The `jira` CLI cannot resolve `DBI`'s components (its component lookup returns nothing for `DBI`), so `-C <name>` at create is rejected as `not valid`, non-deterministically naming whichever one it hit; components are therefore applied after create by numeric id, not at create time (Procedure step 6). The rejection is a clean `400`: nothing is created, so there is no half-made ticket to find or delete. A name the CLI rejects at create can still be perfectly valid on existing issues, so the `400` is not evidence the service is wrong.
- **Epic vs BAU:** attach to an epic with `-P <EPIC-KEY>` at create time. If there is no epic, add the `BAU` label (`-l BAU`) instead. These are mutually exclusive: an epic-attached ticket does not get `BAU`.
- **Notifications cannot be suppressed.** `--skip-notify` requires admin or project-admin permission and returns `403 To discard the user notification either admin or project admin permissions are required`. Drop the flag; watchers get notified, that is the cost of a write. Do not read that `403` as the write itself being refused.

## Procedure

1. **Check for prior context, then check the board for a ticket that already covers it.** Look back in this session for what the ticket is about: an investigation, a parent ticket, a conversation, or an existing draft. If it is already here, use it; do not re-gather. Then search Jira before proposing a new key, because creating a duplicate is the one mistake this command cannot undo: `jira issue list -q '<JQL>' --plain --no-truncate` with a couple of words from the intended summary (`project = DBI AND (summary ~ "portal" OR description ~ "portal")`), and include closed issues (no `--status` filter) since the work may already have shipped. `--no-truncate` exists on `jira issue list`, not on `jira issue view`. Nothing relevant found is a result worth stating in the confirmation, not a step to skip in silence.
2. **Ask the board, the type, and the service.** Board defaults to `DBI`; type is one of the four above; service is the component. Ask, do not infer, and wait for the answer.
3. **Resolve context if step 1 found none.** If there was no prior context, ask for it and use the `keru-gather-context` skill to gather the source (ticket/investigation/chain, read-only) before drafting. Scope comes from it.
4. **Draft with `keru-writing-tickets`.** Invoke that skill to produce the ticket text as its gated deliverable (`/tmp/keru-deliverable-writing-tickets-<id>.md`). Do not hand-write the ticket here.
5. **Show and confirm, then create (no component yet).** Show the mapped fields (project, type, component, epic-or-BAU, summary) and the drafted body, and get explicit confirmation. The `keru-writing-tickets` deliverable leads with the title and follows with the body, so split them before creating:
   - **Summary** (`-s`): the title with the surrounding `**` stripped. Jira's summary is plain text, so the asterisks would show up literally if left on.
   - **Body**: the rest, written to its own file (e.g. `/tmp/keru-create-ticket-body-<id>.md`) and passed with `--template <that file>`. Passing the whole draft file would duplicate the title into the description; pointing `--template` at a body-only file avoids that and avoids shell-escaping the multi-line body.
   ```bash
   jira issue create -p DBI -t <Type> \
     -s "<title, ** stripped>" --template /tmp/keru-create-ticket-body-<id>.md \
     {-P <EPIC-KEY> | -l BAU} --no-input
   ```
   No `-C` here: it is rejected (see the Service note). `jira issue create` is held at `ask`, so this prompts; that prompt is the second gate on top of your confirmation. `--no-input` stops it blocking on an interactive prompt for a field you did not pass. Read back the created key from the output; never claim a key you did not see.
6. **Apply the component(s) by id.** Resolve each service name to its numeric component id: the ids for the common components are cached in memory (`jira-dbi-component-ids`, read it first; the ids are instance-specific so they live there, not in this public repo), else read them from the type's createmeta (`GET /rest/api/3/issue/createmeta/DBI/issuetypes/<typeId>`, `components.allowedValues[]`), or off a ticket that already carries the component (`jira issue view <KEY> --raw | jq '.fields.components[] | {id, name}'`). That `jq` path is the only safe way to read it: a `grep` over the raw JSON drifts into the embedded linked-issue objects and returns another ticket's ids (`keru-gather-context`, "Fetching commands"), and the wrapped `--plain` header misreports how many components a ticket has. Either way confirm the id is not archived and belongs to `DBI` before using it; the cache can be stale. Then set them on the new key in one call with the `keru-jira-set-components` write helper, passing the key and the numeric ids. The helper reads `server` and `login` from the `jira` config (`~/.config/.jira/.config.yml`) and builds the auth header internally from `$JIRA_API_TOKEN`, so the token is never placed on the command line (a `curl -u "$LOGIN:$TOKEN"` would expose it to any local user via `ps`/`/proc`):
   ```bash
   keru-jira-set-components <KEY> <id1> [<id2> ...]
   ```
   It PUTs only the components field and expects `204`, printing the result. This is a remote state change on a ticket that already exists, so it is a follow-up edit, not a bypass of the create gate, and is held at `ask` in `config/permissions.json` (it is deliberately not auto-approved). Then read the ticket back and confirm every intended component landed (Playbook "verify"); do not assume the `204` placed the right ids.

## Several tickets (one at a time)

For more than one ticket, loop the same flow: draft one with `keru-writing-tickets` (its own gated file per `<id>`, so drafts do not overwrite each other), confirm it, create it, then move to the next. Do not bulk-confirm. For a parent + children breakdown, create the parent first so its key exists, then each child, then link the children to it (below).

## Linking (after the keys exist)

Once a ticket is created and you have its real key, propose any links the context implies and confirm each before running it:

- **To an epic:** if not already attached with `-P` at create, `jira epic add <EPIC-KEY> <ISSUE-KEY>`.
- **To another existing ticket** (a related ticket, a blocker, the investigation this came from): `jira issue link <INWARD-KEY> <OUTWARD-KEY> <TYPE>`. Both `jira epic add` and `jira issue link` are held at `ask`. Three things about this call are easy to get wrong, and all three are silent:
  - **The arguments are positional and unlabelled, and the order carries the direction.** `jira issue link A B Blocks` means "A blocks B", which renders on B as `is blocked by A`. Say the sentence out loud with the keys in place before running it; there is no flag to tell you which side you put where.
  - **Take `<TYPE>` from the instance, not from memory.** Read the vocabulary off a ticket that already has links: `jira issue view <KEY> --raw | jq '[.fields.issuelinks[].type | {name, inward, outward}] | unique'` returns the exact `name` to pass plus the phrasing each side renders as (e.g. `Blocks` / `is blocked by` / `blocks`). Confirm which relationship the user wants; do not guess the name.
  - **Verify the direction afterwards, do not assume the call did what you meant.** Read it back on the new ticket and check the sentence, not just that a link exists. Each entry carries only one side (`inwardIssue` or `outwardIssue`), which is what tells you the direction:

    ```bash
    jira issue view <NEW-KEY> --raw | jq -c '.fields.issuelinks[]
      | {type: .type.name,
         reads: (if .inwardIssue then .type.inward + " " + .inwardIssue.key
                 else .type.outward + " " + .outwardIssue.key end)}'
    ```

    It prints the relationship as that ticket displays it (e.g. `{"type":"Blocks","reads":"is blocked by DBI-1669"}`); if that sentence is backwards, the link is backwards.

## Before delivering

State the created key(s) and where each landed (project, epic or BAU, component), read from the real ticket, not assumed (Playbook "verify"). If a step failed (create rejected a required field, or the component edit did not return `204` / a component did not land), that error is a finding: report it and fix the input, do not retry blindly. Do not offer to commit anything; this command's output is the Jira ticket, not a repo change.
