---
description: Implement a code change following the Playbook (invokes the writing-code skill).
---

Implement: $ARGUMENTS

Expects a Jira ticket key or link. Use the `gather-context` skill to gather it and its full chain (read-only) as the source of truth: linked issues, parent/epic, and, if the ticket came from an investigation, that investigation's ticket AND its PR/document. Do not start coding until the gate in the skill passes. Then use the `writing-code` skill. Stay within scope.
