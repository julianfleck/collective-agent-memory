"""Tests for the headed-mode provider helpers (no network)."""

import os
from pathlib import Path

import pytest

from cam import providers


def _clear_mode_env(monkeypatch):
    for var in ("CAM_MODE", "CAM_PROVIDER", "CAM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    for var in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)


def test_get_mode_defaults_to_local(monkeypatch):
    _clear_mode_env(monkeypatch)
    assert providers.get_mode() == "local"
    assert providers.is_headed() is False


def test_get_mode_reads_env(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    monkeypatch.setenv("CAM_PROVIDER", "openrouter")
    assert providers.get_mode() == "headed"
    assert providers.is_headed() is True
    assert providers.get_provider_key() == "openrouter"


def test_get_mode_normalizes_case_and_whitespace(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "  HEADED  ")
    assert providers.get_mode() == "headed"


def test_segment_fixed_empty():
    assert providers.segment_fixed([]) == []


def test_segment_fixed_single_chunk():
    msgs = [{"text": str(i)} for i in range(10)]
    assert providers.segment_fixed(msgs) == [(0, 9)]


def test_segment_fixed_exact_chunk_boundary():
    msgs = [{"text": str(i)} for i in range(40)]
    assert providers.segment_fixed(msgs) == [(0, 19), (20, 39)]


def test_segment_fixed_merges_tiny_tail():
    # 22 messages with chunk_size=20 produces a (20,21) tail of size 2,
    # which should be merged into the previous chunk.
    msgs = [{"text": str(i)} for i in range(22)]
    assert providers.segment_fixed(msgs) == [(0, 21)]


def test_segment_fixed_keeps_full_size_tail():
    # 45 messages with chunk_size=20 produces a (40,44) tail of size 5,
    # which is large enough to stand alone.
    msgs = [{"text": str(i)} for i in range(45)]
    assert providers.segment_fixed(msgs) == [(0, 19), (20, 39), (40, 44)]


def test_verify_headed_setup_local_mode_is_noop(monkeypatch):
    _clear_mode_env(monkeypatch)
    providers.verify_headed_setup()  # must not raise


def test_verify_headed_setup_missing_provider(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    with pytest.raises(RuntimeError, match="CAM_PROVIDER is not set"):
        providers.verify_headed_setup()


def test_verify_headed_setup_unknown_provider(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    monkeypatch.setenv("CAM_PROVIDER", "bogus-provider")
    with pytest.raises(RuntimeError, match="not a known provider"):
        providers.verify_headed_setup()


def test_verify_headed_setup_missing_api_key(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    monkeypatch.setenv("CAM_PROVIDER", "openai")
    monkeypatch.setattr(providers, "KEY_FILE", Path("/nonexistent/.cam/api-key"))
    with pytest.raises(RuntimeError, match="no API key"):
        providers.verify_headed_setup()


def test_verify_headed_setup_with_env_key_passes(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    monkeypatch.setenv("CAM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    providers.verify_headed_setup()  # must not raise


def test_store_api_key_writes_file_with_0600(monkeypatch, tmp_path):
    monkeypatch.setattr(providers, "KEY_FILE", tmp_path / "api-key")
    path = providers.store_api_key("sk-test-key  \n")
    assert path == tmp_path / "api-key"
    assert path.read_text().strip() == "sk-test-key"
    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_get_provider_config_returns_none_in_local_mode(monkeypatch):
    _clear_mode_env(monkeypatch)
    assert providers.get_provider_config() is None


def test_get_provider_config_returns_dict_in_headed_mode(monkeypatch):
    _clear_mode_env(monkeypatch)
    monkeypatch.setenv("CAM_MODE", "headed")
    monkeypatch.setenv("CAM_PROVIDER", "anthropic")
    cfg = providers.get_provider_config()
    assert cfg is not None
    assert cfg["env_var"] == "ANTHROPIC_API_KEY"
    assert cfg["shape"] == "anthropic"


def test_parse_json_loose_handles_fenced_response():
    raw = '```json\n{"title": "test", "keywords": ["a"]}\n```'
    parsed = providers._parse_json_loose(raw)
    assert parsed == {"title": "test", "keywords": ["a"]}


def test_parse_json_loose_handles_prose_wrapper():
    raw = 'Here is the result: {"title": "x", "keywords": []} done.'
    parsed = providers._parse_json_loose(raw)
    assert parsed == {"title": "x", "keywords": []}


def test_parse_json_loose_returns_empty_on_garbage():
    assert providers._parse_json_loose("no json here") == {}
