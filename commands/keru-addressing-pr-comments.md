---
description: Resolve PR review comments following the Playbook (invokes the addressing-pr-comments skill).
---

Address the review comments on: $ARGUMENTS

Expects a GitHub PR link. First use the `gather-context` skill to gather the PR and its linked ticket and chain (read-only), then use the `addressing-pr-comments` skill. Validate each comment before applying; push back when warranted.
