"""SQLite FTS5-based search index for CAM segments."""

import math
import sqlite3
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml


@dataclass
class SearchResult:
    """A single search result."""
    path: str           # Relative path within sessions dir (agent@machine/date/file.md)
    title: str
    score: float
    date: str
    agent: str
    machine: str
    first_timestamp: Optional[str] = None
    last_timestamp: Optional[str] = None
    snippet: Optional[str] = None  # Text snippet with match context
    keywords: Optional[str] = None  # Space-separated keywords
    entities: Optional[str] = None  # Space-separated entities


@dataclass
class IndexStats:
    """Statistics about the search index."""
    segments: int
    sessions: int


class SearchIndex:
    """SQLite FTS5-based search index for CAM segments."""

    def __init__(self, db_path: Path, workspace_dir: Optional[Path] = None):
        """Initialize the search index.

        Args:
            db_path: Path to the SQLite database file
            workspace_dir: Path to the sessions directory (for rebuild)
        """
        self.db_path = Path(db_path)
        self.workspace_dir = workspace_dir
        self._ensure_schema()

    def _ensure_schema(self):
        """Create tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                -- Metadata table (content source for FTS5)
                CREATE TABLE IF NOT EXISTS segments (
                    id INTEGER PRIMARY KEY,
                    path TEXT UNIQUE,
                    session_id TEXT,
                    agent TEXT,
                    machine TEXT,
                    date TEXT,
                    first_timestamp TEXT,
                    last_timestamp TEXT,
                    title TEXT,
                    keywords TEXT,
                    entities TEXT,
                    body TEXT
                );

                -- Create indexes for filtering
                CREATE INDEX IF NOT EXISTS idx_segments_agent ON segments(agent);
                CREATE INDEX IF NOT EXISTS idx_segments_date ON segments(date);
                CREATE INDEX IF NOT EXISTS idx_segments_session ON segments(session_id);
                CREATE INDEX IF NOT EXISTS idx_segments_timestamp ON segments(first_timestamp);
            """)

            # Check if FTS5 table exists
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='segments_fts'"
            )
            if not cursor.fetchone():
                conn.executescript("""
                    -- FTS5 index with weighted columns
                    CREATE VIRTUAL TABLE segments_fts USING fts5(
                        title,
                        keywords,
                        entities,
                        body,
                        content='segments',
                        content_rowid='id',
                        tokenize='porter unicode61'
                    );

                    -- Triggers to keep FTS in sync
                    CREATE TRIGGER segments_ai AFTER INSERT ON segments BEGIN
                        INSERT INTO segments_fts(rowid, title, keywords, entities, body)
                        VALUES (new.id, new.title, new.keywords, new.entities, new.body);
                    END;

                    CREATE TRIGGER segments_ad AFTER DELETE ON segments BEGIN
                        INSERT INTO segments_fts(segments_fts, rowid, title, keywords, entities, body)
                        VALUES('delete', old.id, old.title, old.keywords, old.entities, old.body);
                    END;

                    CREATE TRIGGER segments_au AFTER UPDATE ON segments BEGIN
                        INSERT INTO segments_fts(segments_fts, rowid, title, keywords, entities, body)
                        VALUES('delete', old.id, old.title, old.keywords, old.entities, old.body);
                        INSERT INTO segments_fts(rowid, title, keywords, entities, body)
                        VALUES (new.id, new.title, new.keywords, new.entities, new.body);
                    END;
                """)

    def _parse_segment(self, segment_path: Path) -> Optional[dict]:
        """Parse a segment file and extract indexable data.

        Returns dict with: path, session_id, agent, machine, date,
        first_timestamp, last_timestamp, title, keywords, entities, body
        """
        try:
            content = segment_path.read_text(encoding='utf-8')
        except Exception:
            return None

        # Split frontmatter and body
        if not content.startswith('---'):
            return None

        parts = content.split('---', 2)
        if len(parts) < 3:
            return None

        try:
            frontmatter = yaml.safe_load(parts[1])
        except Exception:
            return None

        if not frontmatter:
            return None

        body = parts[2].strip()

        # Extract agent and machine from path or frontmatter
        agent = frontmatter.get('agent', '')
        machine = frontmatter.get('machine', '')

        # Build relative path (agent@machine/date/filename.md)
        # The segment_path should be like: .../sessions/agent@machine/date/file.md
        try:
            # Find the sessions dir in the path
            path_parts = segment_path.parts
            sessions_idx = None
            for i, part in enumerate(path_parts):
                if part == 'sessions' or part.endswith('@' + machine) or '@' in part:
                    if '@' in part:
                        sessions_idx = i
                        break

            if sessions_idx is not None:
                rel_path = '/'.join(path_parts[sessions_idx:])
            else:
                # Fallback: use last 3 parts (agent@machine/date/file.md)
                rel_path = '/'.join(path_parts[-3:])
        except Exception:
            rel_path = segment_path.name

        # Flatten keywords list to space-separated string
        keywords = frontmatter.get('keywords', [])
        if isinstance(keywords, list):
            keywords = ' '.join(str(k) for k in keywords)

        # Flatten entities dict to space-separated string
        entities_dict = frontmatter.get('entities', {})
        entities_list = []
        if isinstance(entities_dict, dict):
            for entity_type, values in entities_dict.items():
                if isinstance(values, list):
                    entities_list.extend(str(v) for v in values)
                else:
                    entities_list.append(str(values))
        entities = ' '.join(entities_list)

        return {
            'path': rel_path,
            'session_id': frontmatter.get('session_id', ''),
            'agent': agent,
            'machine': machine,
            'date': frontmatter.get('date', ''),
            'first_timestamp': frontmatter.get('first_timestamp', ''),
            'last_timestamp': frontmatter.get('last_timestamp', ''),
            'title': frontmatter.get('title', ''),
            'keywords': keywords,
            'entities': entities,
            'body': body,
        }

    def index_segment(self, segment_path: Path) -> bool:
        """Index a single segment file.

        Returns True if successful, False otherwise.
        """
        data = self._parse_segment(segment_path)
        if not data:
            return False

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO segments
                (path, session_id, agent, machine, date, first_timestamp,
                 last_timestamp, title, keywords, entities, body)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data['path'], data['session_id'], data['agent'], data['machine'],
                data['date'], data['first_timestamp'], data['last_timestamp'],
                data['title'], data['keywords'], data['entities'], data['body']
            ))

        return True

    def index_segments(self, segment_paths: List[Path]) -> int:
        """Index multiple segment files.

        Returns the number of successfully indexed segments.
        """
        count = 0
        for path in segment_paths:
            if self.index_segment(path):
                count += 1
        return count

    def remove_session(self, session_id: str) -> int:
        """Remove all segments for a session.

        Returns the number of removed segments.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM segments WHERE session_id = ?",
                (session_id,)
            )
            return cursor.rowcount

    def search(
        self,
        query: str,
        limit: int = 10,
        agent: Optional[str] = None,
        machine: Optional[str] = None,
        since: Optional[datetime] = None,
        min_score: float = 20.0,
        dynamic_cutoff: bool = True,
        snippet_tokens: int = 15,
        fast: bool = False,
    ) -> List[SearchResult]:
        """Search segments using FTS5 with weighted columns.

        Column weights: title (10x), keywords (5x), entities (3x), body (1x)

        By default, uses query expansion with a local LLM (HyDE approach) for
        better recall. Use fast=True to skip expansion for faster searches.

        Args:
            query: Search query (FTS5 syntax supported)
            limit: Maximum number of results
            agent: Filter by agent name (e.g., 'claude', 'cursor')
            machine: Filter by machine name (e.g., 'wintermute', 'data')
            since: Filter to segments after this timestamp
            min_score: Minimum score threshold (0-100)
            dynamic_cutoff: Apply dynamic cutoff based on score drops
            snippet_tokens: Number of tokens in snippet (default 15, max 64)
            fast: Skip query expansion for faster but less comprehensive search

        Returns:
            List of SearchResult objects, sorted by relevance
        """
        # Clamp snippet tokens
        snippet_tokens = max(5, min(64, snippet_tokens))

        # Get queries to search (expanded or just original)
        if fast:
            queries = [query]
        else:
            from cam.expand import expand_query
            queries = expand_query(query)

        # Search all queries and merge results
        all_results = []
        seen_paths = set()

        for q in queries:
            # Try AND query first (precise)
            results = self._search_fts(q, limit, agent, machine, since, use_or=False,
                                       snippet_tokens=snippet_tokens)

            # If too few results, try OR query (broad)
            if len(results) < 3:
                or_results = self._search_fts(q, limit, agent, machine, since, use_or=True,
                                              snippet_tokens=snippet_tokens)
                for r in or_results:
                    if r.path not in {x.path for x in results}:
                        results.append(r)

            # Add to all results, avoiding duplicates
            for r in results:
                if r.path not in seen_paths:
                    all_results.append(r)
                    seen_paths.add(r.path)

        # Sort by score and limit
        all_results.sort(key=lambda r: -r.score)
        all_results = all_results[:limit]

        # Apply dynamic cutoff
        if dynamic_cutoff and all_results:
            all_results = self._apply_cutoff(all_results, min_score)

        return all_results

    def _apply_cutoff(
        self,
        results: List[SearchResult],
        min_score: float = 20.0,
        drop_threshold: float = 0.4,
    ) -> List[SearchResult]:
        """Apply dynamic cutoff to results based on score distribution.

        Cuts off results when:
        1. Score drops below min_score
        2. Score drops more than drop_threshold (40%) from previous result

        Always returns at least 1 result if available.
        """
        if not results:
            return results

        filtered = [results[0]]  # Always include first result

        for i in range(1, len(results)):
            curr = results[i]
            prev = results[i - 1]

            # Stop if score is too low
            if curr.score < min_score:
                break

            # Stop if there's a significant score drop
            if prev.score > 0:
                drop = (prev.score - curr.score) / prev.score
                if drop > drop_threshold:
                    break

            filtered.append(curr)

        return filtered

    def _search_fts(
        self,
        query: str,
        limit: int,
        agent: Optional[str],
        machine: Optional[str],
        since: Optional[datetime],
        use_or: bool,
        snippet_tokens: int = 15,
    ) -> List[SearchResult]:
        """Execute FTS5 search with given query mode."""
        safe_query = self._prepare_query(query, use_or=use_or)

        if not safe_query:
            return []

        # Build the query with optional filters
        # snippet() extracts text around matches: (table, col_idx, start, end, ellipsis, tokens)
        # Column indices: title=0, keywords=1, entities=2, body=3
        sql = f"""
            SELECT
                s.path,
                s.title,
                bm25(segments_fts, 10.0, 5.0, 3.0, 1.0) as score,
                s.date,
                s.agent,
                s.machine,
                s.first_timestamp,
                s.last_timestamp,
                s.keywords,
                s.entities,
                snippet(segments_fts, 3, '', '', '...', {snippet_tokens}) as snippet
            FROM segments_fts
            JOIN segments s ON segments_fts.rowid = s.id
            WHERE segments_fts MATCH ?
        """
        params = [safe_query]

        if agent:
            sql += " AND s.agent = ?"
            params.append(agent)

        if machine:
            sql += " AND s.machine = ?"
            params.append(machine)

        if since:
            sql += " AND s.first_timestamp >= ?"
            params.append(since.isoformat())

        sql += " ORDER BY score LIMIT ?"
        params.append(limit)

        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(sql, params)
                for row in cursor:
                    # BM25 returns negative scores (more negative = better match)
                    # Use log scale for better differentiation at high scores
                    # Typical range: -5 (weak) to -30 (strong multi-term match)
                    # Log scale: maps -5 to ~45, -10 to ~60, -20 to ~75, -30 to ~85
                    raw_score = row['score']
                    normalized_score = min(100, max(0, 25 * math.log1p(-raw_score)))

                    results.append(SearchResult(
                        path=row['path'],
                        title=row['title'],
                        score=normalized_score,
                        date=row['date'],
                        agent=row['agent'],
                        machine=row['machine'],
                        first_timestamp=row['first_timestamp'],
                        last_timestamp=row['last_timestamp'],
                        snippet=row['snippet'],
                        keywords=row['keywords'],
                        entities=row['entities'],
                    ))
            except sqlite3.OperationalError:
                # Query syntax error - try simpler approach
                pass

        return results

    def _prepare_query(self, query: str, use_or: bool = False) -> str:
        """Prepare a query string for FTS5.

        Args:
            query: Raw query string
            use_or: If True, use OR between terms (broader). If False, use AND (precise).

        Returns:
            FTS5 query string.
        """
        if not query or not query.strip():
            return ""

        # Remove problematic characters, convert hyphens/underscores to spaces
        cleaned = re.sub(r'[^\w\s@.]', ' ', query)
        cleaned = re.sub(r'[-_]', ' ', cleaned)

        # Split into terms and filter stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
                     'would', 'could', 'should', 'may', 'might', 'must', 'shall',
                     'can', 'need', 'dare', 'ought', 'used', 'to', 'of', 'in',
                     'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into',
                     'through', 'during', 'before', 'after', 'above', 'below',
                     'between', 'under', 'again', 'further', 'then', 'once',
                     'here', 'there', 'when', 'where', 'why', 'how', 'all',
                     'each', 'few', 'more', 'most', 'other', 'some', 'such',
                     'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than',
                     'too', 'very', 'just', 'and', 'but', 'if', 'or', 'because',
                     'until', 'while', 'what', 'which', 'who', 'whom', 'this',
                     'that', 'these', 'those', 'am', 'it', 'its', 'i', 'me',
                     'my', 'myself', 'we', 'our', 'ours', 'ourselves', 'you',
                     'your', 'yours', 'yourself', 'yourselves', 'he', 'him',
                     'his', 'himself', 'she', 'her', 'hers', 'herself', 'they',
                     'them', 'their', 'theirs', 'themselves'}

        terms = [t.lower() for t in cleaned.split() if t.lower() not in stopwords and len(t) > 1]
        if not terms:
            # All stopwords - use original terms
            terms = [t.lower() for t in cleaned.split() if len(t) > 1]
        if not terms:
            return ""

        # Join terms - AND for precision, OR for recall
        joiner = ' OR ' if use_or else ' '
        return joiner.join(terms)

    def get_stats(self) -> IndexStats:
        """Get statistics about the search index."""
        with sqlite3.connect(self.db_path) as conn:
            segments = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
            sessions = conn.execute(
                "SELECT COUNT(DISTINCT session_id) FROM segments"
            ).fetchone()[0]

        return IndexStats(segments=segments, sessions=sessions)

    def search_entities(
        self,
        entity_name: str,
        limit: int = 10,
        agent: Optional[str] = None,
        machine: Optional[str] = None,
        snippet_tokens: int = 15,
    ) -> List[SearchResult]:
        """Search segments by entity name.

        Searches the entities column for matching entity names.

        Args:
            entity_name: Entity name to search for (case-insensitive)
            limit: Maximum number of results
            agent: Filter by agent name
            machine: Filter by machine name
            snippet_tokens: Number of tokens in snippet

        Returns:
            List of SearchResult objects, sorted by date descending
        """
        # Search entities column using FTS5
        # Entities are space-separated in the index
        query = entity_name.lower().replace('-', ' ').replace('_', ' ')

        sql = f"""
            SELECT
                s.path,
                s.title,
                s.date,
                s.agent,
                s.machine,
                s.first_timestamp,
                s.last_timestamp,
                s.keywords,
                s.entities,
                snippet(segments_fts, 3, '', '', '...', {snippet_tokens}) as snippet
            FROM segments_fts
            JOIN segments s ON segments_fts.rowid = s.id
            WHERE segments_fts MATCH 'entities:' || ?
        """
        params = [query + '*']

        if agent:
            sql += " AND s.agent = ?"
            params.append(agent)

        if machine:
            sql += " AND s.machine = ?"
            params.append(machine)

        sql += " ORDER BY s.first_timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(sql, params)
                for row in cursor:
                    results.append(SearchResult(
                        path=row['path'],
                        title=row['title'],
                        score=100.0,  # Entity matches are exact
                        date=row['date'],
                        agent=row['agent'],
                        machine=row['machine'],
                        first_timestamp=row['first_timestamp'],
                        last_timestamp=row['last_timestamp'],
                        snippet=row['snippet'],
                        keywords=row['keywords'],
                        entities=row['entities'],
                    ))
            except sqlite3.OperationalError:
                pass

        return results

    def list_recent(
        self,
        since: datetime,
        limit: int = 20,
        agent: Optional[str] = None,
        machine: Optional[str] = None,
    ) -> List[SearchResult]:
        """List recent segments by timestamp.

        Args:
            since: Return segments after this timestamp
            limit: Maximum number of results
            agent: Filter by agent name
            machine: Filter by machine name

        Returns:
            List of SearchResult objects, sorted by timestamp descending
        """
        sql = """
            SELECT
                path,
                title,
                date,
                agent,
                machine,
                first_timestamp,
                last_timestamp,
                entities,
                keywords
            FROM segments
            WHERE first_timestamp >= ?
        """
        params = [since.isoformat()]

        if agent:
            sql += " AND agent = ?"
            params.append(agent)

        if machine:
            sql += " AND machine = ?"
            params.append(machine)

        sql += " ORDER BY first_timestamp DESC LIMIT ?"
        params.append(limit)

        results = []
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            try:
                cursor = conn.execute(sql, params)
                for row in cursor:
                    results.append(SearchResult(
                        path=row['path'],
                        title=row['title'],
                        score=100.0,
                        date=row['date'],
                        agent=row['agent'],
                        machine=row['machine'],
                        first_timestamp=row['first_timestamp'],
                        last_timestamp=row['last_timestamp'],
                        snippet=None,  # No body snippet for recent listing
                        keywords=row['keywords'],
                        entities=row['entities'],
                    ))
            except sqlite3.OperationalError:
                pass

        return results

    def rebuild(self, workspace_dir: Optional[Path] = None) -> int:
        """Rebuild the entire index from segment files.

        Args:
            workspace_dir: Directory containing segment files.
                          Uses self.workspace_dir if not provided.

        Returns:
            Number of indexed segments.
        """
        workspace = workspace_dir or self.workspace_dir
        if not workspace:
            raise ValueError("workspace_dir must be provided")

        workspace = Path(workspace)
        if not workspace.exists():
            return 0

        # Clear existing data
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM segments")

        # Find all segment files
        segment_files = list(workspace.rglob("*.md"))

        # Index each file
        return self.index_segments(segment_files)
