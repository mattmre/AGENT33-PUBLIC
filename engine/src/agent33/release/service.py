"""Release orchestration service — CRUD, lifecycle, checklist, sync, rollback."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import ValidationError

from agent33.component_security.models import (
    FindingsSummary,
    RunStatus,
    SecurityGatePolicy,
    SecurityGateResult,
)
from agent33.release.checklist import ChecklistEvaluator, build_checklist
from agent33.release.models import (
    CheckStatus,
    Release,
    ReleaseStatus,
    ReleaseType,
    RollbackType,
    SyncRule,
)
from agent33.release.rollback import RollbackManager
from agent33.release.security_gate import evaluate_security_gate
from agent33.release.sync import SyncEngine

if TYPE_CHECKING:
    from agent33.services.orchestration_state import OrchestrationStateStore
    from agent33.services.security_scan import SecurityScanService

logger = logging.getLogger(__name__)

# Valid state transitions for release lifecycle
_VALID_TRANSITIONS: dict[ReleaseStatus, frozenset[ReleaseStatus]] = {
    ReleaseStatus.PLANNED: frozenset({ReleaseStatus.FROZEN}),
    ReleaseStatus.FROZEN: frozenset(
        {
            ReleaseStatus.RC,
            ReleaseStatus.PLANNED,
        }
    ),
    ReleaseStatus.RC: frozenset(
        {
            ReleaseStatus.VALIDATING,
            ReleaseStatus.FAILED,
        }
    ),
    ReleaseStatus.VALIDATING: frozenset(
        {
            ReleaseStatus.RELEASED,
            ReleaseStatus.FAILED,
        }
    ),
    ReleaseStatus.RELEASED: frozenset({ReleaseStatus.ROLLED_BACK}),
    ReleaseStatus.FAILED: frozenset({ReleaseStatus.PLANNED}),
    ReleaseStatus.ROLLED_BACK: frozenset({ReleaseStatus.PLANNED}),
}


class ReleaseNotFoundError(Exception):
    """Raised when a release is not found."""


class InvalidReleaseTransitionError(Exception):
    """Raised when a release state transition is invalid."""

    def __init__(self, from_status: ReleaseStatus, to_status: ReleaseStatus) -> None:
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"Invalid transition: {from_status.value} -> {to_status.value}")


class ReleaseService:
    """Full release lifecycle orchestration."""

    def __init__(
        self,
        state_store: OrchestrationStateStore | None = None,
        security_scan_service: SecurityScanService | None = None,
        security_gate_policy: SecurityGatePolicy | None = None,
    ) -> None:
        self._state_store = state_store
        self._security_scan_service = security_scan_service
        self._security_gate_policy = security_gate_policy or SecurityGatePolicy()
        self._releases: dict[str, Release] = {}
        self._evaluator = ChecklistEvaluator()
        self._sync = SyncEngine(on_change=self._persist_state)
        self._rollback = RollbackManager(on_change=self._persist_state)
        if state_store is None:
            logger.warning(
                "release_service_no_persistence: state_store is None, all release records "
                "are in-memory only and will be lost on restart. Set "
                "ORCHESTRATION_STATE_STORE_PATH to enable durable persistence."
            )
        self._load_state()

    def _persist_state(self) -> None:
        if self._state_store is None:
            return
        self._state_store.write_namespace(
            "release",
            {
                "releases": {
                    release_id: release.model_dump(mode="json")
                    for release_id, release in self._releases.items()
                },
                "sync_rules": self._sync.snapshot_state().get("rules", {}),
                "sync_executions": self._sync.snapshot_state().get("executions", {}),
                "rollback_records": self._rollback.snapshot_state().get("records", {}),
            },
        )

    def _load_state(self) -> None:
        if self._state_store is None:
            return
        payload = self._state_store.read_namespace("release")

        releases_payload = payload.get("releases", {})
        if isinstance(releases_payload, dict):
            for release_id, release_data in releases_payload.items():
                if not isinstance(release_id, str):
                    continue
                try:
                    self._releases[release_id] = Release.model_validate(release_data)
                except ValidationError:
                    logger.warning("release_restore_failed id=%s", release_id)

        self._sync.restore_state(
            {
                "rules": payload.get("sync_rules", {}),
                "executions": payload.get("sync_executions", {}),
            }
        )
        self._rollback.restore_state({"records": payload.get("rollback_records", {})})

    @property
    def sync_engine(self) -> SyncEngine:
        return self._sync

    @property
    def rollback_manager(self) -> RollbackManager:
        return self._rollback

    # ------------------------------------------------------------------
    # Release CRUD
    # ------------------------------------------------------------------

    def create_release(
        self,
        version: str,
        release_type: ReleaseType = ReleaseType.MINOR,
        description: str = "",
    ) -> Release:
        """Create a new release in PLANNED state with a populated checklist."""
        release = Release(
            version=version,
            release_type=release_type,
            description=description,
        )
        release.evidence.checklist = build_checklist(release)
        self._releases[release.release_id] = release
        logger.info(
            "release_created id=%s version=%s type=%s",
            release.release_id,
            version,
            release_type.value,
        )
        self._persist_state()
        return release

    def get_release(self, release_id: str) -> Release:
        release = self._releases.get(release_id)
        if release is None:
            raise ReleaseNotFoundError(f"Release not found: {release_id}")
        return release

    def list_releases(
        self,
        status: ReleaseStatus | None = None,
        limit: int = 50,
    ) -> list[Release]:
        results = list(self._releases.values())
        if status is not None:
            results = [r for r in results if r.status == status]
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Lifecycle transitions
    # ------------------------------------------------------------------

    def transition(self, release_id: str, to_status: ReleaseStatus) -> Release:
        release = self.get_release(release_id)
        valid = _VALID_TRANSITIONS.get(release.status, frozenset())
        if to_status not in valid:
            raise InvalidReleaseTransitionError(release.status, to_status)
        release.status = to_status
        logger.info(
            "release_transition id=%s to=%s",
            release_id,
            to_status.value,
        )
        self._persist_state()
        return release

    def freeze(self, release_id: str) -> Release:
        return self.transition(release_id, ReleaseStatus.FROZEN)

    def cut_rc(self, release_id: str, rc_version: str = "") -> Release:
        release = self.transition(release_id, ReleaseStatus.RC)
        if rc_version:
            release.rc_version = rc_version
        return release

    def start_validation(self, release_id: str) -> Release:
        """Begin VALIDATING phase and automatically evaluate the security gate.

        If a ``SecurityScanService`` is wired in, the most recent completed scan
        run for this release is fetched and ``evaluate_security_gate`` is called
        to update RL-06 in the checklist.  If no completed scan exists, a warning
        is added to the RL-06 check so operators know the gate was not evaluated.
        """
        release = self.transition(release_id, ReleaseStatus.VALIDATING)
        self._auto_evaluate_security_gate(release)
        return release

    def _auto_evaluate_security_gate(self, release: Release) -> None:
        """Look up the most recent completed scan and evaluate RL-06."""
        if self._security_scan_service is None:
            return
        tenant_id: str | None = getattr(release, "tenant_id", None) or None
        try:
            completed_runs = self._security_scan_service.list_runs(
                tenant_id=tenant_id,
                status=RunStatus.COMPLETED,
                limit=100,
            )
        except Exception:
            logger.warning(
                "release_security_gate_scan_lookup_failed release_id=%s",
                release.release_id,
                exc_info=True,
            )
            self._evaluator.update_check(
                release.evidence.checklist,
                "RL-06",
                CheckStatus.FAIL,
                "Security gate could not be evaluated: scan service lookup failed",
            )
            self._persist_state()
            return

        # Filter to runs associated with this release candidate if possible
        release_runs = [
            run
            for run in completed_runs
            if run.metadata.release_candidate_id == release.release_id
        ]
        # Fall back to most recent completed run when no release-scoped run exists
        candidate_run = (
            release_runs[0] if release_runs else (completed_runs[0] if completed_runs else None)
        )

        if candidate_run is None:
            logger.warning(
                "release_security_gate_no_scan_available release_id=%s",
                release.release_id,
            )
            self._evaluator.update_check(
                release.evidence.checklist,
                "RL-06",
                CheckStatus.FAIL,
                "Security gate not evaluated: no completed scan run found for this release",
            )
            self._persist_state()
            return

        result = evaluate_security_gate(
            run_id=candidate_run.id,
            summary=candidate_run.findings_summary,
            policy=self._security_gate_policy,
        )
        release.evidence.gate_passed = result.decision.value == "pass"
        check_status = CheckStatus.PASS if release.evidence.gate_passed else CheckStatus.FAIL
        self._evaluator.update_check(
            release.evidence.checklist,
            "RL-06",
            check_status,
            result.message,
        )
        logger.info(
            "release_security_gate_evaluated release_id=%s run_id=%s decision=%s",
            release.release_id,
            candidate_run.id,
            result.decision.value,
        )
        self._persist_state()

    def publish(self, release_id: str, released_by: str = "") -> Release:
        """Publish a release (transition to RELEASED).

        Validates the checklist first — all required checks must pass.
        """
        release = self.get_release(release_id)
        passed, failures = self._evaluator.evaluate(release.evidence.checklist)
        if not passed:
            raise InvalidReleaseTransitionError(release.status, ReleaseStatus.RELEASED)
        release = self.transition(release_id, ReleaseStatus.RELEASED)
        release.released_by = released_by

        from datetime import UTC, datetime

        release.released_at = datetime.now(UTC)
        self._persist_state()
        return release

    def mark_failed(self, release_id: str) -> Release:
        return self.transition(release_id, ReleaseStatus.FAILED)

    # ------------------------------------------------------------------
    # Checklist
    # ------------------------------------------------------------------

    def update_check(
        self,
        release_id: str,
        check_id: str,
        status: CheckStatus,
        message: str = "",
    ) -> Release:
        release = self.get_release(release_id)
        self._evaluator.update_check(release.evidence.checklist, check_id, status, message)
        self._persist_state()
        return release

    def evaluate_checklist(self, release_id: str) -> tuple[bool, list[str]]:
        """Evaluate the release checklist. Returns (passed, failures)."""
        release = self.get_release(release_id)
        return self._evaluator.evaluate(release.evidence.checklist)

    def apply_component_security_gate(
        self,
        release_id: str,
        *,
        run_id: str,
        summary: FindingsSummary,
        policy: SecurityGatePolicy | None = None,
    ) -> SecurityGateResult:
        """Evaluate and apply RL-06 status from component security findings."""
        release = self.get_release(release_id)
        gate_policy = policy or SecurityGatePolicy()
        result = evaluate_security_gate(run_id=run_id, summary=summary, policy=gate_policy)
        release.evidence.gate_passed = result.decision.value == "pass"
        check_status = CheckStatus.PASS if release.evidence.gate_passed else CheckStatus.FAIL
        self._evaluator.update_check(
            release.evidence.checklist,
            "RL-06",
            check_status,
            result.message,
        )
        self._persist_state()
        return result

    # ------------------------------------------------------------------
    # Sync (delegated to SyncEngine)
    # ------------------------------------------------------------------

    def add_sync_rule(self, rule: SyncRule) -> SyncRule:
        return self._sync.add_rule(rule)

    def list_sync_rules(self) -> list[SyncRule]:
        return self._sync.list_rules()

    # ------------------------------------------------------------------
    # Rollback (delegated to RollbackManager)
    # ------------------------------------------------------------------

    def initiate_rollback(
        self,
        release_id: str,
        reason: str,
        rollback_type: RollbackType = RollbackType.PLANNED,
        target_version: str = "",
        initiated_by: str = "",
    ) -> Release:
        """Initiate a rollback for a released version."""
        release = self.get_release(release_id)
        self._rollback.create(
            release_id=release_id,
            reason=reason,
            rollback_type=rollback_type,
            target_version=target_version,
            initiated_by=initiated_by,
        )
        if release.status == ReleaseStatus.RELEASED:
            self.transition(release_id, ReleaseStatus.ROLLED_BACK)
        self._persist_state()
        return release
