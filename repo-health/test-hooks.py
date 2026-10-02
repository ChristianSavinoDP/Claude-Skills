#!/usr/bin/env python3
"""Behavioral tests for the repo's Bash/Stop hooks, run by repo-health.

These guard the hooks' LOGIC, not just their existence: the kind of regression
docs/permissions/installer checks cannot see. A hook can be installed, named
right, and documented, yet reason about a stale assumption (e.g. that a
`/keru-*` slash command emits a `Skill` tool_use). That class of bug shows up
only by exercising the hook on real inputs, which is what this does.

Tests target the scripts in scripts/ (the source of truth), not the installed
~/.local/bin copies. Exit 0 if all pass, 1 otherwise.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOOKS = os.path.join(REPO, "scripts", "hooks")
SAFE_READ = os.path.join(HOOKS, "keru-safe-read.py")
REQUIRE_SKILL = os.path.join(HOOKS, "keru-require-skill.py")
CHECK_OUTPUT = os.path.join(HOOKS, "keru-check-output.py")
JUDGE_OUTPUT = os.path.join(HOOKS, "keru-judge-output.py")
GATE = os.path.join(HOOKS, "keru-gate-deliverable.py")
GATE_COMMENTS = os.path.join(HOOKS, "keru-gate-comments.py")
CHECK_DRIFT = os.path.join(HOOKS, "keru-check-drift.py")
BLOCK_INLINE = os.path.join(HOOKS, "keru-block-inline-interp.py")

results = []


def check(name, ok):
    results.append((name, bool(ok)))


# --- keru-safe-read ----------------------------------------------------------

def sr_decision(cmd, cwd=None):
    """Decision for a Bash command under safe-read, with the model slow-path
    neutralized (dp hidden via empty HOME/PATH) so the test is deterministic and
    offline: the fast static path still returns 'allow' for provably-safe
    commands, and anything else hits the slow path which fail-safes to 'ask'.
    `cwd`, if given, is passed in the payload so relative-path resolution (the
    repo-file recognition) is deterministic. Returns 'allow', 'ask', or 'NONE'."""
    env = dict(os.environ)
    env["HOME"] = "/nonexistent"
    env["PATH"] = "/usr/bin:/bin"   # no `dp` here -> slow path fail-safes to ask
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    if cwd is not None:
        payload["cwd"] = cwd
    stdin = json.dumps(payload)
    out = subprocess.run([sys.executable, SAFE_READ], input=stdin,
                         capture_output=True, text=True, env=env).stdout.strip()
    if not out:
        return "NONE"
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"]
    except Exception:
        return "NONE"


def test_safe_read():
    # FAST PATH: provably read-only/local-reversible -> instant allow, no model.
    allow = [
        ("grep pipeline", 'grep -rn "foo" . | head'),
        ("git --no-pager diff", "git --no-pager diff --stat"),
        ("gh pr view", "gh pr view 123 --repo o/r --json title"),
        ("gh api GET", "gh api repos/o/r/rulesets --jq '.[].name'"),
        ("jira issue view", "jira issue view DBI-1 --plain"),
        ("go tool bare", "go tool | grep templ"),
        ("go get", "go get -tool github.com/a/b@v1"),
        ("pip list piped", "pip list | grep -i boto"),
        ("python -m py_compile", "python -m py_compile src/x.py"),
        (".venv python py_compile", ".venv/bin/python -m py_compile a.py"),
        # pup read subcommands the datadog-audit skill uses. traces search/aggregate
        # (walk a failing trace), monitors, and slos are all reads; `traces metrics`
        # (span-metric CRUD) is a write and must defer -> in the ask list below.
        ("pup traces search", 'pup traces search --query "env:production service:extend-api @http.status_code:500" --from "7d" --limit 3'),
        ("pup traces aggregate", 'pup traces aggregate --query "env:production status:error" --compute count --group-by service'),
        ("pup traces search trace_id piped", 'pup traces search --query "env:production trace_id:abc status:error" --from 7d --limit 20 --no-agent | jq -r ".data[].attributes.service"'),
        ("pup monitors search", 'pup monitors search --query "tag:(service:extend-api)" --per-page 50'),
        ("pup slos status", 'pup slos status 123 --from 7d --to now'),
        ("keru-jira-dev", "keru-jira-dev DBI-1477"),
        ("keru-jira-dev probe", 'keru-jira-dev DBI-1477 2>/dev/null || echo "NO_DEV_HELPER_OR_EMPTY"'),
        ("keru-bot-triage", "keru-bot-triage o/r"),
        ("keru-branch-cleanup audit", "keru-branch-cleanup audit ~/Documents/GitHub"),
        # keru-repo-update: both audit and update are local-reversible (update
        # stashes + --ff-only, restorable, never touches the remote), so both
        # fast-allow. Unlike keru-branch-cleanup clean, it has no destructive
        # subcommand to defer.
        ("keru-repo-update audit", "keru-repo-update audit ~/Documents/GitHub"),
        ("keru-repo-update update", "keru-repo-update update ~/Documents/GitHub/payments"),
        # keru-claude-update: only `audit` is read-only (`cli` installs a build,
        # `models` writes settings.json); both of those are in the ask list below.
        ("keru-claude-update audit", "keru-claude-update audit"),
        ("keru-claude-update audit --pin", "keru-claude-update audit --pin opus"),
        # gh api with an EXPLICIT GET method: -f/-F are query-string params, not a
        # POST body, so the search is read-only. The two real-session forms.
        ("gh api -X GET search/code",
         'gh api -X GET search/code -f q=\'"trace-analytics alert" datadog_monitor in:file language:hcl\' --jq \'.items[].html_url\' 2>&1 | head -20 || echo "SEARCH_FAILED"'),
        ("gh api -X GET search/code chained",
         'echo "==="; gh api -X GET search/code -f q=\'datadog_monitor in:file\' --jq \'.items[].html_url\' 2>&1 | head -10; echo "---"; gh api -X GET search/code -f q=\'a in:file\' --jq \'.total_count\' 2>&1 | head -3'),
        ("gh api --method GET", "gh api --method GET search/code -f q=foo --jq .total_count"),
        ("gh api --method=GET", "gh api --method=GET search/code -f q=foo"),
        ("gh api -XGET glued", "gh api -XGET search/code -f q=foo"),
        # `make <target>` for a build/test/lint/codegen target is local-reversible
        # (the hot path of writing-code / responding-to-ci), so it fast-allows
        # without a model call, same category as `go test` / `pytest`.
        ("make test", "make test"),
        ("make lint-local", "make lint-local"),
        ("make multi safe targets", "make lint test"),
        ("make -C sub build", "make -C ./sub build"),
        ("make -j4 test", "make -j4 test"),
        ("make VAR override", "make FOO=bar test"),
        ("gmake check", "gmake check"),
        ("make chained with go test", "make lint-local && go test ./..."),
        # `sleep` is a pure no-op wait, so a compound that pauses then reads is as
        # safe as the read. These are the exact forms that prompted before the fix.
        ("sleep then echo", "sleep 1 && echo x"),
        ("sleep then gh read", "sleep 30 && gh pr checks 821"),
        ("sleep bare piped", "sleep 5; ls"),
        # gofmt/goimports reformat Go source (git-reversible), same as `go fmt`.
        ("gofmt -l", "gofmt -l ."),
        ("gofmt -d chained", "gofmt -d . | head"),
        ("goimports -l", "goimports -l -w internal/"),
        # `timeout` recurses on the wrapped command: safe iff that command is.
        ("timeout go vet", "timeout 180 go vet ./..."),
        ("timeout with signal flag", "timeout -s KILL 60 go test ./..."),
        ("timeout kill-after", "timeout -k 10 30 make test"),
        ("timeout grep piped", "timeout 5 grep -rn foo . | head"),
        # bun dev subcommands (local-reversible) and `run <safe-script>`.
        ("bun install", "bun install"),
        ("bun run build", "bun run build"),
        ("bun test", "bun test"),
        ("bun build chained", "cd apps/dbi-docs && bun run build"),
        # docker/kubectl/aws/helm READ subcommands: inspect/list/logs/describe/get
        # and friends only read, so they fast-allow without a model call, the same
        # category as `gh ... view`. Every mutating verb (run/exec/apply/delete/
        # install/create) is NOT recognized and defers -> in the ask list below.
        ("docker ps", "docker ps -a"),
        ("docker images piped", "docker images | grep app"),
        ("docker logs", "docker logs my-container --tail 100"),
        ("docker inspect", "docker inspect abc123"),
        ("docker image ls namespace", "docker image ls"),
        ("docker compose ps", "docker compose ps"),
        ("docker -H host ps", "docker -H unix:///var/run/docker.sock ps"),
        ("kubectl get", "kubectl get pods -n prod -o wide"),
        ("kubectl describe", "kubectl describe deploy/api -n prod"),
        ("kubectl logs", "kubectl logs pod/api-xyz -n prod --tail 50"),
        ("kubectl -n ns get (verb after global flag)", "kubectl -n prod get svc"),
        ("kubectl auth can-i", "kubectl auth can-i get pods"),
        ("kubectl config view", "kubectl config view --minify"),
        ("kubectl top piped", "kubectl top pods -n prod | head"),
        ("aws describe", "aws ec2 describe-instances --region us-east-1"),
        ("aws list piped", "aws s3api list-buckets | jq ."),
        ("aws get-caller-identity", "aws sts get-caller-identity"),
        ("aws region-before-service", "aws --region us-east-1 ec2 describe-vpcs"),
        ("aws s3 ls", "aws s3 ls s3://bucket/path/"),
        ("aws s3api head-object", "aws s3api head-object --bucket b --key k"),
        ("helm list", "helm list -n prod"),
        ("helm status", "helm status my-release -n prod"),
        ("helm get values", "helm get values my-release"),
        ("helm template local render", "helm template ./chart"),
    ]
    for name, cmd in allow:
        check("safe-read fast-allows: " + name, sr_decision(cmd) == "allow")

    # SLOW PATH (model hidden -> fail-safe ASK): not provably safe by static
    # parsing. With dp present these get a model verdict; with it absent they must
    # ASK, never silently allow. The key guarantee: an unknown command is never
    # auto-allowed without a positive judgment.
    ask = [
        ("git push", "git push origin main"),
        ("rm -rf outside", "rm -rf /tmp/whatever"),
        ("go run remote@version", "go run github.com/a/b@latest fmt ."),
        ("go tool <name>", "go tool templ fmt ."),
        ("pip install", "pip install requests"),
        ("python script", "python main.py"),
        ("python -m http.server", "python -m http.server"),
        # docker/kubectl/aws/helm MUTATING verbs are not in the read allowlists,
        # so they still defer (fail-safe ask). run/exec run arbitrary code; the
        # per-segment cases prove a read chained before a mutation still defers.
        ("docker run", "docker run --rm alpine echo hi"),
        ("docker exec", "docker exec -it web sh"),
        ("docker rm", "docker rm -f web"),
        ("docker build", "docker build -t app ."),
        ("docker compose up", "docker compose up -d"),
        ("docker read then rm (per-segment)", "docker ps && docker rm -f web"),
        ("kubectl apply", "kubectl apply -f deploy.yaml"),
        ("kubectl delete", "kubectl delete pod api-xyz -n prod"),
        ("kubectl exec", "kubectl exec -it api -- sh"),
        ("kubectl port-forward", "kubectl port-forward svc/api 8080:80"),
        ("kubectl auth reconcile", "kubectl auth reconcile -f rbac.yaml"),
        ("kubectl config use-context", "kubectl config use-context prod"),
        ("kubectl read then delete (per-segment)", "kubectl get pods && kubectl delete pod x"),
        ("aws run-instances", "aws ec2 run-instances --image-id ami-123"),
        ("aws terminate-instances", "aws ec2 terminate-instances --instance-ids i-123"),
        ("aws s3 rm", "aws s3 rm s3://bucket/key"),
        ("aws lambda invoke", "aws lambda invoke --function-name f out.json"),
        ("helm install", "helm install my-release ./chart -n prod"),
        ("helm upgrade", "helm upgrade my-release ./chart -n prod"),
        ("helm uninstall", "helm uninstall my-release -n prod"),
        ("helm repo add", "helm repo add stable https://example.com"),
        # `make build` alone is safe now (a known target), so to keep testing the
        # "unknown command never auto-allowed" guarantee this pairs py_compile with
        # a make target NOT in the safe set (`deploy`), which must still defer.
        ("py_compile && make deploy", "python -m py_compile a.py && make deploy"),
        ("make bare (unknown default target)", "make"),
        ("make deploy", "make deploy"),
        ("make test + deploy (one unsafe taints)", "make test deploy"),
        ("gh api POST", "gh api -X POST repos/o/r/issues"),
        # No explicit method but field flags present: gh auto-switches GET->POST,
        # so this is a write and must defer.
        ("gh api -f no method (implicit POST)", "gh api repos/o/r/issues -f title=x"),
        ("gh api --method PATCH", "gh api --method PATCH repos/o/r/issues/1 -f state=closed"),
        ("keru-branch-cleanup clean", "keru-branch-cleanup clean ~/Documents/GitHub"),
        ("keru-claude-update cli", "keru-claude-update cli"),
        ("keru-claude-update models", "keru-claude-update models --pin opus"),
        # pup traces metrics is span-metric CRUD (a write); a flag value that
        # happens to read "search" must not promote it to a read.
        ("pup traces metrics create", "pup traces metrics create --file m.json"),
        ("pup traces metrics delete", "pup traces metrics delete some-metric-id"),
        # timeout must recurse, not blanket-approve: a destructive wrapped command
        # still defers. This is the guarantee that keeps the new timeout branch safe.
        ("timeout wrapping rm -rf", "timeout 5 rm -rf /tmp/x"),
        ("timeout wrapping git push", "timeout 60 git push origin main"),
        ("timeout no command", "timeout 10"),
        # sleep taints nothing, but a real mutation after it still defers per-segment.
        ("sleep then git push", "sleep 5 && git push origin main"),
        # bun run of an unknown script (could be a deploy) and bun x (fetch-exec)
        # are not provably safe: they defer.
        ("bun run deploy", "bun run deploy"),
        ("bun x arbitrary pkg", "bun x some-cli --do-thing"),
        ("bunx arbitrary pkg", "bunx create-app foo"),
    ]
    for name, cmd in ask:
        check("safe-read slow-asks (model absent): " + name, sr_decision(cmd) == "ask")

    # Inline interpreters are NOT safe-read's job (a separate block hook denies
    # them); safe-read should not fast-allow `python -c`.
    check("safe-read does not fast-allow python -c", sr_decision('python -c "import os"') != "allow")

    # THIS REPO's own tooling auto-allows regardless of interpreter: running the
    # test harness, installer, or a hook/helper script from the repo is trusted
    # wholesale. In the harness the source runs in place, so the hook resolves
    # _REPO_DIR from its own path (the installed copy uses the baked path). The
    # command's cwd is supplied so relative paths resolve against the repo.
    repo_allow = [
        ("test-hooks relative", "python3 repo-health/test-hooks.py", REPO),
        ("repo-health.sh relative", "bash repo-health/repo-health.sh hooks", REPO),
        ("install.sh dot-slash", "./scripts/install.sh", REPO),
        ("uninstall.sh relative", "bash scripts/uninstall.sh", REPO),
        ("hook script direct", "python3 scripts/hooks/keru-check-drift.py", REPO),
        ("absolute repo path (no cwd needed)",
         "python3 " + os.path.join(REPO, "repo-health", "test-hooks.py"), None),
        ("chained with a read", "python3 repo-health/test-hooks.py | tail -5", REPO),
    ]
    for name, cmd, cwd in repo_allow:
        check("safe-read allows repo tooling: " + name, sr_decision(cmd, cwd) == "allow")

    # ...but the recognition is scoped and cannot be abused: a path that escapes
    # the repo, a repo file run from the WRONG cwd (so the relative path misses),
    # a non-existent repo path, and a repo script chained before a REMOTE
    # mutation (per-segment: the second segment still defers) all fail closed.
    repo_ask = [
        ("path escaping repo", "python3 ../evil.py", REPO),
        ("relative path from wrong cwd", "python3 repo-health/test-hooks.py", "/tmp"),
        ("non-existent repo file", "python3 repo-health/does-not-exist.py", REPO),
        ("repo script then git push",
         "python3 repo-health/test-hooks.py && git push origin main", REPO),
    ]
    for name, cmd, cwd in repo_ask:
        check("safe-read defers non-repo/tainted: " + name, sr_decision(cmd, cwd) == "ask")


# --- keru-require-skill ------------------------------------------------------

def rs_block(user_text, invoked, stop_hook_active=False, trailing=None):
    """True if the Stop hook blocks for this turn.

    `trailing` is an optional list of extra raw records appended AFTER the human
    prompt and the Skill invocations, to simulate injected isMeta/non-human user
    records (skill body, hook feedback) that must NOT be read as the prompt."""
    recs = [{"type": "user", "message": {"content": user_text}}]
    for s in invoked:
        recs.append({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Skill", "input": {"skill": s}}]}})
    for extra in (trailing or []):
        recs.append(extra)
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    stdin = json.dumps({"transcript_path": path,
                        "stop_hook_active": stop_hook_active})
    out = subprocess.run([sys.executable, REQUIRE_SKILL], input=stdin,
                         capture_output=True, text=True).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_require_skill():
    slash = ("<command-name>/keru-pr-description</command-name>\n"
             "Write the PR description.\n"
             "Use the keru-gather-context skill to gather the ticket.")
    # The core regression (DBI-1470): a slash-command skill needs no Skill tool.
    check("slash command satisfies (no Skill tool, no block)",
          not rs_block(slash, []))
    check("slash command satisfies even if only gather-context invoked",
          not rs_block(slash, ["keru-gather-context"]))
    check("bare /keru-* line satisfies",
          not rs_block("/keru-addressing-pr-comments\nhandle these", []))
    notice = {"type": "user", "origin": {"kind": "task-notification"},
              "message": {"content": "<task-notification>Use the keru-addressing-pr-comments "
                                     "skill for this.</task-notification>"}}
    check("a subagent notification naming a skill is not the user's request",
          not rs_block("<command-name>/keru-writing-code</command-name>\nsigue", [],
                       trailing=[notice]))
    # Namespace: invoked keru-pr-review satisfies a requested pr-review.
    check("keru- wrapper invocation satisfies bare request",
          not rs_block("use the pr review skill", ["keru-pr-review"]))
    # The value case: a prose request ignored entirely still blocks once.
    check("prose 'use the X skill' not invoked -> blocks once",
          rs_block("recorda usar el skill de escribir ticket", []))
    # ...but never twice (loop cap).
    check("stop_hook_active caps at one block",
          not rs_block("recorda usar el skill de escribir ticket", [],
                       stop_hook_active=True))
    # No skill mentioned -> never blocks.
    check("no skill request -> no block",
          not rs_block("just summarize the diff", []))

    # isMeta records must NOT be read as the user's prompt. These are the
    # false-positive sources: the injected SKILL.md body, the "Base directory"
    # preamble, and the hook's own re-injected feedback. A plain human prompt
    # ("gracias, listo") with any of these trailing must NOT block.
    skill_body = {"type": "user", "isMeta": True, "message": {"content":
        "Implement: \n\nUse the `gather-context` skill to gather it and its chain."}}
    base_dir = {"type": "user", "isMeta": True, "message": {"content":
        "Base directory for this skill: /x/skills/keru-writing-code\n# Writing Code"}}
    hook_fb = {"type": "user", "isMeta": True, "message": {"content":
        "Stop hook feedback:\nYou were explicitly asked to use the `writing-code` skill this turn"}}
    check("isMeta skill-body not read as prompt -> no block",
          not rs_block("gracias, listo", [], trailing=[skill_body]))
    check("isMeta base-directory not read as prompt -> no block",
          not rs_block("gracias, listo", [], trailing=[base_dir]))
    check("isMeta hook-feedback does not re-trigger the hook -> no block",
          not rs_block("gracias, listo", [], trailing=[hook_fb]))
    # Defense in depth: even if the feedback text arrived as a real (non-meta)
    # prompt, requested_skill ignores its own feedback string.
    check("hook feedback text as non-meta prompt still does not block",
          not rs_block("Stop hook feedback:\nYou were explicitly asked to use "
                       "the `writing-code` skill this turn", []))

    # A newly-added skill is genuinely enforced (regression for the 6 that were
    # missing from the map): a prose "use the debugging skill" not invoked blocks.
    check("added skill (debugging) is enforced -> blocks once",
          rs_block("please use the debugging skill for this", []))

    # Negation: a FORBIDDEN skill must NOT be demanded. "do not use the X skill"
    # matches the USE_SKILL verb+skill shape, but a negator precedes the phrase, so
    # the hook must return None (no block) rather than ordering the very skill the
    # user prohibited. Both languages.
    check("EN negated request -> no block",
          not rs_block("do not use the writing-code skill here", []))
    check("ES negated request -> no block",
          not rs_block("no uses el skill de codigo", []))
    # The scan-every-occurrence loop: a later un-negated mention still asks for the
    # skill even after an earlier negated one, and an all-negated string never does.
    # Two occurrences of the SAME phrase pin the loop from both sides; a single
    # occurrence cannot (it would return on that one match and never test the scan,
    # and would pass or fail on the incidental distance of a negator from the window
    # edge rather than on the loop's logic).
    check("negated then affirmed (two occurrences) -> blocks on the affirmed one",
          rs_block("do not use the debugging skill; on reflection, do use the "
                   "debugging skill", []))
    check("both occurrences negated -> no block",
          not rs_block("do not use the debugging skill and, again, do not use "
                       "the debugging skill", []))
    # A non-negating "no" lead-in ("no problem", "there's no way") must NOT suppress
    # a genuine request: a clause boundary (comma/semicolon) between the "no" and the
    # phrase means it is not negating it. Both must still block.
    check("non-negating 'no problem' lead-in -> still blocks",
          rs_block("no problem, use the pr-review skill", []))
    check("non-negating 'there's no way' lead-in -> still blocks",
          rs_block("there's no way around it, use the debugging skill", []))

    # Every skill id in the hook's SKILLS table must exist on disk, and vice versa.
    check("hook skill ids match skills/ on disk (both ways)", _skill_ids_exist())


def _skill_ids_exist():
    """keru-require-skill's SKILLS table and the skill dirs on disk must match
    EXACTLY, both ways: every id maps to a real skill dir (no typo or stale id),
    AND every skill dir appears in the table (no skill silently left unguarded). A
    one-directional check let a disk skill missing from the map pass unnoticed,
    which is precisely how 6 skills went unenforced while docs advertised the
    safeguard."""
    import re
    src = open(REQUIRE_SKILL, encoding="utf-8").read()
    # Grab the first string in each ("id", [..]) tuple of the SKILLS list.
    map_ids = set(re.findall(r'\(\s*"(keru-[a-z-]+)"\s*,\s*\[', src))
    skills_dir = os.path.join(REPO, "skills")
    disk_ids = {d for d in os.listdir(skills_dir)
                if d.startswith("keru-") and os.path.isdir(os.path.join(skills_dir, d))}
    return bool(map_ids) and map_ids == disk_ids


# --- keru-check-output -------------------------------------------------------

def co_block(slash_cmd, assistant_msg, stop_hook_active=False):
    """True if the output gate blocks. Simulates a turn: a /keru-* prompt, then
    an assistant message (the delivered text)."""
    recs = [
        {"type": "user", "message": {"content":
            "<command-name>/%s</command-name>\ndo it" % slash_cmd}},
        {"type": "assistant", "message": {"content":
            [{"type": "text", "text": assistant_msg}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    stdin = json.dumps({"transcript_path": path,
                        "stop_hook_active": stop_hook_active})
    out = subprocess.run([sys.executable, CHECK_OUTPUT], input=stdin,
                         capture_output=True, text=True).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def co_block_noskill(user_text, assistant_msg):
    """Like co_block but the user prompt is plain text with NO /keru-* command and
    no Skill tool_use: exercises detection of a deliverable produced WITHOUT its
    skill ever being loaded (the audit case)."""
    recs = [
        {"type": "user", "message": {"content": user_text}},
        {"type": "assistant", "message": {"content":
            [{"type": "text", "text": assistant_msg}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    out = subprocess.run([sys.executable, CHECK_OUTPUT],
                         input=json.dumps({"transcript_path": path, "stop_hook_active": False}),
                         capture_output=True, text=True).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_check_output():
    # pr-review: compliant verdict-first opening passes; decorated/prose opening blocks.
    good_review = "Approve\n\n### Nits\n`a.go:1`\n```go\nx\n```\nWhy: nit."
    check("pr-review verdict-first -> no block", not co_block("keru-pr-review", good_review))
    # The canonical "Verdict: <word>" label opens cleanly (the real review of DBI today).
    check("pr-review 'Verdict: Comment' label -> no block",
          not co_block("keru-pr-review", "Verdict: Comment\n\n### Questions\n`a.go:1`\nComment (paste into the PR):\ntext\nWhy: y."))
    check("pr-review bare 'Comment' still ok -> no block",
          not co_block("keru-pr-review", "Comment\n\n### Questions\n`a.go:1`\nWhy: y."))
    # But the label must not carry decoration after the word.
    check("pr-review 'Verdict: Comment (decorated)' -> BLOCK",
          co_block("keru-pr-review", "Verdict: Comment (one question on paging)\n\n### Questions\n`a.go:1`"))
    check("pr-review decorated verdict -> BLOCK",
          co_block("keru-pr-review", "`Request changes` (one blocking question)\n\n### Blocking\n`a.go:1`"))
    check("pr-review prose intro before heading -> BLOCK",
          co_block("keru-pr-review",
                   "The find-and-replace is clean. The one issue is behavioral.\n\n### Blocking\n`a.go:1`"))
    # A clarifying question (not the deliverable) must NOT block.
    check("pr-review: asking for the PR number -> no block",
          not co_block("keru-pr-review", "What PR number should I review?"))

    # writing-tickets: title-first passes; prose intro blocks.
    good_ticket = "**Fix the thing**\n\nProblem.\n\n### Acceptance Criteria\n\n- x"
    check("ticket title-first -> no block", not co_block("keru-writing-tickets", good_ticket))
    check("ticket prose intro -> BLOCK",
          co_block("keru-writing-tickets",
                   "Here is the ticket you asked for:\n\n**Fix it**\n\n### Acceptance Criteria\n- x"))
    check("ticket: asking which type -> no block",
          not co_block("keru-writing-tickets", "Is this a bug or a feature ticket?"))

    # pr-description: title block first passes; recap intro blocks.
    good_desc = "**feat(<scope>): [DBI-1] do x**\n\n````\n## What Changed\nstuff\n````"
    check("pr-desc title-first -> no block", not co_block("keru-pr-description", good_desc))
    check("pr-desc prose intro -> BLOCK",
          co_block("keru-pr-description",
                   "Based on the branch work, here is the description.\n\n## What Changed\nstuff"))

    # investigation: heading-first passes; generic intro blocks.
    good_inv = "## How onboarding works\n\nThe consumer registers via...\n\n## Sources\n\n- x"
    check("investigation heading-first -> no block", not co_block("keru-investigation", good_inv))
    check("investigation generic intro -> BLOCK",
          co_block("keru-investigation",
                   "I investigated the Kafka onboarding. Here is what I found.\n\n## Findings\ntext"))

    # addressing-pr-comments: bold-header block-first passes; summary intro blocks.
    good_addr = "**a.go:55**\n\nValid; applied a root-cause rewrite.\n\n**b.md:10**\n\nPushed back."
    check("addressing bold-block-first -> no block", not co_block("keru-addressing-pr-comments", good_addr))
    check("addressing bare path:line (not bold) -> BLOCK",
          co_block("keru-addressing-pr-comments", "`a.go:55`\n\nApplied a rewrite."))
    check("addressing summary intro -> BLOCK",
          co_block("keru-addressing-pr-comments",
                   "I reviewed both Copilot comments. Here is how I handled them.\n\n**a.go:55**\nApplied."))

    # bot-triage: bold service header first passes; intro blocks. (Links use ':'
    # not an em dash, matching the no-em-dash rule the template now follows.)
    good_bot = "**xapi**\nPRs:\n\n- bump x: http://u\n\nSecurity (no fixing PR): none"
    check("bot-triage service-header-first -> no block", not co_block("keru-bot-triage", good_bot))
    check("bot-triage intro before service -> BLOCK",
          co_block("keru-bot-triage",
                   "I triaged all 3 repos. Here is the rundown.\n\n**xapi**\nPRs:\n- bump x: http://u"))

    # The loop cap holds for this hook too.
    check("check-output stop_hook_active cap",
          not co_block("keru-pr-review", "Prose intro that would otherwise block.\n### Blocking\n`a.go:1`",
                       stop_hook_active=True))

    # Em-dash rule (Playbook): a well-formed deliverable with an em dash in prose
    # is still blocked; em dashes inside code/diffs are allowed; clean passes.
    em_review = "Approve\n\n### Nits\n`a.go:1`\nWhy: this is fine — but the dash is not."
    check("em dash in deliverable prose -> BLOCK", co_block("keru-pr-review", em_review))
    em_in_code = ("Approve\n\n### Nits\n`a.go:1`\n```go\nx := a — b // pasted diff\n```\n"
                  "Why: the dash above is inside code, allowed.")
    check("em dash only inside code fence (```go) -> no block", not co_block("keru-pr-review", em_in_code))
    em_in_diff = ("Comment\n\n### Nits\n`a.go:1`\n```diff\n- old — value\n```\nWhy: nit.")
    check("em dash inside ```diff -> no block", not co_block("keru-pr-review", em_in_diff))
    em_ticket = "**Fix the thing**\n\nProblem — with a dash.\n\n### Acceptance Criteria\n- x"
    check("em dash in ticket prose -> BLOCK", co_block("keru-writing-tickets", em_ticket))
    # The audit's real case (caught live by /keru-pr-review): an em dash inside the
    # "Comment (paste into the PR)" block, which is FENCED PROSE that goes verbatim
    # to GitHub. A bare (no-language) fence is prose, so the rule applies there.
    em_paste = ("Verdict: Comment\n\n### Questions\n`config.go:55`\n\n"
                "Comment (paste into the PR):\n\n`````\n"
                "This drops the retry these writes rely on — the lag surfaces as NotFound.\n"
                "`````\n\nWhy: AC asks to confirm.")
    check("em dash inside paste-into-PR block (fenced prose) -> BLOCK",
          co_block("keru-pr-review", em_paste))
    # The audit's exact regression (addressing-pr-comments deliverable, PR #915): the
    # paste block was tagged ```markdown, which routed it into _strip_code's code
    # branch and hid three em dashes from the gate, so the file passed. A markdown/md
    # -tagged fence in a deliverable is a paste-into-destination block (prose shipped
    # verbatim), not a code sample, so its prose must stay checked like a bare fence.
    em_md_paste = ("Verdict: Comment\n\n### Questions\n`config.go:55`\n\n"
                   "Comment (paste into the PR):\n\n```markdown\n"
                   "Thanks Logan — all fifteen verified out and applied.\n"
                   "```\n\nWhy: AC asks to confirm.")
    check("em dash inside ```markdown paste block (prose) -> BLOCK",
          co_block("keru-pr-review", em_md_paste))
    em_md_short = ("Verdict: Comment\n\n### Questions\n`config.go:55`\n\n"
                   "Comment (paste into the PR):\n\n```md\n"
                   "One reply — verbatim to GitHub.\n```\n\nWhy: nit.")
    check("em dash inside ```md paste block (prose) -> BLOCK",
          co_block("keru-pr-review", em_md_short))
    # False-positive guard: a clean markdown paste block (no em dash) still passes,
    # and a real code fence with an em dash is still excused (```go covered above).
    clean_md_paste = ("Verdict: Comment\n\n### Questions\n`config.go:55`\n\n"
                      "Comment (paste into the PR):\n\n```markdown\n"
                      "Thanks Logan, all fifteen verified out and applied.\n"
                      "```\n\nWhy: AC asks to confirm.")
    check("clean ```markdown paste block -> no block",
          not co_block("keru-pr-review", clean_md_paste))
    # A malformed-opening message is still caught on the opening first, regardless.
    check("clean deliverable, no dash -> no block",
          not co_block("keru-pr-review", "Approve\n\n### Nits\n`a.go:1`\nWhy: clean, no dash here."))

    # Language rule (Playbook: all deliverables in English regardless of chat
    # language). A well-formed ticket whose PROSE is Spanish is blocked; its
    # English twin passes. This is the live bug: chat is Spanish, deliverable must
    # not be. Detection is conservative (Spanish-only punctuation, or >=3 marker
    # words), so an English deliverable that merely mentions a foreign package name
    # is not tripped.
    es_ticket = ("**Cerrar los PRs duplicados**\n\nHay que cerrar los PRs duplicados "
                 "y actualizar las vulnerabilidades.\n\n### Acceptance Criteria\n"
                 "- Los duplicados quedan cerrados.")
    check("Spanish ticket prose -> BLOCK", co_block("keru-writing-tickets", es_ticket))
    en_ticket = ("**Close the duplicate PRs**\n\nClose the stale duplicate bot PRs and "
                 "remediate the alerts.\n\n### Acceptance Criteria\n\n- The duplicates are closed.")
    check("English ticket prose -> no block", not co_block("keru-writing-tickets", en_ticket))
    # Spanish-only inverted punctuation alone is enough to prove non-English.
    es_punct = "**Arreglar esto**\n\n¿Por qué falla?\n\n### Acceptance Criteria\n- x"
    check("Spanish inverted punctuation -> BLOCK", co_block("keru-writing-tickets", es_punct))
    # False-positive guard: an English deliverable naming foreign identifiers/pkgs
    # in code (path-to-regexp, a repo slug) must NOT be flagged as non-English.
    en_with_code = ("**xapi**\nPRs:\n\n- bump `path-to-regexp` in los-angeles-svc: http://u\n\n"
                    "Security (no fixing PR): none")
    check("English deliverable with foreign code tokens -> no block",
          not co_block("keru-bot-triage", en_with_code))

    # Well-formed-markdown rule (Playbook, render-correctness). A deliverable whose
    # opening/em-dash/language are all fine is STILL blocked if a list is glued to
    # surrounding text or a code fence is left unclosed; the clean twin passes.
    # This is the MD032/unclosed-fence class the datadog report tripped live.
    md_glued_above = ("**svc**\nVolume: 7 errors over 24h\n- foo: bar, one recurring error x3\n"
                      "- baz\n\nTicket candidates: none")
    check("list glued to text above -> BLOCK (datadog)", co_block("keru-datadog-audit", md_glued_above))
    md_glued_below = ("**svc**\nVolume: 7 errors over 24h\n\n- foo: bar, one recurring error x3\n"
                      "- baz\nTicket candidates: none")
    check("list glued to text below -> BLOCK (datadog)", co_block("keru-datadog-audit", md_glued_below))
    md_clean = ("**svc**\nVolume: 7 errors over 24h\n\n- foo: bar, one recurring error x3\n"
                "- baz\n\nTicket candidates: none")
    check("list with blank lines -> no block (datadog)", not co_block("keru-datadog-audit", md_clean))
    # Unclosed fence anywhere in a deliverable body swallows the rest as code.
    md_unclosed = ("**svc**\nVolume: 7 errors\n\n- foo\n\nTicket candidates: none\n\n```text\nleftover")
    check("unclosed code fence -> BLOCK (datadog)", co_block("keru-datadog-audit", md_unclosed))
    # False-positive guards: nested fences of different lengths are valid (the
    # pr-review paste block nests a ```` inside `````), and an indented
    # continuation line under a list item does not end the list.
    md_nested_ok = ("Verdict: Comment\n\n### Questions\n`a.go:1`\n\nComment (paste into the PR):\n\n"
                    "`````\nSome prose with an inner ```go fence shown literally.\n`````\n\nWhy: nit.")
    check("nested/longer fences -> no block (pr-review)", not co_block("keru-pr-review", md_nested_ok))
    md_cont_ok = ("**Fix the thing**\n\nProblem.\n\n### Acceptance Criteria\n\n- one, which\n"
                  "  continues on an indented line\n- two")
    check("indented list continuation -> no block (ticket)", not co_block("keru-writing-tickets", md_cont_ok))

    # NON-DELIVERABLE turns must never be gated: a turn that asks for missing
    # context or waits on a design decision is not the deliverable, so the gate
    # must stay silent. These are the false-positives the gate must not produce.
    missing_context = [
        ("keru-pr-review", "I need the PR number or link to review. Which PR is this?"),
        ("keru-pr-description", "I can't write this without the ticket. What's the Jira key?"),
        ("keru-writing-tickets", "Before I draft: is this a bug, feature, or investigation ticket?"),
        ("keru-investigation", "I couldn't find the investigation doc referenced in DBI-1. Point me to it?"),
        ("keru-bot-triage", "No repo list is saved. Which repos should I triage?"),
        ("keru-addressing-pr-comments", "Which PR are these comments on? I need the link first."),
    ]
    for slash, msg in missing_context:
        check("non-deliverable (missing context) not gated: " + slash,
              not co_block(slash, msg))

    design_decision = [
        ("keru-pr-description",
         "There are two ways to frame this PR depending on whether the opsgenie "
         "removal is intentional. Can you confirm before I write it?"),
        ("keru-addressing-pr-comments",
         "One comment hinges on whether the tier is critical. How do you want me to respond?"),
        ("keru-writing-tickets",
         "This could be one ticket or split into three. Which scope do you want?"),
    ]
    for slash, msg in design_decision:
        check("non-deliverable (design decision pending) not gated: " + slash,
              not co_block(slash, msg))

    # Deliverable produced WITHOUT loading its skill (the audit case): a strong
    # structural fingerprint still gates it. No /keru-* command, no Skill tool.
    free = "Logan left a comment on config.go:55, validate again"
    # addressing: two bold path:line blocks with a prose intro -> caught.
    check("no-skill addressing (prose + 2 blocks) -> BLOCK",
          co_block_noskill(free, "Reviewed both.\n\n**a.go:55**\n\nApplied.\n\n**b.go:10**\n\nPushed back."))
    check("no-skill addressing well-formed (2 blocks) -> no block",
          not co_block_noskill(free, "**a.go:55**\n\nApplied.\n\n**b.go:10**\n\nPushed back."))
    # ticket WELL-FORMED but no skill loaded: bold title + AC fingerprints it, so
    # an em dash or other body issue would still be checked. (Opening is fine here.)
    check("no-skill ticket well-formed (title + ### AC) -> no block",
          not co_block_noskill(free, "**Fix the thing**\n\nProblem.\n\n### Acceptance Criteria\n\n- x"))
    # Accepted limit: a ticket that OPENS with prose and was produced with no
    # /keru-* command has no strong fingerprint (the title-first form is the
    # fingerprint), so it is not gated. Firing on a bare '### Acceptance Criteria'
    # in free chat would false-positive. With the slash command it IS caught
    # (see test_check_output's co_block cases).
    check("no-skill ticket prose-opening -> not gated (accepted limit)",
          not co_block_noskill(free, "Here is the ticket:\n\n**T**\n\n### Acceptance Criteria\n- x"))
    # Plain chat must NOT be gated even if it mentions a path:line or a heading.
    check("no-skill plain chat (one path mention) -> no block",
          not co_block_noskill(free, "The issue is in config.go:55, middleware.Timeout cancels context."))
    check("no-skill single bold block (too weak) -> no block",
          not co_block_noskill(free, "**a.go:55**\n\nJust one note, not the deliverable."))
    # Known limit (chosen): a review produced without its skill is only caught
    # when well-formed; a prose-opening review without a verdict is NOT gated,
    # because firing on a bare '### Questions' would false-positive in chat.
    check("no-skill review prose-opening -> not gated (accepted limit)",
          not co_block_noskill(free, "The change looks clean overall.\n\n### Questions\n`a.go:1`"))


def judge_blocks(slash_cmd, assistant_msg):
    """Run keru-judge-output with `dp` made unavailable (empty PATH) so no real
    model call happens. Tests the GATING logic only: the judge must exit silent
    (no block) for anything that should not reach the model, and fail-open when
    `dp` is missing. A live judgment test is too slow/costly for repo-health."""
    recs = [
        {"type": "user", "message": {"content":
            "<command-name>/%s</command-name>\ndo it" % slash_cmd}},
        {"type": "assistant", "message": {"content":
            [{"type": "text", "text": assistant_msg}]}},
    ]
    fd, path = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    env = dict(os.environ)
    env["PATH"] = "/nonexistent"      # hide `dp`
    env["HOME"] = "/nonexistent"      # hide the mise fallback path too
    out = subprocess.run([sys.executable, JUDGE_OUTPUT],
                         input=json.dumps({"transcript_path": path, "stop_hook_active": False}),
                         capture_output=True, text=True, env=env).stdout.strip()
    os.unlink(path)
    return bool(out) and json.loads(out).get("decision") == "block"


def test_judge_gating():
    # Chat / non-deliverable turn must not reach the judge and must not block.
    check("judge: chat turn -> no block (no model call)",
          not judge_blocks("keru-pr-review", "Sure, I'll review the PR shortly."))
    check("judge: clarifying question -> no block",
          not judge_blocks("keru-pr-review", "Which PR should I review?"))
    # A deliverable-shaped turn would reach the model, but with `dp` hidden the
    # judge fails open (no block) rather than wedging the turn.
    check("judge: fail-open when dp unavailable -> no block",
          not judge_blocks("keru-pr-review", "Verdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # investigation is excluded from the judge (it has its own adversarial review),
    # so a well-formed investigation never reaches the judge: must not block even
    # though dp is hidden (proves it short-circuited before the model call).
    check("judge: investigation excluded -> no block",
          not judge_blocks("keru-investigation", "## Findings\n\nThe consumer registers via X.\n\n## Sources\n- a"))
    # The judged set must match the intended four-plus-bot-triage list exactly.
    import importlib.util as _ilu
    _s = _ilu.spec_from_file_location("kjo", JUDGE_OUTPUT)
    _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)
    check("judge: JUDGED_SKILLS is exactly the intended set",
          _m.JUDGED_SKILLS == {"pr-review", "writing-tickets", "pr-description",
                               "addressing-pr-comments", "bot-triage", "datadog-audit"})


def gate_denies(file_path, content, tool="Write"):
    """Run the PreToolUse Write/Edit gate; True if it denies the write."""
    return gate_verdict(file_path, content, tool)[0] == "deny"


def gate_reason(file_path, content, tool="Write"):
    """The gate's reason string for one payload, or '' when it allowed silently.
    A denial has to be actionable, so some tests assert on what it says."""
    return gate_verdict(file_path, content, tool)[1]


def gate_verdict(file_path, content, tool="Write"):
    """(decision, reason) from the gate for one Write/Edit payload. ('', '') when
    the gate stayed silent, which is how it allows."""
    key = "content" if tool == "Write" else "new_string"
    payload = {"tool_name": tool, "tool_input": {"file_path": file_path, key: content}}
    out = subprocess.run([sys.executable, GATE], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return "", ""
    try:
        h = json.loads(out)["hookSpecificOutput"]
        return h.get("permissionDecision", ""), h.get("permissionDecisionReason", "")
    except Exception:
        return "", ""


def test_write_gate():
    # A gated draft is accepted only in the deliverables dir, so every CONTENT
    # assertion below uses a path there; the location rule is asserted on its own
    # at the end. Nothing is created: the gate validates the payload, it does not
    # write. The dir is resolved the same way the gate resolves it.
    _cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    _ddir = os.path.join(_cfg, "keru-deliverables")

    def dpath(name):
        return os.path.join(_ddir, name)

    P = dpath("keru-deliverable-pr-review.md")
    # Malformed deliverable to the gated path -> DENY (file never written).
    check("write-gate: malformed review -> deny",
          gate_denies(P, "Verified CI. Now:\n\nVerdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # Compliant deliverable -> allowed (no deny).
    check("write-gate: valid review -> allow",
          not gate_denies(P, "Verdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # Em dash in the gated file -> deny.
    check("write-gate: em-dash review -> deny",
          gate_denies(P, "Verdict: Comment\n\n### Nits\n`a.go:1`\nComment (paste into the PR):\n`````\nreuse it — please\n`````\nWhy: x."))
    # A NON-deliverable file (normal code) is never gated, even with an em dash.
    check("write-gate: normal code file -> allow",
          not gate_denies("/Users/x/main.go", "package main // a — b"))

    # Disambiguating <id> suffix (Jira key / PR number) is still gated: the skill
    # must resolve from the stem despite the suffix, so a malformed deliverable to
    # an id-suffixed path is denied and a valid one is allowed.
    check("write-gate: id-suffixed review (PR num) malformed -> deny",
          gate_denies(dpath("keru-deliverable-pr-review-3254.md"),
                      "Intro prose.\n\nVerdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    check("write-gate: id-suffixed review (PR num) valid -> allow",
          not gate_denies(dpath("keru-deliverable-pr-review-3254.md"),
                          "Verdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok."))
    # A skill name that itself contains hyphens must resolve with an id suffix too.
    check("write-gate: hyphenated skill + Jira id malformed -> deny",
          gate_denies(dpath("keru-deliverable-addressing-pr-comments-DBI-1477.md"),
                      "I reviewed both.\n\n**a.go:55**\n\nApplied."))
    check("write-gate: hyphenated skill + Jira id valid -> allow",
          not gate_denies(dpath("keru-deliverable-addressing-pr-comments-DBI-1477.md"),
                          "**a.go:55**\n\nApplied a rewrite.\n\n**b.md:10**\n\nPushed back."))
    # Em dash still caught with an id suffix present.
    check("write-gate: id-suffixed ticket em-dash -> deny",
          gate_denies(dpath("keru-deliverable-writing-tickets-DBI-9.md"),
                      "**Fix it**\n\nProblem — dash.\n\n### Acceptance Criteria\n- x"))
    # Language rule (Playbook: all deliverables in English). The live bug: a ticket
    # drafted in the chat language (Spanish) was written because nothing enforced
    # English. A well-formed-but-Spanish ticket to the gated path must now DENY.
    check("write-gate: Spanish ticket -> deny",
          gate_denies(dpath("keru-deliverable-writing-tickets-ES.md"),
                      "**Cerrar los PRs duplicados**\n\nHay que cerrar los PRs "
                      "duplicados y actualizar las vulnerabilidades de seguridad.\n\n"
                      "### Acceptance Criteria\n- Los duplicados quedan cerrados."))
    # The English translation of the same ticket is allowed (proves it is the
    # language, not the content, that was blocked).
    check("write-gate: English ticket -> allow",
          not gate_denies(dpath("keru-deliverable-writing-tickets-EN.md"),
                          "**Close the duplicate PRs**\n\nClose the stale duplicate "
                          "bot PRs and remediate the security alerts.\n\n"
                          "### Acceptance Criteria\n\n- The duplicates are closed."))
    # A stem that names no known skill is not gated (allowed), even malformed.
    check("write-gate: unknown skill stem -> allow",
          not gate_denies(dpath("keru-deliverable-nonsense-skill.md"), "Whatever — prose."))
    # Ticket path enforces the ticket contract.
    check("write-gate: malformed ticket -> deny",
          gate_denies(dpath("keru-deliverable-writing-tickets.md"),
                      "Here is the ticket:\n\n**T**\n\n### Acceptance Criteria\n- x"))
    check("write-gate: valid ticket -> allow",
          not gate_denies(dpath("keru-deliverable-writing-tickets.md"),
                          "**Fix it**\n\nProblem.\n\n### Acceptance Criteria\n\n- x"))
    # Edit tool on a deliverable file is gated too (new_string validated).
    check("write-gate: Edit malformed review -> deny",
          gate_denies(P, "Intro prose.\n\nVerdict: Approve\n\n### Nits\n`a.go:1`\nWhy: ok.", tool="Edit"))

    # LOCATION. A compliant deliverable is still denied outside the deliverables
    # dir: /tmp was the old home and does not survive a reboot here, and the rule
    # is enforced rather than left to whichever skill file the model loaded.
    valid_ticket = "**Fix it**\n\nProblem.\n\n### Acceptance Criteria\n\n- x"
    check("write-gate: valid ticket in /tmp -> deny (wrong location)",
          gate_denies("/tmp/keru-deliverable-writing-tickets.md", valid_ticket))
    check("write-gate: valid ticket in the deliverables dir -> allow",
          not gate_denies(dpath("keru-deliverable-writing-tickets.md"), valid_ticket))
    # A literal '~' is refused, not expanded: the Write tool would create a
    # directory actually named '~' instead of resolving it to the home dir.
    check("write-gate: unexpanded ~ path -> deny",
          gate_denies("~/.claude/keru-deliverables/keru-deliverable-writing-tickets.md",
                      valid_ticket))
    # The denial must be actionable, so it names the directory to write to.
    check("write-gate: location denial names the deliverables dir",
          _ddir in gate_reason("/tmp/keru-deliverable-writing-tickets.md", valid_ticket))
    # An unknown stem is still ungated wherever it lives: the location rule only
    # applies once the stem resolves to a real skill contract.
    check("write-gate: unknown stem in /tmp -> allow",
          not gate_denies("/tmp/keru-deliverable-nonsense-skill.md", "Whatever prose."))

    # Regression: the INSTALLED copies have no .py extension. spec_from_file_location
    # infers the loader from the extension, so an extensionless gate used to fail to
    # load its checkers and fail-open (let em dashes through). Replicate that exact
    # condition: copy gate + check-output to a temp dir WITHOUT .py and confirm the
    # gate still loads checkers and denies. This is the bug the repo-path tests miss.
    import shutil
    d = tempfile.mkdtemp()
    try:
        shutil.copy(GATE, os.path.join(d, "keru-gate-deliverable"))
        shutil.copy(CHECK_OUTPUT, os.path.join(d, "keru-check-output"))
        payload = {"tool_name": "Write", "tool_input": {
            "file_path": dpath("keru-deliverable-writing-tickets.md"),
            "content": "**T**\n\nx — y.\n\n### Acceptance Criteria\n- a"}}
        out = subprocess.run([sys.executable, os.path.join(d, "keru-gate-deliverable")],
                             input=json.dumps(payload), capture_output=True, text=True).stdout.strip()
        denied = bool(out) and json.loads(out).get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
        check("write-gate: extensionless (installed-style) still denies em dash", denied)
    finally:
        shutil.rmtree(d, ignore_errors=True)


# --- keru-check-drift --------------------------------------------------------
# The SessionStart install-drift check. Two independent signals, both exercised
# offline and deterministically: (B) the activation-hash logic is pure and needs
# no git, so its drift/no-drift cases run against a plain temp layout; (A) the
# "behind origin" logic runs against a LOCAL bare remote (no network), forcing
# the throttled fetch by aging FETCH_HEAD. The fetch's own failure mode is
# fail-open by design, so it is not itself asserted here.

def _drift(argv, claude_dir):
    """Run keru-check-drift with CLAUDE_CONFIG_DIR (and HOME) pinned to a sandbox,
    so the marker it reads/writes never touches the real ~/.claude."""
    env = dict(os.environ)
    env["CLAUDE_CONFIG_DIR"] = claude_dir
    env["HOME"] = claude_dir
    return subprocess.run([sys.executable, CHECK_DRIFT, *argv],
                          capture_output=True, text=True, env=env)


def _write_layout(root, skill_names):
    """A minimal stand-in for this repo's activatable layout: the skill dirs, the
    two config/*.json, install.sh, and one helper + one hook script."""
    for n in skill_names:
        d = os.path.join(root, "skills", n)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "SKILL.md"), "w") as f:
            f.write("---\nname: %s\n---\n# %s\nbody\n" % (n, n))
    os.makedirs(os.path.join(root, "config"), exist_ok=True)
    with open(os.path.join(root, "config", "permissions.json"), "w") as f:
        json.dump({"permissions": {}}, f)
    with open(os.path.join(root, "config", "hooks.json"), "w") as f:
        json.dump({"hooks": {}}, f)
    os.makedirs(os.path.join(root, "scripts", "helpers"), exist_ok=True)
    os.makedirs(os.path.join(root, "scripts", "hooks"), exist_ok=True)
    with open(os.path.join(root, "scripts", "install.sh"), "w") as f:
        f.write("#!/usr/bin/env bash\necho install\n")
    with open(os.path.join(root, "scripts", "helpers", "keru-x.sh"), "w") as f:
        f.write("#!/usr/bin/env bash\necho x\n")
    with open(os.path.join(root, "scripts", "hooks", "keru-y.py"), "w") as f:
        f.write("print('y')\n")


def _run_git(args, cwd=None):
    """git with author env set and user/system config ignored, so commits succeed
    regardless of the host's git config."""
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_SYSTEM="/dev/null")
    cmd = ["git"] + (["-C", cwd] if cwd else []) + args
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def _commit(repo, fname, content):
    with open(os.path.join(repo, fname), "w") as f:
        f.write(content + "\n")
    _run_git(["add", "-A"], cwd=repo)
    _run_git(["commit", "-q", "-m", content], cwd=repo)


def _init_repo_pair(base):
    """A local bare 'remote' with one commit on main, and a clone of it. No
    network: the clone's origin is a filesystem path."""
    os.makedirs(base)
    remote = os.path.join(base, "remote.git")
    work = os.path.join(base, "work")
    clone = os.path.join(base, "clone")
    # Both the bare remote and the work tree must default to main; otherwise the
    # remote inherits the host's default (e.g. master), origin/HEAD in the clone
    # dangles, and the clone lands on the wrong branch.
    _run_git(["-c", "init.defaultBranch=main", "init", "-q", "--bare", remote])
    _run_git(["-c", "init.defaultBranch=main", "init", "-q", work])
    _run_git(["symbolic-ref", "HEAD", "refs/heads/main"], cwd=work)
    _commit(work, "a.txt", "a")
    _run_git(["remote", "add", "origin", remote], cwd=work)
    _run_git(["push", "-q", "-u", "origin", "main"], cwd=work)
    _run_git(["clone", "-q", remote, clone])
    return work, clone


def _age_fetch_head(repo):
    """Make the last fetch look old so the hook's throttle actually fetches this
    run (FETCH_INTERVAL is hours). Resolves the real git dir for robustness."""
    gd = (_run_git(["rev-parse", "--git-dir"], cwd=repo).stdout or "").strip()
    if gd and not os.path.isabs(gd):
        gd = os.path.join(repo, gd)
    try:
        fh = os.path.join(gd, "FETCH_HEAD")
        open(fh, "a").close()
        os.utime(fh, (0, 0))
    except OSError:
        pass


def test_check_drift():
    base = tempfile.mkdtemp()
    try:
        # --- signal B: activation-hash drift (offline, deterministic) ---------
        repo = os.path.join(base, "repo")
        os.makedirs(repo)
        _write_layout(repo, ["keru-a", "keru-b"])
        cfg = os.path.join(base, "cfg")
        os.makedirs(cfg)

        # No marker yet: signal B stays silent (nothing to compare against).
        check("drift: no marker -> silent",
              _drift([repo], cfg).stdout.strip() == "")

        # --write-marker records the state, returns 0, and writes a hashed marker.
        wm = _drift(["--write-marker", repo], cfg)
        marker = os.path.join(cfg, ".keru-installed-rev")
        check("drift: --write-marker returns 0", wm.returncode == 0)
        check("drift: marker file created with a hash",
              os.path.exists(marker) and "hash" in json.load(open(marker)))

        # Marker == current state -> silent (the round-trip the shared hash logic
        # guarantees: what the installer wrote is what the check reads).
        check("drift: unchanged after install -> silent",
              _drift([repo], cfg).stdout.strip() == "")

        # A SKILL.md body is live via the symlink, so its contents are excluded
        # from the hash: editing one must NOT trigger a reinstall notice.
        with open(os.path.join(repo, "skills", "keru-a", "SKILL.md"), "w") as f:
            f.write("---\nname: keru-a\n---\n# a totally different body\n")
        check("drift: editing a SKILL.md body -> silent (contents excluded)",
              _drift([repo], cfg).stdout.strip() == "")

        # Adding a skill changes the activatable SET -> notice.
        os.makedirs(os.path.join(repo, "skills", "keru-c"))
        check("drift: adding a skill -> reinstall notice",
              "changed since the last install" in _drift([repo], cfg).stdout)

        # Editing config/*.json (merged, not symlinked) -> notice.
        _drift(["--write-marker", repo], cfg)
        with open(os.path.join(repo, "config", "permissions.json"), "w") as f:
            json.dump({"permissions": {"allow": ["X"]}}, f)
        check("drift: editing config/*.json -> reinstall notice",
              "changed since the last install" in _drift([repo], cfg).stdout)

        # Editing a scripts/hooks script (copied onto PATH, not symlinked) -> notice.
        _drift(["--write-marker", repo], cfg)
        with open(os.path.join(repo, "scripts", "hooks", "keru-y.py"), "w") as f:
            f.write("print('changed')\n")
        check("drift: editing a scripts/hooks script -> reinstall notice",
              "changed since the last install" in _drift([repo], cfg).stdout)

        # --- arg handling / fail-open -----------------------------------------
        no_arg = _drift([], cfg)
        check("drift: no repo arg -> silent, exit 0",
              no_arg.returncode == 0 and no_arg.stdout.strip() == "")
        check("drift: --write-marker with no repo -> exit 2",
              _drift(["--write-marker"], cfg).returncode == 2)
        missing = _drift([os.path.join(base, "does-not-exist")], cfg)
        check("drift: nonexistent repo -> fail-open (exit 0, silent)",
              missing.returncode == 0 and missing.stdout.strip() == "")

        # --- signal A: behind origin (offline, via a local bare remote) -------
        if shutil.which("git"):
            work, clone = _init_repo_pair(os.path.join(base, "git"))
            gcfg = os.path.join(base, "gcfg")
            os.makedirs(gcfg)
            # On the default branch, HEAD == origin (fetch throttle skips): silent.
            check("drift: on default, up to date -> silent",
                  "behind origin" not in _drift([clone], gcfg).stdout)
            # Advance the remote; aging FETCH_HEAD forces the hook to fetch, and
            # it should then report the clone is behind.
            _commit(work, "b.txt", "b")
            _run_git(["push", "-q", "origin", "main"], cwd=work)
            _age_fetch_head(clone)
            check("drift: default branch behind origin -> 'behind origin' notice",
                  "behind origin" in _drift([clone], gcfg).stdout)
            # On a feature branch, 'behind' is never reported (no nag, no fetch):
            # the guard returns before the fetch even though main is behind.
            _run_git(["checkout", "-q", "-b", "feature"], cwd=clone)
            _age_fetch_head(clone)
            check("drift: feature branch never flagged behind -> silent",
                  "behind origin" not in _drift([clone], gcfg).stdout)
    finally:
        shutil.rmtree(base, ignore_errors=True)


# --- keru-block-inline-interp ------------------------------------------------

def bii_denies(cmd):
    """True if the inline-interpreter block hook denies this Bash command."""
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}}
    out = subprocess.run([sys.executable, BLOCK_INLINE], input=json.dumps(payload),
                         capture_output=True, text=True).stdout.strip()
    if not out:
        return False
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    except Exception:
        return False


def test_block_inline_interp():
    # DENY: genuine inline code via -c / -e and their variants. The value-taking
    # options (-W/-X) and a leading non-value option (-B) must not hide a later -c;
    # a second interpreter after a pipe or && is caught on its own turn; a path-
    # prefixed interpreter (.venv/bin/python) resolves by basename; deno/bun too.
    deny = [
        ("python3 -c", "python3 -c 'import os; print(1)'"),
        ("python -c attached", "python -c'print(1)'"),
        ("node -e", "node -e 'console.log(1)'"),
        ("ruby -e", "ruby -e 'puts 1'"),
        ("perl -e", "perl -e 'print 1'"),
        ("deno -e", "deno -e 'console.log(1)'"),
        ("bun -e", "bun -e 'console.log(1)'"),
        ("python cluster -Ic", "python3 -Ic 'print(1)'"),
        ("python -W ignore then -c", "python3 -W ignore -c 'print(1)'"),
        ("python -X importtime then -c", "python3 -X importtime -c 'x'"),
        ("python -B then -c", "python3 -B -c 'x'"),
        ("path-prefixed python -c", ".venv/bin/python -c 'print(1)'"),
        ("second interp after pipe", "cat x | python3 -c 'import sys'"),
        ("second interp after &&", "cd x && python3 -c 'import sys'"),
    ]
    for name, cmd in deny:
        check("inline-interp denies: " + name, bii_denies(cmd))

    # DEFER (no deny): running a SCRIPT or MODULE whose own args include -c/-e is
    # explicitly allowed (the documented guarantee), and long options like -config
    # must not be misread as -c. Plain script runs defer too.
    allow = [
        ("script with -c arg", "python3 tool.py -c config.yml"),
        ("module -m with -c arg", "python -m pytest -c setup.cfg"),
        ("node script with -e arg", "node build.js -e production"),
        ("plain python script", "python3 app.py"),
        ("plain node script", "node server.js"),
        ("-W value then script then its -c", "python3 -W ignore app.py -c cfg"),
        ("long option -config not -c", "python3 -config value"),
        ("non-interpreter -e flag", "grep -e foo file"),
        # Regression: the cluster heuristic is python-only, so a perl/ruby attached-
        # value option whose value ends in the flag letter (-e) is NOT a cluster.
        ("perl -M module load not inline", "perl -Mautodie script.pl"),
        ("perl -M feature not inline", "perl -Mfeature script.pl"),
        ("ruby -I include dir not inline", "ruby -Icode app.rb"),
    ]
    for name, cmd in allow:
        check("inline-interp defers: " + name, not bii_denies(cmd))


# --- keru-check-output: file-based deliverable resolution --------------------

def test_turn_deliverable():
    """Regression: a file-based deliverable (a Write to a keru-deliverable-*.md,
    with only a LINK left in chat) must resolve to the FILE's content, so the LLM
    judge reviews the real deliverable instead of the link. Exercises
    keru-check-output's _turn_deliverable / _skill_from_deliverable_path directly."""
    import importlib.util as _ilu
    _s = _ilu.spec_from_file_location("cco_td", CHECK_OUTPUT)
    _m = _ilu.module_from_spec(_s); _s.loader.exec_module(_m)

    # Duplicate check_pr_review removed: it must now be defined exactly once.
    src = open(CHECK_OUTPUT, encoding="utf-8").read()
    check("check-output: check_pr_review defined once (no duplicate)",
          src.count("def check_pr_review(") == 1)

    # Path resolution: hyphenated skill name + optional id both resolve; a
    # non-deliverable path resolves to None. Resolution is by BASENAME, so it holds
    # in the current deliverables dir and in the old /tmp one alike (which is why
    # moving the drafts needed no change here; the gate owns the location rule).
    check("deliverable-path: addressing-pr-comments with id",
          _m._skill_from_deliverable_path(
              os.path.expanduser("~/.claude/keru-deliverables/keru-deliverable-addressing-pr-comments-1.md"))
          == "addressing-pr-comments")
    check("deliverable-path: pr-review no id, any dir",
          _m._skill_from_deliverable_path("/tmp/keru-deliverable-pr-review.md") == "pr-review")
    check("deliverable-path: non-deliverable -> None",
          _m._skill_from_deliverable_path("/tmp/notes.md") is None)

    tmpd = tempfile.mkdtemp()
    dpath = os.path.join(tmpd, "keru-deliverable-pr-review-5.md")
    body = "Verdict: Approve\n\n### Nits\n\n`a.go:1`\n\nWhy: looks fine.\n"
    with open(dpath, "w", encoding="utf-8") as f:
        f.write(body)
    recs = [
        {"type": "user", "message": {"content":
            "<command-name>/keru-pr-review</command-name>\nreview PR 5"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": dpath, "content": body}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "text", "text": "Done. Review at %s" % dpath}]}},
    ]
    skill, content = _m._turn_deliverable(recs)
    check("turn-deliverable: resolves skill from the Write record", skill == "pr-review")
    check("turn-deliverable: returns the FILE content, not the link",
          content.strip().startswith("Verdict: Approve"))
    # The checker run on the file content passes (so the judge would proceed),
    # whereas run on the link text it would 'skip' (the old, broken behavior).
    check("turn-deliverable: file content passes the pr-review checker",
          _m.CHECKERS["pr-review"](content)[0] == "ok")
    check("turn-deliverable: the link text alone would NOT (skip)",
          _m.CHECKERS["pr-review"]("Done. Review at %s" % dpath)[0] == "skip")

    # A turn with no deliverable write resolves to (None, '') so the judge falls
    # back to the inline-message path.
    recs2 = [
        {"type": "user", "message": {"content": "just chatting"}},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
    ]
    check("turn-deliverable: no deliverable write -> (None, '')",
          _m._turn_deliverable(recs2) == (None, ""))

    # The LAST matching deliverable write/edit this turn wins, and an Edit record
    # is recognized (not only Write): a Write to one deliverable followed by an Edit
    # to a later one resolves to the later skill and its on-disk content.
    dpath2 = os.path.join(tmpd, "keru-deliverable-addressing-pr-comments-9.md")
    body2 = "**a.go:1**\n\nApply: the fix is correct.\n"
    with open(dpath2, "w", encoding="utf-8") as f:
        f.write(body2)
    recs3 = [
        {"type": "user", "message": {"content":
            "<command-name>/keru-pr-review</command-name>\ngo"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": dpath, "content": body}}]}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Edit",
             "input": {"file_path": dpath2, "new_string": body2}}]}},
    ]
    skill3, content3 = _m._turn_deliverable(recs3)
    check("turn-deliverable: last write/edit wins and Edit is recognized",
          skill3 == "addressing-pr-comments"
          and content3.strip().startswith("**a.go:1**"))

    # Fail-open: a deliverable write whose file cannot be read (never created, or
    # removed before the Stop hook runs) resolves to (None, '') so the judge is not
    # wedged; it falls back to the inline-message path.
    recs4 = [
        {"type": "user", "message": {"content":
            "<command-name>/keru-pr-review</command-name>\ngo"}},
        {"type": "assistant", "message": {"content": [
            {"type": "tool_use", "name": "Write",
             "input": {"file_path": os.path.join(tmpd, "keru-deliverable-pr-review-404.md"),
                       "content": body}}]}},
    ]
    check("turn-deliverable: unreadable/missing file -> (None, '') fail-open",
          _m._turn_deliverable(recs4) == (None, ""))
    shutil.rmtree(tmpd, ignore_errors=True)


def comments_run(payload):
    """(decision, reason, ok) for one raw payload; ok is False when the hook crashed
    (non-zero exit or stderr), so a crash can never pass as an allow."""
    p = subprocess.run([sys.executable, GATE_COMMENTS], input=payload,
                       capture_output=True, text=True)
    ok = p.returncode == 0 and not p.stderr.strip()
    out = p.stdout.strip()
    if not out:
        return "", "", ok
    try:
        h = json.loads(out)["hookSpecificOutput"]
        return h.get("permissionDecision", ""), h.get("permissionDecisionReason", ""), ok
    except Exception:
        return "", "", False


def comments_verdict(file_path, tool="Write", content=None, old=None, new=None, replace_all=False):
    if tool == "Write":
        ti = {"file_path": file_path, "content": content}
    else:
        ti = {"file_path": file_path, "old_string": old, "new_string": new}
        if replace_all:
            ti["replace_all"] = True
    return comments_run(json.dumps({"tool_name": tool, "tool_input": ti}))


def test_comment_gate():
    tmpd = tempfile.mkdtemp()
    try:
        _comment_gate_cases(tmpd)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _comment_gate_cases(tmpd):
    go = os.path.join(tmpd, "svc", "drift.go")
    py = os.path.join(tmpd, "a.py")
    REF, BLOCK, TOTAL = "ticket or PR reference", "comment block of", "new comment lines in one edit"

    def denied_for(rule, **kw):
        d, reason, ok = comments_verdict(**kw)
        return ok and d == "deny" and rule in reason

    def allowed(**kw):
        d, _, ok = comments_verdict(**kw)
        return ok and d == ""

    def pkg(body):
        return "package x\n\n" + body

    check("comments: ticket key in a Go comment -> deny",
          denied_for(REF, file_path=go, content=pkg("// retired by DBI-1820\nfunc f() {}\n")))
    check("comments: repo and PR number in a trailing Go comment -> deny",
          denied_for(REF, file_path=go, content=pkg("var v = 1 // see dp-protos #2237\n")))
    check("comments: ticket in a Python comment -> deny",
          denied_for(REF, file_path=py, content="# NEXUS-1160 retired it\nx = 1\n"))
    check("comments: ticket in a trailing Python comment -> deny",
          denied_for(REF, file_path=py, content="x = 1  # DBI-7 workaround\n"))
    check("comments: PR ref in a terraform comment -> deny",
          denied_for(REF, file_path=os.path.join(tmpd, "main.tf"), content="# per PR #2237\nlocals {}\n"))
    check("comments: ticket in a SQL comment -> deny",
          denied_for(REF, file_path=os.path.join(tmpd, "q.sql"), content="-- DBI-1820 backfill\nselect 1;\n"))
    check("comments: ticket in a trailing block comment -> deny",
          denied_for(REF, file_path=go, content=pkg("var v = 1 /* DBI-1820 */\n")))
    for ref in ("org/repo#12", "https://github.com/o/r/pull/12", "https://x.atlassian.net/browse/DBI-1"):
        check("comments: %s in a comment -> deny" % ref,
              denied_for(REF, file_path=go, content=pkg("// see %s\nfunc f() {}\n" % ref)))
    check("comments: ticket in a Makefile comment -> deny",
          denied_for(REF, file_path=os.path.join(tmpd, "Makefile"), content="# DBI-9 target\nall:\n"))
    check("comments: ticket in a Python docstring -> deny",
          denied_for(REF, file_path=py, content='def f():\n    """Retired by DBI-1820."""\n    return 1\n'))
    check("comments: standards, licenses and encodings are not tickets -> allow",
          allowed(file_path=go, content=pkg("// UTF-8, SHA-256, CWE-89, CP-1252, GPL-3.0, X86-64.\nfunc f() {}\n")))
    check("comments: an ordinal, a color and an RFC section are not PR refs -> allow",
          allowed(file_path=go, content=pkg("// step #10, color #666666, rfc7519#4\nfunc f() {}\n")))
    check("comments: a ticket inside a terraform string -> allow",
          allowed(file_path=os.path.join(tmpd, "m.tf"),
                  content='module "a" {\n  source = "git::https://github.com/o/r//modules/x?ref=DBI-1820-fix"\n}\n'))
    check("comments: a ticket inside a YAML string -> allow",
          allowed(file_path=os.path.join(tmpd, "r.yml"), content='title: "Release #12 for DBI-1"\n'))
    with_ref = "var v = 1 // MIMO-4422\n"
    check("comments: changing code on a line that already carries a ref -> allow",
          allowed(file_path=go, tool="Edit", old=with_ref, new=with_ref.replace("1", "2")))
    check("comments: fixing a typo in a comment that already carries a ref -> allow",
          allowed(file_path=go, tool="Edit", old="// the schema (MIMO-4422) so logins are queriable\n",
                  new="// the schema (MIMO-4422) so logins are queryable\n"))

    check("comments: a 3-line // block -> deny",
          denied_for(BLOCK, file_path=go, content=pkg("// one\n// two\n// three\nfunc f() {}\n")))
    check("comments: a /* */ block with 3 text lines -> deny",
          denied_for(BLOCK, file_path=go, content=pkg("/* one\n   two\n   three */\nfunc f() {}\n")))
    check("comments: a 3-line Python docstring -> deny",
          denied_for(BLOCK, file_path=py, content='def f():\n    """One.\n\n    Two.\n    Three.\n    """\n    return 1\n'))
    check("comments: a 2-line why -> allow",
          allowed(file_path=go, content=pkg("// Ties break on the encoded bytes, so\n// the order is stable across polls.\nfunc f() {}\n")))
    check("comments: a one-sentence JSDoc block -> allow",
          allowed(file_path=os.path.join(tmpd, "a.ts"), content="/**\n * Returns the thing.\n */\nexport function f() {}\n"))
    block = "// one\n// two\n// three\n// four\n"
    check("comments: an Edit that keeps an existing block -> allow",
          allowed(file_path=go, tool="Edit", old=block + "func f() {}", new=block + "func g() {}"))
    check("comments: an Edit fixing one line of an existing block -> allow",
          allowed(file_path=go, tool="Edit", old=block, new=block.replace("two", "2")))
    check("comments: an Edit rewording an existing block in place -> allow",
          allowed(file_path=go, tool="Edit", old=block, new=block.replace("o", "0")))
    check("comments: an Edit adding 3 lines to an existing block -> deny",
          denied_for(BLOCK, file_path=go, tool="Edit", old=block, new=block + "// five\n// six\n// seven\n"))
    check("comments: an Edit growing a 2-line comment to 3 -> deny",
          denied_for(BLOCK, file_path=go, tool="Edit", old="// one\n// two\nfunc f() {}",
                     new="// one\n// two\n// three\nfunc f() {}"))
    check("comments: an Edit fragment that starts inside a /* */ block is still read -> deny",
          denied_for(BLOCK, file_path=go, tool="Edit", old=" * Returns x.\n */",
                     new=" * Returns x.\n * Retired soon.\n * Really.\n * Truly.\n */"))

    six = pkg("".join("// c%d\nfunc f%d() {}\n" % (i, i) for i in range(6)))
    check("comments: 6 one-line comments in one write -> deny", denied_for(TOTAL, file_path=go, content=six))
    five = pkg("".join("// c%d\nfunc f%d() {}\n" % (i, i) for i in range(5)))
    check("comments: exactly 5 one-line comments -> allow", allowed(file_path=go, content=five))
    trailing = pkg("".join("var a%d = 1 // t%d\n" % (i, i) for i in range(6)))
    check("comments: trailing comments count toward the total -> deny",
          denied_for(TOTAL, file_path=go, content=trailing))
    existing = os.path.join(tmpd, "keep.go")
    with open(existing, "w") as f:
        f.write(pkg("// a\n// b\n// c\n// d\nfunc f() {}\n"))
    check("comments: a Write that keeps the existing comments -> allow",
          allowed(file_path=existing, content=pkg("// a\n// b\n// c\n// d\nfunc g() {}\n")))
    check("comments: a Write over an existing file that adds a ref -> deny",
          denied_for(REF, file_path=existing, content=pkg("// a\n// b\n// c\n// d\n// DBI-1\nfunc g() {}\n")))
    rpath = os.path.join(tmpd, "r.go")
    with open(rpath, "w") as f:
        f.write("package x\n" + "x()\n" * 6)
    check("comments: replace_all counts every occurrence -> deny",
          denied_for(TOTAL, file_path=rpath, tool="Edit", old="x()", new="x() // why", replace_all=True))

    check("comments: adjacent Go directives -> allow",
          allowed(file_path=go, content="//go:build linux\n// +build linux\n//go:generate x\n\npackage x\n\n//nolint:gocyclo\nfunc f() {}\n"))
    check("comments: adjacent Python pragmas -> allow",
          allowed(file_path=py, content="# noqa\n# pylint: disable=all\n# mypy: ignore-errors\nx = 1\n"))
    check("comments: block-form eslint pragmas -> allow",
          allowed(file_path=os.path.join(tmpd, "a.js"),
                  content="/* eslint-disable */\n/* eslint-disable no-x */\n/* istanbul ignore file */\nf()\n"))
    sqlc = "".join("-- name: Q%d :one\nselect %d;\n\n" % (i, i) for i in range(6))
    check("comments: sqlc query annotations -> allow", allowed(file_path=os.path.join(tmpd, "q.sql"), content=sqlc))
    check("comments: goose migration markers -> allow",
          allowed(file_path=os.path.join(tmpd, "m.sql"),
                  content="-- +goose Up\n-- +goose StatementBegin\nselect 1;\n-- +goose StatementEnd\n"
                          "-- +goose Down\n-- +goose StatementBegin\nselect 2;\n-- +goose StatementEnd\n"))
    check("comments: a Go example Output block in a test file -> allow",
          allowed(file_path=os.path.join(tmpd, "svc", "x_test.go"),
                  content=pkg("func ExampleF() {\n\tf()\n\t// Output:\n\t// a\n\t// b\n\t// c\n}\n")))
    check("comments: Output: prose outside a test file still counts -> deny",
          denied_for(BLOCK, file_path=go, content=pkg("// Output: the result\n// a\n// b\nfunc f() {}\n")))
    check("comments: # lines in a Python triple-quoted string -> allow",
          allowed(file_path=py, content='NOTES = """\n# Release\n## Fixed\n## Added\n"""\n'))
    check("comments: # lines in a shell heredoc -> allow",
          allowed(file_path=os.path.join(tmpd, "s.sh"), content="cat <<'EOF' > f\n# a\n# b\n# c\nEOF\n"))
    check("comments: ### lines in a YAML block scalar -> allow",
          allowed(file_path=os.path.join(tmpd, "f.yml"),
                  content="body:\n  value: |\n    ### Steps\n    ### Expected\n    ### Actual\n"))
    check("comments: a version pin after a YAML action -> allow",
          allowed(file_path=os.path.join(tmpd, "ci.yml"), content="steps:\n  - uses: actions/checkout@abc123 # v4.1.1\n"))

    check("comments: a markdown file is out of scope -> allow",
          allowed(file_path=os.path.join(tmpd, "README.md"), content="# Rollout DBI-1820\n# a\n# b\n"))
    check("comments: generated code is out of scope -> allow",
          allowed(file_path=os.path.join(tmpd, "x.pb.go"), content="// DBI-1\n// a\n// b\n"))
    check("comments: vendored code is out of scope -> allow",
          allowed(file_path=os.path.join(tmpd, "vendor", "y.go"), content="// DBI-1\n"))
    check("comments: a task breakdown under docs/ is out of scope -> allow",
          allowed(file_path=os.path.join(tmpd, "docs", "inv", "task-breakdown.yaml"),
                  content="# Tickets from the DBI-1390 investigation\n# a\n# b\nitems: []\n"))
    half = os.path.join(tmpd, "half-repo")
    os.makedirs(os.path.join(half, "playbook"))
    open(os.path.join(half, "playbook", "PLAYBOOK.md"), "w").close()
    check("comments: a repo with only a playbook is not exempt -> deny",
          denied_for(REF, file_path=os.path.join(half, "h.py"), content="# DBI-1669\nx = 1\n"))
    skills = os.path.join(tmpd, "skills-repo")
    os.makedirs(os.path.join(skills, "playbook"))
    os.makedirs(os.path.join(skills, "scripts", "hooks"))
    open(os.path.join(skills, "playbook", "PLAYBOOK.md"), "w").close()
    open(os.path.join(skills, "scripts", "hooks", "keru-gate-comments.py"), "w").close()
    check("comments: the Claude-Skills repo itself is out of scope -> allow",
          allowed(file_path=os.path.join(skills, "scripts", "hooks", "h.py"),
                  content="# DBI-1669 was snapshotted\n# a\n# b\nx = 1\n"))

    three_hash = "# one\n# two\n# three\n"
    code_after_doc = '    """\n    cur.execute(q)\n    row = cur.fetchone()\n    if not row:\n        return None\n    return row\n'
    check("comments: an Edit starting on a docstring's closing quotes, adding code -> allow",
          allowed(file_path=py, tool="Edit", old='    """\n    return cur.fetchone()\n', new=code_after_doc))
    check("comments: SQL in a triple-quoted string argument -> allow",
          allowed(file_path=py, content='cur.execute(\n    """\n    SELECT id\n    FROM users\n    WHERE active\n    """\n)\n'))
    reword_old = "// It is fast.\n// It is safe.\n// It is quick.\nfunc f() {}\nfunc g() {}\n"
    check("comments: rewording a block and adding one line elsewhere -> allow",
          allowed(file_path=go, tool="Edit", old=reword_old,
                  new=reword_old.replace("safe", "sound").replace("func g() {}", "// why g\nfunc g() {}")))
    moved_old = "func a() {}\n" + "".join("// old %d\n" % i for i in range(4)) + "func b() {}\n" + "func c() {}\n" * 3 + "func d() {}\n"
    moved_new = "func a() {}\n" + "func b() {}\n" + "func c() {}\n" * 3 + "".join("// new %d\n" % i for i in range(4)) + "func d() {}\n"
    check("comments: deleting a block does not buy a new one elsewhere -> deny",
          denied_for(BLOCK, file_path=go, tool="Edit", old=moved_old, new=moved_new))
    check("comments: a lone backtick in a trailing comment does not hide later comments -> deny",
          denied_for(BLOCK, file_path=go, content=pkg("var q = 1 // the ` char\n\n// one\n// two\n// three\nfunc f() {}\n")))
    for opener in ("tr a b <<< hello", "x=$(( 1<<n ))", 'echo "use <<EOF here"'):
        check("comments: %r is not a heredoc -> deny the later block" % opener,
              denied_for(BLOCK, file_path=os.path.join(tmpd, "s.sh"), content=opener + "\n\n" + three_hash + "echo done\n"))
    check("comments: triple quotes inside a Python comment open nothing -> deny the later block",
          denied_for(BLOCK, file_path=py, content='x = 1  # strip """ here\n\n' + three_hash + "y = 2\n"))
    check("comments: a YAML block scalar ends at its content's indent -> deny the step's block",
          denied_for(BLOCK, file_path=os.path.join(tmpd, "w.yml"),
                     content="steps:\n  - run: |\n      echo hi\n    # one\n    # two\n    # three\n    env: {}\n"))
    check("comments: # lines in a Dockerfile RUN heredoc -> allow",
          allowed(file_path=os.path.join(tmpd, "Dockerfile"), content="FROM x\nRUN <<EOF\n# a\n# b\n# c\nEOF\n"))
    check("comments: an anchored YAML block scalar -> allow",
          allowed(file_path=os.path.join(tmpd, "a.yml"), content="key: &a |\n  # a\n  # b\n  # c\n"))
    check("comments: SQL continuation lines starting with * -> allow",
          allowed(file_path=os.path.join(tmpd, "p.sql"),
                  content="select a\n  * 100.0 / total as pct,\n  * 2 as b,\n  * 3 as c\nfrom t;\n"))
    check("comments: self-documenting Makefile targets -> allow",
          allowed(file_path=os.path.join(tmpd, "Makefile"),
                  content="".join("t%d: ## help for t%d\n\techo\n" % (i, i) for i in range(6))))
    check("comments: a JS regex with escaped slashes is not a comment -> allow",
          allowed(file_path=os.path.join(tmpd, "r.js"), content="const r = /^https?:\\/\\/DBI-1/\n"))
    check("comments: a quoted ref inside a trailing comment -> deny",
          denied_for(REF, file_path=py, content='x = 1  # see "DBI-1820"\n'))
    check("comments: a ref after a pragma -> deny",
          denied_for(REF, file_path=go, content=pkg("var v = f() //nolint:errcheck // DBI-1820\n")))
    check("comments: reflowing a ref onto one line -> allow",
          allowed(file_path=go, tool="Edit", old="// see dp-protos\n// #2237 for it\n", new="// see dp-protos #2237 for it\n"))
    check("comments: a ref is matched exactly, not as a substring -> deny",
          denied_for(REF, file_path=go, tool="Edit", old="// DBI-18200\n", new="// DBI-18200\n// DBI-1820\n"))
    check("comments: hyphenated words before #NN or a 6-digit color are not PR refs -> allow",
          allowed(file_path=go, content=pkg("// re-run #10, light-gray #666666\nfunc f() {}\n")))
    check("comments: a multi-line JSDoc starting with a tag still counts -> deny",
          denied_for(BLOCK, file_path=os.path.join(tmpd, "d.ts"),
                     content="/** @deprecated\n * one\n * two\n * three\n */\nexport const x = 1\n"))
    check("comments: a block comment opened after code is tracked -> deny",
          denied_for(BLOCK, file_path=go, content=pkg("var v = 1 /* one\n two\n three\n four */\n")))
    for line in ('"\\' * 50000, "-".join(["a"] * 30000) + " x", "AB-1" * 20000, "1" * 20000):
        t0 = time.time()
        _, _, ok = comments_verdict(file_path=go, content=pkg("// " + line + "\nfunc f() {}\n"))
        check("comments: a pathological %d-char line finishes fast" % len(line), ok and time.time() - t0 < 3)

    for raw in ("not json", "[]", '{"tool_name":"Write","tool_input":"x"}',
                '{"tool_name":"Write","tool_input":{"file_path":7,"content":"x"}}',
                '{"tool_name":"Edit","tool_input":{"file_path":"/a/b.go","old_string":1,"new_string":"// DBI-1"}}'):
        d, _, ok = comments_run(raw)
        check("comments: malformed input %s fails open without crashing" % raw[:32], ok and d == "")


def test_not_tickets_in_sync():
    from importlib.machinery import SourceFileLoader
    gate = SourceFileLoader("keru_gate_comments", GATE_COMMENTS).load_module()
    with open(os.path.join(REPO, "scripts", "helpers", "keru-context-snapshot.sh")) as f:
        m = re.search(r"^NOT_TICKETS_JQ='(\[.*\])'$", f.read(), re.M)
    check("not-tickets: the comment gate and the snapshot skip the same prefixes",
          bool(m) and set(json.loads(m.group(1))) == gate.NOT_TICKETS)


def test_context_snapshot():
    jq_bin = shutil.which("jq")
    if not jq_bin:
        check("snapshot: jq available for the snapshot test", False)
        return
    tmpd = tempfile.mkdtemp()
    try:
        _context_snapshot_cases(tmpd, jq_bin)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)


def _context_snapshot_cases(tmpd, jq_bin):
    fix, bindir, cfg = (os.path.join(tmpd, d) for d in ("fix", "bin", "cfg"))
    for d in (fix, bindir):
        os.makedirs(d)

    def text(t, marks=None):
        node = {"type": "text", "text": t}
        if marks:
            node["marks"] = marks
        return node

    def para(*nodes):
        return {"type": "paragraph", "content": list(nodes)}

    def doc(*blocks):
        return {"type": "doc", "version": 1, "content": list(blocks)}

    def issue(key, itype, desc, comments=(), links=()):
        return {"key": key, "fields": {
            "summary": key + " summary", "issuetype": {"name": itype}, "status": {"name": "Open"},
            "updated": "2026-01-01T00:00:00.000+0000", "description": desc,
            "comment": {"comments": [{"author": {"displayName": "A"}, "created": "2026-01-01",
                                      "body": c} for c in comments]},
            "issuelinks": list(links)}}

    root = issue("ROOT-1", "Task", doc(
        {"type": "heading", "attrs": {"level": 2}, "content": [text("Heading")]},
        para(text("Uses "), text("handler.go", [{"type": "code"}]), text(" and "),
             text("docs", [{"type": "link", "attrs": {"href": "https://example.com/d"}}]),
             text(", see INV-9, UTF-8 and SHA-256.")),
        {"type": "bulletList", "content": [{"type": "listItem", "content": [para(text("item"))]}]},
        {"type": "table", "content": [
            {"type": "tableRow", "content": [{"type": "tableHeader", "content": [para(text("a|b"))]}]},
            {"type": "tableRow", "content": [{"type": "tableCell", "content": [para(text("1"))]}]}]}),
        comments=[doc(para(text("root comment")))],
        links=[{"type": {"inward": "is blocked by", "outward": "blocks"}, "outwardIssue": {"key": "ROOT-2"}}])
    linked = issue("ROOT-2", "Task", doc(para(text("linked body"))),
                   comments=[doc(para(text("linked comment names NOPE-5")))])
    inv = issue("INV-9", "Investigation", doc(para(text("why"))))
    for i in (root, linked, inv):
        with open(os.path.join(fix, i["key"] + ".json"), "w") as f:
            json.dump(i, f)
    with open(os.path.join(bindir, "jira"), "w") as f:
        f.write('#!/bin/sh\n[ -f "%s/$3.json" ] && exec cat "%s/$3.json"\necho "not found"\n' % (fix, fix))
    os.chmod(os.path.join(bindir, "jira"), 0o755)

    env = dict(os.environ)
    env.update(PATH=":".join([bindir, os.path.dirname(jq_bin), "/usr/bin", "/bin"]), CLAUDE_CONFIG_DIR=cfg)
    script = os.path.join(REPO, "scripts", "helpers", "keru-context-snapshot.sh")

    def run(mode, key="ROOT-1"):
        p = subprocess.run(["bash", script, mode, key], capture_output=True, text=True, env=env)
        try:
            return p.returncode, json.loads(p.stdout)
        except ValueError:
            return p.returncode, {}

    code, out = run("write")
    check("snapshot: write succeeds", code == 0 and out.get("root") == "ROOT-1")
    check("snapshot: a mentioned investigation is found and standards are skipped",
          out.get("investigations") == ["INV-9"] and out.get("mentioned_keys") == ["INV-9"])
    path = os.path.join(cfg, "keru-context", "ROOT-1.md")
    body = open(path).read() if os.path.isfile(path) else ""
    lines = body.splitlines()
    mark_ok = "keru-validate-->" in lines and lines[lines.index("keru-validate-->") + 1] == "<!--keru-format: 2-->"
    check("snapshot: the format mark follows the header", mark_ok)
    for needle, what in (("**Heading**", "a heading renders bold"), ("`handler.go`", "a code mark renders"),
                         ("docs <https://example.com/d>", "a link keeps its href"), ("| --- |", "a table gets its separator"),
                         ("a\\|b", "a pipe in a cell is escaped"), ("root comment", "the root's comments render"),
                         ("linked comment names NOPE-5", "a linked issue's comments render"),
                         ("this ticket blocks it", "the link relation is named"),
                         ("Not readable as issues: NOPE-5", "an unreadable mention is reported")):
        check("snapshot: " + what, needle in body)
    check("snapshot: no raw ADF JSON is left", '"type":"doc"' not in body and '"type": "doc"' not in body)

    code, out = run("check")
    check("snapshot: check after write is current and lists investigations",
          code == 0 and out.get("status") == "current" and out.get("investigations") == ["INV-9"])
    with open(path, "w") as f:
        f.write(body.replace("<!--keru-format: 2-->\n", ""))
    code, out = run("check")
    check("snapshot: an older-format file reads stale, naming the rewrite",
          code == 3 and out.get("status") == "stale" and "write ROOT-1" in out.get("reason", ""))

    gap = issue("ROOT-4", "Task", doc(para(text("x"))),
                links=[{"type": {"inward": "is blocked by", "outward": "blocks"}, "outwardIssue": {"key": "MISS-1"}}])
    with open(os.path.join(fix, "ROOT-4.json"), "w") as f:
        json.dump(gap, f)
    code, out = run("write", "ROOT-4")
    check("snapshot: a linked key that fails to fetch is reported", out.get("unfetched_keys") == ["MISS-1"])
    code, out = run("check", "ROOT-4")
    check("snapshot: a snapshot missing a linked key never reads current", out.get("status") != "current")
    with open(os.path.join(fix, "MISS-1.json"), "w") as f:
        json.dump(issue("MISS-1", "Investigation", doc(para(text("late")))), f)
    code, out = run("check", "ROOT-4")
    check("snapshot: once the missing key is readable, check says rewrite",
          code == 3 and out.get("status") == "stale" and "MISS-1" in out.get("stale_keys", []))


def main():
    test_safe_read()
    test_require_skill()
    test_check_output()
    test_judge_gating()
    test_write_gate()
    test_comment_gate()
    test_not_tickets_in_sync()
    test_context_snapshot()
    test_check_drift()
    test_block_inline_interp()
    test_turn_deliverable()
    failed = [n for n, ok in results if not ok]
    print("=== hook tests: %d run, %d failed ===" % (len(results), len(failed)))
    for n, ok in results:
        if not ok:
            print("  FAIL: " + n)
    if failed:
        sys.exit(1)
    print("ok: all hook behavioral tests pass")


if __name__ == "__main__":
    main()
