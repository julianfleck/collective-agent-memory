#!/usr/bin/env python3
"""
CAM - Collective Agent Memory

CLI for segmenting, searching, and syncing AI agent sessions across machines.

Usage:
    cam "query"                 # Search sessions (SQLite FTS5)
    cam search "query"          # Explicit search
    cam reindex                 # Rebuild search index
    cam sync                    # Sync with remote repo
    cam index                   # Index new sessions
    cam segment <file.jsonl>    # Segment a single session
    cam status                  # Show status
    cam daemon start            # Start background watcher
    cam daemon stop             # Stop background watcher
"""

import argparse
import json
import os
import platform
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import yaml
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from cam.search import SearchIndex, SearchResult

console = Console()


# =============================================================================
# Unified Output Formatting
# =============================================================================

def format_result(result: SearchResult, show_score: bool = False, workspace_dir: Path = None) -> None:
    """Format and display a single search result with consistent structure.

    Output format:
    - Separator
    - Segment: full path
    - Date: YYYY-MM-DD HH:MM
    - Agent: agent@machine
    - Tags: #tag1 #tag2 ...
    - Entities: entity1 entity2 ...
    - Preview: snippet
    - Separator
    """
    if workspace_dir is None:
        workspace_dir = get_workspace_dir()

    # Full path
    full_path = workspace_dir / result.path

    # Date/time
    display_datetime = result.date
    if result.first_timestamp:
        try:
            dt = datetime.fromisoformat(result.first_timestamp.replace('Z', '+00:00'))
            display_datetime = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            pass

    # Agent@machine
    agent_machine = f"{result.agent}@{result.machine}" if result.machine else result.agent

    # Tags (keywords) - max 7
    tags = []
    if result.keywords:
        tags = result.keywords.split()[:7]
    tags_str = " ".join(f"#{t}" for t in tags) if tags else "-"

    # Entities - max 5 (no # prefix)
    entities = []
    if result.entities:
        entities = result.entities.split()[:5]
    entities_str = " ".join(entities) if entities else "-"

    # Snippet
    snippet = ""
    if result.snippet:
        snippet = ' '.join(result.snippet.split())[:200]

    # Print formatted output
    console.print("[dim]" + "-" * 60 + "[/dim]")
    console.print(f"[bold]Segment:[/bold] {full_path}")
    if show_score:
        console.print(f"[bold]Score:[/bold] [green]{result.score:.0f}%[/green]")
    console.print(f"[bold]Date:[/bold] {display_datetime}")
    console.print(f"[bold]Agent:[/bold] {agent_machine}")
    console.print(f"[bold]Tags:[/bold] [green]{tags_str}[/green]")
    console.print(f"[bold]Entities:[/bold] [yellow]{entities_str}[/yellow]")
    if snippet:
        console.print(f"[bold]Preview:[/bold] [italic]{snippet}[/italic]")
    console.print()


def format_results_json(results: List[SearchResult], show_score: bool = False) -> str:
    """Format results as JSON with consistent schema."""
    formatted = []
    for r in results:
        entry = {
            "path": r.path,
            "date": r.date,
            "timestamp": r.first_timestamp or "",
            "agent": r.agent,
            "machine": r.machine,
            "title": r.title,
            "keywords": r.keywords.split()[:7] if r.keywords else [],
            "entities": r.entities.split()[:5] if r.entities else [],
            "snippet": r.snippet or "",
        }
        if show_score:
            entry["score"] = r.score
        formatted.append(entry)
    return json.dumps(formatted, indent=2)


def _clean_env() -> dict:
    """Get environment dict with malloc debugging vars removed.

    macOS prints 'MallocStackLogging: can't turn off...' warnings when
    subprocess inherits malloc debugging environment variables from parent.
    """
    env = os.environ.copy()
    for key in list(env.keys()):
        if key.startswith('Malloc') or key.startswith('MallocStack'):
            del env[key]
    return env


# Version
__version__ = "0.2.0"


def get_version_string() -> str:
    """Get version string with commit hash."""
    version = __version__

    # Try to get git commit hash
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True,
            cwd=Path(__file__).parent
        )
        if result.returncode == 0:
            commit = result.stdout.strip()
            version = f"{version} ({commit})"
    except Exception:
        pass

    return version


# Environment variable prefix
ENV_PREFIX = "CAM_"

# Config file path
CONFIG_FILE = Path.home() / ".cam" / "config"


def load_config():
    """Load config file into environment variables if not already set."""
    if not CONFIG_FILE.exists():
        return
    
    try:
        with open(CONFIG_FILE) as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith("#"):
                    continue
                # Parse KEY=VALUE
                if "=" in line:
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip()
                    # Only set if not already in environment (env vars take precedence)
                    if key not in os.environ:
                        os.environ[key] = value
    except Exception:
        # Silently ignore config file errors
        pass


# Load config on import
load_config()


def get_env(name: str, default: str = "") -> str:
    """Get environment variable with CAM_ prefix."""
    return os.environ.get(f"{ENV_PREFIX}{name}", default)


def get_hostname() -> str:
    """Get machine hostname for identification."""
    return get_env("MACHINE_ID") or socket.gethostname().split('.')[0]


def get_workspace_dir() -> Path:
    """Get workspace directory for sessions."""
    env_dir = get_env("WORKSPACE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path.home() / ".cam" / "sessions"


def get_sessions_dirs() -> List[Path]:
    """Get all session source directories."""
    dirs = []

    # Claude Code
    claude_dir = Path.home() / ".claude" / "projects"
    if claude_dir.exists():
        dirs.append(claude_dir)

    # Cursor (sessions in agent-transcripts subdirs)
    cursor_dir = Path.home() / ".cursor" / "projects"
    if cursor_dir.exists():
        dirs.append(cursor_dir)

    # OpenClaw
    openclaw_dir = Path.home() / ".openclaw" / "agents" / "main" / "sessions"
    if openclaw_dir.exists():
        dirs.append(openclaw_dir)

    # Codex CLI
    codex_dir = Path.home() / ".codex" / "sessions"
    if codex_dir.exists():
        dirs.append(codex_dir)

    return dirs


def get_sync_repo() -> Optional[str]:
    """Get sync repo from environment."""
    return get_env("SYNC_REPO") or None


def find_session_files(sessions_dir: Path, include_subagents: bool = True) -> List[Path]:
    """Find all session JSONL files in the given directory."""
    if not sessions_dir.exists():
        return []

    # Check if this looks like Claude Code structure
    is_claude_code = sessions_dir.name == "projects" or any(
        (sessions_dir / d).is_dir() and list((sessions_dir / d).glob("*.jsonl"))
        for d in sessions_dir.iterdir() if d.is_dir()
    )

    if is_claude_code:
        if include_subagents:
            return sorted(sessions_dir.glob("**/*.jsonl"))
        else:
            return sorted(
                f for f in sessions_dir.glob("**/*.jsonl")
                if "subagents" not in f.parts
            )
    else:
        return sorted(sessions_dir.glob("*.jsonl"))


# =============================================================================
# Filter Parsing
# =============================================================================

def parse_time_filter(spec: str) -> timedelta:
    """Parse time filter spec like '2h', '15min', '3d', '1w' to timedelta.

    Also handles raw seconds format like '7200s' for internal use.
    """
    # Handle seconds format (internal use)
    if spec.endswith('s') and spec[:-1].isdigit():
        return timedelta(seconds=int(spec[:-1]))

    match = re.match(r'^(\d+)(min|h|d|w)$', spec)
    if not match:
        raise ValueError(f"Invalid time filter: {spec}. Use format like 2h, 15min, 3d, 1w")

    value = int(match.group(1))
    unit = match.group(2)

    if unit == 'min':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    elif unit == 'w':
        return timedelta(weeks=value)

    raise ValueError(f"Unknown time unit: {unit}")


def parse_query_filters(argv: List[str]) -> Tuple[str, Optional[str], Optional[str], Optional[timedelta], List[str]]:
    """Extract query, agent filter, machine filter, and time filter from args.

    Parses inline syntax like:
      - "query" [2h] @claude          -> agent filter
      - "query" openclaw@data         -> agent@machine filter
      - "query" --since 1d            -> time filter (alternative syntax)

    Returns: (query, agent, machine, time_delta, remaining_args)
    """
    agent = None
    machine = None
    time_delta = None
    query_parts = []
    remaining_args = []  # Flags like -n, --json, etc.

    i = 0
    while i < len(argv):
        arg = argv[i]

        # Handle --since / -t inline (for backwards compat)
        if arg in ('--since', '-t', '--time') and i + 1 < len(argv):
            try:
                time_delta = parse_time_filter(argv[i + 1])
                i += 2
                continue
            except ValueError:
                pass

        # Preserve flags for passthrough
        if arg.startswith('-'):
            # Check if it's a flag with value (e.g., -n 3)
            if i + 1 < len(argv) and not argv[i + 1].startswith('-'):
                remaining_args.extend([arg, argv[i + 1]])
                i += 2
                continue
            else:
                remaining_args.append(arg)
                i += 1
                continue

        # @agent filter (e.g., @claude)
        if arg.startswith('@'):
            agent = arg[1:]
        # agent@machine filter (e.g., openclaw@data)
        elif '@' in arg and not arg.startswith('"') and not arg.startswith("'"):
            # Check if it looks like agent@machine (no spaces, simple pattern)
            parts = arg.split('@', 1)
            if len(parts) == 2 and parts[0] and parts[1]:
                # Verify it's not an email or query with @
                if not '.' in parts[1] or parts[1].count('.') == 0:
                    agent = parts[0]
                    machine = parts[1]
                else:
                    query_parts.append(arg)
            else:
                query_parts.append(arg)
        # [2h] time filter
        elif arg.startswith('[') and arg.endswith(']'):
            try:
                time_delta = parse_time_filter(arg[1:-1])
            except ValueError:
                query_parts.append(arg)
        else:
            query_parts.append(arg)

        i += 1

    return ' '.join(query_parts), agent, machine, time_delta, remaining_args


# =============================================================================
# Commands
# =============================================================================

def _run_search(query: str, limit: int = 10, json_output: bool = False,
                files_output: bool = False, agent_filter: str = None,
                machine_filter: str = None, time_filter: timedelta = None,
                snippet_tokens: int = 15) -> int:
    """Run search using SQLite FTS5 index.

    Args:
        query: Search query
        limit: Maximum number of results
        json_output: Output as JSON
        files_output: Output file paths only
        agent_filter: Filter by agent name
        machine_filter: Filter by machine name
        time_filter: Filter to results within this timedelta
        snippet_tokens: Number of tokens in snippet (5-64)

    Returns:
        0 on success, 1 on error
    """
    workspace_dir = get_workspace_dir()
    index_path = workspace_dir.parent / "index.sqlite"

    # Check if index exists
    if not index_path.exists():
        console.print("[yellow]Search index not found. Building index...[/yellow]")
        index = SearchIndex(index_path, workspace_dir)
        count = index.rebuild(workspace_dir)
        console.print(f"[green]Indexed {count} segments[/green]")
    else:
        index = SearchIndex(index_path, workspace_dir)

    # Calculate since timestamp from time_filter
    since = None
    if time_filter:
        since = datetime.now(timezone.utc) - time_filter

    # Run search
    results = index.search(
        query=query,
        limit=limit,
        agent=agent_filter,
        machine=machine_filter,
        since=since,
        snippet_tokens=snippet_tokens,
    )

    if not results:
        console.print("[dim]No results found[/dim]")
        return 0

    # Format output
    if json_output:
        print(format_results_json(results, show_score=True))
    elif files_output:
        for r in results:
            print(r.path)
    else:
        for r in results:
            format_result(r, show_score=True)

    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Keyword search (fast)."""
    query = args.query
    time_filter = None
    agent_filter = getattr(args, 'agent', None)
    machine_filter = getattr(args, 'machine', None)

    # Check if query is actually a time filter like [15min]
    if query and query.startswith('[') and query.endswith(']'):
        try:
            time_filter = parse_time_filter(query[1:-1])
            query = None  # No actual query, just time filter
        except ValueError:
            pass  # Not a valid time filter, treat as literal query

    # Parse explicit -t time filter
    if hasattr(args, 'time') and args.time:
        try:
            time_filter = parse_time_filter(args.time)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # If no query but have time filter, list recent segments
    if not query and time_filter:
        return cmd_recent_with_filter(time_filter, agent_filter, machine_filter, args.limit or 10, args.json, args.files)

    if not query:
        print("Error: query required (or use -t for time-based listing)", file=sys.stderr)
        return 1

    return _run_search(
        query,
        limit=args.limit or 10,
        json_output=args.json,
        files_output=args.files,
        agent_filter=agent_filter,
        machine_filter=machine_filter,
        time_filter=time_filter,
        snippet_tokens=args.snippet,
    )


def cmd_recent_with_filter(
    time_filter: timedelta,
    agent_filter: Optional[str],
    machine_filter: Optional[str],
    limit: int,
    json_output: bool,
    files_output: bool
) -> int:
    """List recent segments matching time/agent/machine filter (no search query)."""
    workspace_dir = get_workspace_dir()
    index_path = workspace_dir.parent / "index.sqlite"
    now = datetime.now(timezone.utc)
    since = now - time_filter

    # Check if index exists
    if not index_path.exists():
        console.print("[yellow]Search index not found. Building index...[/yellow]")
        index = SearchIndex(index_path, workspace_dir)
        count = index.rebuild(workspace_dir)
        console.print(f"[green]Indexed {count} segments[/green]")
    else:
        index = SearchIndex(index_path, workspace_dir)

    # List recent segments
    results = index.list_recent(since=since, limit=limit, agent=agent_filter, machine=machine_filter)

    if not results:
        console.print("[dim]No segments found in time range[/dim]")
        return 0

    # Output
    if json_output:
        print(format_results_json(results, show_score=False))
    elif files_output:
        for r in results:
            print(r.path)
    else:
        for r in results:
            format_result(r, show_score=False)

    return 0


def cmd_segment(args: argparse.Namespace) -> int:
    """Segment a session JSONL file into topic sections."""
    from . import segment

    # Preload all models upfront
    segment.preload_models()

    session_file = Path(args.session_file)
    if not session_file.exists():
        print(f"Error: File not found: {session_file}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else get_workspace_dir()
    machine_id = get_hostname()

    print(f"Loading session: {session_file.name}")
    session_meta, messages = segment.load_session_messages(session_file)

    if not messages:
        print("Error: No messages found in session", file=sys.stderr)
        return 1

    print(f"Loaded {len(messages)} messages")
    print(f"Agent: {session_meta.get('agent', 'unknown')}")

    sections, similarities = segment.segment_session(
        messages,
        window_size=args.window_size,
        threshold=args.threshold,
        min_section_size=args.min_section
    )

    segment.print_sections(messages, sections)

    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Writing sections to: {output_dir}")
    written = segment.write_sections(
        messages, sections, session_meta,
        output_dir=output_dir,
        machine_id=machine_id,
        dry_run=args.dry_run
    )

    if not args.dry_run:
        console.print(f"\nWrote {len(written)} section files")

    console.print("\n[green]Segmentation complete[/green]")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Index new sessions from all sources.

    If the daemon is running, sessions are queued for background indexing
    with priority (processed before watcher-detected changes).

    If the daemon is not running, sessions are indexed directly.
    """
    from . import daemon

    output_dir = Path(args.output_dir) if args.output_dir else get_workspace_dir()
    include_subagents = not args.no_subagents
    machine_id = get_hostname()

    # Get all session directories
    if args.sessions_dir:
        sessions_dirs = [Path(args.sessions_dir)]
    else:
        sessions_dirs = get_sessions_dirs()

    if not sessions_dirs:
        print("No session directories found.", file=sys.stderr)
        return 1

    # Track processed sessions
    state_file = output_dir / ".indexed_sessions"
    indexed = set()
    if state_file.exists() and not args.force:
        indexed = set(state_file.read_text().strip().split('\n'))

    # Find all sessions across all directories
    all_sessions = []
    for sessions_dir in sessions_dirs:
        console.print(f"[dim]{sessions_dir}[/dim]")
        files = find_session_files(sessions_dir, include_subagents)
        all_sessions.extend(files)
        console.print(f"   Found {len(files)} sessions")

    # Filter to new sessions
    new_sessions = [f for f in all_sessions if str(f) not in indexed]

    if not new_sessions:
        print("\nNo new sessions to index.")
        return 0

    console.print(f"\n[bold]{len(new_sessions)} new sessions to index[/bold]")

    # Check if daemon is running
    if daemon.is_daemon_running() and not getattr(args, 'no_queue', False):
        # Queue sessions for background indexing with priority
        queued = daemon.queue_sessions_for_indexing(
            new_sessions,
            priority=True,
            force=args.force
        )
        console.print(f"[green]Queued {queued} sessions for background indexing[/green]")
        console.print("[dim]Run 'cam status' to check progress[/dim]")
        return 0

    # Daemon not running - index directly
    from . import segment

    # Preload all models upfront for better progress feedback
    segment.preload_models()

    count = 0
    errors = 0
    total = len(new_sessions)

    def save_state():
        output_dir.mkdir(parents=True, exist_ok=True)
        state_file.write_text('\n'.join(sorted(indexed)))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Indexing [0/{total}]", total=total)

        for i, session_file in enumerate(new_sessions):
            progress.update(task, description=f"Indexing [{i+1}/{total}] {session_file.name[:40]}")

            try:
                session_meta, messages = segment.load_session_messages(session_file)

                if len(messages) < 6:
                    indexed.add(str(session_file))
                    save_state()
                    progress.advance(task)
                    continue

                sections, _ = segment.segment_session(messages)
                segment.write_sections(
                    messages, sections, session_meta,
                    output_dir=output_dir,
                    machine_id=machine_id
                )

                indexed.add(str(session_file))
                count += 1
                save_state()

            except Exception as e:
                errors += 1
                indexed.add(str(session_file))
                save_state()

            progress.advance(task)

    # Summary
    if errors > 0:
        console.print(f"[green]Indexed {count} sessions[/green] [dim]({errors} errors)[/dim]")
    else:
        console.print(f"[green]Indexed {count} sessions[/green]")
    return 0


def cmd_reindex(args: argparse.Namespace) -> int:
    """Rebuild the search index from all segment files.

    This scans all existing segments in the workspace and rebuilds
    the SQLite FTS5 search index from scratch.
    """
    workspace_dir = get_workspace_dir()
    index_path = workspace_dir.parent / "index.sqlite"

    console.print(f"[bold]Rebuilding search index...[/bold]")
    console.print(f"[dim]Workspace: {workspace_dir}[/dim]")
    console.print(f"[dim]Index: {index_path}[/dim]")

    # Create fresh index
    index = SearchIndex(index_path, workspace_dir)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Scanning segments...", total=None)

        # Find all segment files
        segment_files = list(workspace_dir.rglob("*.md"))
        progress.update(task, description=f"Found {len(segment_files)} segments")

        # Clear and rebuild
        progress.update(task, description="Building index...")
        count = index.rebuild(workspace_dir)

    stats = index.get_stats()
    console.print(f"\n[green]Indexed {stats.segments} segments from {stats.sessions} sessions[/green]")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    """Sync segments with remote repository."""
    sync_repo = args.repo or get_sync_repo()
    workspace_dir = get_workspace_dir()
    machine_id = get_hostname()

    if not sync_repo:
        print("Error: No sync repo configured.", file=sys.stderr)
        print("Set CAM_SYNC_REPO or use: cam sync --repo <user/repo>", file=sys.stderr)
        return 1

    workspace_dir.mkdir(parents=True, exist_ok=True)
    os.chdir(workspace_dir)

    # Initialize git if needed
    if not (workspace_dir / ".git").exists():
        print(f"Initializing git repo...")
        subprocess.run(["git", "init"], capture_output=True, env=_clean_env())
        subprocess.run(["git", "remote", "add", "origin", f"https://github.com/{sync_repo}.git"],
                      capture_output=True, env=_clean_env())

    # Pull latest
    if not args.push_only:
        console.print(f"Pulling from {sync_repo}...")
        subprocess.run(["git", "fetch", "origin", "main"], capture_output=True, env=_clean_env())
        result = subprocess.run(["git", "merge", "origin/main", "--no-edit"],
                               capture_output=True, text=True, env=_clean_env())
        if result.returncode != 0 and "not something we can merge" not in result.stderr:
            # Might be first push, that's ok
            pass

    # Index new sessions
    if not args.pull_only:
        console.print("Indexing sessions...")
        index_args = argparse.Namespace(
            sessions_dir=None, output_dir=str(workspace_dir),
            force=False, no_subagents=False
        )
        cmd_index(index_args)

        # Commit and push
        result = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True, env=_clean_env())
        if result.stdout.strip():
            console.print(f"Pushing to {sync_repo}...")
            subprocess.run(["git", "add", "-A"], env=_clean_env())
            segment_count = len(result.stdout.strip().split('\n'))
            subprocess.run(["git", "commit", "-m", f"Add segments from {machine_id}"], env=_clean_env())
            subprocess.run(["git", "branch", "-M", "main"], capture_output=True, env=_clean_env())
            push_result = subprocess.run(["git", "push", "-u", "origin", "main"],
                                        capture_output=True, text=True, env=_clean_env())
            if push_result.returncode != 0:
                print(f"  Push failed: {push_result.stderr}", file=sys.stderr)
        else:
            print("No new segments to push")

    console.print("[green]Sync complete[/green]")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Show status of CAM."""
    from . import daemon

    workspace_dir = get_workspace_dir()
    sync_repo = get_sync_repo()
    machine_id = get_hostname()

    console.print(Panel.fit(f"Collective Agent Memory {get_version_string()}", style="bold"))
    console.print()

    # Config table
    config_table = Table(show_header=False, box=None, padding=(0, 2))
    config_table.add_column("Key", style="dim")
    config_table.add_column("Value")
    config_table.add_row("Machine ID", machine_id)
    config_table.add_row("Workspace", str(workspace_dir))
    config_table.add_row("Sync repo", sync_repo or "[dim](not configured)[/dim]")

    # Last synced (from git log)
    if sync_repo and (workspace_dir / ".git").exists():
        result = subprocess.run(
            ["git", "-C", str(workspace_dir), "log", "-1", "--format=%cr"],
            capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            config_table.add_row("Last synced", result.stdout.strip())

    console.print(config_table)
    console.print()

    # Session sources
    console.print("[bold]Session sources[/bold]")
    for d in get_sessions_dirs():
        count = len(list(d.glob("**/*.jsonl")))
        # Detect agent from path
        path_str = str(d)
        if "/.claude/" in path_str:
            agent = "Claude Code"
        elif "/.cursor/" in path_str:
            agent = "Cursor"
        elif "/.openclaw/" in path_str:
            agent = "OpenClaw"
        elif "/.codex/" in path_str:
            agent = "Codex"
        else:
            agent = d.name
        console.print(f"  {agent}: {count} files")

    if not get_sessions_dirs():
        console.print("  [dim](none found)[/dim]")

    console.print()

    # Segment count
    if workspace_dir.exists():
        segments = list(workspace_dir.glob("**/*.md"))
        console.print(f"Segments: {len(segments)}")
    else:
        console.print("Segments: 0")

    # Indexed count
    state_file = workspace_dir / ".indexed_sessions"
    if state_file.exists():
        indexed = [s for s in state_file.read_text().strip().split('\n') if s]
        console.print(f"Indexed:  {len(indexed)} sessions")

    # Search index status
    console.print()
    index_path = workspace_dir.parent / "index.sqlite"
    if index_path.exists():
        try:
            index = SearchIndex(index_path, workspace_dir)
            stats = index.get_stats()
            console.print(f"[green]\\[ok][/green] Search index: {stats.segments} segments from {stats.sessions} sessions")
        except Exception:
            console.print("[yellow]\\[..][/yellow] Search index: error reading")
    else:
        console.print("[yellow]--[/yellow] Search index not built [dim](run 'cam reindex')[/dim]")

    # Daemon and queue status
    daemon_running = daemon.is_daemon_running()
    system = platform.system()

    if daemon_running:
        if system == "Darwin":
            console.print("[green]\\[ok][/green] Daemon running (launchd)")
        else:
            console.print("[green]\\[ok][/green] Daemon running (systemd)")

        # Show queue status when daemon is running
        priority_size, normal_size = daemon.queue_size()
        total_queue = priority_size + normal_size
        if total_queue > 0:
            console.print(f"[yellow]\\[..][/yellow] Queue: {total_queue} sessions pending")
            # Show breakdown by source
            stats = daemon.queue_stats_by_source()
            for source, count in sorted(stats.items(), key=lambda x: -x[1]):
                console.print(f"         [dim]{source}: {count}[/dim]")
        else:
            console.print("[green]\\[ok][/green] Queue: empty")

        # Check watchdog status
        if daemon.is_watchdog_running():
            console.print("[green]\\[ok][/green] Watchdog active")
        else:
            console.print("[dim]\\[--][/dim] Watchdog not installed [dim](cam daemon watchdog)[/dim]")
    else:
        console.print("[yellow]--[/yellow] Daemon not running")

    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    """Manage the CAM daemon."""
    from . import daemon

    if args.daemon_cmd == "start":
        sync_repo = get_sync_repo()
        workspace_dir = str(get_workspace_dir())
        machine_id = get_hostname()

        if not sync_repo:
            print("Error: CAM_SYNC_REPO not set", file=sys.stderr)
            return 1

        return 0 if daemon.install_service(sync_repo, workspace_dir, machine_id) else 1

    elif args.daemon_cmd == "stop":
        return 0 if daemon.uninstall_service() else 1

    elif args.daemon_cmd == "run":
        # Run in foreground (used by service)
        # Pass environment variables to run_daemon
        sync_repo = get_sync_repo()
        workspace_dir = str(get_workspace_dir())
        daemon.run_daemon(
            sync_repo=sync_repo,
            workspace_dir=workspace_dir,
            foreground=True
        )
        return 0

    elif args.daemon_cmd == "clean":
        # Clean already-indexed sessions from queue
        cleaned = daemon.queue_clean()
        if cleaned > 0:
            console.print(f"[green]Cleaned {cleaned} already-indexed sessions from queue[/green]")
        else:
            console.print("[dim]Queue already clean[/dim]")
        priority, normal = daemon.queue_size()
        console.print(f"[dim]Queue: {priority + normal} sessions pending ({priority} priority, {normal} normal)[/dim]")
        return 0

    elif args.daemon_cmd == "watchdog":
        # Install/manage watchdog
        if daemon.is_watchdog_running():
            console.print("[green]Watchdog is running[/green]")
            console.print("[dim]To uninstall: cam daemon watchdog-stop[/dim]")
        else:
            console.print("Installing watchdog...")
            if daemon.install_watchdog():
                console.print("[green]Watchdog installed (runs every 5 min)[/green]")
                return 0
            return 1
        return 0

    elif args.daemon_cmd == "watchdog-stop":
        return 0 if daemon.uninstall_watchdog() else 1

    else:
        print("Usage: cam daemon <start|stop|run|clean|watchdog|watchdog-stop>")
        return 1


def cmd_skill(args: argparse.Namespace) -> int:
    """Install CAM skill to agent skills directory."""
    # Find SKILL.md - first check package directory, then repo root
    package_dir = Path(__file__).parent
    skill_file = package_dir / "SKILL.md"

    if not skill_file.exists():
        # Try repo root (development mode)
        repo_root = package_dir.parent.parent
        skill_file = repo_root / "SKILL.md"

    if not skill_file.exists():
        print("Error: SKILL.md not found", file=sys.stderr)
        return 1

    # Determine target based on agent type
    agent = args.agent or "claude"

    if agent == "claude":
        target_dir = Path.home() / ".claude" / "skills" / "cam"
    elif agent == "cursor":
        target_dir = Path.home() / ".cursor" / "skills" / "cam"
    elif agent == "openclaw":
        target_dir = Path.home() / ".openclaw" / "skills" / "cam"
    elif agent == "codex":
        target_dir = Path.home() / ".codex" / "skills" / "cam"
    else:
        print(f"Unknown agent: {agent}", file=sys.stderr)
        return 1

    target_dir.mkdir(parents=True, exist_ok=True)
    dest_file = target_dir / "SKILL.md"

    # Copy skill file
    shutil.copy(skill_file, dest_file)

    console.print(f"[green]\\[ok][/green] Skill installed: {dest_file}")

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Interactive CAM setup."""
    from . import init
    init.run_init(non_interactive=getattr(args, 'yes', False))
    return 0


def cmd_recent(args: argparse.Namespace) -> int:
    """List recent session segments by timestamp."""
    workspace_dir = get_workspace_dir()
    index_path = workspace_dir.parent / "index.sqlite"

    # Check if index exists
    if not index_path.exists():
        console.print("[yellow]Search index not found. Building index...[/yellow]")
        index = SearchIndex(index_path, workspace_dir)
        count = index.rebuild(workspace_dir)
        console.print(f"[green]Indexed {count} segments[/green]")
    else:
        index = SearchIndex(index_path, workspace_dir)

    # Parse time filter
    time_filter = None
    if hasattr(args, 'time') and args.time:
        try:
            time_filter = parse_time_filter(args.time)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1

    # Default to 24h if no time specified
    if not time_filter:
        time_filter = timedelta(hours=24)

    now = datetime.now(timezone.utc)
    since = now - time_filter

    # Get limit
    limit = getattr(args, 'limit', None) or 20

    # List recent segments
    results = index.list_recent(
        since=since,
        limit=limit,
        agent=getattr(args, 'agent', None),
        machine=getattr(args, 'machine', None),
    )

    if not results:
        time_str = args.time if hasattr(args, 'time') and args.time else "24h"
        console.print(f"[dim]No session segments found in the last {time_str}[/dim]")
        return 0

    # Output format
    if getattr(args, 'json', False):
        print(format_results_json(results, show_score=False))
    elif getattr(args, 'files', False):
        for r in results:
            print(r.path)
    else:
        for r in results:
            format_result(r, show_score=False)

    return 0


def cmd_get(args: argparse.Namespace) -> int:
    """Retrieve a session segment file by path."""
    workspace_dir = get_workspace_dir()
    segment_path = args.path

    # Remove leading slash if present
    segment_path = segment_path.lstrip('/')

    # Build full path
    full_path = workspace_dir / segment_path

    if not full_path.exists():
        print(f"Error: Session segment not found: {segment_path}", file=sys.stderr)
        return 1

    if not full_path.is_file():
        print(f"Error: Not a file: {segment_path}", file=sys.stderr)
        return 1

    # Read and output the file
    content = full_path.read_text()

    if getattr(args, 'meta', False):
        # Output only frontmatter as JSON
        if content.startswith("---"):
            end = content.find("---", 3)
            if end > 0:
                frontmatter = yaml.safe_load(content[3:end])
                print(json.dumps(frontmatter, indent=2, default=str))
                return 0
        print("{}")
        return 0

    # Output full content
    print(content)
    return 0


def cmd_entity(args: argparse.Namespace) -> int:
    """Search session segments by entity name."""
    workspace_dir = get_workspace_dir()
    index_path = workspace_dir.parent / "index.sqlite"
    entity_name = args.entity
    limit = args.limit or 10

    # Check if index exists
    if not index_path.exists():
        console.print("[yellow]Search index not found. Building index...[/yellow]")
        index = SearchIndex(index_path, workspace_dir)
        count = index.rebuild(workspace_dir)
        console.print(f"[green]Indexed {count} segments[/green]")
    else:
        index = SearchIndex(index_path, workspace_dir)

    # Search by entity
    results = index.search_entities(
        entity_name=entity_name,
        limit=limit,
        agent=getattr(args, 'agent', None),
        machine=getattr(args, 'machine', None),
    )

    if not results:
        console.print(f"[dim]No segments found with entity matching '{entity_name}'[/dim]")
        return 0

    # Output format
    if args.json:
        print(format_results_json(results, show_score=False))
    elif args.files:
        for r in results:
            print(r.path)
    else:
        for r in results:
            format_result(r, show_score=False)

    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    """View CAM daemon logs."""
    import platform

    follow = getattr(args, 'follow', False)
    lines = getattr(args, 'lines', 50)

    system = platform.system()

    if system == "Darwin":
        # macOS: logs are in ~/Library/Logs/
        log_file = Path.home() / "Library" / "Logs" / "cam.error.log"
        if not log_file.exists():
            log_file = Path.home() / "Library" / "Logs" / "cam.log"

        if not log_file.exists():
            console.print("[yellow]No log files found[/yellow]")
            console.print("[dim]Start the daemon with: cam daemon start[/dim]")
            return 1

        if follow:
            # tail -f
            os.execvp("tail", ["tail", "-f", str(log_file)])
        else:
            # tail -n
            subprocess.run(["tail", "-n", str(lines), str(log_file)])

    elif system == "Linux":
        # Linux: use journalctl
        cmd = ["journalctl", "--user", "-u", "cam"]
        if follow:
            cmd.append("-f")
        else:
            cmd.extend(["-n", str(lines)])
        os.execvp("journalctl", cmd)

    else:
        console.print(f"[yellow]Unsupported platform: {system}[/yellow]")
        return 1

    return 0


def cmd_update(args: argparse.Namespace) -> int:
    """Update CAM to the latest version from GitHub."""
    import shutil
    from datetime import datetime, timezone

    REPO = "julianfleck/collective-agent-memory"
    force = getattr(args, 'force', False)

    console.print("[bold]Checking for updates...[/bold]")

    # Get local commit hash
    local_commit = None
    local_commit_time = None
    try:
        # Get the source directory of this package
        src_dir = Path(__file__).parent
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=src_dir
        )
        if result.returncode == 0:
            local_commit = result.stdout.strip()
            # Get commit timestamp
            result = subprocess.run(
                ["git", "log", "-1", "--format=%ct"],
                capture_output=True, text=True, cwd=src_dir
            )
            if result.returncode == 0:
                local_commit_time = datetime.fromtimestamp(int(result.stdout.strip()), tz=timezone.utc)
    except Exception:
        pass

    # Get remote commit info via GitHub API
    remote_commit = None
    remote_commit_time = None
    try:
        import urllib.request
        import json

        url = f"https://api.github.com/repos/{REPO}/commits/main"
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode())
            remote_commit = data["sha"]
            # Parse ISO timestamp
            commit_date = data["commit"]["committer"]["date"]
            remote_commit_time = datetime.fromisoformat(commit_date.replace("Z", "+00:00"))
    except Exception as e:
        console.print(f"[red]Failed to check remote version: {e}[/red]")
        if not force:
            return 1
        console.print("[yellow]Forcing update anyway...[/yellow]")

    # Compare versions
    if local_commit and remote_commit:
        local_short = local_commit[:7]
        remote_short = remote_commit[:7]

        if local_commit == remote_commit:
            console.print(f"[green]Already up to date[/green] ({local_short})")
            if not force:
                return 0
            console.print("[yellow]Forcing reinstall...[/yellow]")
        else:
            console.print(f"  Local:  {local_short}", end="")
            if local_commit_time:
                console.print(f" ({local_commit_time.strftime('%Y-%m-%d %H:%M')})")
            else:
                console.print()

            console.print(f"  Remote: {remote_short}", end="")
            if remote_commit_time:
                console.print(f" ({remote_commit_time.strftime('%Y-%m-%d %H:%M')})")
            else:
                console.print()

            # Check if remote is newer
            if local_commit_time and remote_commit_time:
                if remote_commit_time <= local_commit_time and not force:
                    console.print("[green]Local version is up to date or newer[/green]")
                    return 0
    elif not force:
        console.print("[yellow]Could not determine local version[/yellow]")

    # Perform update
    console.print()
    console.print("[bold]Updating CAM...[/bold]")

    install_url = f"git+https://github.com/{REPO}.git"

    if shutil.which("uv"):
        cmd = ["uv", "tool", "install", "--force", install_url]
    elif shutil.which("pipx"):
        cmd = ["pipx", "install", "--force", install_url]
    else:
        cmd = ["pip3", "install", "--user", "--force-reinstall", install_url]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            console.print(f"[red]Update failed:[/red]")
            console.print(result.stderr)
            return 1

        console.print("[green]Update complete![/green]")
        console.print("[dim]Run 'cam daemon stop && cam daemon start' to restart the daemon[/dim]")
        return 0
    except Exception as e:
        console.print(f"[red]Update failed: {e}[/red]")
        return 1


# =============================================================================
# Main
# =============================================================================

def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    version_str = get_version_string()

    help_text = f"""\
Collective Agent Memory {version_str}

Search:
  cam "query"              Search with weighted ranking (default)
  cam "query" [2h]         Search with time filter
  cam @claude "query"      Search specific agent
  cam openclaw@data "q"    Filter by agent@machine
  cam search "query"       Keyword search (explicit)
  cam entity "name"        Search by entity (tools, files, concepts)

Browse:
  cam recent               List session segments from last 24h
  cam [15min]              List session segments from last 15 minutes
  cam get <path>           Retrieve a session segment file

Manage:
  cam status               Show indexed sessions, sync status
  cam index                Index new sessions
  cam sync                 Sync with GitHub repo

Setup:
  cam init                 Interactive setup
  cam daemon <cmd>         Manage background daemon (start|stop|clean)
  cam skill install        Install /cam skill to agent
  cam logs                 View daemon logs
  cam update               Update CAM to latest version

Filters: -t/--since TIME (15min, 2h, 3d, 1w), -a AGENT, -m MACHINE
Output:  -n NUM (result count), --json, --files
"""

    parser = argparse.ArgumentParser(
        prog="cam",
        description=help_text,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"cam {version_str}")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")

    # Search commands
    def add_search_args(p):
        p.add_argument("query", nargs='?', default=None, help="Search query (optional with -t)")
        p.add_argument("-c", "--collection", default="sessions")
        p.add_argument("-n", "--limit", type=int, help="Number of results")
        p.add_argument("--json", action="store_true", help="JSON output")
        p.add_argument("--files", action="store_true", help="File paths only")
        p.add_argument("-t", "--time", help="Time filter (e.g., 2h, 15min, 3d, 1w)")
        p.add_argument("-a", "--agent", help="Agent filter (e.g., claude, openclaw)")
        p.add_argument("-m", "--machine", help="Machine filter (e.g., wintermute, data)")
        p.add_argument("-s", "--snippet", type=int, default=15,
                       help="Snippet length in tokens (5-64, default: 15)")

    p_search = subparsers.add_parser("search", help="Keyword search")
    add_search_args(p_search)

    p_entity = subparsers.add_parser("entity", help="Search by entity")
    p_entity.add_argument("entity", help="Entity name to search for")
    p_entity.add_argument("-n", "--limit", type=int, default=10, help="Number of results")
    p_entity.add_argument("-a", "--agent", help="Agent filter (e.g., claude, openclaw)")
    p_entity.add_argument("-m", "--machine", help="Machine filter (e.g., wintermute, data)")
    p_entity.add_argument("--json", action="store_true", help="JSON output")
    p_entity.add_argument("--files", action="store_true", help="File paths only")

    p_recent = subparsers.add_parser("recent", help="List recent segments")
    p_recent.add_argument("-t", "--time", default="24h", help="Time window (e.g., 15min, 2h, 3d)")
    p_recent.add_argument("-a", "--agent", help="Agent filter (e.g., claude, openclaw)")
    p_recent.add_argument("-m", "--machine", help="Machine filter (e.g., wintermute, data)")
    p_recent.add_argument("-n", "--limit", type=int, default=20, help="Number of results")
    p_recent.add_argument("--json", action="store_true", help="JSON output")
    p_recent.add_argument("--files", action="store_true", help="File paths only")

    p_get = subparsers.add_parser("get", help="Retrieve segment by path")
    p_get.add_argument("path", help="Session segment path (e.g., claude@wintermute/2026-03-15/01-file.md)")
    p_get.add_argument("--meta", action="store_true", help="Output only frontmatter as JSON")

    # Management commands
    p_index = subparsers.add_parser("index", help="Index new sessions")
    p_index.add_argument("-s", "--sessions-dir")
    p_index.add_argument("-o", "--output-dir")
    p_index.add_argument("-f", "--force", action="store_true")
    p_index.add_argument("--no-subagents", action="store_true")
    p_index.add_argument("--no-queue", action="store_true",
                         help="Index directly instead of queuing")

    subparsers.add_parser("reindex", help="Rebuild search index from segments")

    p_sync = subparsers.add_parser("sync", help="Sync with GitHub repo")
    p_sync.add_argument("-r", "--repo", help="GitHub repo (user/repo)")
    p_sync.add_argument("--pull-only", action="store_true")
    p_sync.add_argument("--push-only", action="store_true")

    subparsers.add_parser("status", help="Show status")

    # Setup commands
    p_init = subparsers.add_parser("init", help="Interactive setup")
    p_init.add_argument("-y", "--yes", action="store_true", help="Non-interactive mode")

    p_daemon = subparsers.add_parser("daemon", help="Manage daemon")
    p_daemon.add_argument("daemon_cmd", choices=["start", "stop", "run", "clean", "watchdog", "watchdog-stop"])

    p_skill = subparsers.add_parser("skill", help="Install skill")
    p_skill.add_argument("skill_cmd", choices=["install"], help="Skill command")
    p_skill.add_argument("-a", "--agent", choices=["claude", "cursor", "openclaw", "codex"],
                         default="claude", help="Agent type (default: claude)")

    p_logs = subparsers.add_parser("logs", help="View daemon logs")
    p_logs.add_argument("-f", "--follow", action="store_true", help="Follow log output")
    p_logs.add_argument("-n", "--lines", type=int, default=50, help="Number of lines")

    p_update = subparsers.add_parser("update", help="Update CAM to latest version")
    p_update.add_argument("-f", "--force", action="store_true", help="Force update even if up to date")

    # Internal command (not shown in grouped help above)
    p_segment = subparsers.add_parser("segment", help="Segment a session file")
    p_segment.add_argument("session_file")
    p_segment.add_argument("-o", "--output-dir")
    p_segment.add_argument("-w", "--window-size", type=int, default=3)
    p_segment.add_argument("-t", "--threshold", type=float, default=0.70)
    p_segment.add_argument("-m", "--min-section", type=int, default=3)
    p_segment.add_argument("-n", "--dry-run", action="store_true")

    # Parse
    if argv is None:
        argv = sys.argv[1:]

    # Handle bare search query with inline filters
    # e.g., cam "query" [2h] @claude or cam [15min] or cam -t 30min
    known_cmds = {"search", "segment", "index", "reindex", "sync", "status", "daemon", "skill", "init", "logs", "update", "entity", "recent", "get"}

    # Handle cam -t TIME (shorthand for cam recent -t TIME)
    if argv and argv[0] in ("-t", "--time") and len(argv) >= 2:
        new_argv = ["recent", "-t", argv[1]] + argv[2:]
        argv = new_argv

    elif argv and argv[0] not in known_cmds and not argv[0].startswith("-"):
        # Parse inline filters from bare query
        query, agent, machine, time_delta, remaining_args = parse_query_filters(argv)

        # If no query but have time filter, use recent command
        if not query and time_delta:
            new_argv = ["recent"]
            total_secs = int(time_delta.total_seconds())
            new_argv.extend(["--time", f"{total_secs}s"])
            if agent:
                new_argv.extend(["--agent", agent])
            if machine:
                new_argv.extend(["--machine", machine])
            new_argv.extend(remaining_args)  # Pass through flags like -n, --json
            argv = new_argv
        else:
            # Rebuild argv with parsed filters as proper arguments for search
            new_argv = ["search"]
            if query:
                new_argv.append(query)
            else:
                new_argv.append("")  # Empty query if only filters provided
            if agent:
                new_argv.extend(["--agent", agent])
            if machine:
                new_argv.extend(["--machine", machine])
            if time_delta:
                total_secs = int(time_delta.total_seconds())
                new_argv.extend(["--time", f"{total_secs}s"])
            new_argv.extend(remaining_args)  # Pass through flags like -n, --json
            argv = new_argv

    args = parser.parse_args(argv)

    # Dispatch
    if args.command == "search":
        return cmd_search(args)
    elif args.command == "segment":
        return cmd_segment(args)
    elif args.command == "index":
        return cmd_index(args)
    elif args.command == "reindex":
        return cmd_reindex(args)
    elif args.command == "sync":
        return cmd_sync(args)
    elif args.command == "status":
        return cmd_status(args)
    elif args.command == "daemon":
        return cmd_daemon(args)
    elif args.command == "skill":
        return cmd_skill(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "logs":
        return cmd_logs(args)
    elif args.command == "update":
        return cmd_update(args)
    elif args.command == "entity":
        return cmd_entity(args)
    elif args.command == "recent":
        return cmd_recent(args)
    elif args.command == "get":
        return cmd_get(args)
    else:
        parser.print_help()
        return 0


def app():
    """Entry point for console script."""
    sys.exit(main())


if __name__ == "__main__":
    app()
