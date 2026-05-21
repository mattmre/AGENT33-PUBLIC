"""Capability pack system -- curated bundles of SpecCapability entries.

Phase 47 delivers importable "packs" that augment agent definitions with
pre-curated sets of capabilities.  A pack bundles a named group of
SpecCapability IDs together with metadata (version, description, compatibility
requirements) so that operators can apply domain-relevant capability profiles
to agents without hand-picking individual taxonomy entries.

Key design decisions:
- Packs *augment* existing agent capabilities -- they never replace them.
- Agents without packs continue to work exactly as before.
- Built-in packs ship with the engine; custom packs can be registered at runtime.
- Compatibility requirements are checked before application and surfaced as errors.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator

from agent33.agents.definition import AgentDefinition, SpecCapability

logger = logging.getLogger(__name__)

# Engine version used for compatibility checks.
ENGINE_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class CompatibilityRequirements(BaseModel):
    """Requirements that must be met before a pack can be applied."""

    min_engine_version: str = Field(
        default="0.1.0",
        description="Minimum engine version required.",
    )
    required_tools: list[str] = Field(
        default_factory=list,
        description="Tool names that must be available for this pack.",
    )
    required_capabilities: list[SpecCapability] = Field(
        default_factory=list,
        description="SpecCapabilities the agent must already have.",
    )
    excluded_capabilities: list[SpecCapability] = Field(
        default_factory=list,
        description="SpecCapabilities that conflict with this pack.",
    )


class CapabilityPack(BaseModel):
    """A named bundle of capabilities with metadata.

    Each pack groups a curated set of SpecCapability IDs under a
    human-readable name with versioning and compatibility metadata.
    """

    name: str = Field(
        ...,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z][a-z0-9-]*$",
        description="Unique pack identifier (kebab-case).",
    )
    description: str = Field(
        default="",
        max_length=500,
        description="Human-readable description of the pack.",
    )
    version: str = Field(
        ...,
        pattern=r"^\d+\.\d+\.\d+$",
        description="Semantic version of this pack.",
    )
    capabilities: list[SpecCapability] = Field(
        ...,
        min_length=1,
        description="SpecCapability IDs included in this pack.",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Searchable tags for this pack.",
    )
    author: str = Field(
        default="agent33",
        description="Author or team that created this pack.",
    )
    compatibility: CompatibilityRequirements = Field(
        default_factory=CompatibilityRequirements,
        description="Requirements for applying this pack.",
    )
    builtin: bool = Field(
        default=False,
        description="Whether this pack ships with the engine.",
    )
    created_at: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="ISO-8601 creation timestamp.",
    )

    @field_validator("capabilities")
    @classmethod
    def deduplicate_capabilities(cls, v: list[SpecCapability]) -> list[SpecCapability]:
        """Remove duplicates while preserving order."""
        seen: set[SpecCapability] = set()
        deduped: list[SpecCapability] = []
        for cap in v:
            if cap not in seen:
                seen.add(cap)
                deduped.append(cap)
        return deduped


class PackApplicationResult(BaseModel):
    """Result of applying or removing a pack from an agent."""

    success: bool
    agent_name: str
    pack_name: str
    capabilities_added: list[str] = Field(default_factory=list)
    capabilities_removed: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class CompatibilityCheckResult(BaseModel):
    """Result of checking whether a pack is compatible with an agent."""

    compatible: bool
    pack_name: str
    agent_name: str
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Built-in packs
# ---------------------------------------------------------------------------


def _builtin_packs() -> list[CapabilityPack]:
    """Return the set of packs that ship with the engine."""
    return [
        CapabilityPack(
            name="research-pack",
            description=(
                "Web search, document analysis, literature survey, "
                "competitive analysis, and knowledge synthesis."
            ),
            version="1.0.0",
            capabilities=[
                SpecCapability.X_01,  # Web Search
                SpecCapability.X_02,  # Codebase Analysis
                SpecCapability.X_03,  # Literature Survey
                SpecCapability.X_04,  # Competitive Analysis
                SpecCapability.X_05,  # Knowledge Synthesis
            ],
            tags=["research", "analysis", "search"],
            author="agent33",
            builtin=True,
        ),
        CapabilityPack(
            name="coding-pack",
            description=(
                "Code generation, modification, unit testing, "
                "integration testing, and code review."
            ),
            version="1.0.0",
            capabilities=[
                SpecCapability.I_01,  # Code Generation
                SpecCapability.I_02,  # Code Modification
                SpecCapability.V_01,  # Unit Testing
                SpecCapability.V_02,  # Integration Testing
                SpecCapability.R_01,  # Code Review
            ],
            tags=["coding", "development", "testing", "review"],
            author="agent33",
            builtin=True,
        ),
        CapabilityPack(
            name="operations-pack",
            description=(
                "Configuration management, integration wiring, "
                "output validation, performance review, and workflow design."
            ),
            version="1.0.0",
            capabilities=[
                SpecCapability.I_03,  # Configuration Management
                SpecCapability.I_05,  # Integration Wiring
                SpecCapability.V_03,  # Output Validation
                SpecCapability.R_04,  # Performance Review
                SpecCapability.P_05,  # Workflow Design
            ],
            tags=["operations", "deployment", "monitoring", "infrastructure"],
            author="agent33",
            builtin=True,
        ),
        CapabilityPack(
            name="security-pack",
            description=(
                "Security scanning, compliance checking, security review, "
                "risk assessment, and output validation."
            ),
            version="1.0.0",
            capabilities=[
                SpecCapability.V_04,  # Security Scanning
                SpecCapability.V_05,  # Compliance Checking
                SpecCapability.R_05,  # Security Review
                SpecCapability.P_04,  # Risk Assessment
                SpecCapability.V_03,  # Output Validation
            ],
            tags=["security", "compliance", "vulnerability", "audit"],
            author="agent33",
            builtin=True,
        ),
        CapabilityPack(
            name="data-pack",
            description=(
                "Data transformation, codebase analysis, output validation, "
                "knowledge synthesis, and integration wiring."
            ),
            version="1.0.0",
            capabilities=[
                SpecCapability.I_04,  # Data Transformation
                SpecCapability.X_02,  # Codebase Analysis
                SpecCapability.V_03,  # Output Validation
                SpecCapability.X_05,  # Knowledge Synthesis
                SpecCapability.I_05,  # Integration Wiring
            ],
            tags=["data", "analysis", "etl", "visualization"],
            author="agent33",
            builtin=True,
        ),
    ]


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse a semver string into a tuple of ints for comparison."""
    try:
        return tuple(int(p) for p in version.split("."))
    except (ValueError, AttributeError):
        return (0, 0, 0)


def _version_gte(current: str, minimum: str) -> bool:
    """Return True if *current* >= *minimum* (semver comparison)."""
    return _parse_version(current) >= _parse_version(minimum)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class CapabilityPackRegistry:
    """In-memory registry of capability packs.

    Loads built-in packs on construction and supports runtime registration
    of custom packs.
    """

    def __init__(self, *, load_builtins: bool = True) -> None:
        self._packs: dict[str, CapabilityPack] = {}
        self._agent_packs: dict[str, set[str]] = {}  # agent_name -> set of pack names
        if load_builtins:
            for pack in _builtin_packs():
                self._packs[pack.name] = pack
            logger.info("loaded %d built-in capability packs", len(self._packs))

    # -- Pack CRUD --------------------------------------------------------

    def register(self, pack: CapabilityPack) -> None:
        """Add or replace a capability pack."""
        if pack.name in self._packs and self._packs[pack.name].builtin:
            raise ValueError(
                f"Cannot replace built-in pack '{pack.name}'. Unregister it first with force=True."
            )
        self._packs[pack.name] = pack
        logger.info("registered capability pack: %s v%s", pack.name, pack.version)

    def register_force(self, pack: CapabilityPack) -> None:
        """Add or replace a capability pack, even if it is built-in."""
        self._packs[pack.name] = pack
        logger.info("force-registered capability pack: %s v%s", pack.name, pack.version)

    def unregister(self, name: str, *, force: bool = False) -> bool:
        """Remove a pack by name.

        Returns True if the pack existed and was removed.
        Raises ValueError if trying to remove a built-in pack without force.
        """
        pack = self._packs.get(name)
        if pack is None:
            return False
        if pack.builtin and not force:
            raise ValueError(f"Cannot unregister built-in pack '{name}'. Use force=True.")
        # Clean up agent associations
        for agent_name in list(self._agent_packs):
            self._agent_packs[agent_name].discard(name)
            if not self._agent_packs[agent_name]:
                del self._agent_packs[agent_name]
        del self._packs[name]
        logger.info("unregistered capability pack: %s", name)
        return True

    def get(self, name: str) -> CapabilityPack | None:
        """Return a pack by name, or None if not found."""
        return self._packs.get(name)

    def list_all(self) -> list[CapabilityPack]:
        """Return all registered packs sorted by name."""
        return sorted(self._packs.values(), key=lambda p: p.name)

    def list_builtin(self) -> list[CapabilityPack]:
        """Return only built-in packs."""
        return sorted(
            (p for p in self._packs.values() if p.builtin),
            key=lambda p: p.name,
        )

    def list_custom(self) -> list[CapabilityPack]:
        """Return only user-registered packs."""
        return sorted(
            (p for p in self._packs.values() if not p.builtin),
            key=lambda p: p.name,
        )

    def search(self, query: str) -> list[CapabilityPack]:
        """Search packs by name, description, or tags (case-insensitive)."""
        q = query.lower()
        results: list[CapabilityPack] = []
        for pack in self._packs.values():
            if (
                q in pack.name.lower()
                or q in pack.description.lower()
                or any(q in tag.lower() for tag in pack.tags)
            ):
                results.append(pack)
        return sorted(results, key=lambda p: p.name)

    def __len__(self) -> int:
        return len(self._packs)

    def __contains__(self, name: str) -> bool:
        return name in self._packs

    # -- Compatibility checks ---------------------------------------------

    def check_compatibility(
        self,
        pack_name: str,
        agent: AgentDefinition,
        *,
        available_tools: list[str] | None = None,
        engine_version: str | None = None,
    ) -> CompatibilityCheckResult:
        """Check whether a pack can be applied to an agent.

        Returns a result with ``compatible=True`` if all requirements pass.
        """
        pack = self._packs.get(pack_name)
        if pack is None:
            return CompatibilityCheckResult(
                compatible=False,
                pack_name=pack_name,
                agent_name=agent.name,
                errors=[f"Pack '{pack_name}' not found."],
            )

        errors: list[str] = []
        warnings: list[str] = []
        effective_version = engine_version or ENGINE_VERSION

        # Engine version check
        if not _version_gte(effective_version, pack.compatibility.min_engine_version):
            errors.append(
                f"Engine version {effective_version} < "
                f"required {pack.compatibility.min_engine_version}."
            )

        # Required tools check
        if pack.compatibility.required_tools:
            available = set(available_tools or [])
            missing = set(pack.compatibility.required_tools) - available
            if missing:
                errors.append(f"Missing required tools: {sorted(missing)}.")

        # Required capabilities check
        agent_caps = set(agent.spec_capabilities)
        for req_cap in pack.compatibility.required_capabilities:
            if req_cap not in agent_caps:
                errors.append(f"Agent '{agent.name}' missing required capability {req_cap.value}.")

        # Excluded capabilities check
        for excl_cap in pack.compatibility.excluded_capabilities:
            if excl_cap in agent_caps:
                errors.append(
                    f"Agent '{agent.name}' has conflicting capability "
                    f"{excl_cap.value} excluded by pack."
                )

        # Warn on overlap
        pack_caps = set(pack.capabilities)
        overlap = agent_caps & pack_caps
        if overlap:
            warnings.append(
                f"Agent already has capabilities from this pack: "
                f"{sorted(c.value for c in overlap)}. "
                "They will not be duplicated."
            )

        return CompatibilityCheckResult(
            compatible=len(errors) == 0,
            pack_name=pack_name,
            agent_name=agent.name,
            errors=errors,
            warnings=warnings,
        )

    # -- Pack application -------------------------------------------------

    def apply_pack(
        self,
        pack_name: str,
        agent: AgentDefinition,
        *,
        available_tools: list[str] | None = None,
        engine_version: str | None = None,
        skip_compat_check: bool = False,
    ) -> PackApplicationResult:
        """Apply a pack's capabilities to an agent definition.

        This *augments* the agent's spec_capabilities -- it never removes
        existing capabilities.
        """
        pack = self._packs.get(pack_name)
        if pack is None:
            return PackApplicationResult(
                success=False,
                agent_name=agent.name,
                pack_name=pack_name,
                errors=[f"Pack '{pack_name}' not found."],
            )

        if not skip_compat_check:
            compat = self.check_compatibility(
                pack_name,
                agent,
                available_tools=available_tools,
                engine_version=engine_version,
            )
            if not compat.compatible:
                return PackApplicationResult(
                    success=False,
                    agent_name=agent.name,
                    pack_name=pack_name,
                    errors=compat.errors,
                    warnings=compat.warnings,
                )

        existing = set(agent.spec_capabilities)
        added: list[str] = []
        for cap in pack.capabilities:
            if cap not in existing:
                agent.spec_capabilities.append(cap)
                added.append(cap.value)

        # Track association
        if agent.name not in self._agent_packs:
            self._agent_packs[agent.name] = set()
        self._agent_packs[agent.name].add(pack_name)

        warnings: list[str] = []
        overlap = existing & set(pack.capabilities)
        if overlap:
            warnings.append(
                f"Skipped already-present capabilities: {sorted(c.value for c in overlap)}."
            )

        logger.info(
            "applied pack '%s' to agent '%s': added %d capabilities",
            pack_name,
            agent.name,
            len(added),
        )

        return PackApplicationResult(
            success=True,
            agent_name=agent.name,
            pack_name=pack_name,
            capabilities_added=added,
            warnings=warnings,
        )

    def remove_pack(
        self,
        pack_name: str,
        agent: AgentDefinition,
    ) -> PackApplicationResult:
        """Remove a pack's capabilities from an agent definition.

        Only removes capabilities that were added by this pack and are not
        shared with another applied pack.
        """
        pack = self._packs.get(pack_name)
        if pack is None:
            return PackApplicationResult(
                success=False,
                agent_name=agent.name,
                pack_name=pack_name,
                errors=[f"Pack '{pack_name}' not found."],
            )

        agent_applied = self._agent_packs.get(agent.name, set())
        if pack_name not in agent_applied:
            return PackApplicationResult(
                success=False,
                agent_name=agent.name,
                pack_name=pack_name,
                errors=[f"Pack '{pack_name}' is not applied to agent '{agent.name}'."],
            )

        # Determine which capabilities are provided by other applied packs
        protected_caps: set[SpecCapability] = set()
        for other_pack_name in agent_applied:
            if other_pack_name == pack_name:
                continue
            other_pack = self._packs.get(other_pack_name)
            if other_pack is not None:
                protected_caps.update(other_pack.capabilities)

        removed: list[str] = []
        warnings: list[str] = []
        for cap in pack.capabilities:
            if cap in protected_caps:
                warnings.append(f"Kept {cap.value} (also provided by another applied pack).")
                continue
            if cap in agent.spec_capabilities:
                agent.spec_capabilities.remove(cap)
                removed.append(cap.value)

        # Update tracking
        agent_applied.discard(pack_name)
        if not agent_applied:
            self._agent_packs.pop(agent.name, None)

        logger.info(
            "removed pack '%s' from agent '%s': removed %d capabilities",
            pack_name,
            agent.name,
            len(removed),
        )

        return PackApplicationResult(
            success=True,
            agent_name=agent.name,
            pack_name=pack_name,
            capabilities_removed=removed,
            warnings=warnings,
        )

    def get_agent_packs(self, agent_name: str) -> list[str]:
        """Return the names of packs currently applied to an agent."""
        return sorted(self._agent_packs.get(agent_name, set()))

    def get_pack_agents(self, pack_name: str) -> list[str]:
        """Return the names of agents that have a given pack applied."""
        return sorted(name for name, packs in self._agent_packs.items() if pack_name in packs)

    # -- Serialization helpers --------------------------------------------

    def to_summary(self, pack: CapabilityPack) -> dict[str, Any]:
        """Return a summary dict suitable for API responses."""
        return {
            "name": pack.name,
            "description": pack.description,
            "version": pack.version,
            "capabilities": [c.value for c in pack.capabilities],
            "capabilities_count": len(pack.capabilities),
            "tags": pack.tags,
            "author": pack.author,
            "builtin": pack.builtin,
        }

    def to_detail(self, pack: CapabilityPack) -> dict[str, Any]:
        """Return a full detail dict suitable for API responses."""
        from agent33.agents.capabilities import CAPABILITY_CATALOG

        cap_details = []
        for cap in pack.capabilities:
            info = CAPABILITY_CATALOG.get(cap)
            cap_details.append(
                {
                    "id": cap.value,
                    "name": info.name if info else cap.value,
                    "description": info.description if info else "",
                    "category": info.category.name.capitalize() if info else "",
                }
            )

        return {
            **self.to_summary(pack),
            "capability_details": cap_details,
            "compatibility": pack.compatibility.model_dump(),
            "created_at": pack.created_at,
            "applied_to_agents": self.get_pack_agents(pack.name),
        }
