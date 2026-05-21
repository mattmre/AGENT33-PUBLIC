"""AEP-B01: verify component-security lifespan init and shutdown cleanup."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from agent33.api.routes import component_security
from agent33.api.routes.component_security import (
    _build_security_scan_store,
    get_component_security_service,
    init_component_security_service,
)
from agent33.services.security_scan import SecurityScanService


@pytest.fixture(autouse=True)
def _reset_module_service() -> Any:
    """Reset the module-level _service to None before and after each test."""
    import agent33.api.routes.component_security as mod

    original = mod._service
    mod._service = None
    yield
    mod._service = original


class TestInitComponentSecurityService:
    """Verify init_component_security_service wires app.state correctly."""

    def test_sets_service_on_app_state(self) -> None:
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=False,
            component_security_scan_store_db_path="",
            component_security_scan_store_retention_days=90,
        )

        init_component_security_service(app, cfg)

        assert hasattr(app.state, "security_scan_service")
        assert isinstance(app.state.security_scan_service, SecurityScanService)

    def test_sets_store_none_when_disabled(self) -> None:
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=False,
            component_security_scan_store_db_path="",
            component_security_scan_store_retention_days=90,
        )

        init_component_security_service(app, cfg)

        assert app.state.security_scan_store is None

    def test_sets_store_when_enabled(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test-security.sqlite3")
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=True,
            component_security_scan_store_db_path=db_path,
            component_security_scan_store_retention_days=30,
        )

        init_component_security_service(app, cfg)

        assert app.state.security_scan_store is not None
        # Cleanup
        app.state.security_scan_store.close()

    def test_get_returns_same_instance_after_init(self) -> None:
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=False,
            component_security_scan_store_db_path="",
            component_security_scan_store_retention_days=90,
        )

        init_component_security_service(app, cfg)
        service = get_component_security_service()

        assert service is app.state.security_scan_service

    def test_records_unavailable_status_when_store_init_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=True,
            component_security_scan_store_db_path="broken.sqlite3",
            component_security_scan_store_retention_days=90,
        )

        def _raise_store_error(*_args: Any, **_kwargs: Any) -> Any:
            raise OSError("disk unavailable")

        monkeypatch.setattr(component_security, "SecurityScanStore", _raise_store_error)

        init_component_security_service(app, cfg)

        assert app.state.security_scan_service is None
        assert app.state.security_scan_store is None
        assert app.state.security_scan_status["status"] == "unavailable"
        assert "disk unavailable" in app.state.security_scan_status["reason"]
        assert "restart" in app.state.security_scan_status["required_action"]


class TestGetComponentSecurityServiceFallback:
    """Verify fallback behavior when init was not called."""

    def test_creates_default_service_when_not_initialized(self) -> None:
        service = get_component_security_service()
        assert isinstance(service, SecurityScanService)

    def test_returns_same_instance_on_repeated_calls(self) -> None:
        first = get_component_security_service()
        second = get_component_security_service()
        assert first is second


class TestBuildSecurityScanStore:
    """Verify _build_security_scan_store respects config."""

    def test_returns_none_when_disabled(self) -> None:
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=False,
            component_security_scan_store_db_path="foo.sqlite3",
        )
        assert _build_security_scan_store(cfg) is None

    def test_returns_none_when_db_path_empty(self) -> None:
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=True,
            component_security_scan_store_db_path="   ",
        )
        assert _build_security_scan_store(cfg) is None

    def test_returns_store_when_enabled(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "test.sqlite3")
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=True,
            component_security_scan_store_db_path=db_path,
        )
        store = _build_security_scan_store(cfg)
        assert store is not None
        store.close()


class TestStoreShutdownCleanup:
    """Verify the store close() pattern used in main.py shutdown."""

    def test_store_close_is_callable(self, tmp_path: Any) -> None:
        db_path = str(tmp_path / "shutdown-test.sqlite3")
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=True,
            component_security_scan_store_db_path=db_path,
            component_security_scan_store_retention_days=90,
        )

        init_component_security_service(app, cfg)
        store = app.state.security_scan_store

        assert store is not None
        # Simulate the shutdown pattern from main.py
        store.close()
        # Second close should not raise
        store.close()

    def test_shutdown_skips_when_store_is_none(self) -> None:
        app = SimpleNamespace()
        app.state = SimpleNamespace()
        cfg = SimpleNamespace(
            component_security_scan_store_enabled=False,
            component_security_scan_store_db_path="",
            component_security_scan_store_retention_days=90,
        )

        init_component_security_service(app, cfg)

        # Simulate the shutdown pattern from main.py
        _security_store = getattr(app.state, "security_scan_store", None)
        if _security_store is not None:
            _security_store.close()
        # No error means the guard works
        assert app.state.security_scan_store is None
