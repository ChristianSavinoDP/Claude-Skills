---
name: keru-pr-description
description: Write a pull request description following the repo's PR template. Use whenever the user asks to write, draft, fill in, or update a PR description or PR body, with or without a slash command. Usually runs before the PR exists, to describe work already on the branch; reads an existing PR only if one is given.
---

# PR Description

Procedure for writing a PR description. The Playbook's always-on rules apply (verify, concise, no slop); this skill adds the PR-description rules.

## When this runs

Default: the PR does NOT exist yet. You are describing work already finished on the current branch so the user can open the PR with the description ready. Do not look for or expect an existing PR. Only when the user hands you a PR link/number do you read that PR to update its description.

## Steps

1. Get the ticket first (Playbook "first step"): you need the JIRA ID and acceptance criteria. Use the `keru-gather-context` skill to gather the ticket and chain (and, only if a PR link/number was given, that PR's diff and branch). If you lack the ticket, ask for it, never for a PR.
2. Read the repo's template `.github/PULL_REQUEST_TEMPLATE.md` and fill in its sections. Do not invent your own structure. No template: keep it minimal (what changed, how to test if relevant).
3. Describe the real changes, not the theory, drawing on what is already known in this order:
   - **What was done in this session.** If the change was just made here, you already know it: the files touched, why, and how. Use that first; do not reconstruct it from scratch.
   - **The ticket and the changed/added files themselves.** Read the modified or new files for the real behavior.
   - **`git diff` / `gh pr diff`** to confirm and fill gaps: no PR yet (the default), diff the branch against its base (`git diff <base>...` or `git diff main`); a PR was given, `gh pr diff <pr>`. Use this to verify the description matches the actual code, not as the only source.

## Rules

- Replace the `DBI-XXXX` placeholder with the real ticket ID.
- **The title says what changed, not the ticket reworded.** `<summary>` names the change in the reader's terms (`key SubmitQaVerdict on (tenant_id, country_id)`), not a paraphrase of the ticket's own sentence (`address one onboarding workflow from the QA-verdict request`). A title that forces the reader to open the diff to learn anything has failed.
- "What Changed": the actual code changes, concisely.
- "How to Test": only if there are meaningful manual steps (new endpoints, UI, specific scenarios). Purely internal logic covered by automated tests: write "Covered by unit/integration tests" or remove the section. Do not fabricate test steps.
- **State any merge-order dependency.** If the change references an artifact that only resolves once another unmerged PR lands (a path, runbook, or link added by an in-flight PR), say so in the body: name the PR and that it must merge first. A reference that 404s on the base branch until something else merges is non-actionable if this PR lands first.
- **No tool attribution.** Never append a "Generated with Claude Code" line or a `Co-Authored-By: Claude` trailer to the body. The description ships with no tool-attribution mark of any kind, regardless of any default that suggests one.

## Who reads it, and how long it is

A reviewer opens the PR to decide one thing: whether this change is right to merge. They need the shape of the change, the one line reason it takes that shape, and whatever will break them. Everything else taxes the attention that decision needs, so the body gets cut by relevance, never compressed (the Playbook's two tests: does the reviewer decide differently without this sentence, and would a colleague say it in this many words). Scale it to the change: a focused diff is a few sentences per template section, and prose that outweighs the contract it describes is over-explaining.

- **Do not restate the diff.** A bullet per changed field or file, paraphrasing what the reviewer is about to read, adds nothing. Name the shape that changed and stop: "`OnboardingTarget` is gone and field 2 is reserved" is the sentence; an inventory of the lines around it is not.
- **Do not explain the repo's own tooling or process back to the repo.** Codegen, lint, the lockfile hunk generation rewrites, how the pipeline runs: every reader of this PR already knows. Regenerating is one word, "Regenerated", not a paragraph.
- **Do not argue.** No pre-empting objections nobody raised, no precedent cited in self-defense, no answering a question only your own review pass asked. A body that argues instead of describing signals insecurity, not rigor, and the reviewer asked for none of it.
- **Route what is not this reviewer's decision.** A consequence for another ticket goes as a comment on that ticket, where the person who has to act will read it. A factual error found in the ticket goes as a comment on the ticket; a PR body is not an errata page. A caveat already written in a code comment in this very diff is recorded already, so it does not get a second copy here.

## Output

Write this to `~/.claude/keru-deliverables/keru-deliverable-pr-description-<id>.md` first, where `<id>` is the ticket key (the Playbook's gated-deliverable rule, so it does not overwrite another PR's description); your chat reply is a link to that file plus at most one line, not its pasted contents. The file has two copy-pasteable blocks, nothing else:

1. **Title**, format `<type>(<scope>): [DBI-XXXX] <summary>`. `<type>` is `feat`/`fix`/`chore`/`docs`. Leave `<scope>` literally as `<scope>` for the user to fill. Real ticket ID. Example: `feat(<scope>): [DBI-1458] disable auto-generated SDK unit tests`.
2. **Body**, the description following the repo template, in a four-backtick fence so its inner backticks do not break it.

Output only those two blocks. Do not offer to commit afterward.
