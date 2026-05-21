"""Tests for the first-run wizard (P64).

Tests verify:
- WizardResult is populated correctly for each step
- Profile selection flows through to result.profile
- LLM provider paths (openai / ollama / skip) populate result correctly
- Test invocation is skipped when provider is "skip"
- Template selection populates result.template
- .env.local is written with correct content
- Wizard is graceful when env detection is unavailable
- Unknown Ollama responses fall back to default model
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from agent33.cli.wizard import (
    QUICK_TEMPLATES,
    TEMPLATE_NAMES,
    FirstRunWizard,
    WizardResult,
    _build_env_lines,
    _stream_test_response,
    _write_env,
)

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

# ---------------------------------------------------------------------------
# Mock I/O helper
# ---------------------------------------------------------------------------


class MockIO:
    """Scriptable I/O for testing.

    Provide ``answers`` as a list of strings; each call to ``prompt``,
    ``confirm``, or ``secret`` consumes the next answer.
    """

    def __init__(self, answers: list[str]) -> None:
        self._answers: Iterator[str] = iter(answers)
        self.messages: list[str] = []

    def info(self, text: str) -> None:
        self.messages.append(text)

    def prompt(
        self,
        question: str,
        choices: list[str] | None = None,
        default: str | None = None,
    ) -> str:
        try:
            return next(self._answers)
        except StopIteration:
            return default or (choices[0] if choices else "")

    def confirm(self, question: str, default: bool = True) -> bool:
        try:
            raw = next(self._answers).strip().lower()
            return raw in ("y", "yes", "true", "1")
        except StopIteration:
            return default

    def secret(self, question: str) -> str:
        try:
            return next(self._answers)
        except StopIteration:
            return ""


@pytest.fixture(autouse=True)
def _restore_llm_api_keys() -> Generator[None, None, None]:
    openai_api_key = os.environ.get("OPENAI_API_KEY")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    try:
        yield
    finally:
        _restore_env_var("OPENAI_API_KEY", openai_api_key)
        _restore_env_var("OPENROUTER_API_KEY", openrouter_api_key)


def _wizard(answers: list[str], tmp_path: Path) -> WizardResult:
    """Convenience: run the wizard with scripted answers into a tmp env file."""
    io = MockIO(answers)
    w = FirstRunWizard(io=io, env_path=tmp_path / ".env.local")
    return w.run()


def _restore_env_var(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


# ---------------------------------------------------------------------------
# Profile selection (step 1)
# ---------------------------------------------------------------------------


def test_wizard_chooses_developer_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=[
            "developer",  # step 1 profile
            "skip",  # step 2 provider
            "None — I'll configure manually",  # step 4 template
        ],
        tmp_path=tmp_path,
    )
    assert result.profile == "developer"
    assert result.completed is True


def test_wizard_chooses_production_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["production", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.profile == "production"


def test_wizard_chooses_minimal_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["minimal", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.profile == "minimal"


def test_wizard_forces_fresh_environment_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[bool] = []

    def _record_detect(*, force_refresh: bool = False) -> object:
        captured.append(force_refresh)
        return SimpleNamespace(
            hardware=SimpleNamespace(cpu_cores=8, ram_gb=16.0, gpu_vram_gb=None, gpu_brand=None),
            tools=SimpleNamespace(ollama_available=True, docker_available=True),
            selected_model=SimpleNamespace(ollama_model="llama3.2:3b"),
            mode="standard",
        )

    monkeypatch.setattr("agent33.cli.wizard.detect_env", _record_detect, raising=False)

    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )

    assert captured == [True]
    assert result.profile == "developer"


def test_wizard_retries_environment_detection_without_force_refresh_kwarg(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[str] = []

    def _legacy_detect() -> object:
        captured.append("retried-without-kwarg")
        return SimpleNamespace(
            hardware=SimpleNamespace(cpu_cores=8, ram_gb=16.0, gpu_vram_gb=None, gpu_brand=None),
            tools=SimpleNamespace(ollama_available=True, docker_available=True),
            selected_model=SimpleNamespace(ollama_model="llama3.2:3b"),
            mode="standard",
        )

    monkeypatch.setattr("agent33.cli.wizard.detect_env", _legacy_detect, raising=False)

    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )

    assert captured == ["retried-without-kwarg"]
    assert result.profile == "developer"


# ---------------------------------------------------------------------------
# LLM provider paths (step 2)
# ---------------------------------------------------------------------------


def test_wizard_skip_provider(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "skip"
    assert result.api_key_set is False
    assert "test_invocation_skipped" in result.steps_completed


def test_wizard_openai_provider_sets_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    # Step 3 confirm=no so we don't actually call OpenAI
    result = _wizard(
        answers=[
            "developer",
            "openai",
            "sk-test-key-12345",
            "no",
            "None — I'll configure manually",
        ],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "openai"
    assert result.api_key_set is True
    assert result.llm_model == "gpt-4o-mini"
    assert result.entered_api_key == "sk-test-key-12345"


def test_wizard_openrouter_provider_sets_api_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=[
            "developer",
            "openrouter",
            "sk-or-test-key-12345",
            "no",
            "None — I'll configure manually",
        ],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "openrouter"
    assert result.api_key_set is True
    assert result.llm_model == "openrouter/auto"
    assert result.entered_api_key == "sk-or-test-key-12345"


def test_wizard_openai_empty_key_does_not_set_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)  # ensure no ambient key
    result = _wizard(
        answers=["developer", "openai", "", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "openai"
    assert result.api_key_set is False
    assert result.entered_api_key is None


def test_wizard_openai_preexisting_env_key_sets_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If OPENAI_API_KEY already exists in env and user leaves blank, api_key_set is True."""
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-preexisting-key")
    result = _wizard(
        answers=["developer", "openai", "", "no", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "openai"
    assert result.api_key_set is True
    assert result.llm_model == "gpt-4o-mini"
    # User did not enter a new key, so entered_api_key should be None
    assert result.entered_api_key is None


def test_wizard_ollama_provider_without_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)  # no ollama binary
    result = _wizard(
        answers=["developer", "ollama", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "ollama"
    # No model set because ollama not installed
    assert result.llm_model is None


def test_wizard_ollama_without_binary_skips_test_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda _: None)
    result = _wizard(
        answers=["developer", "ollama", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.template is None
    assert "test_invocation_skipped" in result.steps_completed
    assert "test_invocation" not in result.steps_completed


def test_wizard_ollama_provider_with_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr("agent33.cli.wizard._pick_ollama_model", lambda: "llama3.2:3b")
    result = _wizard(
        answers=["developer", "ollama", "no", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_provider == "ollama"
    assert result.llm_model == "llama3.2:3b"


# ---------------------------------------------------------------------------
# Test invocation (step 3)
# ---------------------------------------------------------------------------


def test_wizard_skips_test_invocation_when_provider_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert "test_invocation_skipped" in result.steps_completed
    assert "test_invocation" not in result.steps_completed


def test_wizard_skips_test_invocation_when_user_declines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr("agent33.cli.wizard._pick_ollama_model", lambda: "llama3.2:3b")
    result = _wizard(
        answers=["developer", "ollama", "no", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    # "no" answers confirm=False for test invocation
    assert "test_invocation_skipped" in result.steps_completed


def test_wizard_skips_test_invocation_when_ollama_model_detection_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr(
        "agent33.cli.wizard._pick_ollama_model",
        lambda: (_ for _ in ()).throw(RuntimeError("no local models")),
    )
    result = _wizard(
        answers=["developer", "ollama", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.llm_model == "llama3.2:3b"
    assert result.template is None
    assert "test_invocation_skipped" in result.steps_completed
    assert "test_invocation" not in result.steps_completed


def test_wizard_test_invocation_failure_is_graceful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr("agent33.cli.wizard._pick_ollama_model", lambda: "llama3.2:3b")
    monkeypatch.setattr(
        "agent33.cli.wizard._stream_test_response",
        lambda _result, _io: (_ for _ in ()).throw(RuntimeError("connection refused")),
    )
    result = _wizard(
        answers=["developer", "ollama", "yes", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    # Wizard still completes even if test invocation throws
    assert result.completed is True


# ---------------------------------------------------------------------------
# Template picker (step 4)
# ---------------------------------------------------------------------------


def test_wizard_picks_first_template_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    first_label = QUICK_TEMPLATES[0]["label"] + " — " + QUICK_TEMPLATES[0]["description"]
    result = _wizard(
        answers=["developer", "skip", first_label],
        tmp_path=tmp_path,
    )
    assert result.template == QUICK_TEMPLATES[0]["name"]


def test_wizard_picks_research_assistant_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    tmpl = next(t for t in QUICK_TEMPLATES if t["name"] == "research-assistant")
    label = f"{tmpl['label']} — {tmpl['description']}"
    result = _wizard(
        answers=["developer", "skip", label],
        tmp_path=tmp_path,
    )
    assert result.template == "research-assistant"


def test_wizard_no_template_leaves_template_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.template is None


def test_template_names_are_all_present() -> None:
    assert "personal-assistant" in TEMPLATE_NAMES
    assert "research-assistant" in TEMPLATE_NAMES
    assert "document-summarizer" in TEMPLATE_NAMES
    assert "code-reviewer" in TEMPLATE_NAMES
    assert "data-extractor" in TEMPLATE_NAMES
    assert len(QUICK_TEMPLATES) == 5


# ---------------------------------------------------------------------------
# .env.local output (step 5)
# ---------------------------------------------------------------------------


def test_wizard_writes_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.env_written is True
    env_file = tmp_path / ".env.local"
    assert env_file.exists()
    content = env_file.read_text()
    assert "AGENT33_PROFILE=developer" in content


def test_wizard_env_contains_ollama_url_when_ollama_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr("agent33.cli.wizard._pick_ollama_model", lambda: "llama3.2:3b")
    _wizard(
        answers=["developer", "ollama", "no", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    content = (tmp_path / ".env.local").read_text()
    assert "OLLAMA_BASE_URL=http://localhost:11434" in content
    assert "DEFAULT_MODEL=llama3.2:3b" in content


def test_wizard_env_preserves_custom_ollama_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    monkeypatch.setattr("shutil.which", lambda cmd: "/usr/bin/ollama" if cmd == "ollama" else None)
    monkeypatch.setattr("agent33.cli.wizard._pick_ollama_model", lambda: "llama3.2:3b")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.remote:11434")
    _wizard(
        answers=["developer", "ollama", "no", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    content = (tmp_path / ".env.local").read_text()
    assert "OLLAMA_BASE_URL=http://ollama.remote:11434" in content


def test_wizard_env_contains_template_when_chosen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    tmpl = QUICK_TEMPLATES[2]  # document-summarizer
    label = f"{tmpl['label']} — {tmpl['description']}"
    _wizard(
        answers=["developer", "skip", label],
        tmp_path=tmp_path,
    )
    content = (tmp_path / ".env.local").read_text()
    assert "AGENT33_DEFAULT_TEMPLATE=document-summarizer" in content


def test_env_file_appended_not_overwritten(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text("EXISTING_VAR=keep_me\n", encoding="utf-8")

    result = WizardResult(profile="minimal", llm_provider="skip", env_path=env_path)
    lines = _build_env_lines(result)
    _write_env(env_path, lines)

    content = env_path.read_text()
    assert "EXISTING_VAR=keep_me" in content
    assert "AGENT33_PROFILE=minimal" in content


def test_write_env_deduplicates_on_rerun(tmp_path: Path) -> None:
    """Running wizard twice must not produce duplicate AGENT33_PROFILE entries."""
    env_path = tmp_path / ".env.local"

    # First run — developer profile
    result1 = WizardResult(profile="developer", llm_provider="skip", env_path=env_path)
    _write_env(env_path, _build_env_lines(result1))
    content_after_first = env_path.read_text()
    assert content_after_first.count("AGENT33_PROFILE=") == 1

    # Second run — production profile
    result2 = WizardResult(profile="production", llm_provider="skip", env_path=env_path)
    _write_env(env_path, _build_env_lines(result2))
    content_after_second = env_path.read_text()

    # Only one AGENT33_PROFILE entry, and it's the new one
    assert content_after_second.count("AGENT33_PROFILE=") == 1
    assert "AGENT33_PROFILE=production" in content_after_second
    assert "AGENT33_PROFILE=developer" not in content_after_second


def test_write_env_preserves_pre_wizard_content_on_rerun(tmp_path: Path) -> None:
    """Hand-edited lines before the wizard marker are preserved across reruns."""
    env_path = tmp_path / ".env.local"
    env_path.write_text("HAND_EDITED=keep_me\n", encoding="utf-8")

    result = WizardResult(profile="minimal", llm_provider="skip", env_path=env_path)
    _write_env(env_path, _build_env_lines(result))
    # Rerun with different profile
    result2 = WizardResult(profile="enterprise", llm_provider="skip", env_path=env_path)
    _write_env(env_path, _build_env_lines(result2))

    content = env_path.read_text()
    assert "HAND_EDITED=keep_me" in content
    assert "AGENT33_PROFILE=enterprise" in content
    assert "AGENT33_PROFILE=minimal" not in content


# ---------------------------------------------------------------------------
# build_env_lines unit tests
# ---------------------------------------------------------------------------


def test_build_env_lines_skip_provider() -> None:
    result = WizardResult(profile="developer", llm_provider="skip")
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "AGENT33_PROFILE=developer" in joined
    assert "OPENAI" not in joined
    assert "OLLAMA" not in joined


def test_build_env_lines_openai_with_entered_key() -> None:
    result = WizardResult(
        profile="production",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        api_key_set=True,
        entered_api_key="sk-test-abc",
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "OPENAI_API_KEY=sk-test-abc" in joined
    assert "DEFAULT_MODEL=gpt-4o-mini" in joined


def test_build_env_lines_openrouter_with_entered_key() -> None:
    result = WizardResult(
        profile="production",
        llm_provider="openrouter",
        llm_model="openrouter/auto",
        api_key_set=True,
        entered_api_key="sk-or-test-abc",
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "OPENROUTER_API_KEY=sk-or-test-abc" in joined
    assert "DEFAULT_MODEL=openrouter/auto" in joined


def test_build_env_lines_openai_without_entered_key_omits_api_key() -> None:
    """If api_key_set from env but user didn't enter a key, don't write it to .env.local."""
    result = WizardResult(
        profile="production",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        api_key_set=True,
        entered_api_key=None,
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "OPENAI_API_KEY" not in joined
    assert "DEFAULT_MODEL=gpt-4o-mini" in joined


def test_build_env_lines_ollama() -> None:
    result = WizardResult(
        profile="minimal",
        llm_provider="ollama",
        llm_model="llama3.1:8b",
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "OLLAMA_BASE_URL=http://localhost:11434" in joined
    assert "DEFAULT_MODEL=llama3.1:8b" in joined


def test_build_env_lines_ollama_reuses_existing_env_file_url(tmp_path: Path) -> None:
    env_path = tmp_path / ".env.local"
    env_path.write_text("OLLAMA_BASE_URL=http://ollama.internal:11434\n", encoding="utf-8")
    result = WizardResult(
        profile="minimal",
        llm_provider="ollama",
        llm_model="llama3.2:3b",
        env_path=env_path,
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "OLLAMA_BASE_URL=http://ollama.internal:11434" in joined


def test_stream_test_response_ollama_uses_resolved_base_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"response": "hello"}

    class FakeClient:
        def __init__(self, *, timeout: int) -> None:
            captured["timeout"] = timeout

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, json: dict[str, object]) -> FakeResponse:
            captured["url"] = url
            captured["json"] = json
            return FakeResponse()

    io = MockIO([])
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.remote:11434")
    monkeypatch.setattr("httpx.Client", FakeClient)

    _stream_test_response(
        WizardResult(llm_provider="ollama", llm_model="llama3.2:3b"),
        io,
    )

    assert captured["url"] == "http://ollama.remote:11434/api/generate"
    assert captured["json"] == {
        "model": "llama3.2:3b",
        "prompt": "What can you do? (answer in 2 sentences)",
        "stream": False,
    }
    assert io.messages[-1] == "hello"


def test_build_env_lines_with_template() -> None:
    result = WizardResult(
        profile="developer",
        llm_provider="skip",
        template="code-reviewer",
    )
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "AGENT33_DEFAULT_TEMPLATE=code-reviewer" in joined


def test_build_env_lines_no_template() -> None:
    result = WizardResult(profile="developer", llm_provider="skip", template=None)
    lines = _build_env_lines(result)
    joined = "\n".join(lines)
    assert "AGENT33_DEFAULT_TEMPLATE" not in joined


# ---------------------------------------------------------------------------
# Graceful env detection failure
# ---------------------------------------------------------------------------


def test_wizard_handles_missing_env_detection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If env detection raises, wizard falls back gracefully."""
    monkeypatch.setattr("agent33.cli.wizard.detect_env", _failing_detect, raising=False)
    result = _wizard(
        answers=["developer", "skip", "None — I'll configure manually"],
        tmp_path=tmp_path,
    )
    assert result.completed is True
    assert result.profile == "developer"


def test_wizard_full_happy_path_completes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Full happy path: env ok, skip provider, pick template, complete."""
    from unittest.mock import MagicMock

    fake_env = MagicMock()
    fake_env.hardware.cpu_cores = 8
    fake_env.hardware.ram_gb = 16.0
    fake_env.hardware.gpu_vram_gb = 0.0
    fake_env.hardware.gpu_brand = ""
    fake_env.tools.ollama_available = False
    fake_env.tools.docker_available = False
    fake_env.selected_model.ollama_model = "llama3.2:3b"
    fake_env.mode = "lite"

    monkeypatch.setattr("agent33.cli.wizard.detect_env", lambda: fake_env)

    result = _wizard(
        answers=[
            "developer",  # step 1 profile
            "skip",  # step 2 provider
            "Personal Assistant — Task management, questions, and planning",  # step 4
        ],
        tmp_path=tmp_path,
    )
    assert result.completed is True
    assert result.profile == "developer"
    assert result.template == "personal-assistant"
    assert result.env_written is True
    assert "environment" in result.steps_completed
    assert "llm_provider" in result.steps_completed
    assert "template" in result.steps_completed
    assert "complete" in result.steps_completed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _failing_detect() -> None:
    """Stand-in for detect_env that raises — tests graceful fallback."""
    raise ImportError("env detection not available")
