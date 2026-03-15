# Session Search

Search previous Claude Code / OpenClaw sessions for work, decisions, or code patterns.

## Commands

```sh
session-search "query"              # Keyword search (default)
session-search -v "query"           # Semantic search
session-search -q "query"           # Hybrid search with reranking (best)
session-search segment <file.jsonl> # Segment a session file
session-search index                # Index new sessions
session-search status               # Show index status
session-search install-service      # Install systemd timer
session-search skill install        # Install skill to ~/.claude/skills/
session-search skill install --openclaw  # Install skill to ~/.openclaw/skills/
```

## Search Options

```sh
-n <num>        # Number of results (default: 10)
-c <collection> # Collection name (default: sessions)
-v              # Semantic search (vector similarity)
-q              # Hybrid search with reranking
--json          # JSON output for scripts
--files         # File list output
```

## Examples

```sh
# Find previous authentication work
session-search "authentication flow"

# Semantic search for concepts
session-search -v "how to handle rate limiting"

# Best quality search
session-search -q "database schema design decisions"

# More results
session-search "API" -n 20

# JSON for scripts
session-search "error handling" --json
```

## Reading Results

```sh
# Get full section via qmd
qmd get "sessions/2026-03-13/03-setup-work.md" --full

# Or read directly  
cat ~/.openclaw/workspace/sessions/2026-03-13/03-setup-work.md
```

## Setup

```sh
# Install
curl -fsSL https://raw.githubusercontent.com/julianfleck/session-search/main/install.sh | bash

# Index sessions
session-search index

# Enable auto-indexing
session-search install-service
systemctl --user enable --now session-search.timer
```

## Session Output Structure

```
~/.openclaw/workspace/sessions/
  2026-03-13/
    01-morning-briefing.md
    02-research-work.md
    03-implementation.md
```

Each section contains YAML frontmatter (session_id, date, message_range) and formatted messages.

## Dependencies

- qmd (`npm install -g @tobilu/qmd`) — powers the search
- sentence-transformers (Python) — for segmentation embeddings
