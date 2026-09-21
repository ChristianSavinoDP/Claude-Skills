---
name: keru-usage-audit
description: Report Claude Code token spend and estimated cost from the local session transcripts, per month, per day, per session and per project, and say what is driving it. Use whenever the user asks how many tokens or how much money was spent (a session, a day, this month, a project), what the bill is going to, or to compare months, with or without a slash command. Read-only; it prices recorded token counts and never calls a model.
---

# Usage Audit

Answer "what did this cost, and why" from the local transcripts. Read-only: `keru-usage` reads `~/.claude/projects/**/*.jsonl` and prices the recorded token counts. The Playbook's always-on rules apply (verify, never assert); this skill adds the audit procedure.

## Procedure

1. **Pick the scope from the question.**
   - The session in progress: Claude Code's own `/usage` (aliases `/cost`, `/stats`). Cost is not persisted anywhere, so for the live session that command is the only source; do not try to derive it.
   - A month, or everything across projects: `keru-usage month [YYYY-MM]` (no argument means the current month).
   - A trend across months: `keru-usage months`.
   - Which sessions were expensive: `keru-usage sessions [N] [YYYY-MM]`.
   - Whether a cheaper setting would pay for itself: `keru-usage blocks [YYYY-MM]`, which counts how often each Stop gate kicked a turn back and what the rework cost.

   Add `--table` when the numbers go to the user; take the JSON when you are going to compute from them.
2. **Lead with the total**, then the breakdown that answers the question that was asked (by model, by directory, by day, or the session list). Do not dump all four tables when one was asked for.
3. **State both caveats, every time.** They change how the number should be read:
   - It is an **estimate**: first-party list prices applied to recorded tokens. On Bedrock or Vertex the provider's rates apply, so the invoice differs.
   - It is a **floor**: a hook that calls a headless model with `--no-session-persistence` leaves no transcript, so its spend is not in the total.
4. **Say what is driving it**, from the numbers rather than from assumption. The pools, in the order they usually rank: cache reads (context re-sent every turn), cache writes (context newly cached), output (thinking tokens live here). If the user wants the split by pool, or spend attributed to subagents versus main sessions, compute it from the JSON.

## Reading the numbers

- **Cache reads dominating is normal**, and it means the driver is the *size of the context* being re-sent each turn, not how much was generated. The lever is a smaller context (narrower reads, `/clear` between unrelated tasks), not shorter answers.
- **A single request with a huge `cache_write` is a full re-cache of the prefix**: the 5-minute cache TTL expired, or something invalidated it (switching model mid-session invalidates everything, since caches are per-model). At Opus rates a re-cache costs about $0.63 per 100K of context, so an idle gap mid-session is not free.
- **Thinking tokens are output tokens.** A high effort level shows up here, at the output rate, not as a separate line.
- **Subagent spend is real and separate**: subagent transcripts live under `<session>/subagents/`. If they are running the strong model on mechanical legs, that is the Playbook's "Match the model to the leg" being ignored, and it is visible here as subagent cost by model.

- **A gate with no row in `blocks` never blocked in that scope.** Absence is the finding: it means that gate is not the reason anything was redone, so a rework argument cannot lean on it.

Before recommending any change, measure the lever you are about to recommend on this data. A cheaper cache TTL, a lower effort level, or a cheaper model for a leg each trade something; quote what it saves here rather than what it saves in general.

When the change trades quality for cost, weigh it against `blocks` for the same period and say the break-even out loud (how much extra rework would cancel the saving). And say what that comparison cannot see: the gates check form and skill compliance, not whether a root cause was right or a review caught the real bug. A quality regression that never trips a gate will not appear in these numbers, so a cost win here is not by itself evidence that quality held.
