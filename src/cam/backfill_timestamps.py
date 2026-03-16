#!/usr/bin/env python3
"""
Backfill timestamps for segment files that are missing them.

This script finds segment markdown files where messages lack timestamps,
reads the source session file's mtime, and rewrites the segment with
estimated timestamps.
"""

import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple
import yaml


def parse_frontmatter(content: str) -> Tuple[dict, str]:
    """Parse YAML frontmatter from markdown content."""
    if not content.startswith('---'):
        return {}, content

    # Find end of frontmatter
    end_match = re.search(r'\n---\n', content[3:])
    if not end_match:
        return {}, content

    frontmatter_end = end_match.start() + 3
    frontmatter_yaml = content[4:frontmatter_end]
    body = content[frontmatter_end + 5:]  # Skip \n---\n

    try:
        frontmatter = yaml.safe_load(frontmatter_yaml)
        return frontmatter or {}, body
    except yaml.YAMLError:
        return {}, content


def needs_timestamp_backfill(content: str) -> bool:
    """Check if segment file needs timestamp backfill."""
    frontmatter, body = parse_frontmatter(content)

    # Check if frontmatter timestamps are missing
    if not frontmatter.get('first_timestamp') or not frontmatter.get('last_timestamp'):
        return True

    # Check if any message is missing timestamp (format: **User** _timestamp_)
    # Messages without timestamps just have **User** or **Assistant** without italic
    message_pattern = r'\*\*(User|Assistant)\*\*(?!\s+_)'
    if re.search(message_pattern, body):
        return True

    return False


def get_source_mtime(source_path: str) -> Optional[datetime]:
    """Get modification time of source session file."""
    try:
        path = Path(source_path).expanduser()
        if path.exists():
            return datetime.fromtimestamp(path.stat().st_mtime)
    except (OSError, ValueError):
        pass
    return None


def count_messages(body: str) -> int:
    """Count messages in segment body."""
    return len(re.findall(r'\*\*(User|Assistant)\*\*', body))


def backfill_segment(segment_path: Path, dry_run: bool = False) -> bool:
    """Backfill timestamps in a segment file.

    Returns True if file was modified (or would be in dry_run).
    """
    content = segment_path.read_text()

    if not needs_timestamp_backfill(content):
        return False

    frontmatter, body = parse_frontmatter(content)
    source_path = frontmatter.get('source', '')

    if not source_path:
        print(f"  [skip] No source path: {segment_path.name}")
        return False

    mtime = get_source_mtime(source_path)
    if not mtime:
        print(f"  [skip] Source not found: {segment_path.name}")
        return False

    # Count messages and generate timestamps
    msg_count = count_messages(body)
    if msg_count == 0:
        return False

    # Generate timestamps for each message (spread backwards from mtime)
    timestamps = []
    for i in range(msg_count):
        offset_minutes = (msg_count - 1 - i) * 2  # 2 min per message
        msg_time = mtime - timedelta(minutes=offset_minutes)
        timestamps.append(msg_time)

    # Update frontmatter timestamps
    first_ts = timestamps[0].isoformat() if timestamps else ''
    last_ts = timestamps[-1].isoformat() if timestamps else ''

    # Rebuild body with timestamps
    def add_timestamp(match):
        nonlocal timestamps
        if not timestamps:
            return match.group(0)
        ts = timestamps.pop(0)
        ts_str = ts.strftime("%Y-%m-%d %H:%M:%S")
        role = match.group(1)
        return f"**{role}** _{ts_str}_"

    # Reset timestamps list for replacement
    timestamps = []
    for i in range(msg_count):
        offset_minutes = (msg_count - 1 - i) * 2
        msg_time = mtime - timedelta(minutes=offset_minutes)
        timestamps.append(msg_time)

    new_body = re.sub(r'\*\*(User|Assistant)\*\*(?:\s+_[^_]+_)?', add_timestamp, body)

    # Rebuild frontmatter
    frontmatter['first_timestamp'] = first_ts
    frontmatter['last_timestamp'] = last_ts

    # Format frontmatter YAML manually to preserve order
    new_content = "---\n"
    for key in ['session_id', 'date', 'agent', 'machine', 'source', 'section_index',
                'message_range', 'message_count', 'title']:
        if key in frontmatter:
            value = frontmatter[key]
            if key == 'title':
                new_content += f'{key}: "{value}"\n'
            elif isinstance(value, list):
                new_content += f'{key}: {value}\n'
            else:
                new_content += f'{key}: {value}\n'

    # Add keywords
    if frontmatter.get('keywords'):
        new_content += "keywords:\n"
        for kw in frontmatter['keywords']:
            new_content += f"  - {kw}\n"

    # Add entities
    if frontmatter.get('entities'):
        new_content += "entities:\n"
        for etype, elist in sorted(frontmatter['entities'].items()):
            if elist:
                new_content += f"  {etype}:\n"
                for e in elist:
                    new_content += f"    - {e}\n"

    new_content += f"first_timestamp: {first_ts}\n"
    new_content += f"last_timestamp: {last_ts}\n"
    new_content += "---\n"
    new_content += new_body

    if dry_run:
        print(f"  [would fix] {segment_path.name} ({msg_count} messages)")
    else:
        segment_path.write_text(new_content)
        print(f"  [fixed] {segment_path.name} ({msg_count} messages)")

    return True


def backfill_workspace(workspace_dir: Path, dry_run: bool = False) -> int:
    """Backfill timestamps for all segments in workspace.

    Returns number of files fixed.
    """
    if not workspace_dir.exists():
        print(f"Workspace not found: {workspace_dir}")
        return 0

    fixed = 0
    total = 0

    for agent_dir in workspace_dir.iterdir():
        if not agent_dir.is_dir() or agent_dir.name.startswith('.'):
            continue

        print(f"\n{agent_dir.name}:")

        for date_dir in sorted(agent_dir.iterdir()):
            if not date_dir.is_dir():
                continue

            for segment_file in sorted(date_dir.glob("*.md")):
                total += 1
                if backfill_segment(segment_file, dry_run):
                    fixed += 1

    return fixed


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description='Backfill timestamps for segment files missing them'
    )
    parser.add_argument(
        '--workspace', '-w',
        type=Path,
        default=Path.home() / '.cam' / 'sessions',
        help='Workspace directory (default: ~/.cam/sessions)'
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Show what would be fixed without making changes'
    )
    parser.add_argument(
        '--file', '-f',
        type=Path,
        help='Fix a single segment file'
    )

    args = parser.parse_args()

    if args.file:
        if backfill_segment(args.file, args.dry_run):
            print("Fixed 1 file" if not args.dry_run else "Would fix 1 file")
        else:
            print("No changes needed")
    else:
        print(f"Scanning workspace: {args.workspace}")
        if args.dry_run:
            print("(dry run - no changes will be made)\n")

        fixed = backfill_workspace(args.workspace, args.dry_run)

        print(f"\n{'Would fix' if args.dry_run else 'Fixed'} {fixed} files")


if __name__ == "__main__":
    main()
