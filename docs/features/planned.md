# Planned Features

## Design Principles

1. **Minimize agent tool calls** - Context recovery should take 1-2 calls, not 5
2. **User-oriented API** - Commands should match how users think/speak
3. **Sessions vs Topics** - Sessions are work units; topics are conversation chunks
4. **Grouped subcommands** - Avoid polluting root namespace

## Nomenclature

| Internal | User-facing | Description |
|----------|-------------|-------------|
| segment | topic | A conversation chunk about one subject |
| session | session | A complete agent session (JSONL file) |

"Segment" is an implementation detail (how we split sessions). "Topic" is what
users care about - the subject matter they discussed.


## Search vs Context

Two distinct use cases, two commands:

| Intent | Command | Output |
|--------|---------|--------|
| "Did I work on X before?" | `cam "X"` | List of matches, quick scan |
| "Continue where I worked on X" | `cam context "X"` | Full context, ready to resume |

**Search** (`cam "query"`) is exploratory - show what's there, let user pick.

**Context** (`cam context "query"`) is actionable - compile everything needed to continue.

```bash
# Search: quick scan
$ cam "telegram"
3 results for "telegram"
  claude@wintermute/2026-03-20/02-spot-telegram.md (85%)
  claude@wintermute/2026-03-18/01-bot-setup.md (72%)
  ...

# Context: full recovery
$ cam context "telegram"
## Session: abc123 (claude@wintermute, Mar 20)
### Last Task
Fixing Spot's Telegram webhook...
[full context output]
```


## User Scenarios

### "Let's continue the last session"

```bash
cam sessions last                    # → last session + its topics
cam sessions last --topics           # → just topic paths for reading
```

### "Continue where we fixed Spot's telegram problems"

```bash
cam sessions search "spot telegram"  # → matching sessions with context
```

### "What did I work on yesterday?"

```bash
cam sessions list -t 1d              # → sessions from last 24h
cam sessions list --date 2026-03-23  # → sessions from specific date
```

### "Show me recent work on authentication"

```bash
cam search "authentication" -t 1w    # → existing command, searches topics
```


## Proposed API

### `cam sessions` - Session Management

```bash
cam sessions list                    # List all sessions
cam sessions list -t 2d              # Last 2 days
cam sessions list -a claude          # Claude sessions only
cam sessions list --machine laptop   # From specific machine

cam sessions last                    # Most recent session
cam sessions last -a openclaw        # Most recent OpenClaw session

cam sessions search "query"          # Search sessions (not segments)
cam sessions search "spot telegram"  # Find by topic/content

cam sessions get <session-id>        # Session details + topic list
```

**Output format for `sessions list`:**

```
SESSION                              DATE        AGENT    TOPICS
────────────────────────────────────────────────────────────────────
abc123  claude@wintermute            Mar 23      claude   3 topics
def456  openclaw@server              Mar 23      openclaw 5 topics
ghi789  claude@wintermute            Mar 22      claude   2 topics
```

**Output format for `sessions last`:**

```
Session: abc123
Agent: claude@wintermute
Date: 2026-03-23 14:30
Duration: 45 min
Topics:
  1. 01-spot-telegram-fix.md (14:30-14:45)
  2. 02-api-refactoring.md (14:45-15:00)
  3. 03-documentation-update.md (15:00-15:15)

To read: cam get claude@wintermute/2026-03-23/01-spot-telegram-fix.md
```


### `cam topics` - Topic Browsing

```bash
cam topics list                      # List recent topics
cam topics list -t 1d                # Last 24 hours
cam topics list -a claude            # Claude topics only
cam topics list --session abc123     # Topics from specific session

cam topics recent                    # Alias for `cam topics list -t 24h`
```

**Note:** `cam search` already handles topic search. `cam topics` is for
browsing/listing without a query.


### `cam context` - Context Assembly

Assemble everything an agent needs to continue a session or topic:

```bash
cam context                          # Context from last session
cam context <session-id>             # Context from specific session
cam context <topic-path>             # Context from specific topic
cam context "query"                  # Search + compile (recency-first)
cam context "query" --best           # Prioritize relevance score over recency
cam context --json                   # Machine-readable for agents
```

The query form is a wrapper around `cam search` that compiles full context
from the top result(s) - no need to search then read separately.

**Default: recency-first.** When continuing work, you almost always want the
most recent match, not an old session with better keyword overlap.

Use `--best` to sort by relevance score (with recency boost) when you need
the best keyword match regardless of age.

**Output:**

```markdown
## Session: abc123 (claude@wintermute, Mar 23)

### Last Task
Fixing Spot's Telegram webhook integration

### State
In progress - webhook receiving messages, but reply formatting broken

### Pending Items
- [ ] Fix markdown escaping in replies
- [ ] Add rate limiting for webhook endpoint
- [ ] Test with production bot token

### Key Files
- src/telegram/webhook.py (modified)
- tests/test_telegram.py (3 failing)
- docs/telegram-setup.md (created)

### Last Decision
Decided to use python-telegram-bot v20 async API instead of polling

---

## Last Messages

**User** _2026-03-23 15:12_
The webhook is receiving messages now but the replies look broken -
markdown isn't rendering properly in Telegram.

**Assistant** _2026-03-23 15:13_
I see the issue. Telegram uses a different markdown flavor. Let me check
the python-telegram-bot docs for the correct parse mode...

[reads src/telegram/webhook.py]

The problem is we're using `parse_mode="Markdown"` but Telegram expects
`parse_mode="MarkdownV2"` which has different escaping rules. I'll fix
the `format_reply()` function to escape special characters properly.

---

## Topic Content

[Full content of the most recent topic, or the specified topic]
```

**What's included:**
1. **Extracted context** - Task, state, pending items, key files, decisions
2. **Last 2 messages per role** - Full user + assistant messages for continuity
3. **Topic content** - The full topic markdown

**Implementation:**
- Detect argument type:
  - No arg → last session
  - Looks like path → topic path
  - Looks like session ID → session
  - Otherwise → search query
- For queries: run `cam search`, take top result
- Extract structured context (TODO items, file mentions, decisions)
- Pull last 2 user + 2 assistant messages from raw session JSONL
- Include full topic markdown
- Single output, no follow-up calls needed


## Agent Integration

### SKILL.md Guidance

Add to CAM skill for Claude:

```markdown
## Context Recovery Workflow

When user wants to continue previous work:

1. **One-call recovery:**
   - "continue last session" → `cam context`
   - "continue where we worked on X" → `cam context "X"`
   - "continue session abc123" → `cam context abc123`

2. **Present findings:**
   - Summarize the task state
   - List pending items
   - Ask how to proceed

`cam context` handles everything - search, read, compile. One call.
```

### One-Call Design

`cam context` returns everything an agent needs in one call:
- Session/topic metadata
- Extracted context (task, state, pending items, files)
- Last 2 user + 2 assistant messages (full text)
- Full topic content

The agent can then read specific codebase files if needed, but shouldn't need
multiple CAM calls to understand the conversation context.


## Migration from Current API

| Current | New | Notes |
|---------|-----|-------|
| `cam recent` | `cam topics recent` | Alias kept for compatibility |
| `cam search` | unchanged | Topic search stays at root |
| `cam get` | unchanged | Topic retrieval stays at root |
| `cam query` | unchanged | Synthesis stays at root |
| - | `cam context` | New: one-call context assembly |
| - | `cam sessions *` | New: session management |
| - | `cam topics *` | New: topic browsing |


## Priority

| Feature | Effort | Value | Status |
|---------|--------|-------|--------|
| `cam context` | Medium | High | **DONE** |
| `cam sessions last` | Low | High | Planned |
| `cam sessions list` | Low | Medium | Planned |
| `cam topics list` | Low | Low | Nice to have, `cam recent` exists |
| `cam sessions search` | Medium | Medium | Can use `cam search` for now |
| Rename segment → topic | Medium | Medium | Codebase + output refactor |


## Non-Goals

- **TUI browser** - Focus on CLI + agent integration
- **Session editing** - Read-only access to history
- **Cross-repo sessions** - Each repo has its own CAM index
