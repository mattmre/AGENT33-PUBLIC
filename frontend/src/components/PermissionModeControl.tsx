import {
  PERMISSION_MODES,
  getPermissionMode,
  isPermissionModeId,
  type PermissionModeId
} from "../data/permissionModes";
import type { OperatorMode } from "../features/advanced/AdvancedControlPlanePanel";

interface PermissionModeControlProps {
  selectedModeId: PermissionModeId;
  operatorMode: OperatorMode;
  onSelectMode: (modeId: PermissionModeId) => void;
  onOperatorModeChange: (mode: OperatorMode) => void;
}

export function PermissionModeControl({
  selectedModeId,
  operatorMode,
  onSelectMode,
  onOperatorModeChange
}: PermissionModeControlProps): JSX.Element {
  const selectedMode = getPermissionMode(selectedModeId);
  const controlPlaneLabel =
    operatorMode === "pro"
      ? "Live control plane prioritized"
      : "Guided routes prioritized";

  return (
    <section className={`permission-mode-control permission-mode-control-${selectedMode.tone}`} aria-label="Permission mode">
      <div className="permission-mode-picker">
        <label htmlFor="cockpit-permission-mode">Permission mode</label>
        <select
          id="cockpit-permission-mode"
          value={selectedModeId}
          onChange={(event) => {
            const nextMode = event.target.value;
            if (!isPermissionModeId(nextMode)) {
              throw new Error(`Permission mode selection "${nextMode}" is unavailable.`);
            }
            onSelectMode(nextMode);
          }}
        >
          {PERMISSION_MODES.map((mode) => (
            <option key={mode.id} value={mode.id}>
              {mode.label}
            </option>
          ))}
        </select>
      </div>

      <div className="permission-mode-summary" aria-live="polite">
        <strong>{selectedMode.headline}</strong>
        <p>{selectedMode.description}</p>
      </div>

      <dl className="permission-mode-details">
        <div>
          <dt>Allowed now</dt>
          <dd>{selectedMode.allowedNow}</dd>
        </div>
        <div>
          <dt>Review gate</dt>
          <dd>{selectedMode.reviewGate}</dd>
        </div>
        <div>
          <dt>Control plane</dt>
          <dd>{controlPlaneLabel}</dd>
        </div>
      </dl>

      <button
        type="button"
        className="permission-mode-plane-toggle"
        onClick={() => onOperatorModeChange(operatorMode === "pro" ? "beginner" : "pro")}
      >
        {operatorMode === "pro" ? "Prioritize guided routes" : "Prioritize live controls"}
      </button>
    </section>
  );
}
