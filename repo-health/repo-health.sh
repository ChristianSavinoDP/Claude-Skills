#!/usr/bin/env bash
# Deterministic self-health checks for this repo, run by the repo-health skill.
# Covers the mechanical parts only; the semantic parts (rule drift between the
# playbook and skills, whether a doc's prose is still accurate) stay with the
# skill, which reads this script's findings and layers its own judgment.
#
# Checks:
#   docs        - skills/commands match what docs/ documents (no undocumented
#                 skill/command, no orphan doc entry)
#   permissions - structural checks on config/permissions.json (no rule in both
#                 allow and ask, no exact duplicates)
#   installer   - install.sh is idempotent and uninstall.sh reverses it, run in
#                 a sandbox HOME so nothing real is touched
#
# Usage: repo-health/repo-health.sh [all|docs|permissions|installer]  (default: all)
# Exit code: 1 if any check fails, 0 otherwise. Read-only except the installer
# check, which writes only under a temp dir it removes on exit.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SANDBOX=""
trap '[ -n "$SANDBOX" ] && rm -rf "$SANDBOX"' EXIT

FAILURES=()
WARNINGS=()
fail() { FAILURES+=("$1"); }
warn() { WARNINGS+=("$1"); }

# --- docs: skills/commands vs what docs/ documents ---------------------------
# repo-health itself lives outside skills/ and commands/ (in repo-health/), so
# it is intentionally excluded from this cross-check and documents itself in its
# own README.
check_docs() {
  local skills_dir="$REPO_DIR/skills"
  local skills_md="$REPO_DIR/docs/skills.md"

  # Each skill is its own slash command (the wrapper layer was removed): the
  # directory name under skills/ is the command name, so skills are named keru-*.
  # Every skill on disk must be documented in docs/skills.md.
  for d in "$skills_dir"/*/; do
    [ -d "$d" ] || continue
    local name; name="$(basename "$d")"
    if ! grep -q "\`$name\`" "$skills_md"; then
      fail "skill '$name' exists but is not in docs/skills.md"
    fi
    case "$name" in
      keru-*) : ;;
      *) fail "skill '$name' is not prefixed keru-; its slash command would not show as /keru-*" ;;
    esac
  done

  # Orphan entries: a skill the catalogue table lists but no longer exists.
  while IFS= read -r name; do
    [ -n "$name" ] || continue
    if [ ! -d "$skills_dir/$name" ]; then
      fail "docs/skills.md lists skill '$name' but skills/$name/ does not exist"
    fi
  done < <(grep -oE '^\| `keru-[a-z-]+`' "$skills_md" | tr -d '|` ')
}

# --- permissions: structural checks on config/permissions.json ---------------
check_permissions() {
  local perms="$REPO_DIR/config/permissions.json"
  if ! command -v jq >/dev/null 2>&1; then
    warn "jq not found; skipping permissions structural check"
    return 0
  fi
  if [ ! -f "$perms" ]; then
    warn "config/permissions.json not found; skipping permissions check"
    return 0
  fi

  # A rule in both allow and ask is contradictory (ask wins, so the allow is dead).
  local both
  both="$(jq -r '[.permissions.allow[]?] as $a | [.permissions.ask[]?] as $k | ($a - ($a - $k)) | .[]' "$perms")"
  if [ -n "$both" ]; then
    while IFS= read -r r; do [ -n "$r" ] && fail "rule in both allow and ask: $r"; done <<< "$both"
  fi

  # Exact duplicates within a list.
  local key dup
  for key in allow ask deny; do
    dup="$(jq -r --arg k "$key" '[.permissions[$k][]?] | group_by(.) | map(select(length > 1) | .[0]) | .[]' "$perms")"
    if [ -n "$dup" ]; then
      while IFS= read -r r; do [ -n "$r" ] && fail "duplicate $key rule: $r"; done <<< "$dup"
    fi
  done
}

# --- installer: idempotency + clean uninstall, in a sandbox HOME -------------
# Records every symlink (target normalized) and file hash under the sandboxed
# ~/.claude and ~/.local/bin, plus the shell profile, excluding *.bak backups.
snapshot() {
  # Ensure both dirs exist: find exits non-zero on a missing path arg, which
  # under set -e+pipefail would abort the function before `return 0`.
  mkdir -p "$SANDBOX/.claude" "$SANDBOX/.local/bin"
  {
    find "$SANDBOX/.claude" "$SANDBOX/.local/bin" -name '*.bak' -prune -o \( -type l -o -type f \) -print 2>/dev/null \
      | sort | while IFS= read -r full; do
          local rel="${full#"$SANDBOX"}"
          if [ -L "$full" ]; then
            printf 'L %s -> %s\n' "$rel" "$(readlink "$full" | sed "s|^$REPO_DIR|<REPO>|")"
          else
            printf 'F %s %s\n' "$rel" "$(shasum -a 256 "$full" | awk '{print $1}')"
          fi
        done
    local p
    for p in "$SANDBOX/.zshrc" "$SANDBOX/.bashrc" "$SANDBOX/.profile"; do
      [ -f "$p" ] && printf 'P %s %s\n' "${p#"$SANDBOX"}" "$(shasum -a 256 "$p" | awk '{print $1}')"
    done
  } > "$1"
  return 0  # the last [ -f ] test must not become snapshot's exit status (set -e)
}

check_installer() {
  SANDBOX="$(mktemp -d)"
  local s1="$SANDBOX/.snap1" s2="$SANDBOX/.snap2" d="$SANDBOX/.diff"

  # Pin BOTH HOME and CLAUDE_CONFIG_DIR to the sandbox: the installer resolves
  # its target as ${CLAUDE_CONFIG_DIR:-$HOME/.claude}, so if the caller's env has
  # CLAUDE_CONFIG_DIR set (Claude Code does), a HOME-only override would leak and
  # uninstall.sh would strip the REAL ~/.claude. Isolation must not depend on env.
  run_install()   { HOME="$SANDBOX" CLAUDE_CONFIG_DIR="$SANDBOX/.claude" SHELL=/bin/zsh bash "$REPO_DIR/scripts/install.sh"   >/dev/null 2>&1; }
  run_uninstall() { HOME="$SANDBOX" CLAUDE_CONFIG_DIR="$SANDBOX/.claude" SHELL=/bin/zsh bash "$REPO_DIR/scripts/uninstall.sh" >/dev/null 2>&1; }

  if ! run_install; then fail "install.sh failed in sandbox"; return; fi
  snapshot "$s1"
  if ! run_install; then fail "install.sh failed on the second run"; return; fi
  snapshot "$s2"

  if ! diff "$s1" "$s2" > "$d" 2>&1; then
    fail "install.sh is not idempotent (run 1 vs run 2 differ): $(tr '\n' ' ' < "$d" | cut -c1-300)"
  fi

  if ! run_uninstall; then warn "uninstall.sh returned non-zero in sandbox"; fi

  # No symlink pointing back into the repo should remain.
  local leftover="" link target
  while IFS= read -r link; do
    [ -n "$link" ] || continue
    target="$(readlink "$link")"
    case "$target" in "$REPO_DIR"/*) leftover="$leftover $link" ;; esac
  done < <(find "$SANDBOX/.claude" -type l 2>/dev/null)
  if [ -n "$leftover" ]; then
    fail "uninstall.sh left repo symlinks:$leftover"
  fi
  # No helper scripts should remain.
  if find "$SANDBOX/.local/bin" -name 'keru-*' 2>/dev/null | grep -q .; then
    fail "uninstall.sh left keru-* helpers in ~/.local/bin"
  fi
  # The managed marker should be gone.
  if [ -f "$SANDBOX/.claude/settings.json" ] && command -v jq >/dev/null 2>&1; then
    if jq -e 'has("_keruManaged")' "$SANDBOX/.claude/settings.json" >/dev/null 2>&1; then
      fail "uninstall.sh left _keruManaged in settings.json"
    fi
  fi
}

# --- run ---------------------------------------------------------------------
target="${1:-all}"
case "$target" in
  docs)        check_docs ;;
  permissions) check_permissions ;;
  installer)   check_installer ;;
  all)         check_docs; check_permissions; check_installer ;;
  *) echo "usage: $(basename "$0") [all|docs|permissions|installer]" >&2; exit 2 ;;
esac

echo "=== repo-health: $target ==="
if [ "${#WARNINGS[@]}" -gt 0 ]; then
  echo "warnings (${#WARNINGS[@]}):"
  for w in "${WARNINGS[@]}"; do echo "  - $w"; done
fi
if [ "${#FAILURES[@]}" -gt 0 ]; then
  echo "failures (${#FAILURES[@]}):"
  for f in "${FAILURES[@]}"; do echo "  - $f"; done
  exit 1
fi
echo "ok: no mechanical issues found"
