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
- **Service** = a native Jira **Component**, not a label and not the "Modules or Component" custom field. Component names are the repos, but not always verbatim (`xapi` is the component `XAPI BFF`). The `jira` CLI cannot resolve `DBI`'s components (its component lookup returns nothing for `DBI`), so `-C <name>` at create is rejected as `not valid`, non-deterministically naming whichever one it hit; components are therefore applied after create by numeric id, not at create time (Procedure step 6).
- **Epic vs BAU:** attach to an epic with `-P <EPIC-KEY>` at create time. If there is no epic, add the `BAU` label (`-l BAU`) instead. These are mutually exclusive: an epic-attached ticket does not get `BAU`.

## Procedure

1. **Check for prior context.** Look back in this session for what the ticket is about: an investigation, a parent ticket, a conversation, or an existing draft. If it is already here, use it; do not re-gather.
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
6. **Apply the component(s) by id.** Resolve each service name to its numeric component id: the ids for the common components are cached in memory (recalled when relevant; the ids are instance-specific so they live there, not in this public repo), else read them from the type's createmeta (`GET /rest/api/3/issue/createmeta/DBI/issuetypes/<typeId>`, `components.allowedValues[]`). Either way confirm the id is not archived and belongs to `DBI` before using it; the cache can be stale. Then set them on the new key in one call. Read `server` and `login` from the `jira` config (`~/.config/.jira/.config.yml`) rather than hardcoding them; the token is `$JIRA_API_TOKEN`:
   ```bash
   curl -s -o /dev/null -w "%{http_code}" \
     -u "$JIRA_LOGIN:$JIRA_API_TOKEN" -X PUT \
     "$JIRA_SERVER/rest/api/2/issue/<KEY>" \
     -H "Content-Type: application/json" \
     -d '{"fields":{"components":[{"id":"<id1>"},{"id":"<id2>"}]}}'
   ```
   Expect `204`. This is a remote state change on a ticket that already exists, so it is a follow-up edit, not a bypass of the create gate. Then read the ticket back and confirm every intended component landed (Playbook "verify"); do not assume the `204` placed the right ids.

## Several tickets (one at a time)

For more than one ticket, loop the same flow: draft one with `keru-writing-tickets` (its own gated file per `<id>`, so drafts do not overwrite each other), confirm it, create it, then move to the next. Do not bulk-confirm. For a parent + children breakdown, create the parent first so its key exists, then each child, then link the children to it (below).

## Linking (after the keys exist)

Once a ticket is created and you have its real key, propose any links the context implies and confirm each before running it:

- **To an epic:** if not already attached with `-P` at create, `jira epic add <EPIC-KEY> <ISSUE-KEY>`.
- **To another existing ticket** (a related ticket, a blocker, the investigation this came from): `jira issue link <ISSUE-A> <ISSUE-B> <TYPE>` where `<TYPE>` is the relationship (`Blocks`, `Relates`, etc.). Confirm the relationship type with the user rather than guessing it. Both `jira epic add` and `jira issue link` are held at `ask`.

## Before delivering

State the created key(s) and where each landed (project, epic or BAU, component), read from the real ticket, not assumed (Playbook "verify"). If a step failed (create rejected a required field, or the component edit did not return `204` / a component did not land), that error is a finding: report it and fix the input, do not retry blindly. Do not offer to commit anything; this command's output is the Jira ticket, not a repo change.
