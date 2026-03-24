"""Query expansion using Ollama API.

Uses a local LLM via Ollama for keyword expansion.
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


def expand_query(query: str) -> List[str]:
    """Expand query using local LLM via Ollama.

    Args:
        query: The search query to expand

    Returns:
        List of expanded terms (original + synonyms)
    """
    model = _find_model()
    if not model:
        return [query]

    prompt = f"For the term '{query}', list any common abbreviations, alternative spellings, or closely related technical terms. Just 1-2, comma separated. If none exist, say 'none'."

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

        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            response = data.get("response", "").strip()

            if not response:
                return [query]

            # Parse comma-separated keywords
            keywords = []
            for part in response.replace("\n", ",").split(","):
                term = part.strip().lower()
                # Remove parenthetical explanations
                if "(" in term:
                    term = term.split("(")[0].strip()
                # Clean up
                term = term.strip(".-*•123456789() \"'")
                # Skip noise
                if term in ("none", "n/a", "na", "null", ""):
                    continue
                if term and 1 < len(term) < 30 and term not in keywords and term != query.lower():
                    keywords.append(term)

            if keywords:
                return [query] + keywords[:2]

    except (urllib.error.URLError, TimeoutError):
        pass
    except Exception:
        pass

    return [query]


def is_available() -> bool:
    """Check if query expansion is available."""
    return _find_model() is not None
