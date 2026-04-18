```
█▀▀ ▄▀█ █▀▄▀█            🇨​🇴​🇱​🇱​🇪​🇨​🇹​🇮​🇻​🇪​
█▄▄ █▀█ █░▀░█            🇦​🇬​🇪​🇳​🇹​ 🇲​🇪​🇲​🇴​🇷​🇾​
```

---

# Collective Agent Memory
## Shared, searchable agent memory across machines

CAM indexes sessions from Claude Code, Cursor, OpenClaw, and Codex CLI, segments them into searchable topics, and optionally syncs them across machines via GitHub. Your agents can search previous work, decisions, and code patterns from any session on any machine.

## What It Does

- **Context recovery** - Continue previous work with one command: `cam context "topic"`
- **Search past sessions** - Find previous work with fast weighted keyword search
- **Entity search** - Find sessions mentioning specific tools, files, concepts, or people
- **Filter by time** - Get only recent results: last 2 hours, last day, last week
- **Filter by agent** - Search only Claude, OpenClaw, or other specific agents
- **Shared memory** - Sync sessions across machines so all agents can search everything
- **Topic segmentation** - Sessions are automatically split into coherent topics with keywords
- **Entity extraction** - Typed entities (tools, files, concepts, etc.) are extracted and indexed
- **Fast local search** - SQLite FTS5, no embeddings needed, sub-second results

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/julianfleck/collective-agent-memory/main/install.sh | bash
```

The installer will:

1. Install CAM and its dependencies
2. Detect your host RAM and prompt for **local** or **headed** mode (see below)
3. Download ML models (~1.5GB) for embeddings and entity extraction (local mode only)
4. Detect your coding agents (Claude Code, Cursor, OpenClaw, Codex)
5. Index existing sessions into searchable session segments
6. Optionally set up GitHub sync for cross-machine access
7. Install the `/cam` skill to your agents

**Tip:** Set `HF_TOKEN` before installing for faster model downloads (see [Configuration](#configuration)).  
The installer + `cam init` writes the required `CAM_*` config automatically, so manual config setup is usually not needed.

## Modes: Local vs Headed

CAM's local mode loads ~1.3 GB of ML models (sentence-transformers, KeyBERT, GLiNER2) at daemon startup. On low-RAM hosts (laptops, small VMs) this can OOM-kill or thrash. Headed mode skips local models and routes title/keyword extraction to a cloud LLM API instead.

`cam init` reads `/proc/meminfo`, compares against a **6 GB** threshold, and prompts:

| Host RAM      | Behaviour                                                                              |
| ------------- | -------------------------------------------------------------------------------------- |
| `>= 6 GB`     | Recommends **local**, offers headed as opt-in.                                         |
| `< 6 GB`      | Loud warning, requires explicit choice between **headed** or **abort** (no silent fallback). |

In **headed** mode, `cam init` prompts for a provider (OpenAI / OpenRouter / Anthropic) and an API key. The key is written to `~/.cam/api-key` with `0600` permissions. Mode + provider are persisted to `~/.cam/config` as `CAM_MODE=` and `CAM_PROVIDER=`.

### Capability Differences

| Capability                       | Local                          | Headed                                        |
| -------------------------------- | ------------------------------ | --------------------------------------------- |
| Daemon resident memory           | ~1.3 GB                        | < 200 MB                                      |
| Title + keywords                 | KeyBERT (local model)          | Provider's chat completion (`analyze_section`) |
| Topic segmentation               | Embedding similarity (semantic) | Fixed-size chunks (20 messages)               |
| Typed entity extraction (GLiNER2) | ✓                              | **Off** — no reliable cloud equivalent without a second API key. Pre-approved asymmetry; entity search returns no results in headed mode. |
| Search backend (FTS5)            | ✓                              | ✓                                             |
| Query expansion (Ollama)         | Optional (if Ollama installed) | Optional (if Ollama installed)                |

### Switching Modes

Re-run `cam init`. To override at runtime, set `CAM_MODE=local` or `CAM_MODE=headed` in your env (env wins over `~/.cam/config`).

### Failure Mode

In headed mode, if the API key is missing or the provider is unrecognized, the daemon exits at startup with a clear error rather than silently producing empty titles. Check `journalctl --user -u cam -e` if the daemon won't stay up.

## Usage

### Context Recovery

When you want to continue previous work:

```bash
cam context                            # context from last session
cam context "authentication"           # search + compile context (recency-first)
cam context "auth" --best              # prioritize relevance over recency
cam context --json                     # JSON output for agents
```

Returns structured output with topic metadata, extracted context (TODOs, files, decisions), last messages, and full topic content.

### Basic Search

```bash
cam "authentication flow"              # search with weighted ranking (default)
cam search "error handling"            # explicit search command
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

### Machine Filters

Filter by machine name:

```bash
cam "error" -m wintermute              # specific machine only
cam openclaw@data "phase harmonics"   # agent@machine shorthand
```

### Combined Filters

```bash
cam @claude "error" [2h]               # Claude errors in last 2 hours
cam "API" -a openclaw -t 1w -n 20      # OpenClaw API work, last week
cam openclaw@data "auth" --since 3d   # agent@machine with --since alias
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
cam search "error" --since 1d -m wintermute
```

## Commands


| Command               | Description                                      |
| --------------------- | ------------------------------------------------ |
| `cam context`         | Assemble context from last session               |
| `cam context "query"` | Search + compile context (recency-first)         |
| `cam "query"`         | Search with weighted ranking (default)           |
| `cam search "query"`  | Explicit search command                          |
| `cam entity "name"`   | Search by extracted entity (tools, files, etc.)  |
| `cam [15min]`         | List recent topics (no search query)             |
| `cam recent`          | List topics from last 24h                        |
| `cam get <path>`      | Retrieve a topic file by path                    |
| `cam reindex`         | Rebuild search index from topics                 |


## Search Options


| Flag            | Description                                           |
| --------------- | ----------------------------------------------------- |
| `-n N`          | Number of results (default: 10)                       |
| `-t TIME`       | Time filter: `15min`, `2h`, `3d`, `1w`                |
| `--since TIME`  | Alias for `-t`                                        |
| `-a AGENT`      | Agent filter: `claude`, `openclaw`, `cursor`, `codex` |
| `-m MACHINE`    | Machine filter: `wintermute`, `data`, etc.            |
| `--sort ORDER`  | Sort order: `date`/`newest`, `oldest`, `score`/`best` |
| `-s N`          | Snippet length in tokens (5-64, default: 15)          |
| `--fast`        | Skip query expansion for faster search                |
| `--json`        | JSON output for scripts                               |
| `--files`       | Output file paths only                                |


**Inline syntax**: `[2h]` for time filters, `@claude` for agent filters, `openclaw@data` for agent+machine, `[newest]` for sort order.

### Sort Order

By default, search results are sorted by relevance score with a strong recency boost (2x for today, exponential decay).

```bash
cam "query"                   # default: best match + recency boost
cam "query" --sort newest     # sort by date (newest first)
cam "query" --sort oldest     # sort by date (oldest first)
cam "query" --sort score      # sort by relevance only
cam "query" "[newest]"        # bracket syntax for sort
cam "query" "[2h,newest]"     # combined: last 2 hours, newest first
```

### Query Expansion

By default, CAM expands your search query using a local LLM via [Ollama](https://ollama.com/). This finds related terms and abbreviations to improve recall:

```
$ cam "authentication"
Expanded: "auth", "authn" (1200ms)
...results...
```

If Ollama is not installed or running, CAM falls back to the original query only. Use `--fast` to skip expansion:

```bash
cam "authentication" --fast    # no expansion, instant search
```

Supported models (in preference order): qwen2:0.5b, qwen2:1.5b, gemma2:2b, phi3:mini, llama3.2, llama3.1.

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

## Performance

CAM uses **SQLite FTS5** for search, not embeddings or vector databases. This means:

- **No GPU required** - Runs on any machine
- **Instant startup** - No model loading for search
- **Small index** - ~48MB for 6,600 topics (vs GB+ for vector indices)
- **Fast search** - Sub-second results even with query expansion

### Benchmarks

Tested on M1 MacBook Pro with 6,600+ indexed topics from 380 sessions:

| Operation | Time | Notes |
|-----------|------|-------|
| Search (fast) | **~50ms** | `--fast` flag, no query expansion |
| Search (default) | **~350ms** | With LLM query expansion |
| Context retrieval | **~450ms** | Search + read + parse |
| Reindex 6,600 topics | **~26s** | ~250 topics/sec |

### Why Not Vector Search?

Vector search (embeddings) is great for semantic similarity but overkill for session memory:

1. **Keywords work** - You remember "auth", "telegram", "that error" - not semantic concepts
2. **Recency matters more** - You want recent work, not the most semantically similar
3. **Speed** - FTS5 is ~10x faster than vector similarity search
4. **Simplicity** - No embedding model to load, no vector DB to maintain

CAM uses embeddings only for **topic segmentation** (splitting sessions into coherent chunks), not for search. The segmentation happens during indexing, so search stays fast.


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
4. **Index**: Segments are indexed locally with SQLite FTS5 (weighted: title 10x, keywords 5x, entities 3x, body 1x)
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

CAM installs a skill so agents can search and recover context directly:

```
User: "Continue where we worked on rate limiting"
Agent: [runs cam context "rate limiting"]
Agent: "Found your session from 2 hours ago. You were implementing rate limiting
        with Redis. Pending: add per-user limits, update tests. Should I continue?"
```

```
User: "How did we implement auth before?"
Agent: [runs cam "authentication"]
Agent: "Found 3 relevant sessions. In March 10th session, we implemented
        JWT auth with refresh token rotation..."
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


| Variable            | Description                                                                          | Default           |
| ------------------- | ------------------------------------------------------------------------------------ | ----------------- |
| `CAM_SYNC_REPO`     | GitHub repo for sync                                                                 | (none)            |
| `CAM_WORKSPACE_DIR` | Segment storage directory                                                            | `~/.cam/sessions` |
| `CAM_MACHINE_ID`    | Machine identifier                                                                   | hostname          |
| `CAM_MODE`          | `local` (loads local ML models) or `headed` (routes to API). See [Modes](#modes-local-vs-headed). | `local`           |
| `CAM_PROVIDER`      | Required when `CAM_MODE=headed`. One of `openai`, `openrouter`, `anthropic`.          | (none)            |
| `CAM_MODEL`         | Optional override for the headed-mode model. Defaults per provider.                   | (none)            |
| `HF_TOKEN`          | HuggingFace token for faster model downloads (local mode only)                       | (none)            |

API keys live in `~/.cam/api-key` (mode `0600`), not in `~/.cam/config` — the config file is broadcast into the process environment on every CLI invocation, which is the wrong place for a secret.


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

# Index your sessions
cam index

# Build search index
cam reindex

# (Optional) Set up sync
export CAM_SYNC_REPO="youruser/agent-memory"
cam sync

# (Optional) Install skill to agents
cam skill install
```

## Dependencies

- **Python 3.10+**: Core runtime
- **uv**: Recommended package manager ([install](https://docs.astral.sh/uv/getting-started/installation/))
- **SQLite**: Search index (included with Python)
- **sentence-transformers**: Topic segmentation
- **KeyBERT**: Keyword extraction
- **GLiNER2**: Entity extraction (205M params, [fastino-ai/GLiNER2](https://github.com/fastino-ai/GLiNER2))

## Credits

- Topic segmentation via [sentence-transformers](https://www.sbert.net/)
- Keywords via [KeyBERT](https://github.com/MaartenGr/KeyBERT)
- Entity extraction via [GLiNER2](https://github.com/fastino-ai/GLiNER2)

## License

MIT