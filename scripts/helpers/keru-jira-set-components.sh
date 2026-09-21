#!/usr/bin/env bash
# WRITE: set the Components field on an existing Jira issue by numeric id.
# Usage: keru-jira-set-components <ISSUE-KEY> <componentId> [<componentId> ...]
# Does ONE authenticated PUT against /rest/api/2/issue/<KEY> setting only the
# components field. Reads creds from JIRA_API_TOKEN and ~/.config/.jira/.config.yml.
# The token is built into the Authorization header INSIDE the python block; it is
# never placed on argv (unlike `curl -u "$LOGIN:$TOKEN"`, which leaks the secret to
# any local user via `ps`/`/proc/<pid>/cmdline`). This is used by the keru-create-ticket
# command's step 6; it is a state change, so it is held at `ask` in
# config/permissions.json and is deliberately NOT in keru-safe-read.py's read-only
# helper allowlist (do not add it there).
set -euo pipefail

KEY="${1:-}"
shift || true
if [ -z "$KEY" ] || [ "$#" -eq 0 ]; then
  echo "usage: keru-jira-set-components <ISSUE-KEY> <componentId> [<componentId> ...]" >&2
  exit 2
fi
# Reject anything that is not a plain issue key (e.g. ABC-123): no flags, no
# URLs, no shell metacharacters, no embedded newline reaching the request. bash
# =~ matches the WHOLE string (unlike grep's per-line ^$), so a multi-line value
# whose first line looks valid is rejected here, not just caught downstream.
if ! [[ "$KEY" =~ ^[A-Z][A-Z0-9]+-[0-9]+$ ]]; then
  echo "error: '$KEY' is not a valid issue key (expected like DBI-1234)" >&2
  exit 2
fi
# Each remaining argument must be a bare numeric component id. Reject names or
# flags: the command resolves the name to an id before calling this helper.
for cid in "$@"; do
  if ! [[ "$cid" =~ ^[0-9]+$ ]]; then
    echo "error: '$cid' is not a numeric component id" >&2
    exit 2
  fi
done

JIRA_API_TOKEN="${JIRA_API_TOKEN:-}"
if [ -z "$JIRA_API_TOKEN" ]; then
  echo "error: JIRA_API_TOKEN is not set" >&2
  exit 1
fi

python3 - "$KEY" "$@" <<'PY'
import json, os, sys, base64, urllib.request, urllib.error

key = sys.argv[1]
component_ids = sys.argv[2:]
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

body = json.dumps({"fields": {"components": [{"id": c} for c in component_ids]}}).encode()
req = urllib.request.Request(
    server + f"/rest/api/2/issue/{key}",
    data=body, method="PUT",
    headers={"Authorization": f"Basic {auth}",
             "Content-Type": "application/json",
             "Accept": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=30) as r:
        code = r.getcode()
except urllib.error.HTTPError as e:
    detail = e.read().decode(errors="replace")
    sys.exit(f"error: PUT {key} components failed: HTTP {e.code} {detail}")
except (urllib.error.URLError, OSError) as e:
    # DNS / connection refused / timeout: a clean message, not a Python traceback.
    # The token lives only in the header object, so nothing sensitive is exposed.
    sys.exit(f"error: PUT {key} components failed: {e}")

# A successful components PUT returns 204 No Content.
print(f"set components on {key}: HTTP {code}")
if code != 204:
    sys.exit(f"error: expected HTTP 204, got {code}")
PY
