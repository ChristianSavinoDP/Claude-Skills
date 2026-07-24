---
description: Run a PR review and publish it to GitHub, typed-only. Runs keru-pr-review to produce the gated review, validates that every inline comment anchors to a modified line, then posts one review with the verdict's event (approve / request changes / comment) and the inline + PR-level comments. Approves with a short LGTM when there are no findings. Explicit call only; never auto-fires.
disable-model-invocation: true
---

# Review and Publish

Review a PR and post the review to GitHub in one deliberate step. `disable-model-invocation: true` means this never fires on its own; it runs only when the user types `/keru-review-publish <PR>`, which is the intent to publish a review (a remote state change). The Playbook's always-on rules apply (verify never assume, GitHub through the `gh` CLI never WebFetch); this command adds the publish procedure.

This command delegates the review itself. `keru-pr-review` owns the analysis, the fan-out, the per-finding verification, and the gated deliverable; this command only validates diff-attribution and posts. The one genuinely new action here is the posting.

## Procedure

1. **Run `keru-pr-review <PR>`.** Let it do its full job (pin the repo/branch, fan out, verify each finding, classify) and produce its gated deliverable at `/tmp/keru-deliverable-pr-review-<pr>.md`. Do not review the PR yourself here; use that skill's output as the source.
2. **Validate before posting.** Every inline comment must anchor to a line the PR actually modified, which is exactly `keru-pr-review`'s own diff-attribution rule (it already verifies each finding sits on an added/changed line before classifying it). Re-check that here against the deliverable, do not re-derive the mechanic. For each finding:
   - If it anchors to a modified line, it is a real inline comment.
   - If it does not (it points at unchanged or pre-existing code), it is not postable as an inline comment. Re-invoke `keru-pr-review` to correct or re-anchor it, UNLESS it is a general / PR-level finding (a missing acceptance criterion, a scope question), which by that skill's own rule has no line anchor and belongs in the review body, not as an inline comment. Do not loop on this indefinitely: if a comment cannot be anchored after one correction pass, demote it to the review body rather than re-invoking again.
3. **Build and post one review.** Map the deliverable's `Verdict:` line to the review event: `Request changes` -> `REQUEST_CHANGES`, `Comment` -> `COMMENT`, `Approve` -> `APPROVE`. If there are findings, post them; if there are none, approve with a short body (e.g. `Reviewed, LGTM`). Confirm with the user before posting (posting is a remote state change).

## Posting mechanism

`gh pr review` takes only a single `--body` and cannot attach line-anchored comments, so a review with inline comments goes through the reviews API in one call. Do NOT try to build the payload with `gh api -F 'comments[][path]=...'`: `gh api`'s field flags only build flat arrays, so nested-object bracket syntax is taken as a literal key and the comments are never sent. Build the JSON explicitly with `jq` and pipe it in with `--input -`. Each inline finding is one object in `comments[]` (`path` + `line` + `side`, `RIGHT` for added lines; a multi-line finding adds `start_line`); the PR-level findings and the verdict summary become the review `body`:

```bash
jq -n --arg body '<PR-level comments + summary>' '{
  event: "<APPROVE|REQUEST_CHANGES|COMMENT>",
  body: $body,
  comments: [
    {path: "<file>", line: <line>, side: "RIGHT", body: "<the Comment block for that finding>"}
  ]
}' | gh api repos/<owner>/<repo>/pulls/<pr>/reviews --method POST --input -
```

A no-findings approval needs no `comments[]`:

```bash
gh api repos/<owner>/<repo>/pulls/<pr>/reviews --method POST -f event=APPROVE -f body='Reviewed, LGTM'
```

This `POST` is held at `ask` (a review is a remote write), so it prompts on top of your confirmation. Only the fenced "Comment" block of each finding goes into a comment body; the deliverable's `Why:` lines are internal and never posted (`keru-pr-review`'s "Tone" rule). Build the comment bodies verbatim from the deliverable, do not re-summarize them.

## Before delivering

State the posted review's event and where it landed, from the real API response (the review id / URL), never an assumed success (Playbook "verify"). If a finding was demoted from inline to the body because it could not be anchored, say so. If the post failed (a comment on a line outside the diff is a common cause), that error is a finding: fix the anchor and retry, do not retry blindly. Do not offer to commit anything.
