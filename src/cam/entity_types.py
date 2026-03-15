"""
Entity types for GLiNER2 extraction.

These are the semantic categories that GLiNER2 will extract from session segments.
Entity types should be general enough to work across different domains and use cases.
"""

# General entity types for session extraction
ENTITY_TYPES = [
    # Decisions & Outcomes
    "decision",
    "solution",
    "problem",
    # Technical
    "technology",
    "tool",
    "file",
    "command",
    # Concepts
    "concept",
    "topic",
    "method",
    # People & Organizations
    "person",
    "organization",
    "product",
    # Actions
    "task",
    "error",
    # Resources
    "url",
    "service",
    "api",
]
