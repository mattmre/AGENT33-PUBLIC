"""Tests for Phase 55: Browser automation completion.

Covers:
  - vision_analyze action: screenshot capture + LLM vision call
  - Cloud browser backend: session lifecycle
  - Session TTL cleanup with configurable TTL
  - Tenant isolation for sessions
  - list_sessions action
  - Error handling (no router, no question, no vision model)
"""

from __future__ import annotations

import base64
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent33.config import settings
from agent33.llm.base import LLMResponse
from agent33.tools.base import ToolContext, ToolResult
from agent33.tools.builtin.browser import (
    _DEFAULT_SESSION_TTL_SECONDS,
    _VISION_MODEL_PREFIXES,
    BrowserSession,
    BrowserTool,
    _sessions,
)
from agent33.tools.builtin.browser_cloud import CloudBrowserBackend, CloudSession

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_sessions(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Ensure browser sessions are clean before/after each test."""
    monkeypatch.setattr(settings, "browser_computer_use_enabled", True)
    _sessions.clear()
    yield
    _sessions.clear()


def _make_context(
    *,
    tenant_id: str = "test-tenant",
    session_id: str = "",
    allow_interactive: bool = True,
) -> ToolContext:
    policies = {"browser": "allow"} if allow_interactive else {}
    return ToolContext(tenant_id=tenant_id, session_id=session_id, tool_policies=policies)


def _make_mock_router(
    *,
    content: str = "Analysis result",
    models: list[str] | None = None,
) -> MagicMock:
    """Create a mock ModelRouter that returns a vision analysis response."""
    router = MagicMock()
    router.complete = AsyncMock(
        return_value=LLMResponse(
            content=content,
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
        )
    )
    # providers property returns a dict of mock providers
    mock_provider = MagicMock()
    mock_provider.list_models = AsyncMock(return_value=models or ["gpt-4o", "llama3.2"])
    router.providers = {"openai": mock_provider}
    return router


def _make_mock_page(*, screenshot_bytes: bytes = b"fake-png-data") -> MagicMock:
    """Create a mock Playwright Page."""
    page = AsyncMock()
    page.screenshot = AsyncMock(return_value=screenshot_bytes)
    page.goto = AsyncMock()
    page.title = AsyncMock(return_value="Test Page")
    page.inner_text = AsyncMock(return_value="Page text content")
    page.click = AsyncMock()
    page.fill = AsyncMock()
    page.select_option = AsyncMock()
    page.mouse = MagicMock()
    page.mouse.wheel = AsyncMock()
    page.wait_for_selector = AsyncMock()
    page.query_selector_all = AsyncMock(return_value=[])
    return page


def _install_fake_session(
    session_id: str,
    *,
    tenant_id: str = "test-tenant",
    idle_seconds: float = 0.0,
) -> MagicMock:
    """Install a fake BrowserSession in the global session dict."""
    page = _make_mock_page()
    pw = MagicMock()
    browser = MagicMock()
    browser.close = AsyncMock()
    pw.stop = AsyncMock()
    sess = BrowserSession(
        pw=pw,
        browser=browser,
        page=page,
        tenant_id=tenant_id,
        last_used=time.monotonic() - idle_seconds,
    )
    _sessions[session_id] = sess
    return page


# ===========================================================================
# BrowserTool: vision_analyze action
# ===========================================================================


@patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True)
class TestVisionAnalyze:
    """Tests for the vision_analyze action."""

    async def test_vision_analyze_returns_llm_analysis(self) -> None:
        """vision_analyze captures screenshot, calls vision model, returns analysis."""
        router = _make_mock_router(content="Login form with email and password fields")
        tool = BrowserTool(router=router, vision_model="gpt-4o")
        page = _install_fake_session("s1")

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "session_id": "s1",
                "question": "What login options are shown?",
            },
            _make_context(),
        )

        assert result.success is True
        assert "Login form" in result.output
        # Verify screenshot was captured
        page.screenshot.assert_awaited_once()
        # Verify LLM was called with image content
        router.complete.assert_awaited_once()
        call_args = router.complete.call_args
        messages = call_args[0][0]
        assert len(messages) == 2
        # System message
        assert messages[0].role == "system"
        # User message has image + text blocks
        assert messages[1].role == "user"
        content_parts = messages[1].content
        assert isinstance(content_parts, list)
        assert len(content_parts) == 2

    async def test_vision_analyze_no_router_fails(self) -> None:
        """vision_analyze fails gracefully when no ModelRouter is provided."""
        tool = BrowserTool(router=None)
        _install_fake_session("s1")

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "session_id": "s1",
                "question": "What is on this page?",
            },
            _make_context(),
        )

        assert result.success is False
        assert "ModelRouter" in result.error

    async def test_vision_analyze_no_question_fails(self) -> None:
        """vision_analyze requires a question parameter."""
        router = _make_mock_router()
        tool = BrowserTool(router=router, vision_model="gpt-4o")
        _install_fake_session("s1")

        result = await tool.execute(
            {"action": "vision_analyze", "session_id": "s1"},
            _make_context(),
        )

        assert result.success is False
        assert "question" in result.error.lower()

    async def test_vision_analyze_auto_detects_model(self) -> None:
        """vision_analyze auto-detects a vision model when none configured."""
        router = _make_mock_router(models=["llama3.2", "gpt-4o-mini", "codellama"])
        tool = BrowserTool(router=router, vision_model="")
        _install_fake_session("s1")

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "session_id": "s1",
                "question": "Describe the page",
            },
            _make_context(),
        )

        assert result.success is True
        # Should have auto-detected gpt-4o-mini as vision model
        call_args = router.complete.call_args
        assert call_args.kwargs["model"] == "gpt-4o-mini"

    async def test_vision_analyze_no_vision_model_detected(self) -> None:
        """vision_analyze fails when no vision model can be detected."""
        router = _make_mock_router(models=["codellama", "phi-2"])
        tool = BrowserTool(router=router, vision_model="")
        _install_fake_session("s1")

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "session_id": "s1",
                "question": "What is on this page?",
            },
            _make_context(),
        )

        assert result.success is False
        assert "vision" in result.error.lower()

    async def test_vision_analyze_oneshot_requires_url(self) -> None:
        """vision_analyze without session_id requires a URL."""
        router = _make_mock_router()
        tool = BrowserTool(router=router, vision_model="gpt-4o")

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "question": "What is shown?",
            },
            _make_context(),
        )

        assert result.success is False
        assert "URL" in result.error or "url" in result.error.lower()

    async def test_vision_analyze_passes_image_as_base64(self) -> None:
        """The screenshot is sent to the LLM as a base64-encoded ImageBlock."""
        screenshot_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
        router = _make_mock_router(content="Page shows a dashboard")
        tool = BrowserTool(router=router, vision_model="gpt-4o")
        page = _install_fake_session("s1")
        page.screenshot = AsyncMock(return_value=screenshot_bytes)

        result = await tool.execute(
            {
                "action": "vision_analyze",
                "session_id": "s1",
                "question": "What is this?",
            },
            _make_context(),
        )

        assert result.success is True
        call_args = router.complete.call_args
        messages = call_args[0][0]
        image_block = messages[1].content[0]
        expected_b64 = base64.b64encode(screenshot_bytes).decode()
        assert image_block.base64_data == expected_b64
        assert image_block.media_type == "image/png"


# ===========================================================================
# BrowserTool: Session TTL and tenant isolation
# ===========================================================================


class TestSessionManagement:
    """Tests for session TTL, tenant isolation, and list_sessions."""

    async def test_configurable_ttl_cleanup(self) -> None:
        """Sessions exceeding the configured TTL are cleaned up."""
        tool = BrowserTool(session_ttl_seconds=10)
        # Install a session that has been idle for 20 seconds
        _install_fake_session("old-session", idle_seconds=20.0)
        # Install a fresh session
        _install_fake_session("fresh-session", idle_seconds=1.0)

        assert "old-session" in _sessions
        assert "fresh-session" in _sessions

        # Trigger cleanup via any action that fails early (no Playwright)
        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            # list_sessions triggers cleanup indirectly (it doesn't, but
            # execute() does for other actions)
            await tool.execute(
                {"action": "close_session", "session_id": "nonexistent"},
                _make_context(),
            )

        # old-session should have been cleaned up (20s > 10s TTL)
        assert "old-session" not in _sessions
        # fresh-session should remain (1s < 10s TTL)
        assert "fresh-session" in _sessions

    async def test_default_ttl_is_300(self) -> None:
        """Default session TTL is 300 seconds."""
        assert _DEFAULT_SESSION_TTL_SECONDS == 300

    async def test_tenant_isolation_blocks_cross_tenant_access(self) -> None:
        """Sessions from one tenant cannot be accessed by another."""
        tool = BrowserTool()
        _install_fake_session("s1", tenant_id="tenant-a")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {
                    "action": "screenshot",
                    "session_id": "s1",
                },
                _make_context(tenant_id="tenant-b"),
            )

        assert result.success is False
        assert "different tenant" in result.error

    async def test_same_tenant_can_access_session(self) -> None:
        """Sessions can be accessed by the same tenant."""
        tool = BrowserTool()
        page = _install_fake_session("s1", tenant_id="tenant-a")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "screenshot", "session_id": "s1"},
                _make_context(tenant_id="tenant-a"),
            )

        assert result.success is True
        page.screenshot.assert_awaited_once()

    async def test_list_sessions_shows_only_own_tenant(self) -> None:
        """list_sessions filters sessions by tenant."""
        tool = BrowserTool()
        _install_fake_session("s1", tenant_id="tenant-a")
        _install_fake_session("s2", tenant_id="tenant-b")
        _install_fake_session("s3", tenant_id="tenant-a")

        result = await tool.execute(
            {"action": "list_sessions"},
            _make_context(tenant_id="tenant-a"),
        )

        assert result.success is True
        assert "s1" in result.output
        assert "s3" in result.output
        assert "s2" not in result.output

    async def test_list_sessions_empty(self) -> None:
        """list_sessions returns appropriate message when no sessions exist."""
        tool = BrowserTool()

        result = await tool.execute(
            {"action": "list_sessions"},
            _make_context(),
        )

        assert result.success is True
        assert "No active sessions" in result.output

    async def test_list_sessions_does_not_require_playwright(self) -> None:
        """list_sessions works even when Playwright is not installed."""
        tool = BrowserTool()

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", False):
            result = await tool.execute(
                {"action": "list_sessions"},
                _make_context(),
            )

        assert result.success is True


# ===========================================================================
# BrowserTool: backward compatibility
# ===========================================================================


class TestBackwardCompatibility:
    """Existing actions continue to work with the updated BrowserTool."""

    async def test_unknown_action_rejected(self) -> None:
        """Unknown actions return an error."""
        tool = BrowserTool()

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "nonexistent"},
                _make_context(),
            )

        assert result.success is False
        assert "Unknown action" in result.error

    async def test_interactive_browser_action_requires_explicit_policy(self) -> None:
        """Interactive browser actions fail closed without an allow policy."""
        tool = BrowserTool()

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "navigate", "url": "https://example.com"},
                _make_context(allow_interactive=False),
            )

        assert result.success is False
        assert "explicit allow policy" in result.error
        assert "browser-computer-use-gate" in result.error

    async def test_read_browser_action_allowed_without_interactive_policy(self) -> None:
        """Read-only browser actions stay available for inspection."""
        tool = BrowserTool()
        _install_fake_session("s1")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "screenshot", "session_id": "s1"},
                _make_context(allow_interactive=False),
            )

        assert result.success is True

    async def test_close_session_requires_session_id(self) -> None:
        """close_session fails without session_id."""
        tool = BrowserTool()

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "close_session"},
                _make_context(),
            )

        assert result.success is False
        assert "session_id" in result.error.lower()

    async def test_close_session_success(self) -> None:
        """close_session removes the session."""
        tool = BrowserTool()
        _install_fake_session("s1")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "close_session", "session_id": "s1"},
                _make_context(),
            )

        assert result.success is True
        assert "s1" not in _sessions

    async def test_navigate_with_session(self) -> None:
        """navigate action works with a session."""
        tool = BrowserTool()
        page = _install_fake_session("s1")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {
                    "action": "navigate",
                    "session_id": "s1",
                    "url": "https://example.com",
                },
                _make_context(),
            )

        assert result.success is True
        assert "example.com" in result.output
        page.goto.assert_awaited_once()

    async def test_playwright_not_available(self) -> None:
        """Actions requiring Playwright fail gracefully when not installed."""
        tool = BrowserTool()

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", False):
            result = await tool.execute(
                {"action": "navigate", "url": "https://example.com"},
                _make_context(),
            )

        assert result.success is False
        assert "Playwright" in result.error

    async def test_parameters_schema_includes_new_actions(self) -> None:
        """Parameters schema documents new actions."""
        tool = BrowserTool()
        schema = tool.parameters_schema

        assert "vision_analyze" in schema["properties"]["action"]["description"]
        assert "list_sessions" in schema["properties"]["action"]["description"]
        assert "question" in schema["properties"]

    async def test_name_is_browser(self) -> None:
        """Tool name remains 'browser' for backward compatibility."""
        tool = BrowserTool()
        assert tool.name == "browser"


# ===========================================================================
# CloudBrowserBackend
# ===========================================================================


class TestCloudBrowserBackend:
    """Tests for the BrowserBase cloud browser backend."""

    def test_not_configured_without_api_key(self) -> None:
        """Backend reports not configured when API key is empty."""
        backend = CloudBrowserBackend()
        assert backend.is_configured is False

    def test_configured_with_api_key(self) -> None:
        """Backend reports configured when API key is provided."""
        backend = CloudBrowserBackend(api_key="test-key-123")
        assert backend.is_configured is True

    async def test_connect_returns_none_when_not_configured(self) -> None:
        """connect() returns None when no API key is set."""
        backend = CloudBrowserBackend()
        session = await backend.connect()
        assert session is None

    async def test_connect_creates_session(self) -> None:
        """connect() creates a session via BrowserBase API."""
        backend = CloudBrowserBackend(api_key="test-key", api_url="http://fake")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "id": "sess-123",
            "connectUrl": "wss://cloud.example.com/cdp/sess-123",
            "status": "created",
            "projectId": "proj-1",
        }

        with patch("agent33.tools.builtin.browser_cloud.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            session = await backend.connect(session_label="test")

        assert session is not None
        assert session.session_id == "sess-123"
        assert session.connect_url == "wss://cloud.example.com/cdp/sess-123"
        assert session.status == "created"

    async def test_connect_handles_api_error(self) -> None:
        """connect() returns None on API error instead of raising."""
        backend = CloudBrowserBackend(api_key="test-key", api_url="http://fake")

        with patch("agent33.tools.builtin.browser_cloud.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=Exception("Network error"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            session = await backend.connect()

        assert session is None

    async def test_disconnect_session(self) -> None:
        """disconnect() stops a cloud session."""
        backend = CloudBrowserBackend(api_key="test-key", api_url="http://fake")
        # Pre-populate active sessions
        backend._active_sessions["sess-123"] = CloudSession(
            session_id="sess-123", connect_url="wss://..."
        )

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()

        with patch("agent33.tools.builtin.browser_cloud.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            result = await backend.disconnect("sess-123")

        assert result is True
        assert "sess-123" not in backend._active_sessions

    async def test_disconnect_returns_false_when_not_configured(self) -> None:
        """disconnect() returns False when backend is not configured."""
        backend = CloudBrowserBackend()
        result = await backend.disconnect("sess-123")
        assert result is False

    async def test_list_sessions_returns_cached_when_no_api_key(self) -> None:
        """list_sessions falls back to locally cached sessions."""
        backend = CloudBrowserBackend()
        backend._active_sessions["s1"] = CloudSession(session_id="s1", connect_url="")

        sessions = await backend.list_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == "s1"

    async def test_list_sessions_from_api(self) -> None:
        """list_sessions fetches sessions from the BrowserBase API."""
        backend = CloudBrowserBackend(api_key="test-key", api_url="http://fake")

        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = [
            {"id": "s1", "connectUrl": "", "status": "running", "projectId": "p1"},
            {"id": "s2", "connectUrl": "", "status": "created", "projectId": "p1"},
        ]

        with patch("agent33.tools.builtin.browser_cloud.httpx") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_httpx.AsyncClient.return_value = mock_client

            sessions = await backend.list_sessions()

        assert len(sessions) == 2
        assert sessions[0].session_id == "s1"
        assert sessions[0].status == "running"
        assert sessions[1].session_id == "s2"


# ===========================================================================
# Config integration
# ===========================================================================


class TestBrowserConfig:
    """Verify Phase 55 settings exist and have correct defaults."""

    def test_browser_settings_defaults(self) -> None:
        """Browser settings have expected defaults."""
        from agent33.config import Settings

        s = Settings(
            environment="test",
            jwt_secret="test-secret-long-enough",
        )
        assert s.browser_session_ttl_seconds == 300
        assert s.browser_vision_model == ""
        assert s.browser_cloud_api_key.get_secret_value() == ""
        assert s.browser_cloud_api_url == "https://www.browserbase.com/v1"

    def test_browser_settings_custom_values(self) -> None:
        """Browser settings can be overridden."""
        from agent33.config import Settings

        s = Settings(
            environment="test",
            jwt_secret="test-secret-long-enough",
            browser_session_ttl_seconds=600,
            browser_vision_model="claude-3-opus",
            browser_cloud_api_key="bb-key-123",
            browser_cloud_api_url="https://custom.browserbase.dev/v2",
        )
        assert s.browser_session_ttl_seconds == 600
        assert s.browser_vision_model == "claude-3-opus"
        assert s.browser_cloud_api_key.get_secret_value() == "bb-key-123"
        assert s.browser_cloud_api_url == "https://custom.browserbase.dev/v2"


# ===========================================================================
# Cloud backend wiring (Gap 1)
# ===========================================================================


class TestCloudBackendWiring:
    """Tests for CloudBrowserBackend integration into BrowserTool."""

    def test_browser_tool_accepts_cloud_backend(self) -> None:
        """BrowserTool constructor accepts and stores a cloud_backend parameter."""
        backend = CloudBrowserBackend(api_key="test-key")
        tool = BrowserTool(cloud_backend=backend)
        assert tool._cloud_backend is backend

    def test_browser_tool_cloud_backend_defaults_to_none(self) -> None:
        """BrowserTool defaults cloud_backend to None when not provided."""
        tool = BrowserTool()
        assert tool._cloud_backend is None

    async def test_cloud_fallback_when_playwright_unavailable(self) -> None:
        """When Playwright is unavailable and cloud backend is configured,
        the cloud backend is used to create a session."""
        backend = CloudBrowserBackend(api_key="test-key")
        cloud_session = CloudSession(
            session_id="cloud-1", connect_url="wss://cloud.example.com/cdp"
        )
        backend.connect = AsyncMock(return_value=cloud_session)
        mock_page = _make_mock_page()
        backend.get_playwright_page = AsyncMock(return_value=mock_page)

        tool = BrowserTool(cloud_backend=backend)

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", False):
            result = await tool.execute(
                {
                    "action": "extract_text",
                    "session_id": "cloud-session-1",
                },
                _make_context(),
            )

        assert result.success is True
        assert "Page text content" in result.output
        backend.connect.assert_awaited_once()
        backend.get_playwright_page.assert_awaited_once()
        # Session should be registered
        assert "cloud-session-1" in _sessions

    async def test_cloud_fallback_not_used_when_local_succeeds(self) -> None:
        """Cloud backend is not called when local Playwright session already exists."""
        backend = CloudBrowserBackend(api_key="test-key")
        backend.connect = AsyncMock()

        tool = BrowserTool(cloud_backend=backend)
        # Pre-install a local session
        _install_fake_session("s1")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {"action": "extract_text", "session_id": "s1"},
                _make_context(),
            )

        assert result.success is True
        backend.connect.assert_not_awaited()

    async def test_playwright_unavailable_no_cloud_returns_error(self) -> None:
        """When Playwright is unavailable and no cloud backend is configured,
        an error is returned (not a crash)."""
        tool = BrowserTool(cloud_backend=None)

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", False):
            result = await tool.execute(
                {"action": "navigate", "url": "https://example.com"},
                _make_context(),
            )

        assert result.success is False
        assert "Playwright" in result.error


# ===========================================================================
# Secret redaction (Gap 2)
# ===========================================================================


@patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True)
class TestSecretRedaction:
    """Tests for secret redaction on text-extracting browser actions."""

    async def test_extract_text_redacts_secrets(self) -> None:
        """extract_text action applies secret redaction to output."""
        tool = BrowserTool()
        page = _install_fake_session("s1")
        # Simulate page text containing an API key
        page.inner_text = AsyncMock(
            return_value="Config: sk-abcdefghijklmnopqrstuvwxyz1234567890 is the key"
        )

        with patch(
            "agent33.security.redaction.redact_secrets",
            side_effect=lambda text, **kw: text.replace(
                "sk-abcdefghijklmnopqrstuvwxyz1234567890", "sk-abc...7890"
            ),
        ) as mock_redact:
            result = await tool.execute(
                {"action": "extract_text", "session_id": "s1"},
                _make_context(),
            )

        assert result.success is True
        mock_redact.assert_called_once()
        # The secret should be masked in the output
        assert "sk-abcdefghijklmnopqrstuvwxyz1234567890" not in result.output
        assert "sk-abc...7890" in result.output

    async def test_redaction_called_on_vision_analyze(self) -> None:
        """vision_analyze action also applies redaction to its output."""
        router = _make_mock_router(content="Found API key sk-testkey1234567890123456 on page")
        tool = BrowserTool(router=router, vision_model="gpt-4o")
        _install_fake_session("s1")

        with patch(
            "agent33.security.redaction.redact_secrets",
            side_effect=lambda text, **kw: text.replace(
                "sk-testkey1234567890123456", "sk-tes...3456"
            ),
        ) as mock_redact:
            result = await tool.execute(
                {
                    "action": "vision_analyze",
                    "session_id": "s1",
                    "question": "What secrets are visible?",
                },
                _make_context(),
            )

        assert result.success is True
        mock_redact.assert_called_once()

    async def test_redaction_not_applied_to_navigate(self) -> None:
        """navigate action does not trigger redaction (not a text-extraction action)."""
        tool = BrowserTool()
        _install_fake_session("s1")

        with patch(
            "agent33.security.redaction.redact_secrets",
        ) as mock_redact:
            result = await tool.execute(
                {
                    "action": "navigate",
                    "session_id": "s1",
                    "url": "https://example.com",
                },
                _make_context(),
            )

        assert result.success is True
        mock_redact.assert_not_called()

    async def test_redaction_failure_returns_original_output(self) -> None:
        """If redaction fails, the original output is returned (fail-safe)."""
        tool = BrowserTool()
        page = _install_fake_session("s1")
        page.inner_text = AsyncMock(return_value="Page content with secrets")

        with patch(
            "agent33.security.redaction.redact_secrets",
            side_effect=RuntimeError("redaction broke"),
        ):
            result = await tool.execute(
                {"action": "extract_text", "session_id": "s1"},
                _make_context(),
            )

        assert result.success is True
        assert result.output == "Page content with secrets"

    async def test_redaction_not_applied_to_failed_results(self) -> None:
        """Redaction is skipped for failed tool results."""
        result = ToolResult.fail("Some error")
        out = BrowserTool._maybe_redact("extract_text", result)
        assert out is result


# ===========================================================================
# Extended vision model prefixes (Gap 3)
# ===========================================================================


class TestExtendedVisionPrefixes:
    """Tests for the extended vision model prefix list."""

    @pytest.mark.parametrize(
        "model_name",
        [
            "qwen2.5-vl-7b",
            "qwen-vl-plus",
            "internvl2-26b",
            "cogvlm-chat-hf",
            "phi-3-vision-128k",
            "phi-3.5-vision-instruct",
        ],
    )
    def test_new_vision_prefixes_recognized(self, model_name: str) -> None:
        """Each new vision model prefix is recognized by the prefix list."""
        lower = model_name.lower()
        matched = any(lower.startswith(p) for p in _VISION_MODEL_PREFIXES)
        assert matched, f"{model_name} should match a vision prefix"

    @pytest.mark.parametrize(
        "model_name",
        [
            "gpt-4o-mini",
            "claude-3-opus",
            "claude-4-sonnet",
            "gemini-pro",
            "llava-v1.6",
            "llama3.2-vision-11b",
            "minicpm-v-2",
        ],
    )
    def test_original_vision_prefixes_still_work(self, model_name: str) -> None:
        """Original vision model prefixes continue to match."""
        lower = model_name.lower()
        matched = any(lower.startswith(p) for p in _VISION_MODEL_PREFIXES)
        assert matched, f"{model_name} should match a vision prefix"

    @pytest.mark.parametrize(
        "model_name",
        [
            "codellama-34b",
            "phi-2",
            "mistral-7b",
        ],
    )
    def test_non_vision_models_not_matched(self, model_name: str) -> None:
        """Non-vision models are not matched by the prefix list."""
        lower = model_name.lower()
        matched = any(lower.startswith(p) for p in _VISION_MODEL_PREFIXES)
        assert not matched, f"{model_name} should NOT match a vision prefix"

    async def test_auto_detect_finds_new_vision_models(self) -> None:
        """Auto-detection finds new vision-capable models like qwen2.5-vl."""
        router = _make_mock_router(models=["codellama-34b", "qwen2.5-vl-7b", "mistral-7b"])
        tool = BrowserTool(router=router, vision_model="")
        _install_fake_session("s1")

        with patch("agent33.tools.builtin.browser._PLAYWRIGHT_AVAILABLE", True):
            result = await tool.execute(
                {
                    "action": "vision_analyze",
                    "session_id": "s1",
                    "question": "Describe the page",
                },
                _make_context(),
            )

        assert result.success is True
        call_args = router.complete.call_args
        assert call_args.kwargs["model"] == "qwen2.5-vl-7b"
