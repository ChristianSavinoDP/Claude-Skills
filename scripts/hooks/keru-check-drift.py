#!/usr/bin/env python3
"""SessionStart hook: warn when the active Claude-Skills install is stale.

This repo activates by mechanisms with DIFFERENT staleness rules, and none is
covered by any built-in Claude Code check (a plain skills dir is not version
tracked):

  - Symlinked skills and the cat'd playbook are LIVE: editing them in the repo
    takes effect on the next session with no reinstall. Nothing to warn about.
  - But three kinds of change only activate on `scripts/install.sh`: a newly
    ADDED or REMOVED skill (needs a new symlink / prune), a change to
    config/*.json (merged into settings.json), and a change to a helper or hook
    SCRIPT under scripts/ (those are COPIED into ~/.local/bin, not symlinked).
    Edit one of those and forget to reinstall, and the running Claude Code
    silently uses the old copy.
  - Separately, the local clone can just be behind origin (another machine
    pushed, or you never pulled).

So this hook prints, at session start, a short notice for two independent signals
and stays silent when there is nothing to say:

  A. HEAD is behind the remote default branch. Local refs only, NO fetch, so it
     is "as of your last fetch" and adds zero startup latency. Only checked when
     you are actually on the default branch, so feature-branch work is not nagged.
  B. The set of activatable artifacts (skill dir names, config/*.json, the
     scripts/ helpers and hooks, install.sh) differs from what was present at the
     last install, recorded in ~/.claude/.keru-installed-rev by --write-marker.

Fail-open in every branch: any error prints nothing and exits 0, so a broken
check never delays or disrupts a session. Called two ways:

  keru-check-drift <repo_dir>                 the SessionStart check
  keru-check-drift --write-marker <repo_dir>  install.sh, records current state

The hash logic lives here only, so the marker written at install time and the
state checked at session start can never drift apart.
"""
import hashlib
import json
import os
import subprocess
import sys

# Resolve the config dir the same way install.sh does
# (CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"), so the marker written at
# install time and the one read at session start always point at the same file,
# even under a custom CLAUDE_CONFIG_DIR.
CLAUDE_DIR = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
MARKER = os.path.join(CLAUDE_DIR, ".keru-installed-rev")


def _git(repo, *args):
    """Run a git command in repo; return stripped stdout, or None on any failure.
    Never raises. Every caller below reads only local refs, so this never fetches."""
    try:
        out = subprocess.run(["git", "-C", repo, *args],
                             capture_output=True, text=True, timeout=5)
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _default_branch(repo):
    """origin's default branch short name (main/master/...), or None. Reads the
    local origin/HEAD ref, then falls back to whichever conventional remote ref
    exists. No network."""
    ref = _git(repo, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    prefix = "refs/remotes/origin/"
    if ref and ref.startswith(prefix):
        return ref[len(prefix):]
    for name in ("main", "master"):
        if _git(repo, "rev-parse", "--verify", "--quiet", prefix + name) is not None:
            return name
    return None


def _behind_count(repo):
    """How many commits the remote default branch is ahead of HEAD, or 0. Only
    reported when HEAD is ON the default branch, so deliberate feature-branch work
    is never flagged as 'behind'."""
    branch = _default_branch(repo)
    if not branch:
        return 0
    current = _git(repo, "symbolic-ref", "--short", "--quiet", "HEAD")
    if current != branch:
        return 0  # on a feature branch (or detached HEAD): not our concern
    count = _git(repo, "rev-list", "--count", "HEAD..refs/remotes/origin/" + branch)
    try:
        return int(count)
    except (TypeError, ValueError):
        return 0


def _sha_bytes(*chunks):
    h = hashlib.sha256()
    for c in chunks:
        h.update(c.encode("utf-8") if isinstance(c, str) else c)
        h.update(b"\0")
    return h.hexdigest()


def _file_sig(path):
    """Content hash of one file, or '' if unreadable (a missing file then
    contributes a stable empty signature rather than raising)."""
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return ""


def _activation_hash(repo):
    """A hash of exactly the artifacts that only take effect on reinstall, so it
    changes iff a reinstall is actually needed, and NOT when a live-editable file
    (a SKILL.md body, the playbook) changes. Returns None if the repo layout is
    unreadable (caller then skips signal B)."""
    skills_dir = os.path.join(repo, "skills")
    try:
        # The SET of skill dir names: adding/removing a skill needs a new symlink
        # or prune. Editing files INSIDE a skill is live (the dir is symlinked
        # whole), so their contents are deliberately excluded here.
        names = sorted(d for d in os.listdir(skills_dir)
                       if os.path.isdir(os.path.join(skills_dir, d)))
    except OSError:
        return None
    parts = ["skills=" + ",".join(names)]

    # Files that are copied/merged by the installer, so an edit is inert until the
    # next run: config merged into settings.json, and the helper/hook scripts plus
    # the installer itself copied onto PATH.
    rels = ["config/permissions.json", "config/hooks.json", "scripts/install.sh"]
    for sub in ("scripts/helpers", "scripts/hooks"):
        for root, dirs, files in os.walk(os.path.join(repo, sub)):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                if not name.endswith(".pyc"):
                    rels.append(os.path.relpath(os.path.join(root, name), repo))
    for rel in sorted(set(rels)):
        parts.append(rel + "=" + _file_sig(os.path.join(repo, rel)))
    return _sha_bytes(*parts)


def _write_marker(repo):
    h = _activation_hash(repo)
    if h is None:
        return 1
    try:
        os.makedirs(os.path.dirname(MARKER), exist_ok=True)
        with open(MARKER, "w", encoding="utf-8") as f:
            json.dump({"repo": os.path.abspath(repo), "hash": h}, f)
            f.write("\n")
    except OSError:
        return 1
    return 0


def _marker_hash():
    try:
        with open(MARKER, encoding="utf-8") as f:
            return json.load(f).get("hash")
    except (OSError, ValueError):
        return None


def _check(repo):
    notices = []

    behind = _behind_count(repo)
    if behind > 0:
        branch = _default_branch(repo) or "the default branch"
        notices.append(
            "%d commit%s behind origin/%s (as of your last fetch). "
            "Run: git -C %s pull --ff-only"
            % (behind, "" if behind == 1 else "s", branch, repo))

    # Signal B only when a marker exists (i.e. the repo has been installed with a
    # marker-writing installer at least once); otherwise stay silent, no noise.
    marker = _marker_hash()
    if marker is not None:
        current = _activation_hash(repo)
        if current is not None and current != marker:
            notices.append(
                "the repo changed since the last install (a new or removed skill, "
                "a config/*.json edit, or a helper/hook script edit only take "
                "effect on reinstall). Run: %s/scripts/install.sh" % repo)

    if notices:
        # SessionStart stdout becomes context for Claude, not a UI banner, so ask
        # Claude to relay it. Only ever printed when there is real drift.
        print("[Claude-Skills] Your install is out of date. Tell the user, then continue:")
        for n in notices:
            print("  - " + n)


def main():
    args = sys.argv[1:]
    if args and args[0] == "--write-marker":
        return _write_marker(args[1]) if len(args) >= 2 else 2
    if not args:
        return 0  # no repo given: nothing to check, stay silent
    try:
        _check(args[0])
    except Exception:
        pass  # fail-open: a broken check must never disrupt a session
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
