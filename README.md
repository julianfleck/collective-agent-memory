```
█▀▀ ▄▀█ █▀▄▀█            🇨​🇴​🇱​🇱​🇪​🇨​🇹​🇮​🇻​🇪​
█▄▄ █▀█ █░▀░█            🇦​🇬​🇪​🇳​🇹​ 🇲​🇪​🇲​🇴​🇷​🇾​
```

---

# Collective Agent Memory
## Shared, searchable agent memory across machines

CAM indexes sessions from Claude Code, Cursor, OpenClaw, and Codex CLI, segments them into searchable topics, and optionally syncs them across machines via GitHub. Your agents can search previous work, decisions, and code patterns from any session on any machine.

## What It Does

- **Search past sessions** - Find previous work with keyword, semantic, or hybrid search
- **Entity search** - Find sessions mentioning specific tools, files, concepts, or people
- **Filter by time** - Get only recent results: last 2 hours, last day, last week
- **Filter by agent** - Search only Claude, OpenClaw, or other specific agents
- **Shared memory** - Sync sessions across machines so all agents can search everything
- **Topic segmentation** - Sessions are automatically split into coherent topics with keywords
- **Entity extraction** - Typed entities (tools, files, concepts, etc.) are extracted and added to the session metadata
- **Fast local search** - Powered by [qmd](https://github.com/tobi/qmd) for instant results

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
```

The installer will:

1. Install CAM and its dependencies
2. Download ML models (~1.5GB) for embeddings and entity extraction
3. Detect your coding agents (Claude Code, Cursor, OpenClaw, Codex)
4. Index existing sessions into searchable session segments
5. Optionally set up GitHub sync for cross-machine access
6. Install the `/cam` skill to your agents

**Tip:** Set `HF_TOKEN` before installing for faster model downloads (see [Configuration](#configuration)).  
The installer + `cam init` writes the required `CAM_*` config automatically, so manual config setup is usually not needed.

## Usage

### Basic Search

```bash
cam "authentication flow"              # hybrid search with reranking (default)
cam query "authentication flow"        # same thing, explicit

cam search "error handling"            # keyword search (fast)
cam vsearch "how to deploy"            # semantic search (vector similarity)
```

### Time Filters

Search only recent sessions:

```bash
cam "auth" [15min]                     # last 15 minutes
cam "database" [2h]                    # last 2 hours
cam "API design" [1d]                  # last day
cam "setup" [1w]                       # last week
```

### List Recent Segments

List session segments by time without a search query:

```bash
cam [15min]                            # list session segments from last 15 minutes
cam [2h]                               # list session segments from last 2 hours
cam recent                             # list session segments from last 24h (default)
cam recent -t 30min                    # last 30 minutes
cam recent -t 1d -n 50                 # last day, more results
```

### Agent Filters

Search sessions from a specific agent:

```bash
cam @claude "authentication"           # Claude Code sessions only
cam @openclaw "deployment"             # OpenClaw sessions only
cam @cursor "refactoring"              # Cursor sessions only
```

### Combined Filters

```bash
cam @claude "error" [2h]               # Claude errors in last 2 hours
cam query "API" -a openclaw -t 1w      # OpenClaw API work, last week, best search
```

### Entity Search

Search session segments by extracted entities (tools, files, concepts, etc.):

```bash
cam entity "docker"                    # sessions mentioning Docker
cam entity "config.json"               # sessions working with config.json
cam entity "authentication"            # sessions about authentication
cam entity "Redis" -n 20               # more results
cam entity "pip" --json                # JSON output
```

### Retrieve a Segment

Get the full content of a session segment by path (useful for agents):

```bash
cam get claude@wintermute/2026-03-15/01-auth-flow.md
cam get claude@wintermute/2026-03-15/01-auth-flow.md --meta  # frontmatter only (JSON)
```

### Explicit Flag Syntax

The inline `[time]` and `@agent` syntax is shorthand. You can also use flags:

```bash
cam search "auth" -t 2h -a claude -n 20
```

## Commands


| Command               | Description                                     |
| --------------------- | ----------------------------------------------- |
| `cam "query"`         | Hybrid search with reranking (default)          |
| `cam query "query"`   | Same as above, explicit                         |
| `cam search "query"`  | Keyword search (fast)                           |
| `cam vsearch "query"` | Semantic search (vector similarity)             |
| `cam entity "name"`   | Search by extracted entity (tools, files, etc.) |
| `cam [15min]`         | List recent session segments (no search query)  |
| `cam recent`          | List session segments from last 24h             |
| `cam get <path>`      | Retrieve a session segment file by path         |


## Search Options


| Flag       | Description                                           |
| ---------- | ----------------------------------------------------- |
| `-n N`     | Number of results (default: 5)                        |
| `-t TIME`  | Time filter: `15min`, `2h`, `3d`, `1w`                |
| `-a AGENT` | Agent filter: `claude`, `openclaw`, `cursor`, `codex` |
| `--json`   | JSON output for scripts                               |
| `--files`  | Output file paths only                                |


**Inline syntax**: `[2h]` for time filters, `@claude` for agent filters.

## Other Commands

```bash
cam status                  # show indexed sessions, segments, sync status
cam index                   # index new sessions
cam index -f                # force re-index all sessions
cam sync                    # sync with GitHub repo (pull, index, push)
cam init                    # interactive setup / reconfigure sync + config
cam logs                    # view daemon logs
cam logs -f                 # follow daemon logs
cam skill install           # install skill to Claude Code
cam skill install -a openclaw  # install skill to OpenClaw
```

## How It Works

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Machine A     │     │     GitHub      │     │   Machine B     │
│   (laptop)      │     │  agent-memory   │     │   (server)      │
├─────────────────┤     ├─────────────────┤     ├─────────────────┤
│ Claude Code     │     │                 │     │ OpenClaw        │
│ Cursor          │────▶│  Synced         │◀────│                 │
│                 │     │  Segments       │     │                 │
│ ~/.cam/sessions │◀───▶│                 │◀───▶│ ~/.cam/sessions │
│                 │     │                 │     │                 │
│ cam "query"     │     │                 │     │ cam "query"     │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

1. **Segment**: Sessions are split into topics using embedding similarity (sentence-transformers)
2. **Extract keywords**: Topic keywords are extracted for each segment (KeyBERT)
3. **Extract entities**: Typed entities (tools, files, concepts) are extracted (GLiNER2)
4. **Index**: Segments are indexed locally for fast search (qmd)
5. **Sync**: Segments optionally sync to GitHub for cross-machine access

## Session Storage

Sessions are organized by agent and machine:

```
~/.cam/sessions/
  claude@laptop/
    2024-03-15/
      01-authentication-flow.md
      02-database-schema.md
      03-api-endpoints.md
  openclaw@server/
    2024-03-15/
      01-deployment-setup.md
```

Each session segment includes metadata in YAML frontmatter:

```yaml
---
session_id: abc123
date: 2024-03-15
agent: claude
machine: laptop
source: ~/.claude/projects/myproject/abc123.jsonl
message_range: [45, 82]
title: "authentication flow with JWT tokens"
keywords:
  - authentication
  - jwt tokens
  - middleware
entities:
  concept:
    - authentication
    - JWT
  tool:
    - express
    - bcrypt
  file:
    - auth.ts
    - middleware.ts
first_timestamp: 2024-03-15T14:30:00Z
last_timestamp: 2024-03-15T15:45:00Z
---
```

## Multi-Machine Sync

Share memory across machines by pointing them to the same GitHub repo:

```bash
# On your laptop
curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
cam init

# On your server
curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
cam init
```

When prompted, pick the same GitHub repo on each machine (for example `youruser/agent-memory`).
The background daemon then watches for new sessions and syncs automatically. Agents on any machine can search sessions from all machines.

For non-interactive setup (CI, scripts):

```bash
curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
cam init -y
```

## Agent Skill

CAM installs a skill so agents can search sessions directly in conversation:

```
User: "How did we implement rate limiting before?"
Agent: [uses /cam skill]
Agent: "Found 3 relevant sessions. In session from March 10th, we implemented
        rate limiting using Redis with a sliding window algorithm..."
```

The skill is installed to `~/.claude/skills/cam/`, `~/.openclaw/skills/cam/`, etc.

## Session Sources

CAM automatically detects and indexes sessions from:


| Agent       | Session Location                                  |
| ----------- | ------------------------------------------------- |
| Claude Code | `~/.claude/projects/**/*.jsonl`                   |
| Cursor      | `~/.cursor/projects/**/agent-transcripts/*.jsonl` |
| OpenClaw    | `~/.openclaw/agents/main/sessions/*.jsonl`        |
| Codex CLI   | `~/.codex/sessions/*.jsonl`                       |


## Configuration

Set in `~/.cam/config` or as environment variables.

In normal usage, you do **not** need to set these manually: the installer + `cam init` writes them for you.
Use this section to understand or override values.


| Variable            | Description                                  | Default           |
| ------------------- | -------------------------------------------- | ----------------- |
| `CAM_SYNC_REPO`     | GitHub repo for sync                         | (none)            |
| `CAM_WORKSPACE_DIR` | Segment storage directory                    | `~/.cam/sessions` |
| `CAM_MACHINE_ID`    | Machine identifier                           | hostname          |
| `HF_TOKEN`          | HuggingFace token for faster model downloads | (none)            |


### Faster Model Downloads

CAM uses ML models from HuggingFace (~1.5GB total). Setting `HF_TOKEN` speeds up downloads:

```bash
# Get a token from https://huggingface.co/settings/tokens
export HF_TOKEN=hf_xxxxx

# Add to your shell profile for persistence
echo 'export HF_TOKEN=hf_xxxxx' >> ~/.bashrc  # or ~/.zshrc
```

## Auto-Sync Daemon

The daemon watches session directories and syncs when:

- No activity for 5 minutes (session likely complete)
- At least every hour (fallback)

**macOS**: launchd (`~/Library/LaunchAgents/net.julianfleck.cam.plist`)
**Linux**: systemd (`~/.config/systemd/user/cam.service`)

`cam daemon start` requires `CAM_SYNC_REPO` to be configured (usually handled during `cam init`).

```bash
cam daemon start            # start the daemon
cam daemon stop             # stop the daemon
cam logs -f                 # follow daemon logs
```

## Manual Installation

If you prefer to install manually:

```bash
# Install CAM with uv (recommended)
uv tool install "collective-agent-memory @ git+https://github.com/julianfleck/collective-agent-memory.git"

# Or with pip
pip install git+https://github.com/julianfleck/collective-agent-memory.git

# Install qmd (search engine)
npm install -g @tobilu/qmd

# Index your sessions
cam index

# (Optional) Set up sync
export CAM_SYNC_REPO="youruser/agent-memory"
cam sync

# (Optional) Install skill to agents
cam skill install
```

## Dependencies

- **Python 3.10+**: Core runtime
- **uv**: Recommended package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **qmd**: Fast local search ([npm install -g @tobilu/qmd](https://github.com/tobi/qmd))
- **sentence-transformers**: Topic segmentation
- **KeyBERT**: Keyword extraction
- **GLiNER2**: Entity extraction (205M params, [fastino-ai/GLiNER2](https://github.com/fastino-ai/GLiNER2))

## Credits

- Search powered by [qmd](https://github.com/tobi/qmd) by Tobi Lütke
- Topic segmentation via [sentence-transformers](https://www.sbert.net/)
- Keywords via [KeyBERT](https://github.com/MaartenGr/KeyBERT)
- Entity extraction via [GLiNER2](https://github.com/fastino-ai/GLiNER2)

## License

MIT