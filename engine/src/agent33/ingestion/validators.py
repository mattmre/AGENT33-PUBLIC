"""Schema and semantic validation helpers for candidate asset intake.

Validates raw ``dict`` payloads before they reach ``IngestionService.ingest()``.
No external HTTP calls are performed — all checks are purely local.

CLEAN-ROOM RESTRICTION
=======================
No code in this file may originate from the EvoMap/Evolver project.
"""

from __future__ import annotations

from agent33.ingestion.models import ConfidenceLevel

_KNOWN_URI_SCHEMES = ("http://", "https://", "file://", "skill://", "agent://")


class CandidateValidator:
    """Stateless validator for candidate asset payloads.

    All methods are safe to call concurrently; no shared mutable state is used.
    """

    def validate_schema(self, asset_data: dict[str, object]) -> list[str]:
        """Validate a raw asset payload dict and return a list of error strings.

        An empty return value means the payload is valid.  Required fields:
        - ``name``: non-empty string
        - ``source_uri``: non-empty string
        - ``confidence``: a valid :class:`ConfidenceLevel` value

        Optional checks (only applied when the field is present):
        - ``tenant_id`` must be present
        - ``asset_type`` must be non-empty if provided
        """
        errors: list[str] = []

        name = asset_data.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append("'name' is required and must be a non-empty string.")

        source_uri = asset_data.get("source_uri")
        if not isinstance(source_uri, str) or not source_uri.strip():
            errors.append("'source_uri' is required and must be a non-empty string.")

        confidence_raw = asset_data.get("confidence")
        if confidence_raw is None:
            errors.append("'confidence' is required.")
        elif self.validate_confidence(str(confidence_raw)) is None:
            valid = ", ".join(f"'{v.value}'" for v in ConfidenceLevel)
            errors.append(f"'confidence' must be one of {valid}; got {confidence_raw!r}.")

        if "tenant_id" not in asset_data:
            errors.append("'tenant_id' is required.")

        asset_type = asset_data.get("asset_type")
        if asset_type is not None and (not isinstance(asset_type, str) or not asset_type.strip()):
            errors.append("'asset_type' must be a non-empty string when provided.")

        return errors

    def validate_source_uri(self, uri: str) -> bool:
        """Return ``True`` if *uri* is non-empty and starts with a known scheme.

        Known schemes: ``http``, ``https``, ``file``, ``skill``, ``agent``.
        No external network requests are performed.
        """
        if not uri or not uri.strip():
            return False
        return any(uri.startswith(scheme) for scheme in _KNOWN_URI_SCHEMES)

    def validate_confidence(self, value: str) -> ConfidenceLevel | None:
        """Return the matching :class:`ConfidenceLevel` for *value*, or ``None``.

        Comparison is case-insensitive so that ``"HIGH"``, ``"high"``, and
        ``"High"`` all resolve correctly.
        """
        normalised = value.lower()
        for level in ConfidenceLevel:
            if level.value == normalised:
                return level
        return None
