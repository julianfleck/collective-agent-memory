#!/usr/bin/env python3
"""
Session Segmentation using Embedding Similarity

Parses OpenClaw session JSONL files and segments them into natural topic sections
using embedding similarity (no LLM calls).

Uses sentence-transformers for fast local embeddings.
Outputs structured markdown files with YAML frontmatter.
"""

import json
import re
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from collections import Counter
from datetime import datetime, timedelta
import argparse
import sys

# Lazy load models
_model = None
_keybert_model = None
_gliner_model = None

# Common English stopwords for semantic title extraction
STOPWORDS = {
    'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from', 'has', 'he',
    'in', 'is', 'it', 'its', 'of', 'on', 'or', 'that', 'the', 'to', 'was', 'were',
    'will', 'with', 'you', 'your', 'can', 'could', 'do', 'does', 'did', 'have',
    'had', 'if', 'just', 'me', 'my', 'not', 'now', 'our', 'out', 'so', 'some',
    'than', 'then', 'there', 'these', 'they', 'this', 'up', 'we', 'what', 'when',
    'which', 'who', 'would', 'about', 'after', 'all', 'also', 'any', 'back',
    'because', 'been', 'before', 'being', 'but', 'get', 'go', 'going', 'got',
    'how', 'i', 'im', "i'm", 'into', 'know', 'like', 'make', 'more', 'most',
    'need', 'no', 'one', 'only', 'other', 'over', 'really', 'right', 'see',
    'should', 'something', 'still', 'take', 'them', 'think', 'through', 'time',
    'too', 'us', 'use', 'used', 'using', 'very', 'want', 'way', 'well', 'where',
    'while', 'why', 'work', 'yeah', 'yes', 'yet', 'hey', 'hi', 'hello', 'ok',
    'okay', 'sure', 'thanks', 'thank', 'please', 'let', "let's", 'lets',
    'system', 'user', 'assistant', 'message', 'cron', 'error', 'check'
}


def get_model():
    """Load embedding model lazily."""
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        print("Loading embedding model...")
        _model = SentenceTransformer('all-MiniLM-L6-v2')
        print("Model loaded.")
    return _model


def get_keybert_model():
    """Load KeyBERT model lazily (shares embedding model)."""
    global _keybert_model
    if _keybert_model is None:
        from keybert import KeyBERT
        # Reuse the same embedding model for efficiency
        _keybert_model = KeyBERT(model=get_model())
    return _keybert_model


def get_gliner_model():
    """Load GLiNER2 model lazily for entity extraction."""
    global _gliner_model
    if _gliner_model is None:
        try:
            import sys
            from transformers import AutoConfig, AutoModel
            from gliner2 import GLiNER2
            from gliner2.model import ExtractorConfig, Extractor

            # Register GLiNER2's model type with transformers to avoid
            # "model of type extractor" warning (gliner2 doesn't do this itself)
            try:
                AutoConfig.register('extractor', ExtractorConfig)
                AutoModel.register(ExtractorConfig, Extractor)
            except ValueError:
                pass  # Already registered

            print("Loading GLiNER2 model...", flush=True)
            sys.stdout.flush()

            _gliner_model = GLiNER2.from_pretrained("fastino/gliner2-base-v1")

            print("GLiNER2 model loaded.", flush=True)
        except ImportError:
            print("GLiNER2 not installed, entity extraction disabled", flush=True)
            _gliner_model = False  # Mark as unavailable
    return _gliner_model if _gliner_model else None


def preload_models():
    """Preload all models at startup for better UX."""
    print("Loading models...", flush=True)
    get_model()  # Embedding model
    get_keybert_model()  # KeyBERT (reuses embedding model)
    get_gliner_model()  # GLiNER2 for entity extraction
    print("All models loaded.", flush=True)


def get_embeddings(texts: List[str]) -> np.ndarray:
    """Get embedding vectors for texts using sentence-transformers (batched)."""
    model = get_model()
    return model.encode(texts, show_progress_bar=True)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Compute cosine similarity between two vectors."""
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))


def extract_message_text(msg: Dict) -> str:
    """Extract text content from a message object.

    Supports both OpenClaw and Claude Code session formats:
    - OpenClaw: message.content = [{"type": "text", "text": "..."}]
    - Claude Code: message.content = "..." (string) or array format
    """
    if not isinstance(msg, dict):
        return ""

    message = msg.get("message", {})
    if not isinstance(message, dict):
        return ""

    content = message.get("content", [])

    # Claude Code format: content is a string
    if isinstance(content, str):
        return content.strip()

    # OpenClaw / Claude Code array format
    if not isinstance(content, list):
        return ""

    texts = []
    for item in content:
        if isinstance(item, dict):
            if item.get("type") == "text":
                texts.append(item.get("text", ""))
        elif isinstance(item, str):
            texts.append(item)

    return " ".join(texts).strip()


def detect_agent_from_path(path: Path) -> str:
    """Detect agent type from session file path."""
    path_str = str(path)
    if "/.claude/" in path_str:
        return "claude"
    elif "/.cursor/" in path_str:
        return "cursor"
    elif "/.openclaw/" in path_str:
        return "openclaw"
    elif "/.codex/" in path_str:
        return "codex"
    return "unknown"


def load_session_messages(session_path: Path) -> Tuple[Dict, List[Dict]]:
    """
    Load messages from a session JSONL file.
    Returns (session_metadata, list of message dicts with index, role, text, timestamp).

    Supports both OpenClaw and Claude Code session formats:
    - OpenClaw: type="session" for metadata, type="message" for messages
    - Claude Code: type="user"/"assistant" at top level, or message.role for role
    """
    session_meta = {
        "source_path": str(session_path),
        "agent": detect_agent_from_path(session_path),
    }
    messages = []

    with open(session_path, 'r') as f:
        for idx, line in enumerate(f):
            try:
                data = json.loads(line.strip())
                msg_type = data.get("type", "")

                # Capture session metadata (OpenClaw format)
                if msg_type == "session":
                    session_meta.update({
                        "session_id": data.get("id", ""),
                        "version": data.get("version", 0),
                        "started": data.get("timestamp", ""),
                        "cwd": data.get("cwd", "")
                    })
                    continue

                # Skip non-message types
                if msg_type in ("queue-operation", "summary", "tool_result"):
                    continue

                # Get message object and role
                message = data.get("message", {})
                if not isinstance(message, dict):
                    continue

                # Determine role: check multiple locations
                # - message.role (OpenClaw format)
                # - top-level role (Cursor format)
                # - top-level type (Claude Code format)
                role = message.get("role", "")
                if not role:
                    role = data.get("role", "")
                if not role and msg_type in ("user", "assistant"):
                    role = msg_type

                # Only process user and assistant messages
                if role not in ("user", "assistant"):
                    continue

                # Extract session metadata from first message (Claude Code format)
                if not session_meta.get("session_id") and data.get("sessionId"):
                    session_meta.update({
                        "session_id": data.get("sessionId", ""),
                        "version": data.get("version", ""),
                        "started": data.get("timestamp", ""),
                        "cwd": data.get("cwd", "")
                    })

                text = extract_message_text(data)
                if text:
                    timestamp = data.get("timestamp", "")
                    messages.append({
                        "index": idx,
                        "role": role,
                        "text": text,
                        "timestamp": timestamp,
                        "raw": data
                    })

            except json.JSONDecodeError:
                continue

    # Fallback: use file modification time if no timestamp found
    if not session_meta.get("started"):
        try:
            mtime = session_path.stat().st_mtime
            session_meta["started"] = datetime.fromtimestamp(mtime).isoformat()
        except (OSError, ValueError):
            pass

    # Backfill timestamps for messages without them using file mtime
    if messages and not any(m.get("timestamp") for m in messages):
        try:
            mtime = session_path.stat().st_mtime
            # Use mtime as base, spread messages across a reasonable window
            base_time = datetime.fromtimestamp(mtime)
            for i, msg in enumerate(messages):
                if not msg.get("timestamp"):
                    # Spread messages backwards from mtime (most recent = mtime)
                    offset_minutes = (len(messages) - 1 - i) * 2  # 2 min per message
                    msg_time = base_time - timedelta(minutes=offset_minutes)
                    msg["timestamp"] = msg_time.isoformat()
        except (OSError, ValueError):
            pass

    return session_meta, messages


def segment_session(
    messages: List[Dict],
    window_size: int = 3,
    threshold: float = 0.75,
    min_section_size: int = 3
) -> Tuple[List[Tuple[int, int]], List[float]]:
    """
    Segment session into topic sections using embedding similarity.
    
    Returns:
        - List of (start_idx, end_idx) section boundaries
        - List of similarity scores between adjacent windows
    """
    if len(messages) < window_size * 2:
        # Too few messages, return as single section
        return [(0, len(messages) - 1)], []
    
    # Create windows of concatenated message text
    windows = []
    for i in range(len(messages) - window_size + 1):
        window_text = " ".join([msg["text"] for msg in messages[i:i + window_size]])
        # Truncate to avoid token limits
        windows.append(window_text[:2000])
    
    print(f"Computing embeddings for {len(windows)} windows...")
    embeddings = get_embeddings(windows)
    
    # Compute similarities between adjacent windows
    similarities = []
    for i in range(len(embeddings) - 1):
        sim = cosine_similarity(embeddings[i], embeddings[i + 1])
        similarities.append(sim)
    
    # Find local minima (valleys) below threshold
    boundaries = [0]  # Start with first message
    
    for i in range(1, len(similarities) - 1):
        # Check if this is a local minimum
        is_minimum = similarities[i] < similarities[i-1] and similarities[i] < similarities[i+1]
        below_threshold = similarities[i] < threshold
        
        if is_minimum and below_threshold:
            # Boundary is at the end of the window
            boundary_idx = i + window_size - 1
            
            # Ensure minimum section size
            if boundary_idx - boundaries[-1] >= min_section_size:
                boundaries.append(boundary_idx)
    
    boundaries.append(len(messages) - 1)  # End with last message
    
    # Convert to (start, end) pairs
    sections = []
    for i in range(len(boundaries) - 1):
        sections.append((boundaries[i], boundaries[i + 1]))
    
    return sections, similarities


def slugify(text: str, max_length: int = 60) -> str:
    """Convert text to a URL-safe slug."""
    # Lowercase and replace non-alphanumeric with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    # Remove leading/trailing hyphens
    slug = slug.strip('-')
    # Truncate to max length, respecting word boundaries
    if len(slug) > max_length:
        slug = slug[:max_length].rsplit('-', 1)[0]
    return slug or "section"


def extract_keywords(messages: List[Dict], num_keywords: int = 8) -> List[str]:
    """
    Extract keywords from section messages using KeyBERT.

    Uses MMR (Maximal Marginal Relevance) with diversity for better keyword spread.

    Returns:
        List of keyword strings for frontmatter
    """
    # Collect all message text (prefer user messages)
    texts = []
    for msg in messages:
        if msg["role"] == "user":
            texts.append(msg["text"])

    # If no user messages, use assistant messages
    if not texts:
        for msg in messages:
            if msg["role"] == "assistant":
                texts.append(msg["text"][:1000])

    if not texts:
        return []

    # Combine and clean text
    combined = " ".join(texts)
    # Remove URLs, code blocks, and special characters
    combined = re.sub(r'https?://\S+', '', combined)
    combined = re.sub(r'```[\s\S]*?```', '', combined)
    combined = re.sub(r'`[^`]+`', '', combined)
    # Limit text length for KeyBERT
    combined = combined[:8000]

    if len(combined.strip()) < 20:
        return []

    try:
        kw_model = get_keybert_model()

        # Extract keywords using MMR for diversity
        keywords = kw_model.extract_keywords(
            combined,
            keyphrase_ngram_range=(1, 2),
            stop_words='english',
            use_mmr=True,
            diversity=0.7,
            top_n=num_keywords
        )

        # keywords is list of (keyword, score) tuples
        return [kw for kw, score in keywords]

    except Exception as e:
        print(f"KeyBERT extraction failed: {e}")
        return []


def extract_entities(messages: List[Dict]) -> Dict[str, List[str]]:
    """
    Extract typed entities from section messages using GLiNER2.

    Returns:
        Dict mapping entity type to list of entity strings.
        E.g., {"tool": ["pip", "git"], "file": ["cli.py", "config.json"]}
    """
    from .entity_types import ENTITY_TYPES

    extractor = get_gliner_model()
    if not extractor:
        return {}

    # Collect message text
    texts = []
    for msg in messages:
        texts.append(msg["text"][:2000])  # Truncate long messages

    combined = " ".join(texts)
    # Limit total text for GLiNER context
    combined = combined[:4000]

    if len(combined.strip()) < 20:
        return {}

    try:
        result = extractor.extract_entities(combined, ENTITY_TYPES)

        # Result format: {"entities": {"type": ["entity1", "entity2", ...]}}
        entities_by_type = {}
        if isinstance(result, dict) and "entities" in result:
            for etype, entities in result["entities"].items():
                if entities:
                    # Dedupe while preserving order
                    seen = set()
                    unique = []
                    for entity in entities:
                        text = str(entity).lower()
                        if text not in seen and len(text) > 1:
                            seen.add(text)
                            unique.append(str(entity))
                    if unique:
                        entities_by_type[etype] = unique[:10]  # Limit per type

        return entities_by_type

    except Exception as e:
        print(f"Entity extraction failed: {e}")
        return {}


def _is_noisy_term(term: str) -> bool:
    """Check if a term is noisy and should be excluded from titles."""
    term_lower = term.lower()
    # File extensions
    if term_lower in {'md', 'py', 'js', 'ts', 'json', 'yaml', 'yml', 'txt', 'sh', 'css', 'html'}:
        return True
    # Date patterns (2026-03-21, 2026, 03, 21, etc.)
    if re.match(r'^\d{4}[-/]\d{2}[-/]\d{2}$', term_lower):
        return True
    if re.match(r'^\d{2,4}$', term_lower):
        return True
    # Generic noise
    if term_lower in {'section', 'file', 'memory', 'user', 'assistant', 'start', 'end'}:
        return True
    return False


def generate_title(
    keywords: List[str],
    entities: Dict[str, List[str]],
    text: str = "",
    max_terms: int = 4
) -> str:
    """
    Generate a short descriptive title from keywords and entities.

    Uses term frequency in the segment text to rank candidates,
    picking the most representative terms for the title.

    Args:
        keywords: List of keywords from KeyBERT (already ranked by relevance)
        entities: Dict of entity type -> entity list from GLiNER2
        text: Combined segment text for frequency scoring
        max_terms: Maximum number of terms in title (default: 4)

    Returns:
        Hyphenated title string
    """
    # Collect all candidate terms with scores
    candidates = []  # (term, score)
    text_lower = text.lower()

    def term_score(term: str) -> float:
        """Score a term by frequency in text (simple TF)."""
        term_lower = term.lower()
        # Count occurrences (case-insensitive)
        count = text_lower.count(term_lower)
        # Bonus for longer terms (more specific)
        length_bonus = min(len(term_lower) / 10, 1.0)
        return count + length_bonus

    # Add entities with frequency scores
    # Priority types get a small boost
    priority_types = ["tool", "technology", "product", "command", "concept", "organization"]
    for etype in priority_types:
        if etype in entities:
            for entity in entities[etype]:
                if _is_noisy_term(entity) or len(entity) <= 2:
                    continue
                score = term_score(entity) + 0.5  # Small boost for priority entities
                candidates.append((entity, score))

    # Add other entity types without boost
    for etype, ents in entities.items():
        if etype in priority_types:
            continue
        for entity in ents:
            if _is_noisy_term(entity) or len(entity) <= 2:
                continue
            candidates.append((entity, term_score(entity)))

    # Add keywords (KeyBERT already ranked them, so use position as tiebreaker)
    for i, kw in enumerate(keywords):
        if _is_noisy_term(kw) or len(kw) <= 2:
            continue
        # Keywords get score from frequency + position bonus (earlier = better)
        score = term_score(kw) + (len(keywords) - i) * 0.1
        candidates.append((kw, score))

    # Sort by score (descending)
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Pick top unique terms
    seen_lower = set()
    title_terms = []

    for term, score in candidates:
        if len(title_terms) >= max_terms:
            break
        term_lower = term.lower().replace(' ', '-')
        words = set(term_lower.split('-'))
        # Skip if any word already in title
        if not words & seen_lower:
            title_terms.append(term.replace(' ', '-'))
            seen_lower.add(term_lower)
            seen_lower.update(words)

    if not title_terms:
        return "section"

    return "-".join(title_terms)


def format_timestamp(ts_str: str) -> str:
    """Format ISO timestamp to human-readable form."""
    if not ts_str:
        return ""
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except:
        return ts_str


def format_message_markdown(msg: Dict) -> str:
    """Format a single message as markdown."""
    role = msg["role"].capitalize()
    text = msg["text"]
    timestamp = format_timestamp(msg.get("timestamp", ""))
    
    # Format speaker label
    if role == "User":
        label = "**User**"
    else:
        label = "**Assistant**"
    
    if timestamp:
        label += f" _{timestamp}_"
    
    return f"{label}\n\n{text}\n"


def generate_section_markdown(
    section_idx: int,
    messages: List[Dict],
    session_meta: Dict,
    session_date: str,
    semantic_title: str,
    machine_id: str,
    keywords: Optional[List[str]] = None,
    entities: Optional[Dict[str, List[str]]] = None
) -> str:
    """Generate markdown content for a section file."""
    # YAML frontmatter
    first_msg = messages[0]
    last_msg = messages[-1]

    # Format keywords as YAML list
    keywords_yaml = ""
    if keywords:
        keywords_yaml = "\nkeywords:\n" + "\n".join(f"  - {kw}" for kw in keywords)

    # Format entities as YAML nested dict
    entities_yaml = ""
    if entities:
        entities_yaml = "\nentities:"
        for etype, elist in sorted(entities.items()):
            if elist:
                entities_yaml += f"\n  {etype}:\n" + "\n".join(f"    - {e}" for e in elist)

    agent = session_meta.get('agent', 'unknown')
    source_path = session_meta.get('source_path', '')

    frontmatter = f"""---
session_id: {session_meta.get('session_id', 'unknown')}
date: {session_date}
agent: {agent}
machine: {machine_id}
source: {source_path}
section_index: {section_idx}
message_range: [{first_msg['index']}, {last_msg['index']}]
message_count: {len(messages)}
title: "{semantic_title.replace('-', ' ')}"{keywords_yaml}{entities_yaml}
first_timestamp: {first_msg.get('timestamp', '')}
last_timestamp: {last_msg.get('timestamp', '')}
---

"""
    
    # Section header
    content = f"# Section {section_idx}: {semantic_title.replace('-', ' ').title()}\n\n"
    
    # Messages
    for msg in messages:
        content += format_message_markdown(msg) + "\n---\n\n"
    
    return frontmatter + content


def cleanup_session_segments(output_dir: Path, source_path: str) -> int:
    """Remove existing segments for a session before re-indexing.

    Scans all .md files in output_dir recursively and deletes those
    whose 'source:' field in frontmatter matches the given source_path.

    Returns:
        Number of files deleted
    """
    deleted = 0
    if not output_dir.exists():
        return 0

    for md_file in output_dir.rglob("*.md"):
        try:
            # Quick check: read first 1000 chars for frontmatter
            content = md_file.read_text()[:1000]
            if not content.startswith("---"):
                continue

            # Find source field
            for line in content.split('\n'):
                if line.startswith('source:'):
                    file_source = line.split(':', 1)[1].strip()
                    if file_source == source_path:
                        md_file.unlink()
                        deleted += 1
                    break
                if line == '---' and content.index(line) > 0:
                    break  # End of frontmatter
        except (OSError, UnicodeDecodeError):
            continue

    return deleted


def write_sections(
    messages: List[Dict],
    sections: List[Tuple[int, int]],
    session_meta: Dict,
    output_dir: Path,
    machine_id: str = "unknown",
    dry_run: bool = False
) -> List[Path]:
    """Write section files to disk.

    Output structure: {output_dir}/{agent}@{machine}/{date}/{nn}-{title}.md
    """
    # Extract date from session metadata
    session_start = session_meta.get("started", "")
    if session_start:
        try:
            dt = datetime.fromisoformat(session_start.replace('Z', '+00:00'))
            session_date = dt.strftime("%Y-%m-%d")
        except:
            session_date = "unknown-date"
    else:
        session_date = "unknown-date"

    # Build output path: {agent}@{machine}/{date}/
    agent = session_meta.get("agent", "unknown")
    agent_machine_dir = output_dir / f"{agent}@{machine_id}" / session_date

    # Clean up existing segments for this session before writing new ones
    # This prevents duplicate/orphaned segments on re-indexing
    source_path = session_meta.get("source_path", "")
    if source_path and not dry_run:
        deleted = cleanup_session_segments(output_dir, source_path)
        if deleted > 0:
            print(f"  Cleaned up {deleted} existing segment(s) for re-indexing")

    written_files = []

    for i, (start, end) in enumerate(sections, 1):
        section_messages = messages[start:end + 1]
        keywords = extract_keywords(section_messages)
        entities = extract_entities(section_messages)

        # Combine message text for title scoring
        combined_text = " ".join(msg.get("text", "")[:1000] for msg in section_messages)

        # Generate smart title using frequency scoring
        title = generate_title(keywords, entities, text=combined_text)

        # Generate filename
        filename = f"{i:02d}-{slugify(title)}.md"
        filepath = agent_machine_dir / filename

        # Generate content
        content = generate_section_markdown(
            section_idx=i,
            messages=section_messages,
            session_meta=session_meta,
            session_date=session_date,
            semantic_title=title,
            machine_id=machine_id,
            keywords=keywords,
            entities=entities
        )

        if dry_run:
            print(f"  Would write: {filepath}")
            print(f"    Messages: {start}-{end} ({len(section_messages)} messages)")
            print(f"    Title: {title.replace('-', ' ')}")
            print(f"    Keywords: {', '.join(keywords[:5])}..." if keywords else "    Keywords: none")
        else:
            agent_machine_dir.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content)
            written_files.append(filepath)

    return written_files


def print_sections(messages: List[Dict], sections: List[Tuple[int, int]]):
    """Print section summaries."""
    print("\n" + "=" * 80)
    print(f"DETECTED {len(sections)} SECTIONS")
    print("=" * 80)

    for i, (start, end) in enumerate(sections, 1):
        section_messages = messages[start:end + 1]
        keywords = extract_keywords(section_messages)
        entities = extract_entities(section_messages)
        combined_text = " ".join(msg.get("text", "")[:1000] for msg in section_messages)
        title = generate_title(keywords, entities, text=combined_text)

        print(f"\nSection {i}: Messages {start}-{end} ({end - start + 1} messages)")
        print(f"  Title: {title.replace('-', ' ')}")
        if keywords:
            print(f"  Keywords: {', '.join(keywords[:5])}")
        print("-" * 80)

        # Show first message snippet
        first_role = messages[start]["role"]
        first_msg = messages[start]["text"]
        snippet = first_msg[:300] + "..." if len(first_msg) > 300 else first_msg
        print(f"[{first_role}] {snippet}")


def plot_similarity_curve(similarities: List[float], sections: List[Tuple[int, int]], output_path: Path):
    """Plot similarity curve with detected boundaries."""
    try:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend
        import matplotlib.pyplot as plt
        
        fig, ax = plt.subplots(figsize=(14, 6))
        
        # Plot similarity curve
        ax.plot(similarities, linewidth=2, color='#2E86AB', label='Similarity')
        ax.fill_between(range(len(similarities)), similarities, alpha=0.3, color='#2E86AB')
        
        # Mark section boundaries
        boundaries = [s[0] for s in sections[1:]]  # Skip first boundary (0)
        for boundary in boundaries:
            ax.axvline(x=boundary, color='#E94F37', linestyle='--', alpha=0.8, linewidth=2)
        
        ax.set_xlabel('Window Index', fontsize=12)
        ax.set_ylabel('Cosine Similarity', fontsize=12)
        ax.set_title('Session Segmentation: Inter-window Similarity', fontsize=14)
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.set_ylim(0, 1)
        
        plt.tight_layout()
        plt.savefig(output_path, dpi=150)
        print(f"\nSimilarity plot saved to: {output_path}")

    except ImportError:
        print("\n[--] matplotlib not available, skipping plot")


def main():
    import socket

    parser = argparse.ArgumentParser(description='Segment session into topic sections')
    parser.add_argument('session_file', type=Path, help='Path to session JSONL file')
    parser.add_argument('--window-size', type=int, default=3, help='Window size (default: 3)')
    parser.add_argument('--threshold', type=float, default=0.70, help='Similarity threshold (default: 0.70)')
    parser.add_argument('--min-section', type=int, default=3, help='Min messages per section (default: 3)')
    parser.add_argument('--machine-id', type=str, help='Machine identifier (default: hostname)')
    parser.add_argument('--plot', type=Path, help='Save similarity plot to file')
    parser.add_argument('--output-dir', type=Path,
                        default=Path.home() / '.cam' / 'sessions',
                        help='Output directory for section files (default: ~/.cam/sessions/)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Print what would be written without actually writing files')

    args = parser.parse_args()

    machine_id = args.machine_id or socket.gethostname().split('.')[0]

    if not args.session_file.exists():
        print(f"Error: File not found: {args.session_file}")
        sys.exit(1)

    print(f"Loading session: {args.session_file.name}")
    session_meta, messages = load_session_messages(args.session_file)

    if not messages:
        print("Error: No messages found in session")
        sys.exit(1)

    print(f"Loaded {len(messages)} messages")
    print(f"Session ID: {session_meta.get('session_id', 'unknown')}")
    print(f"Agent: {session_meta.get('agent', 'unknown')}")
    print(f"Started: {session_meta.get('started', 'unknown')}")

    sections, similarities = segment_session(
        messages,
        window_size=args.window_size,
        threshold=args.threshold,
        min_section_size=args.min_section
    )

    print_sections(messages, sections)

    # Write section files
    if args.output_dir:
        print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Writing sections to: {args.output_dir}")
        written = write_sections(
            messages, sections, session_meta,
            output_dir=args.output_dir,
            machine_id=machine_id,
            dry_run=args.dry_run
        )
        if not args.dry_run:
            print(f"\nWrote {len(written)} section files")

    if args.plot and similarities:
        plot_similarity_curve(similarities, sections, args.plot)

    print("\nSegmentation complete!")


if __name__ == "__main__":
    main()
