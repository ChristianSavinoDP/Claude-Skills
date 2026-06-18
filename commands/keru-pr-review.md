---
description: Review a pull request following the Playbook (invokes the pr-review skill).
---

Review the pull request: $ARGUMENTS

Expects a GitHub PR link (or number with repo). First use the `gather-context` skill to gather read-only context: the PR (branch, body, files) and its linked Jira ticket and chain. Then use the `pr-review` skill.
