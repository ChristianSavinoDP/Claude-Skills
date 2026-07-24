# External Tools

Skills drive external tools through their CLIs, run via Bash. Each must be installed and authenticated once; credentials live with the tool, never in this repo. The installer checks each and prints an `action:` line for anything unconfigured.

## dp ai (headless Claude on Bedrock)

The DailyPay CLI's `dp ai claude` runs Claude Code headless against Bedrock. Two hooks use it as a model in a script:

- `keru-safe-read` calls `dp ai claude -p --bare "<judge prompt>"` to judge a Bash command that is not provably safe by static parsing (the slow path; the fast path needs no model). Fail-safe: if `dp` is missing or the call fails or times out, it returns `ask`, never an unevaluated `allow`.
- `keru-judge-output` calls it to review a finished deliverable for the rules a regex cannot check.

It is found on PATH as `dp`, or under `~/.local/share/mise/installs/dailypay-dp/*/bin/dp`. `dp ai claude` is non-interactive with `-p`; `--bare` skips hooks/plugins so the judge call cannot recurse into these same gates. No extra setup beyond having `dp` installed and Bedrock auth working. Source: <https://github.com/dailypay/dpcli>.

## GitHub (gh)

The PR skills use the GitHub CLI.

```bash
brew install gh
gh auth login
```

## Jira (jira-cli)

The `keru-gather-context` skill reads tickets through [jira-cli](https://github.com/ankitpokhrel/jira-cli).

```bash
brew install ankitpokhrel/jira-cli/jira-cli
```

`jira-cli` reads the API token from the `JIRA_API_TOKEN` environment variable; it is never stored in the config file. So the token must be exported both to run `jira init` and, persistently, for every later session (including Claude's).

1. Create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>.

2. Export it persistently so it survives new shells and reaches Claude Code. Add it to the `env` block of `~/.claude/settings.json` (loaded into every session, not committed to this public repo). To keep the token out of shell history, run this in your terminal and paste at the hidden prompt (it edits the JSON with `jq`, then swaps the file in atomically):

   ```bash
   read -rs JIRA_API_TOKEN && f="$HOME/.claude/settings.json" && \
     jq --arg t "$JIRA_API_TOKEN" '.env.JIRA_API_TOKEN = $t' "$f" > "$f.tmp" \
     && mv "$f.tmp" "$f" && echo "JIRA_API_TOKEN written to settings env"
   ```

3. Configure the rest once. From the project URL, the server is `https://<org>.atlassian.net` and the project key is the segment after `/projects/` (e.g. `DBI`):

   ```bash
   export JIRA_API_TOKEN='<paste-token>'   # for this init only; step 2 handles persistence
   jira init --installation cloud \
     --server https://<your-org>.atlassian.net \
     --login <your-email> \
     --auth-type basic \
     --project <DEFAULT_PROJECT_KEY>
   ```

   Config (server, login, project, board) is stored in `~/.config/.jira/`. Nothing secret touches this repo. The persisted token only reaches Claude's sessions after a restart, since the `env` block loads at session start.

Verify with `jira me` (returns your user) and `jira issue view <KEY> --plain`.

## DataDog (pup)

The `keru-datadog-audit` skill reads DataDog error-tracking and error logs through [pup](https://github.com/DataDog/pup), DataDog's agent-oriented CLI (docs <https://docs.datadoghq.com/cli/>). It fits the repo's "authenticated CLI, never WebFetch" rule the same way `gh`/`jira` do: a real CLI with JSON output and OAuth2+PKCE auth, so no long-lived `DD_API_KEY`/`DD_APP_KEY` is stored in this repo.

```bash
brew tap datadog-labs/pack
brew install datadog-labs/pack/pup
pup auth login
```

`pup auth login` opens a browser for an interactive OAuth flow, so it is a one-time step you run yourself (the installer cannot do it). Verify with `pup auth status` (returns `authenticated: true` and the token's scopes). Tokens are short-lived and auto-refresh; re-run `pup auth login` if `auth status` reports no token.

Only `pup`'s read subcommands are used and allowlisted (`error-tracking issues search/get`, `logs search/aggregate/list/query`, `events search/list`, `metrics query/search/list`, `auth status`); every write (`cases create/jira`, `metrics submit`, `metrics metadata update`, `logs archives/metrics delete`) is in `ask` and out of scope for the read-only audit. See [permissions.md](permissions.md) for the exact boundary.

## Giving Claude task context

The `keru-gather-context` skill takes whatever you have, not just a bare key:

- a Jira key (`DBI-1458`),
- a Jira issue URL (`https://<org>.atlassian.net/browse/DBI-1458`),
- a Jira epic (lists its children to get full scope),
- a GitHub PR link (reads the PR, pulls the branch from `headRefName`, and finds the Jira key in the branch or body to fetch that ticket too).

To find the PRs, branches, and deployments tied to a ticket, it prefers Jira's own Development panel (the dev-status endpoint), which is authoritative, and falls back to searching GitHub by ticket key when that panel is empty.

It is read-only. It reads issue, epic, and PR content, and may inspect CI (runs, Actions, check statuses) but never changes state. See [permissions.md](permissions.md) for the exact read vs write boundary.
