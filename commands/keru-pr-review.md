---
description: Review a pull request following the Playbook (invokes the pr-review skill).
---

Review the pull request: $ARGUMENTS

Expects a GitHub PR link (or number with repo). First use the `gather-context` skill to gather read-only context: the PR (branch, body, files) and its linked Jira ticket and chain. Then use the `pr-review` skill, producing the review in the chat in its exact output format (verdict line, then findings with a location+code reference, the comment in a copy-pasteable fenced block, and the why). Not a prose essay or a conversation log.
