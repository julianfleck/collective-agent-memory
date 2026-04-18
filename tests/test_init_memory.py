"""Tests for the init.py memory-check + write_config additions."""

from pathlib import Path

import pytest

from cam import init


def test_read_total_ram_gb_returns_float():
    # On any Linux host /proc/meminfo exists; on others it returns 0.0.
    val = init.read_total_ram_gb()
    assert isinstance(val, float)
    assert val >= 0.0


def test_read_total_ram_gb_handles_missing_file(monkeypatch, tmp_path):
    fake = tmp_path / "no-such-file"

    class FakePath:
        def __init__(self, p):
            self._p = p

        def read_text(self):
            return Path(self._p).read_text()  # will raise OSError

    # Monkeypatch Path("/proc/meminfo") used inside read_total_ram_gb.
    real_path_cls = init.Path

    def fake_path(arg):
        if arg == "/proc/meminfo":
            return real_path_cls(str(fake))
        return real_path_cls(arg)

    monkeypatch.setattr(init, "Path", fake_path)
    assert init.read_total_ram_gb() == 0.0


def test_read_total_ram_gb_parses_synthetic_meminfo(monkeypatch, tmp_path):
    meminfo = tmp_path / "meminfo"
    meminfo.write_text(
        "MemTotal:        8000000 kB\n"
        "MemFree:         3000000 kB\n"
        "MemAvailable:    4000000 kB\n"
    )

    real_path_cls = init.Path

    def fake_path(arg):
        if arg == "/proc/meminfo":
            return real_path_cls(str(meminfo))
        return real_path_cls(arg)

    monkeypatch.setattr(init, "Path", fake_path)
    val = init.read_total_ram_gb()
    # 8_000_000 kB / (1024 * 1024) ≈ 7.629 GB
    assert 7.5 < val < 7.7


def test_write_config_writes_mode_and_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    # write_config uses Path.home() which honours HOME on Linux
    init.write_config(
        sync_repo="user/repo",
        workspace_dir=tmp_path / "sessions",
        machine_id="testbox",
        mode="headed",
        provider="openrouter",
    )
    config_text = (tmp_path / ".cam" / "config").read_text()
    assert "CAM_MODE=headed" in config_text
    assert "CAM_PROVIDER=openrouter" in config_text
    assert "CAM_SYNC_REPO=user/repo" in config_text
    assert "CAM_MACHINE_ID=testbox" in config_text


def test_write_config_local_mode_omits_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    init.write_config(
        sync_repo=None,
        workspace_dir=tmp_path / "sessions",
        machine_id="testbox",
        mode="local",
    )
    config_text = (tmp_path / ".cam" / "config").read_text()
    assert "CAM_MODE=local" in config_text
    assert "CAM_PROVIDER" not in config_text


def test_local_mode_min_ram_gb_constant_is_six():
    # The 6 GB threshold is decision-of-record (cam-lead 2026-04-17).
    # If you change it, update the artifact + README.
    assert init.LOCAL_MODE_MIN_RAM_GB == 6.0
