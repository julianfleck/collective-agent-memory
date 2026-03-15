---
name: cam
description: Search previous Claude Code / Cursor / OpenClaw / Codex sessions for specific work, decisions, or code patterns. Collective Agent Memory - segments sessions into topics and syncs across machines.
---

# CAM - Collective Agent Memory

Search past sessions to find previous work, decisions, code patterns, or context.

## Search Commands

```bash
# Keyword search (fast)
cam search "authentication flow"
cam "authentication flow"              # shorthand

# Semantic search (vector similarity)
cam vsearch "how to handle user login"

# Hybrid search with reranking (best quality)
cam query "error handling patterns"

# Entity search (find by tool, file, decision, etc.)
cam entity "docker"                    # sessions using Docker
cam entity "config.json"               # sessions with config.json
cam entity "use Redis"                 # find decisions about Redis

# Time filtering
cam "authentication" "[2h]"            # last 2 hours
cam "database" "[15min]"               # last 15 minutes
cam "API design" "[3d]"                # last 3 days
cam "setup" "[1w]"                     # last week

# Agent filtering
cam "@claude" "authentication"         # Claude sessions only
cam "@openclaw" "error handling"       # OpenClaw sessions only

# Combined filters
cam "@claude" "error" "[2h]"           # Claude errors in last 2 hours

# Explicit syntax (equivalent)
cam search "auth" -t 2h -a claude

# Options
cam search "API design" -n 20          # more results
cam query "database schema" --json     # JSON output
```

## Other Commands

```bash
cam status              # Show status (indexed sessions, segments)
cam sync                # Sync with remote repo (if configured)
cam index               # Index new local sessions
cam logs                # View daemon logs
cam logs -f             # Follow daemon logs
```

## Search Options

| Option | Description |
|--------|-------------|
| `-n N` | Return N results (default: 10) |
| `-t TIME` | Time filter (2h, 15min, 3d, 1w) |
| `-a AGENT` | Agent filter (claude, openclaw, etc.) |
| `--json` | JSON output |
| `--files` | File list output |

### Inline Filter Syntax

Time and agent filters can also be specified inline:
- `[2h]` `[15min]` `[3d]` `[1w]` - Time filters
- `@claude` `@openclaw` - Agent filters

## Reading Results

After searching, read the full segment:

```bash
# Via qmd
qmd get "sessions/claude@laptop/2026-03-15/03-api-design.md" --full

# Or directly
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
