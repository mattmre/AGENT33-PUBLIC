"""Deferred product surface decision contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class DeferredSurface(StrEnum):
    I18N = "i18n"
    THEMES = "themes"
    WASM = "wasm"
    SANDBOX_UI = "sandbox_ui"


class DeferredSurfaceDecision(BaseModel):
    surface: DeferredSurface
    decision: str = "defer"
    reason: str
    revisit_after: str = ""


def active_deferred_surfaces(
    decisions: list[DeferredSurfaceDecision],
) -> list[DeferredSurface]:
    return [decision.surface for decision in decisions if decision.decision == "defer"]


def deferred_surface_actions(
    decisions: list[DeferredSurfaceDecision],
) -> list[str]:
    return [
        f"{decision.surface.value}: {decision.reason}"
        for decision in decisions
        if decision.decision == "defer"
    ]
