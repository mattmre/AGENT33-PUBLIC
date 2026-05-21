"""Pack registry: discover, install, uninstall, enable/disable, search.

The PackRegistry manages installed skill packs and their lifecycle.
It sits between the filesystem (where packs are stored) and the
SkillRegistry (where individual skills are registered).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import TYPE_CHECKING

import structlog

from agent33.packs.loader import (
    compute_pack_checksum,
    load_pack_manifest,
    load_pack_skills,
    validate_pack_directory,
    verify_checksums,
)
from agent33.packs.marketplace import MarketplaceResolvedPack  # noqa: TC001
from agent33.packs.models import (
    InstalledPack,
    InstallResult,
    PackStatus,
)
from agent33.packs.provenance import (
    evaluate_trust,
    verify_pack,
)
from agent33.packs.provenance_models import PackProvenance, PackTrustPolicy
from agent33.packs.version import Version, VersionConstraint

if TYPE_CHECKING:
    from agent33.packs.marketplace import PackMarketplace
    from agent33.packs.models import PackSource
    from agent33.packs.trust_manager import TrustPolicyManager
    from agent33.skills.definition import SkillDefinition
    from agent33.skills.registry import SkillRegistry

logger = structlog.get_logger()

_SESSION_PACK_SOURCE_PRECEDENCE = {"shared": 0, "explicit": 1}


class PackRegistry:
    """Manages installed skill packs and their lifecycle.

    Pack skills are registered in the existing SkillRegistry using
    qualified names: ``{pack_name}/{skill_name}`` plus an alias
    for the bare skill name (for backward compatibility).
    """

    def __init__(
        self,
        packs_dir: Path,
        skill_registry: SkillRegistry,
        *,
        marketplace: PackMarketplace | None = None,
        trust_policy: PackTrustPolicy | None = None,
        trust_policy_manager: TrustPolicyManager | None = None,
        ppack_v3_enabled: bool = False,
    ) -> None:
        self._packs_dir = packs_dir
        self._skill_registry = skill_registry
        self._installed: dict[str, InstalledPack] = {}
        self._enabled: dict[str, set[str]] = {}  # tenant_id -> set of enabled pack names
        self._session_enabled: dict[str, set[str]] = {}  # session_id -> set of pack names
        self._session_pack_sources: dict[str, dict[str, str]] = {}
        self._session_pack_sequence: dict[str, dict[str, int]] = {}
        self._session_activation_counter: dict[str, int] = {}
        self._session_tracking_lock = RLock()
        self._marketplace = marketplace
        self._trust_policy = trust_policy or PackTrustPolicy()
        self._trust_policy_manager = trust_policy_manager
        self._ppack_v3_enabled = ppack_v3_enabled

    # ------------------------------------------------------------------
    # Discovery & Loading
    # ------------------------------------------------------------------

    def discover(self, path: Path | None = None) -> int:
        """Scan a directory for PACK.yaml manifests.

        Each subdirectory containing a PACK.yaml is loaded as a pack.
        Returns the number of packs successfully loaded.
        """
        scan_dir = path or self._packs_dir
        if not scan_dir.is_dir():
            logger.warning("pack_directory_not_found", path=str(scan_dir))
            return 0

        loaded = 0
        for entry in sorted(scan_dir.iterdir()):
            if not entry.is_dir():
                continue

            manifest_path = entry / "PACK.yaml"
            if not manifest_path.is_file():
                manifest_path = entry / "pack.yaml"
                if not manifest_path.is_file():
                    continue

            try:
                pack = self.load_pack(entry)
                self._installed[pack.name] = pack
                loaded += 1
                logger.info(
                    "pack_discovered",
                    name=pack.name,
                    version=pack.version,
                    skills=len(pack.loaded_skill_names),
                )
            except Exception:
                logger.warning("pack_discovery_failed", path=str(entry), exc_info=True)

        return loaded

    def load_pack(self, pack_dir: Path) -> InstalledPack:
        """Load a single pack from a directory containing PACK.yaml.

        Validates the manifest, loads each skill definition via the existing
        loader module, and returns an InstalledPack.

        Raises:
            FileNotFoundError: If PACK.yaml is not found.
            ValueError: If validation fails or required skills cannot load.
        """
        manifest = load_pack_manifest(pack_dir)

        # Verify checksums if present
        checksums_ok, mismatches = verify_checksums(pack_dir)
        if not checksums_ok:
            raise ValueError(
                f"Checksum verification failed for pack '{manifest.name}': "
                + "; ".join(mismatches)
            )

        # Load skills
        skills, errors = load_pack_skills(pack_dir, manifest)
        if errors:
            raise ValueError(
                f"Failed to load required skills for pack '{manifest.name}': " + "; ".join(errors)
            )

        # Register skills in SkillRegistry
        loaded_names = self._register_pack_skills(manifest.name, skills)

        # Build InstalledPack

        installed = InstalledPack(
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            license=manifest.license,
            tags=manifest.tags,
            category=manifest.category,
            skills=manifest.skills,
            loaded_skill_names=loaded_names,
            pack_dependencies=manifest.dependencies.packs,
            engine_min_version=manifest.dependencies.engine.get("min_version", ""),
            compatibility=manifest.compatibility,
            prompt_addenda=manifest.prompt_addenda,
            tool_config=manifest.tool_config,
            outcome_packs=manifest.outcome_packs,
            installed_at=datetime.now(UTC),
            source="local",
            checksum=compute_pack_checksum(pack_dir),
            pack_dir=pack_dir,
            governance=manifest.governance,
            status=PackStatus.INSTALLED,
        )

        return installed

    def _register_pack_skills(self, pack_name: str, skills: list[SkillDefinition]) -> list[str]:
        """Register loaded skills in the SkillRegistry.

        Skills are registered with qualified name ``pack_name/skill_name``
        and also with bare ``skill_name`` as an alias (if not already taken).

        Returns the list of registered qualified names.
        """
        registered: list[str] = []
        for skill in skills:
            # Qualified name: pack_name/skill_name
            qualified_name = f"{pack_name}/{skill.name}"
            qualified_skill = skill.model_copy(update={"name": qualified_name})
            self._skill_registry.register(qualified_skill)
            registered.append(qualified_name)

            # Bare alias (if slot not taken by another pack or standalone skill)
            existing = self._skill_registry.get(skill.name)
            if existing is None:
                self._skill_registry.register(skill)

        return registered

    def _unregister_pack_skills(self, pack: InstalledPack) -> None:
        """Remove pack skills from the SkillRegistry."""
        for qualified_name in pack.loaded_skill_names:
            self._skill_registry.remove(qualified_name)

        # Also remove bare aliases if they belong to this pack
        for skill_entry in pack.skills:
            existing = self._skill_registry.get(skill_entry.name)
            if existing is not None and existing.base_path and pack.pack_dir:
                try:
                    existing.base_path.resolve().relative_to(pack.pack_dir.resolve())
                    self._skill_registry.remove(skill_entry.name)
                except ValueError:
                    pass  # Skill belongs to a different source

    # ------------------------------------------------------------------
    # Installation
    # ------------------------------------------------------------------

    def install(
        self,
        source: PackSource,
        *,
        provenance: PackProvenance | None = None,
        verification_key: str = "",
    ) -> InstallResult:
        """Install a pack from a local path or marketplace source.

        Steps:
        1. Validate the directory
        2. Parse and validate PACK.yaml
        3. Verify provenance (if provenance metadata is present)
        4. Verify checksums (if CHECKSUMS.sha256 present)
        5. Load skills into SkillRegistry
        6. Register in installed packs

        Args:
            source: Pack source descriptor.
            provenance: Optional provenance metadata for the pack.
            verification_key: Key used to verify the provenance signature.
        """
        try:
            (
                pack_path,
                install_source,
                source_reference,
                effective_provenance,
            ) = self._resolve_source(source, provenance=provenance)
        except ValueError as exc:
            return InstallResult(
                success=False,
                pack_name=source.name or "unknown",
                errors=[str(exc)],
            )

        # Validate structure
        validation_errors = validate_pack_directory(pack_path)
        if validation_errors:
            return InstallResult(
                success=False,
                pack_name=source.name or "unknown",
                errors=validation_errors,
            )

        # --- Provenance / trust check ---
        trust_decision = evaluate_trust(effective_provenance, self.trust_policy)
        if not trust_decision.allowed:
            return InstallResult(
                success=False,
                pack_name=source.name or "unknown",
                errors=[f"Trust policy violation: {trust_decision.reason}"],
            )

        # If provenance is present and a verification key is provided, verify the signature
        if effective_provenance is not None and verification_key:
            manifest = load_pack_manifest(pack_path)
            if not verify_pack(manifest, effective_provenance, verification_key):
                return InstallResult(
                    success=False,
                    pack_name=manifest.name,
                    errors=["Provenance signature verification failed"],
                )

        try:
            pack = self.load_pack(pack_path)
        except (FileNotFoundError, ValueError) as exc:
            return InstallResult(
                success=False,
                pack_name=source.name or "unknown",
                errors=[str(exc)],
            )

        # Check if already installed
        if pack.name in self._installed:
            existing = self._installed[pack.name]
            return InstallResult(
                success=False,
                pack_name=pack.name,
                version=existing.version,
                errors=[
                    f"Pack '{pack.name}' is already installed at version {existing.version}. "
                    f"Use upgrade to change versions."
                ],
            )

        # Check declared pack dependencies are met
        dep_errors = self._check_dependencies_met(pack)
        if dep_errors:
            # Unregister skills that were loaded during load_pack
            self._unregister_pack_skills(pack)
            return InstallResult(
                success=False,
                pack_name=pack.name,
                version=pack.version,
                errors=dep_errors,
            )

        self._installed[pack.name] = pack.model_copy(
            update={
                "source": install_source,
                "source_reference": source_reference,
                "provenance": effective_provenance,
            }
        )

        return InstallResult(
            success=True,
            pack_name=pack.name,
            version=pack.version,
            skills_loaded=len(pack.loaded_skill_names),
        )

    def uninstall(self, name: str) -> bool:
        """Uninstall a pack.

        Checks that no other installed pack depends on this one before
        removing. Returns True if successfully uninstalled.

        Raises:
            ValueError: If pack is not installed or has dependents.
        """
        pack = self._installed.get(name)
        if pack is None:
            raise ValueError(f"Pack '{name}' is not installed")

        # Check for dependents
        dependents = self._find_dependents(name)
        if dependents:
            raise ValueError(f"Cannot uninstall '{name}': required by {', '.join(dependents)}")

        # Remove skills from SkillRegistry
        self._unregister_pack_skills(pack)

        # Remove from installed dict
        del self._installed[name]

        # Remove from all tenant enablement sets
        for tenant_set in self._enabled.values():
            tenant_set.discard(name)

        # Remove from all session enablement sets
        for session_set in self._session_enabled.values():
            session_set.discard(name)

        logger.info("pack_uninstalled", name=name, version=pack.version)
        return True

    def _find_dependents(self, name: str) -> list[str]:
        """Find installed packs that depend on the named pack."""
        dependents: list[str] = []
        for pack_name, pack in self._installed.items():
            if pack_name == name:
                continue
            for dep in pack.pack_dependencies:
                if dep.name == name:
                    dependents.append(pack_name)
                    break
        return dependents

    def find_dependents(self, name: str) -> list[InstalledPack]:
        """Return installed packs that declare a dependency on the named pack."""
        return [self._installed[pack_name] for pack_name in self._find_dependents(name)]

    def _check_dependencies_met(self, pack: InstalledPack) -> list[str]:
        """Check that all declared pack dependencies are installed and version-compatible.

        Returns a list of error messages (empty means all satisfied).
        """
        errors: list[str] = []
        for dep in pack.pack_dependencies:
            installed_dep = self._installed.get(dep.name)
            if installed_dep is None:
                errors.append(
                    f"Missing dependency: pack '{pack.name}' requires '{dep.name}' "
                    f"({dep.version_constraint}) but it is not installed"
                )
                continue
            try:
                constraint = VersionConstraint.parse(dep.version_constraint)
                installed_version = Version.parse(installed_dep.version)
                if not constraint.satisfies(installed_version):
                    errors.append(
                        f"Incompatible dependency: pack '{pack.name}' requires "
                        f"'{dep.name}' {dep.version_constraint} but installed "
                        f"version is {installed_dep.version}"
                    )
            except ValueError as exc:
                errors.append(
                    f"Invalid version constraint for dependency '{dep.name}' "
                    f"in pack '{pack.name}': {exc}"
                )
        return errors

    def _check_dependents_compatible(self, name: str, new_version: str) -> list[str]:
        """Check that upgrading a pack won't break any dependent packs.

        Finds all installed packs that declare a dependency on *name* and
        verifies their version constraints are still satisfied by *new_version*.

        Returns a list of error messages (empty means upgrade is safe).
        """
        errors: list[str] = []
        try:
            new_ver = Version.parse(new_version)
        except ValueError as exc:
            return [f"Invalid new version '{new_version}': {exc}"]

        for pack_name, pack in self._installed.items():
            if pack_name == name:
                continue
            for dep in pack.pack_dependencies:
                if dep.name != name:
                    continue
                try:
                    constraint = VersionConstraint.parse(dep.version_constraint)
                    if not constraint.satisfies(new_ver):
                        errors.append(
                            f"Upgrade would break dependent: pack '{pack_name}' requires "
                            f"'{name}' {dep.version_constraint} but new version is "
                            f"{new_version}"
                        )
                except ValueError as exc:
                    errors.append(
                        f"Invalid version constraint in dependent '{pack_name}' "
                        f"for '{name}': {exc}"
                    )
        return errors

    def check_dependents_compatible(self, name: str, new_version: str) -> list[str]:
        """Return compatibility errors for dependents if the pack changed version."""
        return self._check_dependents_compatible(name, new_version)

    # ------------------------------------------------------------------
    # Enable/Disable (tenant-scoped)
    # ------------------------------------------------------------------

    def enable(self, name: str, tenant_id: str) -> bool:
        """Enable a pack for a specific tenant.

        Returns True if the pack was enabled (or was already enabled).
        Raises ValueError if the pack is not installed.
        """
        if name not in self._installed:
            raise ValueError(f"Pack '{name}' is not installed")

        if tenant_id not in self._enabled:
            self._enabled[tenant_id] = set()

        self._enabled[tenant_id].add(name)
        logger.info("pack_enabled", name=name, tenant_id=tenant_id)
        return True

    def disable(self, name: str, tenant_id: str) -> bool:
        """Disable a pack for a specific tenant.

        Returns True if the pack was disabled (or was already disabled).
        Raises ValueError if the pack is not installed.
        """
        if name not in self._installed:
            raise ValueError(f"Pack '{name}' is not installed")

        if tenant_id in self._enabled:
            self._enabled[tenant_id].discard(name)

        logger.info("pack_disabled", name=name, tenant_id=tenant_id)
        return True

    def is_enabled(self, name: str, tenant_id: str) -> bool:
        """Check if a pack is enabled for a tenant."""
        return name in self._enabled.get(tenant_id, set())

    def list_enabled(self, tenant_id: str) -> list[InstalledPack]:
        """List all packs enabled for a tenant."""
        enabled_names = self._enabled.get(tenant_id, set())
        return [self._installed[name] for name in sorted(enabled_names) if name in self._installed]

    def enabled_tenants(self, name: str) -> list[str]:
        """List tenants that currently have the pack enabled."""
        return sorted(tenant_id for tenant_id, names in self._enabled.items() if name in names)

    def get_enablement_matrix(self) -> dict[str, dict[str, bool]]:
        """Return a full pack -> tenant -> enabled matrix."""
        packs = sorted(self._installed)
        tenants = sorted(self._enabled)
        return {
            pack_name: {
                tenant_id: pack_name in self._enabled.get(tenant_id, set())
                for tenant_id in tenants
            }
            for pack_name in packs
        }

    def apply_enablement_matrix(self, matrix: dict[str, dict[str, bool]]) -> None:
        """Apply bulk pack enablement updates."""
        for pack_name, tenant_map in matrix.items():
            if pack_name not in self._installed:
                raise ValueError(f"Pack '{pack_name}' is not installed")
            for tenant_id, enabled in tenant_map.items():
                if enabled:
                    self.enable(pack_name, tenant_id)
                else:
                    self.disable(pack_name, tenant_id)

    # ------------------------------------------------------------------
    # Session-Scoped Enable/Disable (P-PACK v1)
    # ------------------------------------------------------------------

    def _record_session_pack_activation(
        self,
        pack_name: str,
        session_id: str,
        source: str,
    ) -> None:
        sources = self._session_pack_sources.setdefault(session_id, {})
        sequence = self._session_pack_sequence.setdefault(session_id, {})
        existing_source = sources.get(pack_name)

        if existing_source == "explicit" and source == "shared":
            return
        if existing_source == source:
            return

        next_sequence = self._session_activation_counter.get(session_id, 0) + 1
        self._session_activation_counter[session_id] = next_sequence
        sources[pack_name] = source
        sequence[pack_name] = next_sequence

    def clear_session_state(self, session_id: str) -> None:
        """Remove all session-scoped pack tracking for a session."""
        with self._session_tracking_lock:
            self._session_enabled.pop(session_id, None)
            self._session_pack_sources.pop(session_id, None)
            self._session_pack_sequence.pop(session_id, None)
            self._session_activation_counter.pop(session_id, None)

    def _session_pack_order(
        self,
        session_id: str,
        *,
        ppack_variant: str | None = None,
    ) -> list[str]:
        with self._session_tracking_lock:
            names = set(self._session_enabled.get(session_id, set()))
            sources = dict(self._session_pack_sources.get(session_id, {}))
            sequence = dict(self._session_pack_sequence.get(session_id, {}))
        if not names:
            return []

        installed_names = [name for name in names if name in self._installed]
        if not self._ppack_v3_enabled or str(ppack_variant).lower() != "treatment":
            return sorted(installed_names)

        return sorted(
            installed_names,
            key=lambda name: (
                _SESSION_PACK_SOURCE_PRECEDENCE.get(sources.get(name, "explicit"), 1),
                sequence.get(name, 0),
                name,
            ),
        )

    def enable_for_session(
        self,
        pack_name: str,
        session_id: str,
        *,
        source: str = "explicit",
    ) -> None:
        """Enable a pack for a specific session only (not global/tenant).

        Raises:
            ValueError: If the pack is not installed.
        """
        if pack_name not in self._installed:
            raise ValueError(f"Pack '{pack_name}' is not installed")
        if source not in _SESSION_PACK_SOURCE_PRECEDENCE:
            raise ValueError(f"Unsupported session pack source '{source}'")

        with self._session_tracking_lock:
            if session_id not in self._session_enabled:
                self._session_enabled[session_id] = set()
            self._session_enabled[session_id].add(pack_name)
            self._record_session_pack_activation(pack_name, session_id, source)
        logger.info(
            "pack_enabled_for_session",
            name=pack_name,
            session_id=session_id,
            source=source,
        )

    def disable_for_session(self, pack_name: str, session_id: str) -> None:
        """Disable a session-scoped pack.

        Raises:
            ValueError: If the pack is not installed.
        """
        if pack_name not in self._installed:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        with self._session_tracking_lock:
            if session_id in self._session_enabled:
                self._session_enabled[session_id].discard(pack_name)
                if not self._session_enabled[session_id]:
                    self.clear_session_state(session_id)
                else:
                    self._session_pack_sources.get(session_id, {}).pop(pack_name, None)
                    self._session_pack_sequence.get(session_id, {}).pop(pack_name, None)
        logger.info("pack_disabled_for_session", name=pack_name, session_id=session_id)

    def get_session_packs(
        self,
        session_id: str,
        *,
        ppack_variant: str | None = None,
    ) -> list[InstalledPack]:
        """Get packs enabled for a specific session.

        Control sessions retain the original name-sorted P-PACK v1 behavior.
        Treatment sessions under ``ppack_v3_enabled`` resolve packs by
        application precedence: workflow-shared packs first, then explicit
        session enables, preserving activation order within each group.
        """
        names = self._session_pack_order(session_id, ppack_variant=ppack_variant)
        return [self._installed[name] for name in names]

    def get_session_prompt_addenda(
        self,
        session_id: str,
        *,
        ppack_variant: str | None = None,
    ) -> list[str]:
        """Collect all prompt addenda from packs enabled for a session.

        Returns a flat list of prompt addenda strings from all active
        session-scoped packs, using the current session-pack resolution order.
        """
        addenda: list[str] = []
        for pack in self.get_session_packs(session_id, ppack_variant=ppack_variant):
            addenda.extend(pack.prompt_addenda)
        return addenda

    def get_session_tool_config(
        self,
        session_id: str,
        *,
        ppack_variant: str | None = None,
    ) -> dict[str, dict[str, object]]:
        """Merge tool_config from all session-scoped packs.

        Later packs in the resolved session-pack order override earlier ones
        for the same tool key. Returns a merged dict of tool_name -> config.
        """
        merged: dict[str, dict[str, object]] = {}
        for pack in self.get_session_packs(session_id, ppack_variant=ppack_variant):
            for tool_name, config in pack.tool_config.items():
                if tool_name not in merged:
                    merged[tool_name] = {}
                merged[tool_name].update(config)
        return merged

    # ------------------------------------------------------------------
    # Dry-Run Simulation (P-PACK v1)
    # ------------------------------------------------------------------

    def dry_run(
        self,
        pack_name: str,
        agent_name: str = "",
        session_id: str = "",
    ) -> dict[str, object]:
        """Return what would change if this pack were applied.

        Does NOT modify any state.

        Raises:
            ValueError: If the pack is not installed.
        """
        if pack_name not in self._installed:
            raise ValueError(f"Pack '{pack_name}' is not installed")

        pack = self._installed[pack_name]
        return {
            "pack_name": pack_name,
            "version": pack.version,
            "prompt_addenda_count": len(pack.prompt_addenda),
            "prompt_addenda_preview": [p[:100] for p in pack.prompt_addenda],
            "tool_config_tools": list(pack.tool_config.keys()),
            "tool_config": pack.tool_config,
            "skills_to_load": [s.name for s in pack.skills],
            "would_apply_to_agent": agent_name or "(all agents)",
            "would_apply_to_session": session_id or "(all sessions in tenant)",
            "injection_scan": "clean",  # validated at load time by manifest validator
        }

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get(self, name: str) -> InstalledPack | None:
        """Look up an installed pack by name."""
        return self._installed.get(name)

    def list_installed(self) -> list[InstalledPack]:
        """List all installed packs sorted by name."""
        return [self._installed[k] for k in sorted(self._installed)]

    @property
    def has_marketplace(self) -> bool:
        """Return whether marketplace-backed installs are configured."""
        return self._marketplace is not None

    @property
    def count(self) -> int:
        """Number of installed packs."""
        return len(self._installed)

    def search(self, query: str) -> list[InstalledPack]:
        """Search installed packs by name, description, or tags."""
        query_lower = query.lower()
        results: list[InstalledPack] = []
        for pack in self._installed.values():
            if (
                query_lower in pack.name.lower()
                or query_lower in pack.description.lower()
                or any(query_lower in t.lower() for t in pack.tags)
            ):
                results.append(pack)
        return sorted(results, key=lambda p: p.name)

    async def check_for_updates(
        self,
        hub: object,
    ) -> list[tuple[InstalledPack, object]]:
        """Return installed packs with newer versions available on the hub.

        Each element is ``(installed_pack, hub_entry)`` where the hub entry
        has a higher semver than the installed version.

        The *hub* parameter is typed as ``object`` to avoid a circular import;
        at runtime it must be a :class:`~agent33.packs.hub.PackHub` instance.
        The hub entry objects are :class:`~agent33.packs.hub.PackHubEntry`
        instances at runtime.
        """
        from agent33.packs.hub import PackHub
        from agent33.packs.version import Version

        assert isinstance(hub, PackHub)

        updates: list[tuple[InstalledPack, object]] = []

        for pack in self._installed.values():
            entry = await hub.get(pack.name)
            if entry is None:
                continue

            try:
                installed_ver = Version.parse(pack.version)
                hub_ver = Version.parse(entry.version)
            except ValueError:
                continue

            if hub_ver > installed_ver:
                updates.append((pack, entry))

        return updates

    @property
    def trust_policy(self) -> PackTrustPolicy:
        """Return the active trust policy."""
        if self._trust_policy_manager is not None:
            return self._trust_policy_manager.get_policy()
        return self._trust_policy.model_copy(deep=True)

    def set_trust_policy(self, policy: PackTrustPolicy) -> None:
        """Update the active trust policy."""
        self._trust_policy = policy

    # ------------------------------------------------------------------
    # Upgrade / Downgrade
    # ------------------------------------------------------------------

    def upgrade(
        self, name: str, new_pack_dir: Path, target_version: str | None = None
    ) -> InstallResult:
        """Upgrade a pack to a newer version from a new directory.

        This unloads old skills, loads the new pack, and re-registers skills.
        Tenant enablement is preserved.
        """
        old_pack = self._installed.get(name)
        if old_pack is None:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[f"Pack '{name}' is not installed"],
            )

        try:
            new_pack = self.load_pack(new_pack_dir)
        except (FileNotFoundError, ValueError) as exc:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[str(exc)],
            )

        if new_pack.name != name:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[f"Pack name mismatch: expected '{name}' but found '{new_pack.name}'"],
            )

        if target_version and new_pack.version != target_version:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[
                    f"Version mismatch: expected '{target_version}' "
                    f"but pack is '{new_pack.version}'"
                ],
            )

        # Check that dependents are still compatible with the new version
        compat_errors = self._check_dependents_compatible(name, new_pack.version)
        if compat_errors:
            # Unregister skills that were loaded during load_pack for the new version
            self._unregister_pack_skills(new_pack)
            return InstallResult(
                success=False,
                pack_name=name,
                version=new_pack.version,
                errors=compat_errors,
            )

        # Unload old skills
        self._unregister_pack_skills(old_pack)

        # Install new version
        self._installed[name] = new_pack.model_copy(
            update={
                "source": old_pack.source,
                "source_reference": old_pack.source_reference,
                "provenance": old_pack.provenance,
            }
        )

        logger.info(
            "pack_upgraded",
            name=name,
            old_version=old_pack.version,
            new_version=new_pack.version,
        )

        return InstallResult(
            success=True,
            pack_name=name,
            version=new_pack.version,
            skills_loaded=len(new_pack.loaded_skill_names),
        )

    def downgrade(self, name: str, old_pack_dir: Path) -> InstallResult:
        """Downgrade a pack to an older version from a directory.

        Functionally identical to upgrade but semantically signals intent.
        """
        return self.upgrade(name, old_pack_dir)

    def upgrade_from_source(
        self,
        name: str,
        source: PackSource,
        *,
        provenance: PackProvenance | None = None,
        verification_key: str = "",
    ) -> InstallResult:
        """Upgrade an installed pack from a local or marketplace source."""
        current = self._installed.get(name)
        if current is None:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[f"Pack '{name}' is not installed"],
            )
        normalized_source = source.model_copy(update={"name": source.name or current.name})
        try:
            (
                pack_path,
                install_source,
                source_reference,
                effective_provenance,
            ) = self._resolve_source(normalized_source, provenance=provenance)
        except ValueError as exc:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[str(exc)],
            )

        trust_decision = evaluate_trust(effective_provenance, self.trust_policy)
        if not trust_decision.allowed:
            return InstallResult(
                success=False,
                pack_name=name,
                errors=[f"Trust policy violation: {trust_decision.reason}"],
            )

        if effective_provenance is not None and verification_key:
            manifest = load_pack_manifest(pack_path)
            if not verify_pack(manifest, effective_provenance, verification_key):
                return InstallResult(
                    success=False,
                    pack_name=manifest.name,
                    errors=["Provenance signature verification failed"],
                )

        result = self.upgrade(name, pack_path, normalized_source.version or None)
        if result.success:
            upgraded = self._installed[name]
            self._installed[name] = upgraded.model_copy(
                update={
                    "source": install_source,
                    "source_reference": source_reference,
                    "provenance": effective_provenance,
                }
            )
        return result

    def _resolve_source(
        self,
        source: PackSource,
        *,
        provenance: PackProvenance | None = None,
    ) -> tuple[Path, str, str, PackProvenance | None]:
        pack_path: Path
        install_source = source.source_type
        source_reference = source.path or source.name
        effective_provenance = provenance
        if source.source_type == "local":
            pack_path = Path(source.path)
            if not pack_path.is_dir():
                raise ValueError(f"Pack directory not found: {source.path}")
            return pack_path, install_source, source_reference, effective_provenance

        if source.source_type == "marketplace":
            if self._marketplace is None:
                raise ValueError("Marketplace registry is not configured")
            if not source.name:
                raise ValueError("Marketplace installs require a pack name")
            resolved = self._marketplace.resolve(source.name, source.version)
            if resolved is None:
                version_suffix = f" version '{source.version}'" if source.version else ""
                raise ValueError(f"Marketplace pack '{source.name}'{version_suffix} was not found")
            (
                pack_path,
                install_source,
                source_reference,
                effective_provenance,
            ) = self._resolved_pack_metadata(
                resolved,
                fallback_provenance=provenance,
            )
            return pack_path, install_source, source_reference, effective_provenance

        raise ValueError(f"Unsupported source type: {source.source_type}")

    @staticmethod
    def _resolved_pack_metadata(
        resolved: MarketplaceResolvedPack,
        *,
        fallback_provenance: PackProvenance | None = None,
    ) -> tuple[Path, str, str, PackProvenance | None]:
        return (
            resolved.pack_dir,
            "marketplace",
            resolved.source_name,
            resolved.provenance or fallback_provenance,
        )
