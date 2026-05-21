"""Tests for environment-seeded auth bootstrap behavior."""

from __future__ import annotations

from fastapi.testclient import TestClient

from agent33.main import app
from agent33.security.auth import verify_token


def test_bootstrap_login_enabled(monkeypatch) -> None:
    from agent33.api.routes import auth as auth_routes

    original_users = dict(auth_routes._users)
    try:
        auth_routes._users.clear()
        monkeypatch.setattr(auth_routes.settings, "auth_bootstrap_enabled", True)
        monkeypatch.setattr(auth_routes.settings, "auth_bootstrap_admin_username", "boot-admin")
        monkeypatch.setattr(
            auth_routes.settings,
            "auth_bootstrap_admin_password",
            auth_routes.settings.auth_bootstrap_admin_password.__class__("boot-pass"),
        )
        monkeypatch.setattr(
            auth_routes.settings,
            "auth_bootstrap_admin_scopes",
            "admin,agents:read,workflows:read",
        )

        client = TestClient(app)
        resp = client.post(
            "/v1/auth/token",
            json={"username": "boot-admin", "password": "boot-pass"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        token = verify_token(data["access_token"])
        assert token.sub == "boot-admin"
        assert "admin" in token.scopes
    finally:
        auth_routes._users.clear()
        auth_routes._users.update(original_users)


def test_bootstrap_login_disabled(monkeypatch) -> None:
    from agent33.api.routes import auth as auth_routes

    original_users = dict(auth_routes._users)
    try:
        auth_routes._users.clear()
        monkeypatch.setattr(auth_routes.settings, "auth_bootstrap_enabled", False)
        monkeypatch.setattr(auth_routes.settings, "auth_bootstrap_admin_username", "nope")
        monkeypatch.setattr(
            auth_routes.settings,
            "auth_bootstrap_admin_password",
            auth_routes.settings.auth_bootstrap_admin_password.__class__("nope"),
        )

        client = TestClient(app)
        resp = client.post(
            "/v1/auth/token",
            json={"username": "nope", "password": "nope"},
        )
        assert resp.status_code == 401
    finally:
        auth_routes._users.clear()
        auth_routes._users.update(original_users)
