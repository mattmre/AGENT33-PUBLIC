"""Environment detection and self-adaptation for AGENT-33.

Standalone module -- does not depend on FastAPI lifespan.
Run before or independently of the server.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)

ENV_CACHE_PATH = Path.home() / ".agent33" / "env.json"
CACHE_TTL_DAYS = 30

# Model selection matrix -- exact Ollama model names
# (min_vram_gb, min_ram_gb, requires_gpu, ollama_model, size_gb, reason)
MODEL_MATRIX = [
    (24.0, 0, True, "qwen2.5-coder:32b", 19.0, "GPU >=24 GB VRAM"),
    (12.0, 0, True, "llama3.1:8b", 4.7, "GPU 12-16 GB VRAM"),
    (6.0, 0, True, "llama3.2:3b", 2.0, "GPU 6-8 GB VRAM"),
    (0, 32, False, "llama3.1:8b", 4.7, "CPU-only, >=32 GB RAM"),
    (0, 16, False, "llama3.2:3b", 2.0, "CPU-only, 16-32 GB RAM"),
    (0, 8, False, "llama3.2:3b", 2.0, "CPU-only, 8-16 GB RAM"),
    (0, 0, False, "tinyllama:1.1b", 0.7, "CPU-only, <8 GB RAM"),
]


@dataclass
class HardwareProfile:
    cpu_cores: int
    cpu_brand: str
    ram_gb: float
    gpu_vram_gb: float
    gpu_brand: str
    disk_free_gb: float
    os_type: str
    os_version: str


@dataclass
class ToolInventory:
    python_path: str
    python_version: str
    docker_available: bool
    git_available: bool
    ollama_available: bool
    node_available: bool
    curl_available: bool


@dataclass
class ModelRecommendation:
    ollama_model: str
    size_gb: float
    reason: str
    fallback_to_api: bool


@dataclass
class EnvProfile:
    version: str = "1"
    detected_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    hardware: HardwareProfile = field(
        default_factory=lambda: HardwareProfile(0, "", 0, 0, "", 0, "", "")
    )
    tools: ToolInventory = field(
        default_factory=lambda: ToolInventory("", "", False, False, False, False, False)
    )
    selected_model: ModelRecommendation = field(
        default_factory=lambda: ModelRecommendation("tinyllama:1.1b", 0.7, "default", False)
    )
    mode: str = "lite"
    llm_source: str = "ollama"


def _run(cmd: list[str], timeout: int = 5) -> str:
    """Run a command and return stdout, empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def detect_hardware() -> HardwareProfile:
    """Detect CPU, RAM, GPU, disk, and OS information."""
    try:
        import psutil

        ram_gb = psutil.virtual_memory().total / (1024**3)
        disk_free_gb = psutil.disk_usage("/").free / (1024**3)
        cpu_count = psutil.cpu_count(logical=False) or psutil.cpu_count() or 1
    except ImportError:
        ram_gb = 0.0
        disk_free_gb = 0.0
        cpu_count = os.cpu_count() or 1

    # CPU brand
    cpu_brand = platform.processor() or "Unknown"

    # GPU detection
    gpu_vram_gb = 0.0
    gpu_brand = "None"

    # NVIDIA via nvidia-smi (Windows-safe -- avoids WMI AdapterRAM 4 GB cap)
    nvidia_out = _run(
        ["nvidia-smi", "--query-gpu=memory.total,name", "--format=csv,noheader,nounits"]
    )
    if nvidia_out:
        lines = nvidia_out.strip().split("\n")
        for line in lines:
            parts = line.split(",")
            if len(parts) >= 2:
                try:
                    vram_mb = float(parts[0].strip())
                    gpu_vram_gb = max(gpu_vram_gb, vram_mb / 1024)
                    gpu_brand = parts[1].strip()
                except ValueError:
                    pass

    # AMD via rocm-smi (Linux)
    if gpu_vram_gb == 0:
        rocm_out = _run(["rocm-smi", "--showmeminfo", "vram", "--json"])
        if rocm_out:
            try:
                data = json.loads(rocm_out)
                for card in data.values():
                    if isinstance(card, dict):
                        vram_bytes = card.get("VRAM Total Memory (B)", 0)
                        gpu_vram_gb = max(gpu_vram_gb, int(vram_bytes) / (1024**3))
                        gpu_brand = "AMD"
            except (json.JSONDecodeError, ValueError):
                pass

    # Apple Silicon unified memory (macOS)
    if sys.platform == "darwin" and gpu_vram_gb == 0:
        sp_out = _run(["system_profiler", "SPHardwareDataType"])
        if "Apple" in sp_out and (
            "M1" in sp_out or "M2" in sp_out or "M3" in sp_out or "M4" in sp_out
        ):
            # Unified memory -- use full RAM as VRAM approximation
            gpu_vram_gb = ram_gb
            gpu_brand = "Apple Silicon (unified)"

    return HardwareProfile(
        cpu_cores=cpu_count,
        cpu_brand=cpu_brand,
        ram_gb=round(ram_gb, 1),
        gpu_vram_gb=round(gpu_vram_gb, 1),
        gpu_brand=gpu_brand,
        disk_free_gb=round(disk_free_gb, 1),
        os_type=platform.system(),
        os_version=platform.version(),
    )


def detect_tools() -> ToolInventory:
    """Detect available tools via shutil.which()."""
    return ToolInventory(
        python_path=sys.executable,
        python_version=platform.python_version(),
        docker_available=shutil.which("docker") is not None,
        git_available=shutil.which("git") is not None,
        ollama_available=shutil.which("ollama") is not None,
        node_available=shutil.which("node") is not None,
        curl_available=shutil.which("curl") is not None,
    )


def select_model(hw: HardwareProfile) -> ModelRecommendation:
    """Select the most capable Ollama model that fits the hardware profile."""
    has_gpu = hw.gpu_vram_gb > 0

    for min_vram, min_ram, req_gpu, model, size, reason in MODEL_MATRIX:
        if req_gpu and not has_gpu:
            continue
        if req_gpu and hw.gpu_vram_gb < min_vram:
            continue
        if not req_gpu and hw.ram_gb < min_ram:
            continue
        return ModelRecommendation(
            ollama_model=model,
            size_gb=size,
            reason=reason,
            fallback_to_api=False,
        )

    # No local inference capable hardware
    return ModelRecommendation(
        ollama_model="",
        size_gb=0,
        reason="No local inference capable hardware detected",
        fallback_to_api=True,
    )


def _is_cache_fresh(cache_path: Path) -> bool:
    """Check if the cache file exists and is within TTL."""
    if not cache_path.exists():
        return False
    try:
        data = json.loads(cache_path.read_text())
        detected_at = datetime.fromisoformat(data.get("detected_at", "2000-01-01"))
        age_days = (datetime.now(UTC) - detected_at).days
        return age_days < CACHE_TTL_DAYS
    except Exception:
        return False


def _save_cache(profile: EnvProfile, cache_path: Path = ENV_CACHE_PATH) -> None:
    """Save environment profile to cache."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(asdict(profile), indent=2))


def _load_cache(cache_path: Path = ENV_CACHE_PATH) -> EnvProfile | None:
    """Load environment profile from cache if fresh."""
    if not _is_cache_fresh(cache_path):
        return None
    try:
        data = json.loads(cache_path.read_text())
        hw = HardwareProfile(**data["hardware"])
        tools = ToolInventory(**data["tools"])
        model = ModelRecommendation(**data["selected_model"])
        return EnvProfile(
            version=data.get("version", "1"),
            detected_at=data["detected_at"],
            hardware=hw,
            tools=tools,
            selected_model=model,
            mode=data.get("mode", "lite"),
            llm_source=data.get("llm_source", "ollama"),
        )
    except Exception:
        return None


def detect_env(force_refresh: bool = False, cache_path: Path = ENV_CACHE_PATH) -> EnvProfile:
    """Run full environment detection, using cache if available."""
    if not force_refresh:
        cached = _load_cache(cache_path)
        if cached is not None:
            return cached

    hw = detect_hardware()
    tools = detect_tools()
    model = select_model(hw)
    llm_source = (
        "api" if model.fallback_to_api else ("ollama" if tools.ollama_available else "api")
    )
    mode = "lite" if not tools.docker_available else "standard"

    profile = EnvProfile(
        hardware=hw,
        tools=tools,
        selected_model=model,
        mode=mode,
        llm_source=llm_source,
    )
    _save_cache(profile, cache_path)
    return profile
