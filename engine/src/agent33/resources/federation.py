"""Federated registry hook contracts."""

from __future__ import annotations

from pydantic import BaseModel


class FederatedRegistry(BaseModel):
    registry_id: str
    base_url: str
    trust_required: bool = True


class RegistryHookEvent(BaseModel):
    event_type: str
    registry_id: str
    resource_id: str = ""
    trust_required: bool = True


def registry_sync_hooks(
    registries: list[FederatedRegistry],
) -> list[RegistryHookEvent]:
    return [
        RegistryHookEvent(
            event_type="registry_sync_requested",
            registry_id=registry.registry_id,
            trust_required=registry.trust_required,
        )
        for registry in registries
    ]
