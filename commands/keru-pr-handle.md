---
description: Handle the author-side lifecycle of a pull request, typed-only. If no PR exists for the current branch, create one (guards branch + clean tree, drafts the body with keru-pr-description, asks draft-or-not, creates). If a PR already exists, route to the skill that owns the next step (comments -> addressing-pr-comments, red CI -> responding-to-ci) or, when it is ready, confirm and merge. Explicit call only; never auto-fires.
disable-model-invocation: true
---

# PR Handle

Drive a PR from the author's side: open it if it does not exist, or move it forward if it does. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-pr-handle`, which is the intent to change remote state (`git push`, `gh pr create`, `gh pr merge`). The Playbook's always-on rules apply (verify never assume, GitHub through the `gh` CLI never WebFetch, read local state before re-fetching remote); this command adds the lifecycle procedure.

Run it from the repo that holds the work (the current clone), not this repo; `gh` resolves the target repo from the remote. This command owns only two genuinely new actions, creating and merging; for everything an existing skill already does (drafting the body, resolving comments, getting CI green, reviewing), it delegates to that skill rather than reimplementing it.

## Detect the state first

Check whether a PR already exists for the current branch, and branch on it:

```bash
gh pr view --json number,state,isDraft,mergeable,reviewDecision
```

Branch on `state`, not just on presence: `gh pr view` returns the PR for the current branch even when it is CLOSED or MERGED. Only `state == "OPEN"` is the existing-PR flow. No PR ("no pull requests found for branch X"), or a CLOSED/MERGED one, means there is no open PR to move forward: take the create flow (or, for a merged one, stop and say so rather than opening a duplicate).

## No PR: create it

1. **Guard the branch and the tree.** Confirm the current branch is NOT the repo's default branch (`gh repo view --json defaultBranchRef -q .defaultBranchRef.name`), and that everything is committed (`git status` shows a clean tree). If on the default branch or the tree is dirty, stop and say why; do not create a PR from an unclean or default-branch state.
2. **Draft the body with `keru-pr-description`.** Invoke that skill to produce the title and body as its gated deliverable (it pulls the ticket via `keru-gather-context`). Then have the user say how to fill the `<scope>` the draft leaves literal, and resolve any other template placeholder (e.g. a `XXXX` Jira id) so the PR does not ship with a placeholder.
3. **Ask draft or not.** Before creating, ask whether this is a draft PR (`--draft`) or a normal one.
4. **Push if needed, then create.** If the branch has no upstream, push it as an explicit confirmed step first (`git push -u origin <branch>`, held at `ask`), never via `gh pr create`'s interactive push prompt. The `keru-pr-description` deliverable keeps the title and body as separate blocks, so do not feed the whole file: take `--title` from the title, and write just the body to its own file for `--body-file` (feeding the raw deliverable would post the label and fence markers into the PR):
   ```bash
   gh pr create --title "<title from the Title block>" --body-file /tmp/keru-pr-handle-body-<id>.md --base <default> [--draft]
   ```
   `gh pr create` is held at `ask`, so this prompts on top of your step-3 confirmation. Report the created PR URL from the real output.

## PR exists: route or merge

A PR already open means the work now belongs to whichever skill owns the next step. This command decides the state and hands off; it does not do the comment-resolution, CI-fixing, or review work itself.

- **Review comments present** -> route to `keru-addressing-pr-comments` (it validates each comment, then applies). Pull them read-only to decide (`gh pr view <pr> --comments`).
- **CI red** -> route to `keru-responding-to-ci` (it triages each failing check and drives the fix). Check read-only with `gh pr checks <pr>`; do not rerun or fix here.
- **Ready to merge** -> confirm with the user, then merge. "Ready" is a real check, not a guess: from the `gh pr view` JSON, CI is green (`gh pr checks`), `mergeable` is `"MERGEABLE"` (it is a `MergeableState` enum string, `MERGEABLE`/`CONFLICTING`/`UNKNOWN`, never a boolean), `isDraft` is false, and `reviewDecision` is `APPROVED`. Note `reviewDecision` can be empty on a repo that does not require reviews; treat empty as "not confirmed approved" and ask the user rather than assuming, since a merge is destructive. Merge with the org's squash convention:
  ```bash
  gh pr merge <pr> --squash --delete-branch
  ```
  `gh pr merge` is held at `ask`, so it prompts; the merge is destructive (it lands code on the default branch), so surface the confirmation yourself, do not lean on the prompt. `--delete-branch` removes the merged branch local and remote.

## Before delivering

State what happened from the real `gh` output: the PR URL on create, or the merge result and the branch deletion on merge, never an assumed success (Playbook "verify"). If you routed to another skill, say which and why. Do not offer to commit or push beyond the confirmed steps above.
