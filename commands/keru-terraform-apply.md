---
description: Guide a person through, or execute for them, a terraform change from local through the dp CLI (dp awsso login, dp terraform run terraform init/plan/apply) against an environment picked explicitly, for any repo laid out as terraform/environments/<env>. Explicit call only. Two modes, same steps: walk the user through each step (they run it), or run it yourself and report. Asks which environment before touching anything, previews with an unlocked plan, scopes the blast radius with -target, confirms before the destructive apply, and never applies to production (the pipeline owns prod). Use when a terraform change needs the apply that CI does not run.
disable-model-invocation: true
---

# Terraform Apply

Run a terraform change from local, safely, through the `dp` CLI, against an environment the user names. The Playbook's always-on rules apply (verify never assume, never fabricate, and above all the safety line: `terraform apply` is destructive, so it is confirmed as a separate intentional step). This command adds the terraform-specific procedure.

The reason it exists: CI runs `terraform plan` on every PR but never `apply`, and `plan` can pass while `apply` fails (name conflicts, IAM eventual consistency, quotas, or an API that validates fields the provider does not check locally). This is the manual apply that closes that gap. It does not touch CI and it does not replace the PR plan; it runs the same plan locally only to produce the file it applies.

**Everything goes through `dp`.** Terraform is always invoked as `dp terraform run terraform <cmd>`, never bare `terraform`: the plugin resolves the correct AWS profile from the backend config, so the run authenticates against the right account. Login is `dp awsso login`. There is no bare-terraform fallback.

## Two modes (ask which the user wants)

The same procedure below serves both; the only difference is who runs the commands. Decide at the start, from how the user framed the request, and ask if it is not clear:

- **Guide:** the user runs each command themselves; you walk them through it one step at a time, giving the exact command for their environment, telling them what a correct result looks like, and reading their output before moving to the next step. Do not run anything yourself in this mode. When they hit an error, match it to Troubleshooting and tell them what to do.
- **Execute:** you run the commands and report. The confirmation gate before `apply` (step 7) still holds, and it is a real stop, not a formality.

Either way the ordering, the environment question, `-target`/`-lock=false`, and the pre-apply confirmation are identical. Never apply to production in either mode.

## Scope

- **In:** login, init, an unlocked preview plan, and a confirmed apply against `staging` / `uat` / a disposable sandbox, scoped to the changed resource(s) with `-target` when possible. Generic: works in any repo whose terraform lives under `terraform/environments/<env>` with an S3 backend.
- **Out:** `production` (the pipeline owns prod, this command never applies there); editing CI/workflows; writing the terraform change itself (that is `keru-writing-code`). Explicit call only, this never auto-fires on a `.tf` edit.

## The safety model

| Command | Mutates infra / shared state? | Role |
| --- | --- | --- |
| `dp terraform run terraform plan -lock=false` | No (reads state, no lock, no changes) | The safe preview. Run freely. |
| `dp terraform run terraform apply` | **Yes** (mutates real infra + the shared remote tfstate) | The change, not a test. Confirm first. |

Two levers keep an apply from breaking the environment, use both:

- **`-target='<resource.address>'`** scopes plan and apply to just the resource you changed, so the blast radius is that one resource, not the whole environment.
- **`-lock=false` on preview plans** so a read does not grab the DynamoDB state lock and collide with a pipeline run. The apply itself takes the lock (`-lock=true`, the default); do not disable it on apply.

## Procedure

Ask the environment first, before running anything. Never infer it.

1. **Pick the environment (ask the user).** List the envs (`dp terraform list environments`, or `terraform/environments/*`) and ask which one. **If the answer is production, stop:** this command does not apply to prod; that is the pipeline's job. Proceed only for staging / uat / a sandbox env.
2. **Log in with dp.** The plugin needs a valid SSO session with the environment's profile configured:
   ```bash
   dp awsso login
   ```
3. **Verify the identity before any change.** Do not assume login resolved the account you intend. Confirm the profile the plugin will use maps to the target environment's account (e.g. `dp awsso list`, or `aws sts get-caller-identity --profile <profile>`); read the env's `backend.tf` bucket to know which account/profile is correct. Wrong account => stop.
4. **Init through dp.** Run from the repo root; the plugin reads the backend in the `-chdir` target and resolves the profile from it:
   ```bash
   dp terraform run terraform -chdir=terraform/environments/<env> init
   ```
   A `dynamodb_table` deprecation warning on this backend is expected; ignore it.
5. **Plan (preview, unlocked).** Scope to the changed resource when you can; save the file so the apply runs exactly what you reviewed:
   ```bash
   # targeted (preferred, smallest blast radius)
   dp terraform run terraform -chdir=terraform/environments/<env> plan -lock=false \
     -target='module.app.<resource.address>' -out=tfplan
   # or full plan when the change is not confined to one resource
   dp terraform run terraform -chdir=terraform/environments/<env> plan -lock=false -out=tfplan
   ```
   If the env's variables require it, pass them (e.g. partner-integrations takes `-var="service_version=<v>"`; its default is `dev`).
6. **Read and classify the plan.** Report adds / changes / and especially **destroys or replaces** to the user. A replace or destroy on a shared env is the thing to catch here, not after.
7. **Confirmation gate (the destructive step).** Show the plan summary and get the user's explicit go-ahead for the apply against this specific environment. In Execute mode, do not run apply until they confirm; in Guide mode, this is the point where you tell them to review and then run it themselves. Make it louder when the plan destroys or replaces anything, or when the env is not a disposable sandbox. (The permission layer also holds `dp terraform run terraform apply` at `ask`, but the confirmation is yours to surface, not something to lean on the prompt for.)
8. **Apply the reviewed plan.** Apply the saved file (it applies exactly what was shown, takes the lock, no re-prompt). In Execute mode you run this after confirmation; in Guide mode you hand the user this exact command:
   ```bash
   dp terraform run terraform -chdir=terraform/environments/<env> apply tfplan
   ```
   Expected success looks like `Apply complete! Resources: N added, M changed, K destroyed.` Report (or have the user read back) the real output; if it errored, that error is a finding, see Troubleshooting or hand it to `keru-debugging`, not something to retry blindly.

## Troubleshooting

- **`No valid credential sources found`**: the SSO session expired or the plugin could not resolve the profile. Re-run `dp awsso login` and confirm the env's profile is configured, then retry.
- **`Backend initialization required`**: `init` was skipped for this env (step 4). Run the init command above, then re-plan.
- **`Module not installed` on `validate`**: `terraform validate` cannot run against a bare module dir without init; run it inside a full environment (staging/uat) that has been `init`ed, not against `modules/<x>` directly.
- **Plan passes but apply fails with an API 4xx**: this is exactly the gap this command exists for, the provider does not validate everything the upstream API does. It is a real finding, not a flake. Read the error, fix the terraform (that is `keru-writing-code`), and re-plan. Examples seen with the Datadog provider: an alert type the SLO API rejects (use a supported type), an invalid enum value on a field, or a required field the provider let through empty. Do not `-auto-approve` past it.

## Before delivering

State plainly what was applied, to which environment and account (from the identity check), and the actual `Apply complete!` line, not an assumed one (Playbook "verify"). If any step failed, say so with the output. Never claim an apply succeeded without the terraform result that proves it.
