---
description: Write a PR description following the Playbook and repo template (invokes the pr-description skill).
---

Write the PR description for: $ARGUMENTS

Expects a GitHub PR link. Use the `gather-context` skill to gather the PR (changes, branch) and its linked Jira ticket and chain (for the JIRA link and acceptance criteria), then use the `pr-description` skill. Follow the repo's PR template; do not invent structure.
