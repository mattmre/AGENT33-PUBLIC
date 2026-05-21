"""Browser automation tool using Playwright (optional dependency).

Phase 55 additions:
  - ``vision_analyze`` action: captures a screenshot and sends it to a
    vision-capable LLM via ModelRouter for structured page analysis.
  - Constructor-injected ``ModelRouter`` (optional) for vision support.
  - Configurable session TTL via ``session_ttl_seconds`` parameter.
  - Tenant-scoped session isolation via ``ToolContext.tenant_id``.
  - ``list_sessions`` action for cleanup visibility.
"""

from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.browser_gate import evaluate_browser_computer_use_gate

logger = logging.getLogger(__name__)

_PLAYWRIGHT_AVAILABLE = True
try:
    from playwright.async_api import async_playwright
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

if TYPE_CHECKING:
    from playwright.async_api import Browser, Page, Playwright

    from agent33.llm.router import ModelRouter
    from agent33.tools.builtin.browser_cloud import CloudBrowserBackend

_DEFAULT_TIMEOUT_MS = 30_000
_DEFAULT_SESSION_TTL_SECONDS = 300  # 5 minutes idle

_VISION_SYSTEM_PROMPT = (
    "You are a web page analysis assistant. Analyze the provided screenshot "
    "and answer the user's question. Describe the page layout, key UI elements, "
    "text content, and any actionable items you can identify. Be specific and "
    "structured in your response."
)

# Known vision-capable model prefixes for auto-detection.
_VISION_MODEL_PREFIXES = (
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4-vision",
    "claude-3",
    "claude-4",
    "gemini",
    "llava",
    "llama3.2-vision",
    "minicpm-v",
    "qwen2.5-vl",
    "qwen-vl",
    "internvl",
    "cogvlm",
    "phi-3-vision",
    "phi-3.5-vision",
)


@dataclass
class BrowserSession:
    """Holds a persistent browser and page for multi-step automation."""

    pw: Playwright  # Playwright context manager
    browser: Browser  # Browser instance
    page: Page  # Page instance
    tenant_id: str = ""  # owning tenant
    last_used: float = field(default_factory=time.monotonic)


# Process-global session registry.  Accessed by module-level helpers
# (_get_session, _close_session, _cleanup_stale_sessions) and by
# BrowserTool._list_sessions.  This is safe in single-process deployments;
# in multi-process deployments (e.g. gunicorn pre-fork) each worker holds
# its own independent copy.  Moving to a BrowserTool instance variable
# would require threading the dict through every helper — deferred until
# BrowserTool is refactored to own its session lifecycle end-to-end.
_sessions: dict[str, BrowserSession] = {}


class _CloudSessionStub:
    """Lightweight stub for ``pw`` / ``browser`` in cloud-backed sessions.

    When a session is created via the cloud backend, Playwright lifecycle
    (``browser.close()``, ``pw.stop()``) is managed by the cloud provider.
    This stub satisfies ``_close_session`` without side-effects.
    """

    async def close(self) -> None:  # noqa: D102
        pass

    async def stop(self) -> None:  # noqa: D102
        pass


async def _get_session(
    session_id: str,
    *,
    tenant_id: str = "",
    cloud_backend: CloudBrowserBackend | None = None,
) -> BrowserSession:
    """Get or create a browser session with tenant isolation.

    When *cloud_backend* is provided and local Playwright is unavailable or
    fails to launch, the function falls back to creating a cloud session via
    the ``CloudBrowserBackend``.
    """
    if session_id in _sessions:
        sess = _sessions[session_id]
        if tenant_id and sess.tenant_id and sess.tenant_id != tenant_id:
            raise PermissionError(f"Session '{session_id}' belongs to a different tenant")
        sess.last_used = time.monotonic()
        return sess

    # Per-tenant session cap enforcement
    if tenant_id:
        from agent33.config import settings as _settings

        tenant_session_count = sum(1 for s in _sessions.values() if s.tenant_id == tenant_id)
        if tenant_session_count >= _settings.max_browser_sessions_per_tenant:
            raise RuntimeError(
                f"Session limit ({_settings.max_browser_sessions_per_tenant}) "
                f"reached for tenant '{tenant_id}'"
            )

    # Try local Playwright first
    if _PLAYWRIGHT_AVAILABLE:
        try:
            pw = await async_playwright().start()
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            sess = BrowserSession(pw=pw, browser=browser, page=page, tenant_id=tenant_id)
            _sessions[session_id] = sess
            return sess
        except Exception:
            logger.warning(
                "Local Playwright launch failed for session %s, trying cloud fallback",
                session_id,
            )
            if cloud_backend is None:
                raise

    # Fallback to cloud backend
    if cloud_backend is not None and cloud_backend.is_configured:
        cloud_session = await cloud_backend.connect(session_label=session_id)
        if cloud_session is not None:
            cloud_page = await cloud_backend.get_playwright_page(cloud_session)
            if cloud_page is not None:
                # Wrap the cloud-provided page in a BrowserSession.
                # The cloud provider manages Playwright/browser lifecycle,
                # so we use lightweight stubs for pw/browser to satisfy
                # ``_close_session`` without side-effects.
                stub = _CloudSessionStub()
                sess = BrowserSession(
                    pw=cast("Playwright", stub),
                    browser=cast("Browser", stub),
                    page=cloud_page,
                    tenant_id=tenant_id,
                )
                _sessions[session_id] = sess
                logger.info("Created cloud-backed browser session %s", session_id)
                return sess

    if not _PLAYWRIGHT_AVAILABLE:
        raise RuntimeError("Playwright is not installed and no cloud backend is available")
    raise RuntimeError("Failed to create browser session via local or cloud backend")


async def _close_session(session_id: str) -> None:
    """Close and remove a browser session."""
    sess = _sessions.pop(session_id, None)
    if sess:
        try:
            await sess.browser.close()
            await sess.pw.stop()
        except Exception:
            logger.debug("Error closing session %s", session_id, exc_info=True)


async def _cleanup_stale_sessions(ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS) -> None:
    """Close sessions idle beyond TTL."""
    now = time.monotonic()
    stale = [sid for sid, s in _sessions.items() if now - s.last_used > ttl_seconds]
    for sid in stale:
        await _close_session(sid)


_VALID_ACTIONS = frozenset(
    {
        "navigate",
        "screenshot",
        "extract_text",
        "click",
        "type_text",
        "select",
        "scroll",
        "wait_for",
        "get_elements",
        "close_session",
        "vision_analyze",
        "list_sessions",
    }
)


class BrowserTool:
    """Navigate pages, take screenshots, extract text, and perform interactive
    automation via Playwright.

    Phase 55: now supports ``vision_analyze`` for LLM-based page analysis and
    tenant-scoped session management.

    Degrades gracefully when Playwright is not installed.
    """

    def __init__(
        self,
        *,
        router: ModelRouter | None = None,
        session_ttl_seconds: int = _DEFAULT_SESSION_TTL_SECONDS,
        vision_model: str = "",
        cloud_backend: CloudBrowserBackend | None = None,
    ) -> None:
        self._router = router
        self._session_ttl_seconds = session_ttl_seconds
        self._vision_model = vision_model
        self._cloud_backend = cloud_backend

    @property
    def name(self) -> str:
        return "browser"

    @property
    def description(self) -> str:
        return (
            "Headless browser automation: navigate, screenshot, extract text, "
            "click, type, select, scroll, wait for elements, vision analysis. "
            "Supports persistent sessions for multi-step interactions."
        )

    @property
    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": (
                        "One of: navigate, screenshot, extract_text, click, "
                        "type_text, select, scroll, wait_for, get_elements, "
                        "close_session, vision_analyze, list_sessions."
                    ),
                    "default": "navigate",
                },
                "url": {"type": "string", "description": "Page URL."},
                "session_id": {
                    "type": "string",
                    "description": "Session ID for persistent browser reuse.",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for interactive actions.",
                },
                "text": {"type": "string", "description": "Text to type."},
                "value": {"type": "string", "description": "Value to select."},
                "direction": {
                    "type": "string",
                    "description": "'up' or 'down' for scroll.",
                    "default": "down",
                },
                "amount": {
                    "type": "integer",
                    "description": "Scroll pixels.",
                    "default": 500,
                },
                "timeout_ms": {
                    "type": "integer",
                    "description": "Timeout in milliseconds.",
                    "default": _DEFAULT_TIMEOUT_MS,
                },
                "question": {
                    "type": "string",
                    "description": "Question for vision_analyze action.",
                },
            },
            "required": [],
        }

    async def execute(self, params: dict[str, Any], context: ToolContext) -> ToolResult:
        """Run a browser action.

        Parameters
        ----------
        params:
            url         : str  - Page URL (required for navigate/screenshot/extract_text).
            action      : str  - One of the supported actions.
            session_id  : str  - Optional session ID to reuse a browser across calls.
            selector    : str  - CSS selector (for click/type_text/select/wait_for/get_elements).
            text        : str  - Text to type (for type_text).
            value       : str  - Value to select (for select).
            direction   : str  - 'up' or 'down' (for scroll, default 'down').
            amount      : int  - Scroll pixels (for scroll, default 500).
            timeout_ms  : int  - Timeout in milliseconds (default 30000).
            question    : str  - Question about the page (for vision_analyze).
        """
        action: str = params.get("action", "navigate")
        gate = evaluate_browser_computer_use_gate(self.name, action, context)
        if not gate.allowed:
            return ToolResult.fail(f"{gate.reason} Evidence: {gate.evidence_line()}")

        # list_sessions does not need Playwright
        if action == "list_sessions":
            return self._list_sessions(context)

        if not _PLAYWRIGHT_AVAILABLE and self._cloud_backend is None:
            return ToolResult.fail(
                "Playwright is not installed. "
                "Install it with: pip install playwright && playwright install chromium"
            )

        if action not in _VALID_ACTIONS:
            return ToolResult.fail(f"Unknown action: {action}")

        session_id: str | None = params.get("session_id")
        timeout_ms: int = params.get("timeout_ms", _DEFAULT_TIMEOUT_MS)
        tenant_id: str = context.tenant_id

        try:
            await _cleanup_stale_sessions(self._session_ttl_seconds)

            if action == "close_session":
                if session_id:
                    await _close_session(session_id)
                    return ToolResult.ok(f"Session '{session_id}' closed")
                return ToolResult.fail("No session_id provided for close_session")

            if action == "vision_analyze":
                result = await self._handle_vision_analyze(session_id, params, context, timeout_ms)
                return self._maybe_redact(action, result)

            # Session-based execution
            if session_id:
                result = await self._run_with_session(
                    session_id,
                    action,
                    params,
                    timeout_ms,
                    tenant_id=tenant_id,
                    cloud_backend=self._cloud_backend,
                )
                return self._maybe_redact(action, result)

            # Legacy one-shot execution (backward compatible)
            url: str = params.get("url", "").strip()
            if not url:
                return ToolResult.fail("No URL provided")
            result = await self._run_oneshot(url, action, params, timeout_ms)
            return self._maybe_redact(action, result)

        except PermissionError as exc:
            return ToolResult.fail(str(exc))
        except Exception as exc:
            logger.exception("Browser tool error")
            return ToolResult.fail(f"Browser error: {exc}")

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    @staticmethod
    def _list_sessions(context: ToolContext) -> ToolResult:
        """List active browser sessions, filtered to the calling tenant."""
        tenant_id = context.tenant_id
        now = time.monotonic()
        entries: list[str] = []
        for sid, sess in _sessions.items():
            if tenant_id and sess.tenant_id and sess.tenant_id != tenant_id:
                continue
            idle = int(now - sess.last_used)
            entries.append(f"{sid} (idle {idle}s, tenant={sess.tenant_id or 'none'})")
        if not entries:
            return ToolResult.ok("No active sessions.")
        return ToolResult.ok(f"Active sessions ({len(entries)}):\n" + "\n".join(entries))

    # ------------------------------------------------------------------
    # Secret redaction
    # ------------------------------------------------------------------

    # Actions whose text output may contain secrets extracted from pages.
    _REDACT_ACTIONS = frozenset({"extract_text", "vision_analyze", "get_elements"})

    @staticmethod
    def _maybe_redact(action: str, result: ToolResult) -> ToolResult:
        """Apply secret redaction to text-extracting actions (fail-safe)."""
        if not result.success or action not in BrowserTool._REDACT_ACTIONS:
            return result
        try:
            from agent33.security.redaction import redact_secrets

            redacted = redact_secrets(result.output)
            if redacted != result.output:
                return ToolResult.ok(redacted)
        except Exception:
            logger.debug("Secret redaction unavailable or failed", exc_info=True)
        return result

    # ------------------------------------------------------------------
    # Vision analysis (Phase 55)
    # ------------------------------------------------------------------

    async def _handle_vision_analyze(
        self,
        session_id: str | None,
        params: dict[str, Any],
        context: ToolContext,
        timeout_ms: int,
    ) -> ToolResult:
        """Capture a screenshot and send it to a vision-capable LLM."""
        if self._router is None:
            return ToolResult.fail(
                "Vision analysis requires a ModelRouter. "
                "The BrowserTool was not initialized with a router."
            )

        question: str = params.get("question", "").strip()
        if not question:
            return ToolResult.fail("No question provided for vision_analyze")

        # Resolve which vision model to use
        vision_model = self._vision_model
        if not vision_model:
            vision_model = await self._detect_vision_model()
            if not vision_model:
                return ToolResult.fail(
                    "No vision-capable model detected. Set browser_vision_model "
                    "in configuration or register a vision model."
                )

        # Capture screenshot
        screenshot_b64 = await self._capture_screenshot(
            session_id, params, timeout_ms, tenant_id=context.tenant_id
        )

        # Build vision request
        from agent33.llm.base import ChatMessage, ImageBlock, TextBlock

        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=_VISION_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=[
                    ImageBlock(base64_data=screenshot_b64, media_type="image/png"),
                    TextBlock(text=question),
                ],
            ),
        ]

        response = await self._router.complete(
            messages,
            model=vision_model,
            temperature=0.3,
            max_tokens=2048,
        )
        return ToolResult.ok(response.content)

    async def _detect_vision_model(self) -> str:
        """Try to find a vision-capable model among registered providers."""
        if self._router is None:
            return ""
        for _name, provider in self._router.providers.items():
            try:
                models = await provider.list_models()
                for model in models:
                    lower = model.lower()
                    for prefix in _VISION_MODEL_PREFIXES:
                        if lower.startswith(prefix):
                            logger.info("Auto-detected vision model: %s", model)
                            return model
            except Exception:
                continue
        return ""

    async def _capture_screenshot(
        self,
        session_id: str | None,
        params: dict[str, Any],
        timeout_ms: int,
        *,
        tenant_id: str = "",
    ) -> str:
        """Capture a screenshot and return it as base64-encoded PNG."""
        if session_id:
            sess = await _get_session(
                session_id, tenant_id=tenant_id, cloud_backend=self._cloud_backend
            )
            page = sess.page
            # Navigate if URL provided and not already on a page
            url: str = params.get("url", "").strip()
            if url:
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            raw = await page.screenshot(full_page=True, type="png")
            return base64.b64encode(raw).decode()

        # One-shot: require URL
        url = params.get("url", "").strip()
        if not url:
            raise ValueError("No URL provided for vision_analyze without session_id")
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
                raw = await page.screenshot(full_page=True, type="png")
                return base64.b64encode(raw).decode()
            finally:
                await browser.close()

    # ------------------------------------------------------------------
    # Session-based execution
    # ------------------------------------------------------------------

    async def _run_with_session(
        self,
        session_id: str,
        action: str,
        params: dict[str, Any],
        timeout_ms: int,
        *,
        tenant_id: str = "",
        cloud_backend: CloudBrowserBackend | None = None,
    ) -> ToolResult:
        sess = await _get_session(session_id, tenant_id=tenant_id, cloud_backend=cloud_backend)
        page = sess.page

        url: str = params.get("url", "").strip()
        if action == "navigate":
            if not url:
                return ToolResult.fail("No URL provided")
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            title = await page.title()
            return ToolResult.ok(f"Navigated to {url} - title: {title}")

        if action == "screenshot":
            raw = await page.screenshot(full_page=True, type="png")
            return ToolResult.ok(base64.b64encode(raw).decode())

        if action == "extract_text":
            text = await page.inner_text("body")
            return ToolResult.ok(text[:100_000])

        return await self._run_interactive(page, action, params, timeout_ms)

    async def _run_oneshot(
        self, url: str, action: str, params: dict[str, Any], timeout_ms: int
    ) -> ToolResult:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            try:
                page = await browser.new_page()
                await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

                if action == "navigate":
                    title = await page.title()
                    return ToolResult.ok(f"Navigated to {url} - title: {title}")

                if action == "screenshot":
                    raw = await page.screenshot(full_page=True, type="png")
                    return ToolResult.ok(base64.b64encode(raw).decode())

                if action == "extract_text":
                    text = await page.inner_text("body")
                    return ToolResult.ok(text[:100_000])

                return await self._run_interactive(page, action, params, timeout_ms)
            finally:
                await browser.close()

    async def _run_interactive(
        self, page: Page, action: str, params: dict[str, Any], timeout_ms: int
    ) -> ToolResult:
        selector: str = params.get("selector", "")

        if action == "click":
            if not selector:
                return ToolResult.fail("No selector provided for click")
            await page.click(selector, timeout=timeout_ms)
            return ToolResult.ok(f"Clicked: {selector}")

        if action == "type_text":
            if not selector:
                return ToolResult.fail("No selector provided for type_text")
            text: str = params.get("text", "")
            await page.fill(selector, text, timeout=timeout_ms)
            return ToolResult.ok(f"Typed into {selector}")

        if action == "select":
            if not selector:
                return ToolResult.fail("No selector provided for select")
            value: str = params.get("value", "")
            await page.select_option(selector, value, timeout=timeout_ms)
            return ToolResult.ok(f"Selected '{value}' in {selector}")

        if action == "scroll":
            direction: str = params.get("direction", "down")
            amount: int = params.get("amount", 500)
            delta = amount if direction == "down" else -amount
            await page.mouse.wheel(0, delta)
            return ToolResult.ok(f"Scrolled {direction} by {amount}px")

        if action == "wait_for":
            if not selector:
                return ToolResult.fail("No selector provided for wait_for")
            await page.wait_for_selector(selector, timeout=timeout_ms)
            return ToolResult.ok(f"Element found: {selector}")

        if action == "get_elements":
            if not selector:
                return ToolResult.fail("No selector provided for get_elements")
            elements = await page.query_selector_all(selector)
            texts = []
            for el in elements[:50]:  # cap at 50 elements
                txt = (await el.text_content() or "").strip()
                if txt:
                    texts.append(txt)
            return ToolResult.ok("\n".join(texts))

        return ToolResult.fail(f"Unhandled action: {action}")
