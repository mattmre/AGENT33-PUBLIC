"""First-run setup wizard for AGENT-33.

Guides a first-time user from a blank install to a working agent in <15 minutes
without editing any files manually.

5-step flow
-----------
1. Environment Summary  — show hardware + tool detection, suggest profile
2. LLM Provider         — OpenRouter, OpenAI, Ollama, or skip
3. Test Invocation      — ask "What can you do?" and stream a response (skipped
                          if provider was skipped or not reachable)
4. Template Picker      — choose a quick-start agent template
5. Done                 — write config to .env.local, show next steps

Design
------
All terminal I/O is delegated to a ``WizardIO`` protocol so the wizard logic
is fully testable without a live terminal.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field

try:
    from agent33.env.detect import detect_env
except ImportError:  # pragma: no cover

    def detect_env(force_refresh: bool = False) -> object:  # type: ignore[misc]
        del force_refresh
        raise ImportError("agent33.env.detect not available")


from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from agent33.env.detect import EnvProfile

# ---------------------------------------------------------------------------
# I/O protocol — the only thing tests need to replace
# ---------------------------------------------------------------------------

STEP_SEPARATOR = "─" * 60


@runtime_checkable
class WizardIO(Protocol):
    """Minimal I/O surface required by ``FirstRunWizard``."""

    def info(self, text: str) -> None:
        """Print an informational message."""

    def prompt(
        self,
        question: str,
        choices: list[str] | None = None,
        default: str | None = None,
    ) -> str:
        """Ask the user a question; return their answer."""

    def confirm(self, question: str, default: bool = True) -> bool:
        """Ask a yes/no question; return True for yes."""

    def secret(self, question: str) -> str:
        """Ask for a secret value (not echoed)."""


class TerminalWizardIO:
    """Real terminal I/O backed by ``rich`` + ``getpass``."""

    def __init__(self) -> None:
        try:
            from rich.console import Console

            self._console = Console()
        except ImportError:  # pragma: no cover
            self._console = None  # type: ignore[assignment]

    def info(self, text: str) -> None:
        if self._console:
            self._console.print(text)
        else:
            print(text)  # noqa: T201

    def prompt(
        self,
        question: str,
        choices: list[str] | None = None,
        default: str | None = None,
    ) -> str:
        if choices:
            numbered = "\n".join(f"  {i + 1}. {c}" for i, c in enumerate(choices))
            self.info(f"\n{question}\n{numbered}")
            default_hint = f" [default: {default}]" if default else ""
            while True:
                raw = input(f"Enter number or name{default_hint}: ").strip()
                if not raw and default:
                    return default
                # Accept number
                if raw.isdigit():
                    idx = int(raw) - 1
                    if 0 <= idx < len(choices):
                        return choices[idx]
                # Accept exact name
                if raw in choices:
                    return raw
                self.info(
                    f"  Please enter a number between 1 and {len(choices)}"
                    " or a name from the list."
                )
        else:
            default_hint = f" [{default}]" if default else ""
            raw = input(f"{question}{default_hint}: ").strip()
            return raw if raw else (default or "")

    def confirm(self, question: str, default: bool = True) -> bool:
        hint = "[Y/n]" if default else "[y/N]"
        raw = input(f"{question} {hint}: ").strip().lower()
        if not raw:
            return default
        return raw in ("y", "yes")

    def secret(self, question: str) -> str:
        import getpass

        return getpass.getpass(f"{question}: ")


# ---------------------------------------------------------------------------
# Templates (quick-start library shown in step 4)
# ---------------------------------------------------------------------------

QUICK_TEMPLATES: list[dict[str, str]] = [
    {
        "name": "personal-assistant",
        "label": "Personal Assistant",
        "description": "Task management, questions, and planning",
    },
    {
        "name": "research-assistant",
        "label": "Research Assistant",
        "description": "Topic → structured report",
    },
    {
        "name": "document-summarizer",
        "label": "Document Summarizer",
        "description": "File or URL → concise summary",
    },
    {
        "name": "code-reviewer",
        "label": "Code Reviewer",
        "description": "Pull request or diff → analysis",
    },
    {
        "name": "data-extractor",
        "label": "Data Extractor",
        "description": "Unstructured text → structured JSON",
    },
]

TEMPLATE_NAMES = [t["name"] for t in QUICK_TEMPLATES]
_OLLAMA_DEFAULT_BASE_URL = "http://localhost:11434"


def _detect_environment(*, force_refresh: bool = False) -> EnvProfile:
    """Run environment detection, forcing a fresh probe when supported."""
    try:
        return detect_env(force_refresh=force_refresh)
    except TypeError:
        return detect_env()


def _existing_env_value(path: Path, key: str) -> str | None:
    """Return the last assignment for ``key`` from an existing env file."""
    if not path.exists():
        return None

    for raw_line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.strip() == key:
            return value.strip()

    return None


def _resolve_ollama_base_url(path: Path | None = None) -> str:
    """Prefer explicit env/file Ollama URLs before falling back to localhost."""
    env_value = os.environ.get("OLLAMA_BASE_URL", "").strip()
    if env_value:
        return env_value

    if path is not None:
        existing_value = _existing_env_value(path, "OLLAMA_BASE_URL")
        if existing_value:
            return existing_value

    return _OLLAMA_DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class WizardResult:
    """Captures the choices made during the wizard run."""

    profile: str = "developer"
    llm_provider: str = "skip"  # "openrouter" | "openai" | "ollama" | "skip"
    llm_model: str | None = None
    ollama_base_url: str | None = None
    api_key_set: bool = False
    entered_api_key: str | None = None  # key user explicitly typed (not from env)
    llm_test_ready: bool = False
    template: str | None = None
    env_path: Path = field(default_factory=lambda: Path(".env.local"))
    env_written: bool = False
    completed: bool = False
    steps_completed: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Wizard
# ---------------------------------------------------------------------------


class FirstRunWizard:
    """Interactive 5-step first-run wizard.

    Parameters
    ----------
    io:
        I/O implementation.  Use ``TerminalWizardIO()`` for live terminals or
        ``MockWizardIO(answers)`` in tests.
    env_path:
        Where to write the generated ``.env.local``.  Defaults to the current
        working directory.
    """

    def __init__(
        self,
        io: WizardIO | None = None,
        env_path: Path | None = None,
    ) -> None:
        self._io: WizardIO = io or TerminalWizardIO()
        self._env_path = env_path or Path(".env.local")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> WizardResult:
        """Execute the full wizard flow.  Returns the collected choices."""
        result = WizardResult(env_path=self._env_path)

        self._io.info("\n" + STEP_SEPARATOR)
        self._io.info("  Welcome to AGENT-33  —  First-Run Setup")
        self._io.info(STEP_SEPARATOR)
        self._io.info(
            "This wizard will guide you through initial configuration.\n"
            "It takes about 5 minutes.  Press Ctrl-C at any time to quit.\n"
        )

        self._step_environment(result)
        self._step_llm_provider(result)
        self._step_test_invocation(result)
        self._step_template(result)
        self._step_complete(result)

        result.completed = True
        return result

    # ------------------------------------------------------------------
    # Step 1 — Environment Summary
    # ------------------------------------------------------------------

    def _step_environment(self, result: WizardResult) -> None:
        self._io.info(f"\n{STEP_SEPARATOR}")
        self._io.info("  Step 1 of 5 — Environment Summary")
        self._io.info(STEP_SEPARATOR)

        try:
            env = _detect_environment(force_refresh=True)
            hw = env.hardware
            tools = env.tools
            rec = env.selected_model

            self._io.info(f"  CPU cores   : {hw.cpu_cores}")
            self._io.info(f"  RAM         : {hw.ram_gb:.1f} GB")
            if hw.gpu_vram_gb:
                self._io.info(
                    f"  VRAM        : {hw.gpu_vram_gb:.1f} GB  ({hw.gpu_brand or 'GPU'})"
                )
            self._io.info(
                f"  Ollama      : {'✓ installed' if tools.ollama_available else '✗ not found'}"
            )
            self._io.info(f"  Docker      : {'✓' if tools.docker_available else '✗ not found'}")
            self._io.info(f"\n  Recommended model  : {rec.ollama_model}")
            suggested_profile = _mode_to_profile(env.mode)
            self._io.info(f"  Recommended profile: {suggested_profile}")
        except Exception:
            # If env detection is unavailable fall back gracefully
            self._io.info("  (Environment detection unavailable — using defaults)")
            suggested_profile = "developer"

        # Let user choose / override profile
        profile_choices = ["minimal", "developer", "production", "enterprise", "airgapped"]
        chosen = self._io.prompt(
            "\nWhich configuration profile would you like to use?",
            choices=profile_choices,
            default=suggested_profile,
        )
        result.profile = chosen
        result.steps_completed.append("environment")
        self._io.info(f"  ✓ Profile: {chosen}")

    # ------------------------------------------------------------------
    # Step 2 — LLM Provider
    # ------------------------------------------------------------------

    def _step_llm_provider(self, result: WizardResult) -> None:
        self._io.info(f"\n{STEP_SEPARATOR}")
        self._io.info("  Step 2 of 5 — LLM Provider")
        self._io.info(STEP_SEPARATOR)
        self._io.info(
            "AGENT-33 needs an LLM to work.  Choose a provider:\n"
            "  • OpenRouter  — one API key, many hosted models\n"
            "  • OpenAI API  — direct OpenAI access\n"
            "  • Ollama      — runs locally, free, requires ~4GB+ RAM\n"
            "  • Skip        — configure manually later\n"
        )

        choice = self._io.prompt(
            "Which provider?",
            choices=["openrouter", "openai", "ollama", "skip"],
            default="skip",
        )

        if choice == "openrouter":
            self._io.info(
                "\n  Get your API key at: https://openrouter.ai/keys\n"
                "  Model refs use forms like `openrouter/auto` or\n"
                "  `openrouter/openai/gpt-5.2`.\n"
                "  (The key will be written to your .env.local — never committed to git.)\n"
            )
            existing_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
            key = self._io.secret("  Paste your OpenRouter API key").strip()
            effective_key = key or existing_key
            result.api_key_set = bool(effective_key)
            result.llm_test_ready = result.api_key_set
            if result.api_key_set:
                result.llm_model = "openrouter/auto"
            if key:
                os.environ["OPENROUTER_API_KEY"] = key
                result.entered_api_key = key
            result.llm_provider = "openrouter"

        elif choice == "openai":
            self._io.info(
                "\n  Get your API key at: https://platform.openai.com/api-keys\n"
                "  (The key will be written to your .env.local — never committed to git.)\n"
            )
            existing_key = os.environ.get("OPENAI_API_KEY", "").strip()
            key = self._io.secret("  Paste your OpenAI API key").strip()
            effective_key = key or existing_key
            result.api_key_set = bool(effective_key)
            result.llm_test_ready = result.api_key_set
            if result.api_key_set:
                result.llm_model = "gpt-4o-mini"
            if key:
                # Only set in os.environ if user actually entered something new
                os.environ["OPENAI_API_KEY"] = key
                # Track that user explicitly entered a key (for .env.local writing)
                result.entered_api_key = key
            result.llm_provider = "openai"

        elif choice == "ollama":
            result.ollama_base_url = _resolve_ollama_base_url(self._env_path)
            ollama_ok = shutil.which("ollama") is not None
            if not ollama_ok:
                self._io.info(
                    "\n  Ollama is not installed.  Install it from https://ollama.com\n"
                    "  then re-run `agent33 wizard` or set OLLAMA_BASE_URL manually.\n"
                )
            else:
                self._io.info("\n  Ollama detected.  Checking for a suitable model…")
                try:
                    model = _pick_ollama_model()
                    self._io.info(f"  Using model: {model}")
                    result.llm_model = model
                    result.llm_test_ready = True
                except Exception:
                    self._io.info(
                        "  (Could not detect Ollama models — will use llama3.2:3b as default)"
                    )
                    result.llm_model = "llama3.2:3b"
                    result.llm_test_ready = False
            result.llm_provider = "ollama"

        else:
            self._io.info(
                "\n  Skipping LLM setup.  You can configure it later by editing .env.local\n"
                "  or running `agent33 bootstrap`.\n"
            )
            result.llm_provider = "skip"

        result.steps_completed.append("llm_provider")

    # ------------------------------------------------------------------
    # Step 3 — Test Invocation
    # ------------------------------------------------------------------

    def _step_test_invocation(self, result: WizardResult) -> None:
        self._io.info(f"\n{STEP_SEPARATOR}")
        self._io.info("  Step 3 of 5 — Test Invocation")
        self._io.info(STEP_SEPARATOR)

        no_provider = result.llm_provider == "skip"
        provider_needs_key = (
            result.llm_provider in {"openai", "openrouter"} and not result.api_key_set
        )
        if no_provider or provider_needs_key:
            self._io.info("  Skipping test invocation (no LLM configured).")
            result.steps_completed.append("test_invocation_skipped")
            return
        if result.llm_provider == "ollama" and not result.llm_test_ready:
            self._io.info(
                "  Skipping test invocation (no usable local Ollama runtime/model detected)."
            )
            result.steps_completed.append("test_invocation_skipped")
            return

        if not self._io.confirm("  Run a quick test ('What can you do?')?", default=True):
            self._io.info("  Skipping test invocation.")
            result.steps_completed.append("test_invocation_skipped")
            return

        self._io.info(
            "\n  Agent: ",
        )
        try:
            _stream_test_response(result, self._io)
        except Exception as exc:
            self._io.info(f"\n  (Test invocation failed: {exc})")
            self._io.info("  You can try again later with `agent33 chat`.")

        result.steps_completed.append("test_invocation")

    # ------------------------------------------------------------------
    # Step 4 — Template Picker
    # ------------------------------------------------------------------

    def _step_template(self, result: WizardResult) -> None:
        self._io.info(f"\n{STEP_SEPARATOR}")
        self._io.info("  Step 4 of 5 — Quick-Start Template")
        self._io.info(STEP_SEPARATOR)
        self._io.info("  Choose an agent template to start with:\n")

        template_labels = [f"{t['label']} — {t['description']}" for t in QUICK_TEMPLATES]
        template_labels.append("None — I'll configure manually")

        choice = self._io.prompt(
            "Which template?",
            choices=template_labels,
            default=template_labels[0],
        )

        # Map display label back to template name via dictionary lookup
        label_to_name = {f"{t['label']} — {t['description']}": t["name"] for t in QUICK_TEMPLATES}
        result.template = label_to_name.get(choice)
        # "None — I'll configure manually" (or any unrecognized choice) leaves
        # result.template as None

        result.steps_completed.append("template")
        label = result.template or "none"
        self._io.info(f"  ✓ Template: {label}")

    # ------------------------------------------------------------------
    # Step 5 — Write config and show completion message
    # ------------------------------------------------------------------

    def _step_complete(self, result: WizardResult) -> None:
        self._io.info(f"\n{STEP_SEPARATOR}")
        self._io.info("  Step 5 of 5 — Saving Configuration")
        self._io.info(STEP_SEPARATOR)

        lines = _build_env_lines(result)
        _write_env(self._env_path, lines)
        result.env_written = True

        self._io.info(f"\n  Configuration written to: {self._env_path}")
        self._io.info("\n" + STEP_SEPARATOR)
        self._io.info("  Setup complete!")
        self._io.info(STEP_SEPARATOR)
        self._io.info(
            f"\n  Profile    : {result.profile}"
            f"\n  Provider   : {result.llm_provider}"
            + (f"\n  Template   : {result.template}" if result.template else "")
            + "\n\n  Next steps:"
            "\n    agent33 chat          — start chatting with your agent"
            "\n    agent33 diagnose      — run subsystem health checks"
            "\n    agent33 status        — view server status"
            "\n"
        )
        result.steps_completed.append("complete")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mode_to_profile(mode: str) -> str:
    """Map an EnvProfile.mode value to the nearest named config profile."""
    return {"lite": "developer", "standard": "production", "enterprise": "enterprise"}.get(
        mode, "developer"
    )


def _pick_ollama_model() -> str:
    """Ask Ollama for the list of pulled models and return the best one."""
    import subprocess

    proc = subprocess.run(
        ["ollama", "list"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError("Could not detect local Ollama models")

    lines = proc.stdout.strip().splitlines()[1:]  # skip header
    pulled = [ln.split()[0] for ln in lines if ln.strip()]

    # Prefer models in priority order
    preferred = ["qwen2.5-coder:32b", "llama3.1:8b", "llama3.2:3b", "tinyllama:1.1b"]
    for pref in preferred:
        if pref in pulled:
            return pref

    if pulled:
        return pulled[0]

    raise RuntimeError("No local Ollama models detected")


def _stream_test_response(result: WizardResult, io: WizardIO) -> None:
    """Send 'What can you do?' to the configured LLM and stream the reply."""
    if result.llm_provider == "openai":
        import httpx

        api_key = os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": result.llm_model or "gpt-4o-mini",
                    "messages": [
                        {"role": "user", "content": "What can you do? (answer in 2 sentences)"}
                    ],
                    "stream": False,
                    "max_tokens": 80,
                },
            )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        io.info(text)

    elif result.llm_provider == "openrouter":
        import httpx

        api_key = os.environ.get("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")

        with httpx.Client(timeout=30) as client:
            resp = client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "http://localhost",
                    "X-OpenRouter-Title": "AGENT-33 Wizard",
                },
                json={
                    "model": result.llm_model or "openrouter/auto",
                    "messages": [
                        {"role": "user", "content": "What can you do? (answer in 2 sentences)"}
                    ],
                    "stream": False,
                    "max_tokens": 80,
                },
            )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"]
        io.info(text)

    elif result.llm_provider == "ollama":
        import httpx

        base_url = (result.ollama_base_url or _resolve_ollama_base_url(result.env_path)).rstrip(
            "/"
        )
        model = result.llm_model or "llama3.2:3b"
        with httpx.Client(timeout=60) as client:
            resp = client.post(
                f"{base_url}/api/generate",
                json={
                    "model": model,
                    "prompt": "What can you do? (answer in 2 sentences)",
                    "stream": False,
                },
            )
        resp.raise_for_status()
        io.info(resp.json().get("response", ""))


def _build_env_lines(result: WizardResult) -> list[str]:
    """Build the .env.local content lines from wizard choices."""
    lines = [
        "# Generated by `agent33 wizard`",
        f"AGENT33_PROFILE={result.profile}",
        "",
    ]
    if result.llm_provider == "openai":
        # Only write the API key if the user explicitly entered it during the
        # wizard — do NOT write a key that was merely present in the ambient env.
        if result.entered_api_key:
            lines.append(f"OPENAI_API_KEY={result.entered_api_key}")
        if result.llm_model:
            lines.append(f"DEFAULT_MODEL={result.llm_model}")
        lines.append("")
    elif result.llm_provider == "openrouter":
        if result.entered_api_key:
            lines.append(f"OPENROUTER_API_KEY={result.entered_api_key}")
        if result.llm_model:
            lines.append(f"DEFAULT_MODEL={result.llm_model}")
        lines.append("")
    elif result.llm_provider == "ollama":
        ollama_base_url = result.ollama_base_url or _resolve_ollama_base_url(result.env_path)
        lines.append(f"OLLAMA_BASE_URL={ollama_base_url}")
        if result.llm_model:
            lines.append(f"DEFAULT_MODEL={result.llm_model}")
        lines.append("")
    if result.template:
        lines.append(f"AGENT33_DEFAULT_TEMPLATE={result.template}")
        lines.append("")
    return lines


_WIZARD_MARKER = "# --- wizard ---"


def _write_env(path: Path, lines: list[str]) -> None:
    """Write wizard-generated config to ``path``.

    If the file already contains a ``# --- wizard ---`` section from a previous
    run, that section (and everything after it) is replaced.  Content before
    the marker — hand-edited lines — is preserved.  This prevents duplicate
    entries when the wizard is re-run.
    """
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    # Strip any previous wizard section so we don't accumulate duplicates
    marker_pos = existing.find(_WIZARD_MARKER)
    base = existing[:marker_pos].rstrip("\n") if marker_pos >= 0 else existing.rstrip("\n")
    separator = f"\n{_WIZARD_MARKER}\n" if base else f"{_WIZARD_MARKER}\n"
    new_content = base + separator + "\n".join(lines) + "\n"
    path.write_text(new_content, encoding="utf-8")
