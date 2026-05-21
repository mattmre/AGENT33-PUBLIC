"""Persistence wrapper for pack trust policy management."""

from __future__ import annotations

from typing import Any

from agent33.packs.provenance_models import PackTrustPolicy, TrustLevel


class TrustPolicyManager:
    """Manage persisted pack trust policy state."""

    def __init__(
        self,
        state_store: Any | None = None,
        *,
        namespace: str = "pack_trust_policy",
    ) -> None:
        self._state_store = state_store
        self._namespace = namespace
        self._policy = PackTrustPolicy()
        self._load()

    def get_policy(self) -> PackTrustPolicy:
        return self._policy.model_copy(deep=True)

    def update_policy(
        self,
        *,
        require_signature: bool | None = None,
        min_trust_level: TrustLevel | None = None,
        allowed_signers: list[str] | None = None,
    ) -> PackTrustPolicy:
        if require_signature is not None:
            self._policy.require_signature = require_signature
        if min_trust_level is not None:
            self._policy.min_trust_level = min_trust_level
        if allowed_signers is not None:
            self._policy.allowed_signers = list(allowed_signers)
        self._persist()
        return self.get_policy()

    def _load(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace(self._namespace)
        if not payload:
            return
        try:
            self._policy = PackTrustPolicy.model_validate(payload)
        except Exception:
            self._policy = PackTrustPolicy()

    def _persist(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(self._namespace, self._policy.model_dump(mode="json"))
