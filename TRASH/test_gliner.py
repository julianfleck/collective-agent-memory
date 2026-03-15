#!/usr/bin/env python3
"""Test GLiNER2 entity extraction on session segments."""

import yaml
from pathlib import Path
from gliner2 import GLiNER2

# Load the model
print("Loading GLiNER2 model...")
extractor = GLiNER2.from_pretrained("fastino/gliner2-base-v1")
print("Model loaded.\n")

# Entity types to extract - relevant for coding sessions
ENTITY_TYPES = [
    "technology",
    "programming_language",
    "framework",
    "library",
    "tool",
    "file",
    "function",
    "concept",
    "task",
    "error",
    "command",
]

def extract_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and body from markdown."""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            frontmatter = yaml.safe_load(parts[1])
            body = parts[2].strip()
            return frontmatter, body
    return {}, content

def test_segment(segment_path: Path):
    """Test GLiNER2 on a single segment."""
    content = segment_path.read_text()
    frontmatter, body = extract_frontmatter(content)

    # Get existing keywords from KeyBERT
    existing_keywords = frontmatter.get("keywords", [])

    print(f"=== {segment_path.name} ===")
    print(f"Title: {frontmatter.get('title', 'N/A')}")
    print()

    # Truncate body if too long (GLiNER has context limits)
    test_text = body[:4000] if len(body) > 4000 else body

    # Extract entities with GLiNER2
    print("GLiNER2 entities:")
    result = extractor.extract_entities(test_text, ENTITY_TYPES)

    # Result format: {"entities": {"type": ["entity1", "entity2", ...]}}
    by_type = {}
    if isinstance(result, dict) and "entities" in result:
        for etype, entities in result["entities"].items():
            if entities:
                # Dedupe and collect
                seen = set()
                unique = []
                for entity in entities:
                    text = str(entity).lower()
                    if text not in seen:
                        seen.add(text)
                        unique.append(entity)
                if unique:
                    by_type[etype] = unique
    else:
        print(f"  Unexpected result format: {result}")

    for etype, entities in sorted(by_type.items()):
        print(f"  {etype}: {', '.join(entities[:8])}")

    print()
    print(f"KeyBERT keywords (existing): {existing_keywords}")
    print()
    print("-" * 60)
    print()

# Find recent segments to test
sessions_dir = Path.home() / ".cam" / "sessions" / "claude@wintermute"
recent_dates = sorted(sessions_dir.iterdir())[-2:]  # Last 2 days

segments_to_test = []
for date_dir in recent_dates:
    if date_dir.is_dir():
        segments = sorted(date_dir.glob("*.md"))[-3:]  # Last 3 segments per day
        segments_to_test.extend(segments)

print(f"Testing {len(segments_to_test)} segments...\n")

for segment in segments_to_test[:5]:  # Limit to 5 for quick test
    test_segment(segment)
