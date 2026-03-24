"""Query expansion using Ollama API.

For short queries (1-3 words): find synonyms/abbreviations
For long queries (sentences): extract key search terms first

Falls back to no expansion if Ollama isn't available.
"""

import json
import urllib.request
import urllib.error
from typing import List, Optional

OLLAMA_API = "http://localhost:11434/api"

# Preferred generative models (smallest first)
PREFERRED_MODELS = [
    "qwen2:0.5b",
    "qwen2:1.5b",
    "gemma2:2b",
    "gemma:2b",
    "phi3:mini",
    "llama3.2:1b",
    "llama3.2:3b",
    "llama3.1:8b",
    "llama3.1:latest",
]

_available_model: Optional[str] = None
_checked: bool = False


def _find_model() -> Optional[str]:
    """Find the best available generative model."""
    global _available_model, _checked

    if _checked:
        return _available_model

    _checked = True

    try:
        req = urllib.request.Request(f"{OLLAMA_API}/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
            models = {m["name"].lower() for m in data.get("models", [])}

            # Find first preferred model that's available
            for model in PREFERRED_MODELS:
                model_lower = model.lower()
                if model_lower in models:
                    _available_model = model
                    return _available_model
                # Also check without tag
                base = model_lower.split(":")[0]
                for m in models:
                    if m.startswith(base):
                        _available_model = m
                        return _available_model

    except Exception:
        pass

    return None


def _call_ollama(prompt: str, timeout: int = 30) -> Optional[str]:
    """Call Ollama API with a prompt."""
    model = _find_model()
    if not model:
        return None

    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode()

        req = urllib.request.Request(
            f"{OLLAMA_API}/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
            return data.get("response", "").strip()

    except Exception:
        return None


def _extract_keywords(query: str) -> List[str]:
    """Extract key search terms from a long query/sentence."""
    prompt = f"""Extract 3-5 key search terms from this question. Return only the terms, comma separated, no explanation.

Question: {query}
Key terms:"""

    response = _call_ollama(prompt)
    if not response:
        # Fallback: just use the words from the query
        words = query.lower().split()
        # Filter stopwords
        stopwords = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
                     'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
                     'could', 'should', 'may', 'might', 'can', 'to', 'of', 'in',
                     'for', 'on', 'with', 'at', 'by', 'from', 'as', 'into', 'this',
                     'that', 'these', 'those', 'it', 'its', 'i', 'we', 'you', 'they',
                     'where', 'what', 'when', 'why', 'how', 'which', 'who', 'whom',
                     'there', 'here', 'only', 'just', 'but', 'and', 'or', 'not'}
        return [w for w in words if w not in stopwords and len(w) > 2][:5]

    # Parse response
    keywords = []
    for part in response.replace("\n", ",").split(","):
        term = part.strip().lower()
        # Remove parenthetical explanations
        if "(" in term:
            term = term.split("(")[0].strip()
        # Clean up
        term = term.strip(".-*•123456789() \"':")
        if term and 2 < len(term) < 40 and term not in keywords:
            keywords.append(term)

    return keywords[:5] if keywords else query.lower().split()[:5]


def _expand_term(term: str) -> List[str]:
    """Expand a single term with synonyms/abbreviations."""
    prompt = f"For '{term}', list 1-2 common abbreviations or synonyms. Just the terms, comma separated. If none, say 'none'."

    response = _call_ollama(prompt, timeout=15)
    if not response:
        return []

    expansions = []
    for part in response.replace("\n", ",").split(","):
        exp = part.strip().lower()
        if "(" in exp:
            exp = exp.split("(")[0].strip()
        exp = exp.strip(".-*•123456789() \"':")
        if exp and exp not in ("none", "n/a", "") and 1 < len(exp) < 30 and exp != term.lower():
            expansions.append(exp)

    return expansions[:2]


def expand_query(query: str) -> List[str]:
    """Expand query for better search recall.

    - Short queries (1-3 words): find synonyms/abbreviations
    - Long queries (4+ words): extract key terms, then expand those

    Args:
        query: The search query to expand

    Returns:
        List of search terms (original + expansions)
    """
    if not _find_model():
        return [query]

    words = query.split()

    # Short query: expand directly
    if len(words) <= 3:
        expansions = _expand_term(query)
        if expansions:
            return [query] + expansions
        return [query]

    # Long query: extract keywords first
    keywords = _extract_keywords(query)
    if not keywords:
        return [query]

    # Return the extracted keywords as search terms
    # For long queries, the keywords ARE the expansion
    return keywords


def is_available() -> bool:
    """Check if query expansion is available."""
    return _find_model() is not None
