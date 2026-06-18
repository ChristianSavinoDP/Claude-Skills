---
description: Produce an investigation deliverable following the Playbook (invokes the investigation skill).
---

Run the investigation for: $ARGUMENTS

Expects a Jira ticket key or link. Use the `gather-context` skill to gather it and its full chain (read-only), including any linked investigation's PR and document. Do not start until the gate in the skill passes. Then use the `investigation` skill. Ask whether a taskbreakdown.yaml is needed.
