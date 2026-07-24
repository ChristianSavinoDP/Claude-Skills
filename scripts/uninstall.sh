#!/usr/bin/env bash
# Reverse what scripts/install.sh did: remove the symlinks it created, the
# permission rules and hooks it managed (tracked under _keruManaged), and the
# helper scripts it installed. Idempotent.
#
# Intentionally does NOT touch: secrets (e.g. JIRA_API_TOKEN in settings env),
# permission rules you added elsewhere, or permissions.defaultMode (its prior
# value was not recorded). Those are reported at the end. Everything the
# installer manages, including the playbook SessionStart hook, is removed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
BIN_DIR="$HOME/.local/bin"

# --reinstall: install.sh runs this as a pre-clean before it re-installs, so the
# closing "restart / left in place" notice would be misleading mid-install.
# Suppress just that epilogue; every removal step still runs.
REINSTALL_MODE=0
[ "${1:-}" = "--reinstall" ] && REINSTALL_MODE=1

# Remove symlinks under ~/.claude/<sub> that point into this repo.
unlink_repo_symlinks() {
  local dest="$CLAUDE_DIR/$1"
  [ -d "$dest" ] || return 0
  for target in "$dest"/*; do
    [ -L "$target" ] || continue
    case "$(readlink "$target")" in
      "$REPO_DIR"/*) rm "$target"; echo "unlinked: $target" ;;
    esac
  done
}

# Remove the permission rules and hooks recorded under _keruManaged, then drop
# the marker. Leaves everything else (external rules, secrets) untouched.
unmerge_config() {
  local settings="$CLAUDE_DIR/settings.json"
  [ -f "$settings" ] || return 0
  command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not found, cannot unmerge config"; return 0; }
  cp "$settings" "$settings.bak"
  python3 - "$settings" "$REPO_DIR" <<'PY'
import json, os, sys
settings_path, repo_dir = sys.argv[1], sys.argv[2]
try:
    with open(settings_path) as f:
        settings = json.load(f)
except (ValueError, OSError) as e:
    print("skip: cannot parse %s (%s); leaving settings untouched" % (settings_path, e))
    sys.exit(0)

settings.pop("todoFeatureEnabled", None)  # set by an older installer; clean it up

marker = settings.pop("_keruManaged", None) or {}

# Permission rules: remove everything the installer adds, marker or not. The
# marker records what the last install added, but it can be missing or stale (a
# settings.json edited by hand, or a half-finished install), which used to leave
# our rules orphaned. So we do NOT rely on the marker alone: the managed set is
# whatever the marker lists UNION what the repo's own config declares UNION the
# runtime-generated home-.claude Edit rule install.sh appends. This mirrors how
# hooks are already removed structurally, not from the marker. A rule the user
# added themselves is in none of these, so it is preserved (that is why we do not
# just clear the lists).
def config_perms():
    try:
        with open(os.path.join(repo_dir, "config", "permissions.json")) as f:
            return json.load(f).get("permissions", {})
    except (ValueError, OSError):
        return {}

cfg = config_perms()
home_edit = "Edit(//%s/**)" % os.path.expanduser("~/.claude").lstrip("/")

perms = settings.get("permissions", {})
removed = 0
for key in ("allow", "ask", "deny"):
    if key not in perms:
        continue
    drop = set(marker.get(key, [])) | set(cfg.get(key, []))
    if key == "allow":
        drop.add(home_edit)
    kept = [r for r in perms[key] if r not in drop]
    removed += len(perms[key]) - len(kept)
    if kept:
        perms[key] = kept
    else:
        del perms[key]

# Hooks: remove OURS structurally, not just what the marker lists, so a stale or
# lost marker still leaves a clean settings. Ours = a command at
# ~/.local/bin/keru-*, any agent-type hook, the playbook SessionStart `cat`, or a
# null/malformed leftover. Anything else is the user's and is preserved.
def is_ours(h):
    if not isinstance(h, dict):
        return True
    if h.get("type") == "agent":
        return True
    cmd = h.get("command", "")
    if isinstance(cmd, str) and ("/.local/bin/keru-" in cmd
                                 or "/playbook/PLAYBOOK.md" in cmd):
        return True
    return False

hooks = settings.get("hooks", {})
for event in list(hooks.keys()):
    for group in hooks[event]:
        group["hooks"] = [h for h in (group.get("hooks") or []) if not is_ours(h)]
    hooks[event] = [g for g in hooks[event] if g.get("hooks")]
    if not hooks[event]:
        del hooks[event]
if not hooks:
    settings.pop("hooks", None)

with open(settings_path, "w") as f:
    json.dump(settings, f, indent=2)
    f.write("\n")
print("removed: %d permission rule(s) and our hooks" % removed if removed
      else "no managed permission rules found to remove; hooks cleaned structurally")
PY
}

# Remove helper scripts the installer placed on PATH.
remove_helpers() {
  for h in "$BIN_DIR"/keru-*; do
    [ -e "$h" ] || continue
    rm "$h"; echo "removed: $h"
  done
}

# Remove the PATH block the installer added to the shell profile, matched by
# the same fixed marker the installer writes (and the export line under it).
PATH_MARKER="# Added by Claude-Skills installer"
remove_path_line() {
  command -v python3 >/dev/null 2>&1 || { echo "skip: python3 not found, leaving PATH line"; return 0; }
  local profile
  case "${SHELL:-}" in
    *zsh) profile="$HOME/.zshrc" ;;
    *bash) profile="$HOME/.bashrc" ;;
    *) profile="$HOME/.profile" ;;
  esac
  [ -f "$profile" ] || return 0
  MARKER="$PATH_MARKER" python3 - "$profile" <<'PY'
import os, sys
profile = sys.argv[1]
marker = os.environ["MARKER"]
lines = open(profile).read().splitlines()
out, i, removed = [], 0, 0
while i < len(lines):
    if lines[i].strip() == marker:
        # Skip the marker and the single export line under it.
        i += 2
        removed += 1
        continue
    out.append(lines[i]); i += 1
open(profile, "w").write(("\n".join(out).rstrip() + "\n") if out else "")
print(f"removed PATH block from {profile}" if removed else f"no PATH block in {profile}")
PY
}

unlink_repo_symlinks skills
unlink_repo_symlinks commands
unmerge_config

# The PATH line and the helper binaries are omitted in --reinstall mode: install
# re-adds both right after, idempotently, and touching them here is what would
# break install idempotency (uninstall's rstrip of the .zshrc PATH block differs
# byte-for-byte from how install re-appends it). A real uninstall removes them.
if [ "$REINSTALL_MODE" -eq 0 ]; then
  remove_helpers
  remove_path_line
fi

# Drop the drift-check marker the installer recorded (the SessionStart hook and
# the helper itself are already removed by unmerge_config / remove_helpers).
rm -f "$CLAUDE_DIR/.keru-installed-rev" && echo "removed: $CLAUDE_DIR/.keru-installed-rev"

# When install.sh calls this as a pre-clean, it re-installs right after, so the
# restart notice and the "left in place" summary do not apply yet.
[ "$REINSTALL_MODE" -eq 1 ] && exit 0

echo "Done. Restart Claude Code sessions to apply."
echo ""
echo "Left in place on purpose (remove by hand if you want):"
echo "  - JIRA_API_TOKEN in $CLAUDE_DIR/settings.json (env)"
echo "  - permissions.defaultMode (its prior value was not recorded)"
