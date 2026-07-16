---
name: keru-addressing-pr-comments
description: Resolve review comments on a PR. Use whenever the user brings PR review feedback (from a person or Copilot), pastes review comments, or asks to address/respond to/fix them, even without a slash command. Trigger on pasted comments or "Copilot said...", "the reviewer wants...", "handle these comments". Expects a GitHub PR link.
---

# Addressing PR Comments

Procedure for working through review comments. The Playbook's always-on rules apply (verify, fix root cause, concise); this skill adds the rules for handling comments.

## Steps

1. Get the ticket first (Playbook "first step"); scope is defined by the ticket type. Use the `keru-gather-context` skill to gather the PR and its linked ticket and chain (read-only) before deciding on any comment.
2. Pull the comments (`gh pr view <pr> --comments`) and the diff for context (`gh pr diff <pr>`).
3. Work through the comments one at a time, deciding apply-or-push-back for each before touching code.

## Rules

- **Validate first.** Evaluate whether each comment is correct and in scope before writing code. Verify it against the codebase, do not dismiss from memory (a wrong dismissal is the common failure). Not every comment deserves a change. This includes style and organization comments: confirm the suggested shape matches the file's existing order before applying, do not assume a convention.
- **Your reply is a deliverable, not chat.** It goes to the reviewer, so every factual claim in it (how a library/API/field behaves, what a value does) is held to the Playbook's verify rule: read the source before asserting, no carve-out for "this is just a discussion answer". Answering a reviewer's "would it make sense to..." is exactly where a confident-but-unchecked claim about a familiar library slips in.
- **Push back when warranted,** directly: if a comment is wrong or out of scope, say why, respectful, concise, factual, not hedged as a suggestion. You are defending your own PR, not reviewing someone else's.
- **Verification has a stopping point.** When a comment (a bot's included) contradicts something you already verified this session against the authoritative source, re-read that existing evidence, do not launch a fresh investigation to re-prove it. "Verify, do not assume" is not "re-verify without limit": once checked against the source of record, a contradiction is a cue to push back with the evidence you have, not to reopen it. If you do re-check, decide up front what result would be conclusive and stop the moment you have it.
- **Fix the root cause,** not a band-aid that silences the comment.
- **Group related comments** that point at the same underlying issue.
- **Do not over-correct.** Change what was asked, nothing more.

## Output

Write this to `/tmp/keru-deliverable-addressing-pr-comments-<pr>.md` first, where `<pr>` is the PR number (the Playbook's gated-deliverable rule, so it does not overwrite another PR's resolution); your chat reply is a link to that file plus at most one line, not its pasted contents. One block per comment, no intro or summary around them. Each block OPENS with a bold header naming the comment (`**path:line**`, or `**<short label>**` when it has no location), nothing before it. Then: apply or push back, the reasoning in a sentence, and the concrete change or the drafted reply. A reply meant to be posted goes in its own copy-pasteable fenced block. Posting on the PR is a state change: confirm first, read-only by default.
