#!/usr/bin/env bash
# Read-only: fetch a Jira issue's Development panel (linked PRs, branches,
# repositories) via the dev-status endpoint, which jira-cli does not expose.
# Usage: keru-jira-dev <ISSUE-KEY>
# Only does authenticated GETs against /rest/dev-status. No writes, no other
# endpoints. Reads creds from JIRA_API_TOKEN and ~/.config/.jira/.config.yml.
# Read-only is relied on by scripts/hooks/keru-safe-read.py (auto-approved
# without prompting); do not add write paths here.
set -euo pipefail

KEY="${1:-}"
if [ -z "$KEY" ]; then
  echo "usage: keru-jira-dev <ISSUE-KEY>" >&2
  exit 2
fi
# Reject anything that is not a plain issue key (e.g. ABC-123): no flags,
# no URLs, no shell metacharacters reaching the request.
if ! printf '%s' "$KEY" | grep -qE '^[A-Z][A-Z0-9]+-[0-9]+$'; then
  echo "error: '$KEY' is not a valid issue key (expected like DBI-1234)" >&2
  exit 2
fi

JIRA_API_TOKEN="${JIRA_API_TOKEN:-}"
if [ -z "$JIRA_API_TOKEN" ]; then
  echo "error: JIRA_API_TOKEN is not set" >&2
  exit 1
fi

python3 - "$KEY" <<'PY'
import json, os, sys, base64, urllib.request, urllib.error

key = sys.argv[1]
token = os.environ["JIRA_API_TOKEN"]

cfg_path = os.path.expanduser("~/.config/.jira/.config.yml")
server = login = None
with open(cfg_path) as f:
    for line in f:
        s = line.strip()
        if s.startswith("server:"):
            server = s.split(":", 1)[1].strip()
        elif s.startswith("login:"):
            login = s.split(":", 1)[1].strip()
if not server or not login:
    sys.exit("error: could not read server/login from " + cfg_path)

auth = base64.b64encode(f"{login}:{token}".encode()).decode()

def get(path):
    req = urllib.request.Request(server + path,
                                 headers={"Authorization": f"Basic {auth}",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)

# Resolve the numeric issue id (dev-status keys on it, not the issue key).
issue = get(f"/rest/api/3/issue/{key}?fields=id")
iid = issue["id"]

detail = get(f"/rest/dev-status/latest/issue/detail"
             f"?issueId={iid}&applicationType=GitHub&dataType=pullrequest")

out = {"issue": key, "id": iid, "pullRequests": [], "branches": [], "repositories": []}
for d in detail.get("detail", []):
    for pr in d.get("pullRequests", []):
        out["pullRequests"].append({"id": pr.get("id"), "url": pr.get("url"),
                                    "status": pr.get("status"),
                                    "name": pr.get("name"),
                                    "branch": (pr.get("source") or {}).get("branch")})
    for b in d.get("branches", []):
        out["branches"].append({"name": b.get("name"), "url": b.get("url")})
    for repo in d.get("repositories", []):
        out["repositories"].append({"name": repo.get("name"), "url": repo.get("url")})

print(json.dumps(out, indent=2))
PY
