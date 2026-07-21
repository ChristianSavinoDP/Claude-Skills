#!/usr/bin/env bash
# Set up this repo in Claude Code: symlink skills into ~/.claude (each skill is
# its own /keru-* slash command, no wrapper layer), merge global permission
# settings and hooks (including the playbook
# SessionStart hook, generated with this machine's repo path), install the
# keru-* helpers onto PATH, and check the external tools (gh, jira). The repo
# stays the single source of truth; edits here take effect everywhere.
# Re-runnable (idempotent).
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"

link_dir() {
  local src="$REPO_DIR/$1" dest="$CLAUDE_DIR/$1"
  [ -d "$src" ] || return 0
  mkdir -p "$dest"
  for entry in "$src"/*/; do
    [ -e "$entry" ] || continue
    local name target
    entry="${entry%/}"
    name="$(basename "$entry")"
    target="$dest/$name"
    if [ -L "$target" ]; then
      rm "$target"
    elif [ -e "$target" ]; then
      echo "skip: $target exists and is not a symlink (leaving as-is)"
      continue
    fi
    ln -s "$entry" "$target"
    echo "linked: $target -> $entry"
  done
}

# Remove symlinks under ~/.claude that point into this repo but no longer
# resolve (skill/command deleted from the repo). Leaves unrelated links alone.
prune_dangling() {
  local dest="$CLAUDE_DIR/$1"
  [ -d "$dest" ] || return 0
  for target in "$dest"/*; do
    [ -L "$target" ] || continue
    local dest_path
    dest_path="$(readlink "$target")"
    case "$dest_path" in
      "$REPO_DIR"/*) [ -e "$target" ] || { rm "$target"; echo "pruned: $target (source gone)"; } ;;
    esac
  done
}

# Merge config/permissions.json and config/hooks.json (plus the generated
# playbook SessionStart hook) into the global ~/.claude/settings.json. Sets
# defaultMode, syncs the allow/ask/deny lists and hook groups against the
# _keruManaged marker (adds new, removes dropped), without touching rules or
# hooks added elsewhere. Idempotent. Backs up the settings first. Needs python3.
merge_config() {
  local perms="$REPO_DIR/config/permissions.json" hooks="$REPO_DIR/config/hooks.json"
  local settings="$CLAUDE_DIR/settings.json"
  [ -f "$perms" ] || [ -f "$hooks" ] || return 0
  command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not found, cannot merge config"; return 0; }
  mkdir -p "$CLAUDE_DIR"
  [ -f "$settings" ] && cp "$settings" "$settings.bak"
  python3 - "$settings" "$perms" "$hooks" "$REPO_DIR" <<'PY'
import json, sys, os, shlex
settings_path, perms_path, hooks_path, repo_dir = sys.argv[1:5]

def load(path):
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}

try:
    settings = load(settings_path)
except (ValueError, OSError) as e:
    print("skip: cannot parse %s (%s); leaving settings untouched" % (settings_path, e))
    sys.exit(0)
perms_frag = load(perms_path).get("permissions", {})
hooks_frag = load(hooks_path).get("hooks", {})

# Inject the playbook SessionStart hook with this machine's repo path resolved
# at runtime, so no absolute path is hardcoded in the committed config. Managed
# like every other hook (synced in, removed on uninstall).
playbook = os.path.join(repo_dir, "playbook", "PLAYBOOK.md")
hooks_frag.setdefault("SessionStart", []).append({
    "hooks": [{"type": "command", "command": "cat " + playbook + " 2>/dev/null"}]
})

# Inject the drift check as a second SessionStart hook, with this machine's repo
# path resolved at runtime (same reason as the playbook: the path is
# machine-specific and cannot live in the committed config). It reads local git
# refs only (no fetch) and the on-disk repo, so it adds no startup latency; it
# prints a notice only when the local clone is behind origin or the repo changed
# since the last install. Referenced by its ~/.local/bin name so is_ours() below
# recognizes it as ours (synced in here, removed on uninstall) like every other
# keru-* hook.
drift = "~/.local/bin/keru-check-drift " + shlex.quote(repo_dir)
hooks_frag.setdefault("SessionStart", []).append({
    "hooks": [{"type": "command", "command": drift, "timeout": 10}]
})

# Allow editing the global ~/.claude tree (skills/config live there as
# symlinks) without a prompt, resolved to this machine's absolute home so no
# user-specific path sits in the committed config. The relative Edit(.claude/**)
# in permissions.json covers the per-repo case; this covers the global one.
home_claude = os.path.expanduser("~/.claude")
perms_frag.setdefault("allow", []).append("Edit(//%s/**)" % home_claude.lstrip("/"))

# Track what this installer manages, so each run SYNCS (adds new, removes
# rules/hooks dropped from config) without touching anything added elsewhere.
prev = settings.get("_keruManaged", {})
managed = {"allow": [], "ask": [], "deny": [], "hooks": []}

# Permissions: set defaultMode; sync allow/ask/deny against the managed set.
perms = settings.setdefault("permissions", {})
if "defaultMode" in perms_frag:
    perms["defaultMode"] = perms_frag["defaultMode"]
for key in ("allow", "ask", "deny"):
    current = perms.get(key, [])
    prev_managed = set(prev.get(key, []))
    want = perms_frag.get(key, [])
    # Drop previously-managed rules that are no longer in config; keep the rest.
    kept = [r for r in current if r not in prev_managed or r in want]
    for rule in want:
        if rule not in kept:
            kept.append(rule)
    if kept:
        perms[key] = kept
    elif key in perms:
        del perms[key]
    managed[key] = list(want)

# Hooks: rebuild our managed hooks from config every run, idempotently. Rather
# than diff against the previous _keruManaged marker (fragile: if the marker is
# lost or stale, old hooks orphan and pile up, and a half-merge can leave nulls),
# we identify OUR hooks structurally and replace them wholesale with what the
# config currently wants. A hook is "ours" if it is a command pointing at
# ~/.local/bin/keru-* or any agent-type hook (all our agent hooks are ours; we do
# not author other agent hooks). Everything else in a group is preserved.
hooks = settings.setdefault("hooks", {})

def is_ours(h):
    if not isinstance(h, dict):
        return True  # null / malformed leftover: drop it
    if h.get("type") == "agent":
        return True
    cmd = h.get("command", "")
    return isinstance(cmd, str) and "/.local/bin/keru-" in cmd

# What the config wants, grouped by (event, matcher).
want = {}  # (event, matcher) -> list of hook dicts, in order
for event, groups in hooks_frag.items():
    for group in groups:
        key = (event, group.get("matcher"))
        want.setdefault(key, []).extend(group.get("hooks", []))

# Strip every one of our hooks (and nulls) from existing groups.
for event in list(hooks.keys()):
    for group in hooks[event]:
        group["hooks"] = [h for h in (group.get("hooks") or []) if not is_ours(h)]

# Re-add the wanted hooks into their (event, matcher) group, in config order.
for (event, matcher), hlist in want.items():
    groups = hooks.setdefault(event, [])
    target = next((g for g in groups if g.get("matcher") == matcher), None)
    if target is None:
        target = {"hooks": []}
        if matcher is not None:
            target["matcher"] = matcher
        groups.append(target)
    target.setdefault("hooks", [])
    for h in hlist:
        if h not in target["hooks"]:
            target["hooks"].append(h)

# Drop now-empty groups and events.
for event in list(hooks.keys()):
    hooks[event] = [g for g in hooks[event] if g.get("hooks")]
    if not hooks[event]:
        del hooks[event]

# Record what we manage (for uninstall); the rebuild above no longer relies on it.
managed["hooks"] = [[event, json.dumps(h, sort_keys=True)]
                    for (event, _), hlist in want.items() for h in hlist]

settings["_keruManaged"] = managed

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("synced: config into", settings_path)
PY
}

# Install repo helper scripts into ~/.local/bin under stable names, so they
# can be invoked by bare command name and allowlisted portably (no per-machine
# paths in committed settings). Copies, so it works from any cwd.
BIN_DIR="$HOME/.local/bin"
install_helpers() {
  mkdir -p "$BIN_DIR"
  # Tool helpers (called by skills) live in scripts/helpers/; hook scripts (run
  # by config/hooks.json) live in scripts/hooks/. Both install under the same
  # bare names on PATH, so the rename is invisible to settings.json and skills.
  install -m 0755 "$REPO_DIR/scripts/helpers/keru-jira-dev.sh" "$BIN_DIR/keru-jira-dev"
  install -m 0755 "$REPO_DIR/scripts/helpers/keru-bot-triage.sh" "$BIN_DIR/keru-bot-triage"
  install -m 0755 "$REPO_DIR/scripts/helpers/keru-branch-cleanup.sh" "$BIN_DIR/keru-branch-cleanup"
  install -m 0755 "$REPO_DIR/scripts/helpers/keru-repo-update.sh" "$BIN_DIR/keru-repo-update"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-safe-read.py" "$BIN_DIR/keru-safe-read"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-block-webfetch.py" "$BIN_DIR/keru-block-webfetch"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-block-inline-interp.py" "$BIN_DIR/keru-block-inline-interp"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-require-skill.py" "$BIN_DIR/keru-require-skill"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-check-output.py" "$BIN_DIR/keru-check-output"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-judge-output.py" "$BIN_DIR/keru-judge-output"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-gate-deliverable.py" "$BIN_DIR/keru-gate-deliverable"
  install -m 0755 "$REPO_DIR/scripts/hooks/keru-check-drift.py" "$BIN_DIR/keru-check-drift"
  echo "installed: keru-jira-dev, keru-bot-triage, keru-branch-cleanup, keru-repo-update, keru-safe-read, keru-block-webfetch, keru-block-inline-interp, keru-require-skill, keru-check-output, keru-judge-output, keru-gate-deliverable, keru-check-drift in $BIN_DIR"
  ensure_on_path
}

# Make sure ~/.local/bin is on PATH so helpers resolve by bare name. Adds a
# line to the user's shell profile if missing (idempotent), and exports it for
# the current process so it works immediately.
PATH_MARKER="# Added by Claude-Skills installer"
ensure_on_path() {
  # Export for the current process so helpers resolve immediately.
  case ":$PATH:" in *":$BIN_DIR:"*) ;; *) export PATH="$BIN_DIR:$PATH" ;; esac
  local profile
  case "${SHELL:-}" in
    *zsh) profile="$HOME/.zshrc" ;;
    *bash) profile="$HOME/.bashrc" ;;
    *) profile="$HOME/.profile" ;;
  esac
  # Detect by the fixed marker, not the path string: the written line contains
  # the literal $HOME, which would never match an expanded BIN_DIR grep.
  if [ -f "$profile" ] && grep -qF "$PATH_MARKER" "$profile"; then
    echo "path: already configured in $profile"
  else
    printf '\n%s\nexport PATH="$HOME/.local/bin:$PATH"\n' "$PATH_MARKER" >> "$profile"
    echo "path: added $BIN_DIR to $profile (open a new shell to pick it up)"
  fi
}

# Ensure a CLI is installed via Homebrew, installing it if missing.
# Returns non-zero if it could not be made available.
ensure_installed() {
  local bin="$1" formula="$2"
  command -v "$bin" >/dev/null 2>&1 && return 0
  if command -v brew >/dev/null 2>&1; then
    echo "installing: $bin ($formula)"
    brew install "$formula" >/dev/null 2>&1 || true
  fi
  command -v "$bin" >/dev/null 2>&1
}

# Check that the external tools the skills rely on are installed and
# authenticated. Installs missing ones via brew; prints the exact setup
# command for anything that needs interactive configuration. Never aborts
# the installer: each tool reports OK / ACTION NEEDED independently.
TOOLS_OK=1
check_tools() {
  echo "--- tools ---"

  # GitHub CLI: needed by the PR skills.
  if ensure_installed gh gh; then
    if gh auth status >/dev/null 2>&1; then
      echo "ok: gh installed and authenticated"
    else
      TOOLS_OK=0
      echo "action: gh installed but not authenticated. Run: gh auth login"
    fi
  else
    TOOLS_OK=0
    echo "action: gh not installed and brew unavailable. See docs/external-tools.md."
  fi

  # Jira CLI: needed by the gather-context skill.
  if ensure_installed jira ankitpokhrel/jira-cli/jira-cli; then
    if jira me >/dev/null 2>&1; then
      echo "ok: jira installed and configured ($(jira me 2>/dev/null))"
    else
      TOOLS_OK=0
      echo "action: jira installed but not configured. Create a token at"
      echo "        https://id.atlassian.com/manage-profile/security/api-tokens then run:"
      echo "        jira init --installation cloud --server https://<org>.atlassian.net \\"
      echo "          --login <email> --auth-type basic --project <PROJECT_KEY>"
    fi
  else
    TOOLS_OK=0
    echo "action: jira not installed and brew unavailable. See docs/external-tools.md."
  fi

  # pup (DataDog CLI): needed by the datadog-audit skill. The fully-qualified
  # formula auto-taps datadog-labs/pack. Auth is an interactive browser OAuth
  # flow the installer cannot do, so it only reports the action.
  if ensure_installed pup datadog-labs/pack/pup; then
    if pup auth status >/dev/null 2>&1 && pup auth status 2>/dev/null | grep -q '"authenticated": true'; then
      echo "ok: pup installed and authenticated"
    else
      TOOLS_OK=0
      echo "action: pup installed but not authenticated. Run: pup auth login"
    fi
  else
    TOOLS_OK=0
    echo "action: pup not installed and brew unavailable. See docs/external-tools.md."
  fi
}

# Record the current activatable state (skill set, config, helper/hook scripts)
# so the SessionStart drift check can tell, on later sessions, that the repo
# changed since this install and a re-run is needed. Uses the just-installed
# helper so the hash logic has a single home. Best-effort; never aborts install.
write_drift_marker() {
  "$BIN_DIR/keru-check-drift" --write-marker "$REPO_DIR" \
    && echo "recorded: install state for drift check" \
    || echo "note: could not record drift-check marker (non-fatal)"
}

link_dir skills
prune_dangling skills
# Skills are their own slash commands; a typed-only command is a skill with
# disable-model-invocation in its frontmatter, not a separate commands/ file.
# Still prune ~/.claude/commands so a prior install's wrapper symlinks (now
# source-gone) are cleaned up.
prune_dangling commands
merge_config
install_helpers
write_drift_marker
check_tools

echo "Done. Restart Claude Code sessions to pick up changes."
[ "$TOOLS_OK" -eq 1 ] || echo "Some tools need setup (see 'action:' lines above)."
