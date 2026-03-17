---
name: cam
description: Search previous Claude Code / Cursor / OpenClaw / Codex sessions for specific work, decisions, or code patterns. Collective Agent Memory - segments sessions into topics and syncs across machines.
---

# CAM - Collective Agent Memory

Search past sessions to find previous work, decisions, code patterns, or context.

## Search Commands

```bash
# Quick search (hybrid with reranking - best quality)
cam "authentication flow"
cam "error handling" -t 2h             # with time filter
cam "API design" -n 20                 # more results

# Keyword search (fast, uses qmd)
cam search "authentication flow" -t 1d

# Semantic search (vector similarity)
cam vsearch "how to handle user login" -t 3d

# Hybrid search with reranking (explicit)
cam query "error handling patterns" -t 2h

# Entity search (find by tool, file, concept)
cam entity "docker"                    # sessions using Docker
cam entity "config.json"               # sessions with config.json

# Browse recent (no search query)
cam -t 1h                              # last hour's segments
cam -t 30min                           # last 30 minutes
cam recent                             # last 24 hours
```

## Filters

```bash
# Time filter (-t)
cam "auth" -t 15min                    # last 15 minutes
cam "auth" -t 2h                       # last 2 hours
cam "auth" -t 3d                       # last 3 days
cam "auth" -t 1w                       # last week

# Agent filter (-a)
cam "error" -a claude                  # Claude sessions only
cam "error" -a cursor                  # Cursor sessions only

# Combined
cam "error handling" -t 2h -a claude -n 20

# Output formats
cam "database" --json                  # JSON output
cam "database" --files                 # file paths only
```

## Other Commands

```bash
cam status              # Show status (indexed sessions, segments)
cam index               # Index new local sessions
cam sync                # Sync with remote repo (if configured)
cam logs -f             # Follow daemon logs
cam update              # Update CAM to latest version
```

## Search Options

| Option | Description |
|--------|-------------|
| `-t TIME` | Time filter: `15min`, `2h`, `3d`, `1w` |
| `-a AGENT` | Agent filter: `claude`, `cursor`, `openclaw` |
| `-n N` | Number of results (default: 10) |
| `--json` | JSON output for scripting |
| `--files` | File paths only |

## JSON Output

```bash
cam search "api" -t 1d --json
```

Returns:
```json
[
  {
    "path": "claude@wintermute/2026-03-16/03-api-design.md",
    "date": "2026-03-16",
    "timestamp": "2026-03-16T14:30:00+00:00",
    "agent": "claude",
    "machine": "wintermute",
    "title": "Section 3: Api Design",
    "score": 0.85
  }
]
```

## Reading Results

After searching, read the full segment:

```bash
# Get segment content
cam get claude@laptop/2026-03-15/03-api-design.md

# Get only metadata as JSON
cam get claude@laptop/2026-03-15/03-api-design.md --meta

# Or read directly
cat ~/.cam/sessions/claude@laptop/2026-03-15/03-api-design.md
```

## Session Structure

Sessions are organized by agent and machine:

```
~/.cam/sessions/
  claude@laptop/
    2026-03-15/
      01-authentication-flow.md
      02-database-schema.md
  openclaw@server/
    2026-03-15/
      01-api-design.md
```

Each file includes provenance (agent, machine, source path) in YAML frontmatter.

## When to Use

- **Find past work**: "Did I implement X before?"
- **Recover decisions**: "What was the decision on Y?" → `cam entity "decision"`
- **Find by tool/file**: "When did we use Docker?" → `cam entity "docker"`
- **Code patterns**: "How did I solve Z?"
- **Research history**: "What did we discuss about W?"

## Environment Variables

If sync is enabled, these are set:

| Variable | Description |
|----------|-------------|
| `CAM_SYNC_REPO` | GitHub repo for sync |
| `CAM_WORKSPACE_DIR` | Segment storage (~/.cam/sessions) |
| `CAM_MACHINE_ID` | Machine identifier |
