#!/usr/bin/env bash
#
# sync-sessions.sh - Sync agent session segments to a shared git repo
#
# This script:
# 1. Pulls latest segments from the shared repo
# 2. Segments any new local sessions (Claude Code, OpenClaw, Codex CLI)
# 3. Commits and pushes new segments
#
# Copy this script to any machine and configure the variables below.
#
set -euo pipefail

# ============================================================================
# CONFIGURATION - Edit these for your setup
# ============================================================================

# GitHub repo for synced segments (e.g., "username/agent-sessions")
SYNC_REPO="${SESSION_SYNC_REPO:-}"

# Local workspace directory (where segments are stored and synced)
WORKSPACE_DIR="${SESSION_WORKSPACE_DIR:-$HOME/.openclaw/workspace/sessions}"

# Machine identifier for commit messages
MACHINE_ID="${SESSION_MACHINE_ID:-$(hostname -s)}"

# ============================================================================
# AUTO-DETECTED SESSION SOURCES
# ============================================================================

# Claude Code sessions (Mac/Linux)
CLAUDE_CODE_DIR="$HOME/.claude/projects"

# OpenClaw sessions
OPENCLAW_DIR="$HOME/.openclaw/agents/main/sessions"

# Codex CLI sessions
CODEX_DIR="$HOME/.codex/sessions"

# ============================================================================
# FUNCTIONS
# ============================================================================

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

error() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

check_dependencies() {
    local missing=()

    if ! command -v git &>/dev/null; then
        missing+=("git")
    fi

    if ! command -v session-search &>/dev/null; then
        missing+=("session-search (pip install session-search)")
    fi

    if [[ ${#missing[@]} -gt 0 ]]; then
        error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

setup_workspace() {
    mkdir -p "$WORKSPACE_DIR"

    if [[ ! -d "$WORKSPACE_DIR/.git" ]]; then
        log "Initializing workspace as git repo..."
        cd "$WORKSPACE_DIR"
        git init

        if [[ -n "$SYNC_REPO" ]]; then
            git remote add origin "https://github.com/$SYNC_REPO.git" 2>/dev/null || \
                git remote set-url origin "https://github.com/$SYNC_REPO.git"
        fi

        # Create initial commit if empty
        if [[ -z "$(git log --oneline 2>/dev/null | head -1)" ]]; then
            echo "# Agent Sessions" > README.md
            echo "" >> README.md
            echo "Synced session segments from multiple machines and agent types." >> README.md
            git add README.md
            git commit -m "Initial commit"
        fi
    fi
}

pull_latest() {
    if [[ -z "$SYNC_REPO" ]]; then
        log "No SYNC_REPO configured, skipping pull"
        return 0
    fi

    cd "$WORKSPACE_DIR"

    # Check if remote has commits
    if git ls-remote --exit-code origin &>/dev/null; then
        log "Pulling latest segments from $SYNC_REPO..."
        git fetch origin main 2>/dev/null || git fetch origin master 2>/dev/null || true

        # Merge if we have a tracking branch
        if git rev-parse --verify origin/main &>/dev/null; then
            git merge origin/main --no-edit 2>/dev/null || true
        elif git rev-parse --verify origin/master &>/dev/null; then
            git merge origin/master --no-edit 2>/dev/null || true
        fi
    else
        log "Remote repo is empty, will push first commit"
    fi
}

segment_sessions() {
    local sources_found=0

    # Segment Claude Code sessions
    if [[ -d "$CLAUDE_CODE_DIR" ]]; then
        log "Segmenting Claude Code sessions from $CLAUDE_CODE_DIR..."
        session-search index --sessions-dir "$CLAUDE_CODE_DIR" --output-dir "$WORKSPACE_DIR" 2>&1 || true
        sources_found=$((sources_found + 1))
    fi

    # Segment OpenClaw sessions
    if [[ -d "$OPENCLAW_DIR" ]]; then
        log "Segmenting OpenClaw sessions from $OPENCLAW_DIR..."
        session-search index --sessions-dir "$OPENCLAW_DIR" --output-dir "$WORKSPACE_DIR" 2>&1 || true
        sources_found=$((sources_found + 1))
    fi

    # Segment Codex CLI sessions
    if [[ -d "$CODEX_DIR" ]]; then
        log "Segmenting Codex CLI sessions from $CODEX_DIR..."
        session-search index --sessions-dir "$CODEX_DIR" --output-dir "$WORKSPACE_DIR" 2>&1 || true
        sources_found=$((sources_found + 1))
    fi

    if [[ $sources_found -eq 0 ]]; then
        log "No session sources found on this machine"
    fi
}

commit_and_push() {
    cd "$WORKSPACE_DIR"

    # Check for changes
    if [[ -z "$(git status --porcelain)" ]]; then
        log "No new segments to commit"
        return 0
    fi

    # Add all new/changed files
    git add -A

    # Create commit
    local segment_count
    segment_count=$(git status --porcelain | wc -l | tr -d ' ')
    git commit -m "Add $segment_count segments from $MACHINE_ID

Synced at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

    log "Committed $segment_count new/updated segments"

    # Push if repo configured
    if [[ -n "$SYNC_REPO" ]]; then
        log "Pushing to $SYNC_REPO..."
        git push -u origin main 2>/dev/null || git push -u origin master 2>/dev/null || {
            # First push - set up main branch
            git branch -M main
            git push -u origin main
        }
        log "Push complete"
    fi
}

update_qmd_index() {
    if command -v qmd &>/dev/null; then
        log "Updating qmd index..."
        cd "$WORKSPACE_DIR"
        qmd embed 2>&1 || true
    else
        log "qmd not installed, skipping index update"
    fi
}

show_status() {
    echo ""
    echo "=== Sync Status ==="
    echo "Workspace: $WORKSPACE_DIR"
    echo "Sync repo: ${SYNC_REPO:-"(not configured)"}"
    echo "Machine ID: $MACHINE_ID"
    echo ""
    echo "Session sources:"
    [[ -d "$CLAUDE_CODE_DIR" ]] && echo "  - Claude Code: $CLAUDE_CODE_DIR" || echo "  - Claude Code: (not found)"
    [[ -d "$OPENCLAW_DIR" ]] && echo "  - OpenClaw: $OPENCLAW_DIR" || echo "  - OpenClaw: (not found)"
    [[ -d "$CODEX_DIR" ]] && echo "  - Codex CLI: $CODEX_DIR" || echo "  - Codex CLI: (not found)"
    echo ""

    if [[ -d "$WORKSPACE_DIR" ]]; then
        local segment_count
        segment_count=$(find "$WORKSPACE_DIR" -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
        echo "Total segments: $segment_count"
    fi
}

# ============================================================================
# MAIN
# ============================================================================

main() {
    local cmd="${1:-sync}"

    case "$cmd" in
        sync)
            check_dependencies
            setup_workspace
            pull_latest
            segment_sessions
            commit_and_push
            update_qmd_index
            log "Sync complete!"
            ;;
        status)
            show_status
            ;;
        pull)
            check_dependencies
            setup_workspace
            pull_latest
            update_qmd_index
            log "Pull complete!"
            ;;
        push)
            check_dependencies
            setup_workspace
            segment_sessions
            commit_and_push
            log "Push complete!"
            ;;
        help|--help|-h)
            echo "Usage: $0 [command]"
            echo ""
            echo "Commands:"
            echo "  sync    Full sync: pull, segment, commit, push (default)"
            echo "  status  Show configuration and status"
            echo "  pull    Only pull latest from remote"
            echo "  push    Only segment and push (no pull)"
            echo "  help    Show this help"
            echo ""
            echo "Environment variables:"
            echo "  SESSION_SYNC_REPO      GitHub repo (e.g., username/agent-sessions)"
            echo "  SESSION_WORKSPACE_DIR  Local workspace directory"
            echo "  SESSION_MACHINE_ID     Machine identifier for commits"
            ;;
        *)
            error "Unknown command: $cmd"
            echo "Run '$0 help' for usage"
            exit 1
            ;;
    esac
}

main "$@"
