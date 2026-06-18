# Tools

Skills drive external tools through their CLIs, run via Bash. Each must be installed and authenticated once; credentials live with the tool, never in this repo. The installer checks both and prints an `action:` line for anything unconfigured.

## GitHub (gh)

The PR skills use the GitHub CLI.

```bash
brew install gh
gh auth login
```

## Jira (jira-cli)

The `gather-context` skill reads tickets through [jira-cli](https://github.com/ankitpokhrel/jira-cli).

```bash
brew install ankitpokhrel/jira-cli/jira-cli
```

`jira-cli` reads the API token from the `JIRA_API_TOKEN` environment variable; it is never stored in the config file. So the token must be exported both to run `jira init` and, persistently, for every later session (including Claude's).

1. Create an API token at <https://id.atlassian.com/manage-profile/security/api-tokens>.

2. Export it persistently so it survives new shells and reaches Claude Code. Add it to the `env` block of `~/.claude/settings.json` (loaded into every session, not committed to this public repo). To keep the token out of shell history, run this in your terminal and paste at the hidden prompt:

   ```bash
   read -rs JIRA_API_TOKEN && python3 - "$JIRA_API_TOKEN" <<'PY'
   import json, os, sys
   p = os.path.expanduser("~/.claude/settings.json")
   d = json.load(open(p))
   d.setdefault("env", {})["JIRA_API_TOKEN"] = sys.argv[1]
   json.dump(d, open(p, "w"), indent=2); open(p, "a").write("\n")
   print("JIRA_API_TOKEN written to settings env")
   PY
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

## Giving Claude task context

The `gather-context` skill takes whatever you have, not just a bare key:

- a Jira key (`DBI-1458`),
- a Jira issue URL (`https://<org>.atlassian.net/browse/DBI-1458`),
- a Jira epic (lists its children to get full scope),
- a GitHub PR link (reads the PR, pulls the branch from `headRefName`, and finds the Jira key in the branch or body to fetch that ticket too).

To find the PRs, branches, and deployments tied to a ticket, it prefers Jira's own Development panel (the dev-status endpoint), which is authoritative, and falls back to searching GitHub by ticket key when that panel is empty.

It is read-only. It reads issue, epic, and PR content, and may inspect CI (runs, Actions, check statuses) but never changes state. See [permissions.md](permissions.md) for the exact read vs write boundary.
