"""CI entry point for runtime import-boundary checks."""

from __future__ import annotations

from pathlib import Path

from agent33.testing.import_boundaries import (
    RUNTIME_BOUNDARY_RULES,
    collect_allowlisted_importers,
    evaluate_runtime_boundaries,
    format_violations,
)


def main() -> int:
    package_root = Path(__file__).resolve().parents[1] / "src" / "agent33"
    violations = evaluate_runtime_boundaries(package_root)
    if violations:
        print(format_violations(violations))
        return 1

    allowlisted = ", ".join(sorted(collect_allowlisted_importers())) or "none"
    print(
        "Runtime import-boundary check passed "
        f"({len(RUNTIME_BOUNDARY_RULES)} rules, allowlisted importers: {allowlisted})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
