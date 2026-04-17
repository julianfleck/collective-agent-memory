"""
Provider abstraction for CAM headed mode.

Headed mode runs CAM without local ML models and routes section analysis
(title + keywords) to a cloud LLM API. Supports OpenAI, OpenRouter, and
Anthropic. One provider is active at a time (configured via `cam init`).

Segmentation in headed mode uses fixed-size chunking instead of embedding
similarity, because only OpenAI offers a reliable embeddings endpoint and
we don't want to require a second API key.

Entity extraction (GLiNER2) is disabled in headed mode.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

import requests

log = logging.getLogger("cam-providers")

# Provider registry. Each entry describes the env var, endpoint, and request
# shape. Kept as a plain dict (not a class hierarchy) because the abstraction
# is intentionally thin: one provider is active per install.
PROVIDERS: Dict[str, Dict] = {
    "openai": {
        "display_name": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4o-mini",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "shape": "openai",
    },
    "openrouter": {
        "display_name": "OpenRouter",
        "env_var": "OPENROUTER_API_KEY",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "default_model": "openai/gpt-4o-mini",
        "auth_header": "Authorization",
        "auth_prefix": "Bearer ",
        "shape": "openai",
    },
    "anthropic": {
        "display_name": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "default_model": "claude-haiku-4-5",
        "auth_header": "x-api-key",
        "auth_prefix": "",
        "shape": "anthropic",
    },
}

KEY_FILE = Path.home() / ".cam" / "api-key"
REQUEST_TIMEOUT = 60


def get_mode() -> str:
    """Return the configured CAM mode: 'local' (default) or 'headed'."""
    return os.environ.get("CAM_MODE", "local").strip().lower() or "local"


def is_headed() -> bool:
    """True when CAM is running in API-driven (no-local-models) mode."""
    return get_mode() == "headed"


def get_provider_key() -> Optional[str]:
    """Return the configured provider key (openai/openrouter/anthropic) or None."""
    return os.environ.get("CAM_PROVIDER", "").strip().lower() or None


def get_provider_config() -> Optional[Dict]:
    """Return the active provider config dict, or None if not in headed mode."""
    if get_mode() != "headed":
        return None
    key = get_provider_key()
    if not key or key not in PROVIDERS:
        return None
    return PROVIDERS[key]


def verify_headed_setup() -> None:
    """Raise RuntimeError if headed mode is on but the setup is incomplete.

    Called at daemon startup to fail loudly instead of silently producing
    garbage segments when the API key is missing or the provider key is
    unrecognized.
    """
    if get_mode() != "headed":
        return
    key = get_provider_key()
    if not key:
        raise RuntimeError("Headed mode: CAM_PROVIDER is not set in ~/.cam/config")
    if key not in PROVIDERS:
        raise RuntimeError(
            f"Headed mode: CAM_PROVIDER={key!r} is not a known provider "
            f"(expected one of {sorted(PROVIDERS)})"
        )
    provider = PROVIDERS[key]
    # Triggers the same env-or-file lookup that analyze_section uses.
    _load_api_key(provider)


def _load_api_key(provider: Dict) -> str:
    """Resolve the API key from env first, then ~/.cam/api-key file."""
    env_val = os.environ.get(provider["env_var"])
    if env_val:
        return env_val
    if KEY_FILE.exists():
        return KEY_FILE.read_text().strip()
    raise RuntimeError(
        f"Headed mode: no API key. Set {provider['env_var']} or write "
        f"the key to {KEY_FILE}"
    )


ANALYZE_SYSTEM_PROMPT = (
    "You extract a short descriptive title and up to 8 keywords from a "
    "snippet of a software-engineering chat session. Return STRICT JSON "
    'with two fields: {"title": "kebab-case-title", "keywords": ["kw1", "kw2", ...]}. '
    "Keywords should be lowercase, 1-2 words each, technical and specific "
    "(tools, files, concepts). Title should be 3-6 kebab-case words. "
    "No prose, no code fences, just the JSON object."
)


def _build_request(provider: Dict, model: str, system: str, user: str) -> tuple[Dict, Dict]:
    """Build (headers, body) tuple for the provider's chat endpoint."""
    api_key = _load_api_key(provider)
    headers = {
        "Content-Type": "application/json",
        provider["auth_header"]: provider["auth_prefix"] + api_key,
    }
    if provider["shape"] == "openai":
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        }
    else:  # anthropic
        headers["anthropic-version"] = "2023-06-01"
        body = {
            "model": model,
            "max_tokens": 512,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
    return headers, body


def _extract_text(provider: Dict, response_json: Dict) -> str:
    """Pull the model's text output from the provider's response envelope."""
    if provider["shape"] == "openai":
        return response_json["choices"][0]["message"]["content"]
    content = response_json.get("content", [])
    for block in content:
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def _parse_json_loose(text: str) -> Dict:
    """Extract the first JSON object from text; tolerate fences or prose."""
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def analyze_section(section_text: str, max_chars: int = 6000) -> Dict:
    """Call the active provider to extract a title and keywords.

    Returns {"title": str, "keywords": List[str]} or {} on any failure —
    callers should fall back to a generic title ("section").
    """
    provider = get_provider_config()
    if not provider:
        return {}

    snippet = section_text.strip()[:max_chars]
    if len(snippet) < 20:
        return {}

    model = os.environ.get("CAM_MODEL", provider["default_model"])
    headers, body = _build_request(
        provider, model, ANALYZE_SYSTEM_PROMPT, snippet
    )

    try:
        resp = requests.post(
            provider["endpoint"], headers=headers, json=body,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        raw = _extract_text(provider, resp.json())
        data = _parse_json_loose(raw)
    except (requests.RequestException, ValueError, KeyError) as e:
        log.warning("analyze_section failed: %s", e)
        return {}

    title = str(data.get("title", "")).strip()
    keywords = data.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = []
    keywords = [str(k).strip().lower() for k in keywords if str(k).strip()][:8]

    return {"title": title, "keywords": keywords}


def segment_fixed(messages: List[Dict], chunk_size: int = 20) -> List[tuple]:
    """Fixed-size segmentation for headed mode (no embeddings)."""
    if not messages:
        return []
    if len(messages) <= chunk_size:
        return [(0, len(messages) - 1)]
    sections = []
    start = 0
    n = len(messages)
    while start < n:
        end = min(start + chunk_size - 1, n - 1)
        sections.append((start, end))
        start = end + 1
    # Merge a tiny tail into the previous chunk so we never emit a 1-2 msg section
    if len(sections) > 1 and sections[-1][1] - sections[-1][0] < 3:
        prev_start, _ = sections[-2]
        _, last_end = sections[-1]
        sections = sections[:-2] + [(prev_start, last_end)]
    return sections


def store_api_key(key: str) -> Path:
    """Persist the API key to ~/.cam/api-key with 0600 perms. Returns the path."""
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip() + "\n")
    try:
        KEY_FILE.chmod(0o600)
    except OSError:
        pass
    return KEY_FILE
