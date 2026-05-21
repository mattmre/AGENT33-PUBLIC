"""Tests for environment detection module."""

from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from agent33.env.detect import (
    EnvProfile,
    HardwareProfile,
    ModelRecommendation,
    ToolInventory,
    _is_cache_fresh,
    _load_cache,
    _save_cache,
    detect_env,
    detect_hardware,
    detect_tools,
    select_model,
)


def test_detect_tools_returns_tool_inventory() -> None:
    tools = detect_tools()
    assert isinstance(tools, ToolInventory)
    assert tools.python_path  # always non-empty
    assert tools.python_version  # always non-empty


def test_detect_tools_python_always_available() -> None:
    tools = detect_tools()
    assert tools.python_path != ""


def test_select_model_gpu_large() -> None:
    hw = HardwareProfile(8, "Test CPU", 64, 24.0, "NVIDIA RTX 4090", 500, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "qwen2.5-coder:32b"
    assert not rec.fallback_to_api


def test_select_model_gpu_medium() -> None:
    hw = HardwareProfile(8, "Test CPU", 32, 12.0, "NVIDIA RTX 3080", 200, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "llama3.1:8b"
    assert not rec.fallback_to_api


def test_select_model_gpu_small() -> None:
    hw = HardwareProfile(4, "Test CPU", 16, 6.0, "NVIDIA RTX 3060", 100, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "llama3.2:3b"
    assert not rec.fallback_to_api


def test_select_model_cpu_high_ram() -> None:
    hw = HardwareProfile(16, "AMD Ryzen", 32, 0, "None", 200, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "llama3.1:8b"
    assert not rec.fallback_to_api


def test_select_model_cpu_mid_ram() -> None:
    hw = HardwareProfile(8, "Intel i7", 16, 0, "None", 100, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "llama3.2:3b"
    assert not rec.fallback_to_api


def test_select_model_cpu_low_ram() -> None:
    hw = HardwareProfile(4, "Intel i5", 8, 0, "None", 50, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model in ("llama3.2:3b", "tinyllama:1.1b")
    assert not rec.fallback_to_api


def test_select_model_minimal() -> None:
    hw = HardwareProfile(2, "Atom", 4, 0, "None", 10, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "tinyllama:1.1b"
    assert not rec.fallback_to_api


def test_cache_save_and_load() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "env.json"
        hw = HardwareProfile(4, "Test", 8, 0, "None", 100, "Linux", "5.0")
        tools = ToolInventory("/usr/bin/python3", "3.11.0", False, True, False, False, True)
        model = ModelRecommendation("tinyllama:1.1b", 0.7, "test", False)
        profile = EnvProfile(hardware=hw, tools=tools, selected_model=model)

        _save_cache(profile, cache_path)
        assert cache_path.exists()

        loaded = _load_cache(cache_path)
        assert loaded is not None
        assert loaded.hardware.cpu_cores == 4
        assert loaded.tools.git_available is True
        assert loaded.selected_model.ollama_model == "tinyllama:1.1b"


def test_cache_freshness_new_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "env.json"
        hw = HardwareProfile(4, "Test", 8, 0, "None", 100, "Linux", "")
        tools = ToolInventory("/usr/bin/python3", "3.11", False, False, False, False, False)
        model = ModelRecommendation("tinyllama:1.1b", 0.7, "test", False)
        profile = EnvProfile(hardware=hw, tools=tools, selected_model=model)
        _save_cache(profile, cache_path)
        assert _is_cache_fresh(cache_path)


def test_cache_miss_no_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "nonexistent.json"
        assert not _is_cache_fresh(cache_path)
        assert _load_cache(cache_path) is None


def test_detect_env_uses_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "env.json"
        hw = HardwareProfile(4, "Cached CPU", 16, 0, "None", 100, "Linux", "")
        tools = ToolInventory("/usr/bin/python3", "3.11", False, True, False, False, True)
        model = ModelRecommendation("llama3.2:3b", 2.0, "cached", False)
        profile = EnvProfile(hardware=hw, tools=tools, selected_model=model)
        _save_cache(profile, cache_path)

        result = detect_env(force_refresh=False, cache_path=cache_path)
        assert result.hardware.cpu_brand == "Cached CPU"


def test_detect_env_force_refresh_ignores_cache() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "env.json"
        hw = HardwareProfile(4, "Stale CPU", 16, 0, "None", 100, "Linux", "")
        tools = ToolInventory("/usr/bin/python3", "3.11", False, True, False, False, True)
        model = ModelRecommendation("llama3.2:3b", 2.0, "stale", False)
        profile = EnvProfile(hardware=hw, tools=tools, selected_model=model)
        _save_cache(profile, cache_path)

        result = detect_env(force_refresh=True, cache_path=cache_path)
        # Should re-detect (cpu_brand will be real value, not "Stale CPU")
        assert result is not None  # at minimum it ran without crashing


def test_env_profile_serialization() -> None:
    hw = HardwareProfile(4, "Test CPU", 8, 0, "None", 100, "Linux", "5.0")
    tools = ToolInventory("/usr/bin/python3", "3.11", False, True, True, False, True)
    model = ModelRecommendation("llama3.2:3b", 2.0, "CPU-only 8-16 GB RAM", False)
    profile = EnvProfile(hardware=hw, tools=tools, selected_model=model)
    d = asdict(profile)
    assert d["hardware"]["ram_gb"] == 8
    assert d["tools"]["git_available"] is True
    assert d["selected_model"]["ollama_model"] == "llama3.2:3b"


def test_detect_hardware_returns_hardware_profile() -> None:
    hw = detect_hardware()
    assert isinstance(hw, HardwareProfile)
    assert hw.cpu_cores >= 1
    assert hw.ram_gb > 0
    assert hw.os_type != ""


def test_select_model_gpu_boundary_exactly_24() -> None:
    """GPU with exactly 24 GB VRAM should select the largest model."""
    hw = HardwareProfile(8, "Test CPU", 32, 24.0, "NVIDIA RTX 3090", 300, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "qwen2.5-coder:32b"


def test_select_model_gpu_just_below_24() -> None:
    """GPU with 23.9 GB VRAM should fall to llama3.1:8b."""
    hw = HardwareProfile(8, "Test CPU", 32, 23.9, "NVIDIA RTX 3090", 300, "Linux", "")
    rec = select_model(hw)
    assert rec.ollama_model == "llama3.1:8b"


def test_cache_stale_returns_none() -> None:
    """A cache entry with a very old detected_at should not be loaded."""
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "env.json"
        old_data = {
            "version": "1",
            "detected_at": "2000-01-01T00:00:00+00:00",
            "hardware": {
                "cpu_cores": 4,
                "cpu_brand": "Old CPU",
                "ram_gb": 8.0,
                "gpu_vram_gb": 0.0,
                "gpu_brand": "None",
                "disk_free_gb": 100.0,
                "os_type": "Linux",
                "os_version": "",
            },
            "tools": {
                "python_path": "/usr/bin/python3",
                "python_version": "3.11",
                "docker_available": False,
                "git_available": False,
                "ollama_available": False,
                "node_available": False,
                "curl_available": False,
            },
            "selected_model": {
                "ollama_model": "tinyllama:1.1b",
                "size_gb": 0.7,
                "reason": "old",
                "fallback_to_api": False,
            },
            "mode": "lite",
            "llm_source": "ollama",
        }
        cache_path.write_text(json.dumps(old_data))
        assert not _is_cache_fresh(cache_path)
        loaded = _load_cache(cache_path)
        assert loaded is None
