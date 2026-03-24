"""Query expansion using local GGUF model.

Uses HyDE (Hypothetical Document Embeddings) approach:
1. Generate hypothetical answer to the query
2. Extract key terms from the hypothetical answer
3. Combine with original query for better recall
"""

import os
from pathlib import Path
from typing import List, Optional

# Lazy load the model
_llm = None
_model_path = None


def get_model_path() -> Optional[Path]:
    """Find the query expansion model."""
    # Check common locations
    locations = [
        Path.home() / ".cache" / "qmd" / "models" / "hf_tobil_qmd-query-expansion-1.7B-q4_k_m.gguf",
        Path.home() / ".cache" / "cam" / "models" / "qmd-query-expansion-1.7B-q4_k_m.gguf",
        Path.home() / ".local" / "share" / "cam" / "models" / "qmd-query-expansion-1.7B-q4_k_m.gguf",
    ]

    # Also check CAM_MODEL_PATH env var
    env_path = os.environ.get("CAM_MODEL_PATH")
    if env_path:
        locations.insert(0, Path(env_path))

    for path in locations:
        if path.exists():
            return path

    return None


def get_llm():
    """Load the query expansion model lazily."""
    global _llm, _model_path

    if _llm is not None:
        return _llm

    model_path = get_model_path()
    if not model_path:
        return None

    try:
        from llama_cpp import Llama

        # Load with conservative settings for query expansion
        _llm = Llama(
            model_path=str(model_path),
            n_ctx=512,  # Small context for short queries
            n_threads=4,
            verbose=False,
        )
        _model_path = model_path
        return _llm
    except Exception as e:
        print(f"Warning: Could not load query expansion model: {e}")
        return None


def expand_query(query: str, max_tokens: int = 100) -> List[str]:
    """Expand a query using HyDE approach.

    Args:
        query: The original search query
        max_tokens: Maximum tokens to generate

    Returns:
        List of expanded query terms (including original)
    """
    llm = get_llm()
    if llm is None:
        # No model available, return just the original query
        return [query]

    # Simple query expansion prompt
    prompt = f"""Expand this search query with related terms and synonyms.

Query: {query}
Expanded:"""

    try:
        response = llm(
            prompt,
            max_tokens=max_tokens,
            temperature=0.3,  # Lower temperature for more focused output
            stop=["\n\n", "Query:", "Example:"],
            echo=False,
        )

        raw_text = response["choices"][0]["text"].strip()

        # Extract just the first line of expansion (most relevant)
        first_line = raw_text.split('\n')[0].strip()

        # Clean up common artifacts
        for prefix in ["Expanded:", "Synonyms:", "Related:"]:
            if first_line.startswith(prefix):
                first_line = first_line[len(prefix):].strip()

        # Return both original query and the expanded version
        if first_line and len(first_line) > 3 and first_line != query:
            return [query, first_line]
        else:
            return [query]

    except Exception as e:
        print(f"Warning: Query expansion failed: {e}")
        return [query]


def is_available() -> bool:
    """Check if query expansion is available."""
    return get_model_path() is not None
