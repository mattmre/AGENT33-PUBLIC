"""Tests for AuthRepository abstraction (P3.4)."""

from __future__ import annotations

import pytest

from agent33.security.auth_repository import (
    AuthRepository,
    InMemoryAuthRepository,
    get_auth_repository,
    set_auth_repository,
)


class TestInMemoryAuthRepositoryUsers:
    """InMemoryAuthRepository user CRUD operations."""

    def test_create_user_returns_record(self) -> None:
        repo = InMemoryAuthRepository()
        user = repo.create_user(
            username="alice",
            password_hash="hash123",
            tenant_id="t1",
            role="admin",
            salt="aabbcc",
            scopes=["admin", "read"],
        )
        assert user["username"] == "alice"
        assert user["password_hash"] == "hash123"
        assert user["tenant_id"] == "t1"
        assert user["role"] == "admin"
        assert user["salt"] == "aabbcc"
        assert user["scopes"] == ["admin", "read"]

    def test_get_user_returns_none_when_missing(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.get_user("nonexistent") is None

    def test_get_user_returns_created_user(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_user(username="bob", password_hash="pw", tenant_id="t1")
        user = repo.get_user("bob")
        assert user is not None
        assert user["username"] == "bob"
        assert user["password_hash"] == "pw"

    def test_create_duplicate_user_raises_value_error(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_user(username="alice", password_hash="hash1", tenant_id="t1")
        with pytest.raises(ValueError, match="alice already exists"):
            repo.create_user(username="alice", password_hash="hash2", tenant_id="t1")

    def test_has_user_true_when_exists(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_user(username="charlie", password_hash="pw", tenant_id="t1")
        assert repo.has_user("charlie") is True

    def test_has_user_false_when_missing(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.has_user("ghost") is False

    def test_set_user_creates_or_overwrites(self) -> None:
        repo = InMemoryAuthRepository()
        repo.set_user("dave", {"password_hash": "p1", "scopes": ["read"]})
        user = repo.get_user("dave")
        assert user is not None
        assert user["password_hash"] == "p1"

        # Overwrite
        repo.set_user("dave", {"password_hash": "p2", "scopes": ["admin"]})
        user2 = repo.get_user("dave")
        assert user2 is not None
        assert user2["password_hash"] == "p2"

    def test_delete_user_returns_true_when_found(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_user(username="eve", password_hash="pw", tenant_id="t1")
        assert repo.delete_user("eve") is True
        assert repo.get_user("eve") is None

    def test_delete_user_returns_false_when_missing(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.delete_user("nobody") is False

    def test_create_user_without_optional_fields(self) -> None:
        repo = InMemoryAuthRepository()
        user = repo.create_user(username="minimal", password_hash="pw", tenant_id="t1")
        assert user["role"] == "user"
        assert "salt" not in user
        assert "scopes" not in user


class TestInMemoryAuthRepositoryApiKeys:
    """InMemoryAuthRepository API key operations."""

    def test_create_api_key_returns_record(self) -> None:
        repo = InMemoryAuthRepository()
        record = repo.create_api_key(
            key_hash="abc123",
            key_id="kid1",
            subject="svc-user",
            scopes=["admin"],
            tenant_id="t1",
            expires_at=9999999999,
        )
        assert record["key_id"] == "kid1"
        assert record["subject"] == "svc-user"
        assert record["scopes"] == ["admin"]
        assert record["tenant_id"] == "t1"
        assert record["expires_at"] == 9999999999
        assert record["created_at"] > 0

    def test_get_api_key_returns_none_when_missing(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.get_api_key("nonexistent") is None

    def test_get_api_key_returns_created_key(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="hash1",
            key_id="kid1",
            subject="user1",
            scopes=["read"],
            tenant_id="t1",
        )
        key = repo.get_api_key("hash1")
        assert key is not None
        assert key["key_id"] == "kid1"

    def test_delete_api_key_returns_true_when_found(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="hash1",
            key_id="kid1",
            subject="user1",
            scopes=[],
            tenant_id="t1",
        )
        assert repo.delete_api_key("hash1") is True
        assert repo.get_api_key("hash1") is None

    def test_delete_api_key_returns_false_when_missing(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.delete_api_key("nope") is False

    def test_revoke_api_key_by_id_admin_bypass(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="kid1",
            subject="alice",
            scopes=["read"],
            tenant_id="t1",
        )
        # Admin bypass: requesting_subject=None
        assert repo.revoke_api_key_by_id("kid1", requesting_subject=None) is True
        assert repo.get_api_key("h1") is None

    def test_revoke_api_key_by_id_owner_match(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="kid1",
            subject="alice",
            scopes=["read"],
            tenant_id="t1",
        )
        assert repo.revoke_api_key_by_id("kid1", requesting_subject="alice") is True

    def test_revoke_api_key_by_id_non_owner_rejected(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="kid1",
            subject="alice",
            scopes=["read"],
            tenant_id="t1",
        )
        assert repo.revoke_api_key_by_id("kid1", requesting_subject="bob") is False
        # Key should still exist
        assert repo.get_api_key("h1") is not None

    def test_revoke_api_key_by_id_not_found(self) -> None:
        repo = InMemoryAuthRepository()
        assert repo.revoke_api_key_by_id("missing") is False

    def test_list_api_keys_returns_all(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="k1",
            subject="a",
            scopes=[],
            tenant_id="t1",
        )
        repo.create_api_key(
            key_hash="h2",
            key_id="k2",
            subject="b",
            scopes=[],
            tenant_id="t2",
        )
        keys = repo.list_api_keys()
        assert len(keys) == 2

    def test_list_api_keys_filtered_by_tenant(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="k1",
            subject="a",
            scopes=[],
            tenant_id="t1",
        )
        repo.create_api_key(
            key_hash="h2",
            key_id="k2",
            subject="b",
            scopes=[],
            tenant_id="t2",
        )
        repo.create_api_key(
            key_hash="h3",
            key_id="k3",
            subject="c",
            scopes=[],
            tenant_id="t1",
        )
        t1_keys = repo.list_api_keys(tenant_id="t1")
        assert len(t1_keys) == 2
        assert all(k["tenant_id"] == "t1" for k in t1_keys)

        t2_keys = repo.list_api_keys(tenant_id="t2")
        assert len(t2_keys) == 1


class TestAuthRepositoryProtocol:
    """Verify InMemoryAuthRepository satisfies the AuthRepository protocol."""

    def test_inmemory_is_auth_repository(self) -> None:
        repo = InMemoryAuthRepository()
        assert isinstance(repo, AuthRepository)


class TestAuthRepositoryAccessors:
    """Test module-level get/set accessor pattern."""

    def test_get_auth_repository_creates_default(self) -> None:
        import agent33.security.auth_repository as mod

        original = mod._repository
        try:
            mod._repository = None
            repo = get_auth_repository()
            assert isinstance(repo, InMemoryAuthRepository)
        finally:
            mod._repository = original

    def test_set_auth_repository_overrides(self) -> None:
        import agent33.security.auth_repository as mod

        original = mod._repository
        try:
            custom = InMemoryAuthRepository()
            set_auth_repository(custom)
            assert get_auth_repository() is custom
        finally:
            mod._repository = original

    def test_get_returns_same_instance(self) -> None:
        import agent33.security.auth_repository as mod

        original = mod._repository
        try:
            mod._repository = None
            repo1 = get_auth_repository()
            repo2 = get_auth_repository()
            assert repo1 is repo2
        finally:
            mod._repository = original


class TestInternalDictBackwardsCompat:
    """Verify that the internal _users and _api_keys dicts are directly accessible."""

    def test_users_dict_shared_with_repository(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_user(username="test", password_hash="pw", tenant_id="t1")
        # Direct dict access for backwards compat
        assert "test" in repo._users
        assert repo._users["test"]["password_hash"] == "pw"

    def test_api_keys_dict_shared_with_repository(self) -> None:
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="k1",
            subject="a",
            scopes=[],
            tenant_id="t1",
        )
        assert "h1" in repo._api_keys
        assert repo._api_keys["h1"]["key_id"] == "k1"

    def test_direct_dict_mutation_visible_through_repo(self) -> None:
        """Tests can mutate internal dicts and the repository sees changes."""
        repo = InMemoryAuthRepository()
        repo.create_api_key(
            key_hash="h1",
            key_id="k1",
            subject="a",
            scopes=[],
            tenant_id="t1",
            expires_at=9999,
        )
        # Mutate directly (like test_phase14_security does)
        repo._api_keys["h1"]["expires_at"] = 0
        key = repo.get_api_key("h1")
        assert key is not None
        assert key["expires_at"] == 0
