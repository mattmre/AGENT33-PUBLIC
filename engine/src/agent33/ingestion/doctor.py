"""Detect-only diagnostics module for ingested candidate assets.

``SkillsDoctor`` inspects assets and reports health issues without
modifying any state.  It never triggers lifecycle transitions or
any other mutations.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

from agent33.ingestion.models import CandidateStatus, ConfidenceLevel
from agent33.ingestion.validators import CandidateValidator

if TYPE_CHECKING:
    from agent33.ingestion.service import IngestionService

CheckResult = Literal["pass", "warn", "fail", "critical"]
OverallStatus = Literal["healthy", "warning", "critical"]

_STALE_CANDIDATE_DAYS = 7
_validator = CandidateValidator()


def _check_result(name: str, result: CheckResult, detail: str) -> dict[str, str]:
    return {"name": name, "result": result, "detail": detail}


def _overall_from_checks(checks: list[dict[str, str]]) -> OverallStatus:
    results = {c["result"] for c in checks}
    if "fail" in results or "critical" in results:
        return "critical"
    if "warn" in results:
        return "warning"
    return "healthy"


class SkillsDoctor:
    """Read-only diagnostics engine for candidate assets.

    All methods are purely observational — no asset state is mutated.
    """

    def __init__(self, service: IngestionService) -> None:
        self._service = service

    def diagnose_asset(self, asset_id: str, tenant_id: str) -> dict[str, Any]:
        """Run all health checks on a single asset.

        Returns a diagnostic report dict with keys ``asset_id``,
        ``tenant_id``, ``status`` (``"healthy"`` | ``"warning"`` |
        ``"critical"``), and ``checks`` (ordered list of check results).

        The ``asset_exists`` check runs first; if it fails, all remaining
        checks are skipped and the overall status is ``"critical"``.
        """
        checks: list[dict[str, str]] = []

        asset = self._service.get(asset_id)
        if asset is None:
            checks.append(
                _check_result(
                    "asset_exists",
                    "fail",
                    f"Asset {asset_id!r} not found.",
                )
            )
            return {
                "asset_id": asset_id,
                "tenant_id": tenant_id,
                "status": "critical",
                "checks": checks,
            }

        checks.append(_check_result("asset_exists", "pass", "Asset found."))

        asset_dict = asset.model_dump(mode="json")
        schema_errors = _validator.validate_schema(asset_dict)
        if schema_errors:
            checks.append(
                _check_result(
                    "schema_valid",
                    "fail",
                    "; ".join(schema_errors),
                )
            )
        else:
            checks.append(_check_result("schema_valid", "pass", "Schema is valid."))

        if asset.source_uri is not None:
            uri_ok = _validator.validate_source_uri(asset.source_uri)
            if not uri_ok:
                checks.append(
                    _check_result(
                        "source_uri_valid",
                        "warn",
                        f"source_uri {asset.source_uri!r} is not a recognised scheme.",
                    )
                )
            else:
                checks.append(_check_result("source_uri_valid", "pass", "source_uri is valid."))
        else:
            checks.append(_check_result("source_uri_valid", "warn", "source_uri is absent."))

        if asset.confidence == ConfidenceLevel.LOW:
            checks.append(
                _check_result(
                    "confidence_level",
                    "warn",
                    "Asset has LOW confidence; manual review is recommended.",
                )
            )
        else:
            checks.append(
                _check_result(
                    "confidence_level",
                    "pass",
                    f"Confidence is {asset.confidence.value}.",
                )
            )

        if asset.status == CandidateStatus.CANDIDATE:
            created_at = asset.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=UTC)
            age_days = (datetime.now(UTC) - created_at).days
            if age_days > _STALE_CANDIDATE_DAYS:
                checks.append(
                    _check_result(
                        "stale_candidate",
                        "warn",
                        f"Asset has been in CANDIDATE status for {age_days} days "
                        f"(threshold: {_STALE_CANDIDATE_DAYS}).",
                    )
                )
            else:
                checks.append(
                    _check_result("stale_candidate", "pass", "Candidate age is within threshold.")
                )
        else:
            checks.append(
                _check_result(
                    "stale_candidate",
                    "pass",
                    f"Asset is in {asset.status.value} status; staleness check not applicable.",
                )
            )

        if asset.metadata.get("review_required") is True:
            checks.append(
                _check_result(
                    "review_flag",
                    "warn",
                    "Asset metadata has review_required=True.",
                )
            )
        else:
            checks.append(_check_result("review_flag", "pass", "No review flag set."))

        if asset.metadata.get("quarantine") is True:
            checks.append(
                _check_result(
                    "quarantine_flag",
                    "critical",
                    "Asset metadata has quarantine=True.",
                )
            )
        else:
            checks.append(_check_result("quarantine_flag", "pass", "No quarantine flag set."))

        return {
            "asset_id": asset_id,
            "tenant_id": tenant_id,
            "status": _overall_from_checks(checks),
            "checks": checks,
        }

    def diagnose_tenant(self, tenant_id: str) -> dict[str, Any]:
        """Run ``diagnose_asset`` for every asset belonging to *tenant_id*.

        Returns aggregate counts and the full per-asset report list.
        """
        assets = self._service.list_by_tenant(tenant_id)
        reports = [self.diagnose_asset(a.id, tenant_id) for a in assets]

        healthy = sum(1 for r in reports if r["status"] == "healthy")
        warning = sum(1 for r in reports if r["status"] == "warning")
        critical = sum(1 for r in reports if r["status"] == "critical")

        return {
            "tenant_id": tenant_id,
            "total": len(reports),
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
            "assets": reports,
        }

    def summary_report(self, tenant_id: str) -> dict[str, Any]:
        """Return a summary report that omits healthy assets from the list.

        Counts include all assets; only warning/critical assets appear in
        the ``assets`` list.  This keeps the payload small for operators
        who only care about problem assets.
        """
        full = self.diagnose_tenant(tenant_id)
        non_healthy = [r for r in full["assets"] if r["status"] != "healthy"]
        return {
            "tenant_id": full["tenant_id"],
            "total": full["total"],
            "healthy": full["healthy"],
            "warning": full["warning"],
            "critical": full["critical"],
            "assets": non_healthy,
        }
