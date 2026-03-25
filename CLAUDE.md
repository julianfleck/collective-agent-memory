# CAM - Collective Agent Memory

Search previous Claude Code / OpenClaw / Cursor / Codex sessions for work, decisions, or code patterns.

## Commands

```sh
cam "query"                    # Search with keyword expansion (default)
cam context                    # Assemble context from last session
cam context "query"            # Search + compile context from matches
cam context <path>             # Context from specific topic
cam search "query"             # Explicit search command
cam query "question"           # Ask a question, get synthesized answer
cam entity "docker"            # Search by entity name
cam get <path>                 # Get topic content
cam recent                     # List recent topics
cam status                     # Show index status
cam reindex                    # Rebuild search index
```

## Search Options

```sh
-n <num>        # Number of results (default: 10)
-t <time>       # Time filter: 15min, 2h, 3d, 1w
-a <agent>      # Agent filter: claude, openclaw, cursor, codex
--fast          # Skip query expansion
--json          # JSON output for scripts
--files         # File paths only
```

## Examples

```sh
# Continue last session (context recovery)
cam context

# Continue where we worked on auth
cam context "authentication"

# Find previous authentication work
cam "authentication flow"

# Recent work only
cam "API" -t 2h

# Agent-specific search
cam "error handling" -a claude

# Ask a question
cam query "how did we implement rate limiting?"

# JSON for scripts
cam "database" --json
cam context --json              # Context as JSON for agents
```

## Reading Results

```sh
# Get topic by path
cam get claude@wintermute/2026-03-15/03-api-design.md

# Or read directly
cat ~/.cam/sessions/claude@wintermute/2026-03-15/03-api-design.md
```

## Topic Output Structure

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

Each topic contains YAML frontmatter (session_id, date, keywords, entities) and formatted messages.

## Dependencies

- Python 3.10+
- sentence-transformers — for topic segmentation
- KeyBERT — for keyword extraction
- GLiNER2 — for entity extraction
- SQLite FTS5 — for search (built into Python)
