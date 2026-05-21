import type { CockpitOpsSafetyRecord } from "../data/cockpitOpsSafety";
import type { PermissionModeId } from "../data/permissionModes";
import { getPermissionMode } from "../data/permissionModes";
import { countSafetyGateRecords, getSafetyStatusLabel } from "../data/safetyGatePresentation";

interface SafetyGateIndicatorProps {
  readonly permissionModeId: PermissionModeId;
  readonly opsSafetyRecords: ReadonlyArray<CockpitOpsSafetyRecord>;
  readonly isCompact?: boolean;
}

export function SafetyGateIndicator({
  permissionModeId,
  opsSafetyRecords,
  isCompact = false
}: SafetyGateIndicatorProps): JSX.Element {
  const permissionMode = getPermissionMode(permissionModeId);
  const counts = countSafetyGateRecords(opsSafetyRecords);
  const visibleCounts =
    counts.blocked + counts.needsReview + counts.watching > 0
      ? [
          { status: "blocked" as const, count: counts.blocked },
          { status: "needs-review" as const, count: counts.needsReview },
          { status: "watching" as const, count: counts.watching }
        ].filter((item) => item.count > 0)
      : [{ status: "clear" as const, count: counts.clear }];

  return (
    <section
      className={`safety-gate-indicator safety-gate-indicator-${permissionMode.tone}${
        isCompact ? " safety-gate-indicator-compact" : ""
      }`}
      aria-label="Safety gate summary"
    >
      <div className="safety-gate-indicator-copy">
        <span className="eyebrow">Permission gate</span>
        <strong>{permissionMode.label}</strong>
        {!isCompact ? <p>{permissionMode.reviewGate}</p> : null}
      </div>
      <div className="safety-gate-badges" aria-label="Safety gate counts">
        {visibleCounts.map((item) => (
          <span
            key={item.status}
            className={`safety-gate-badge safety-gate-badge-${item.status}`}
            aria-label={`${getSafetyStatusLabel(item.status)}: ${item.count}`}
          >
            {getSafetyStatusLabel(item.status)} {item.count}
          </span>
        ))}
      </div>
    </section>
  );
}
