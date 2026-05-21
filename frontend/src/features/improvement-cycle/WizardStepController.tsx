import { useState, useCallback } from "react";

export interface WizardStepConfig {
  id: string;
  title: string;
  prerequisite?: () => boolean;
}

export interface WizardStepState {
  currentStep: number;
  completedSteps: Set<number>;
  canAdvance: boolean;
  canGoBack: boolean;
  advance: () => void;
  goBack: () => void;
  jumpTo: (step: number) => void;
  markComplete: (step: number) => void;
}

export function useWizardSteps(steps: WizardStepConfig[]): WizardStepState {
  const [currentStep, setCurrentStep] = useState(0);
  const [completedSteps, setCompletedSteps] = useState<Set<number>>(new Set());

  // Computed eagerly each render so prerequisite closures are always fresh.
  let canAdvance = currentStep < steps.length - 1;
  if (canAdvance) {
    const nextStep = steps[currentStep + 1];
    if (nextStep?.prerequisite && !nextStep.prerequisite()) {
      canAdvance = false;
    }
  }

  const canGoBack = currentStep > 0;

  const advance = useCallback(() => {
    if (currentStep < steps.length - 1) {
      setCompletedSteps((prev) => new Set([...prev, currentStep]));
      setCurrentStep(currentStep + 1);
    }
  }, [currentStep, steps.length]);

  const goBack = useCallback(() => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  }, [currentStep]);

  const jumpTo = useCallback(
    (step: number) => {
      if (step >= 0 && step < steps.length && (completedSteps.has(step) || step < currentStep)) {
        setCurrentStep(step);
      }
    },
    [steps.length, completedSteps, currentStep]
  );

  const markComplete = useCallback((step: number) => {
    setCompletedSteps((prev) => new Set([...prev, step]));
  }, []);

  return {
    currentStep,
    completedSteps,
    canAdvance,
    canGoBack,
    advance,
    goBack,
    jumpTo,
    markComplete
  };
}

interface StepIndicatorProps {
  steps: WizardStepConfig[];
  currentStep: number;
  completedSteps: Set<number>;
  onJumpTo: (step: number) => void;
}

export function StepIndicator({
  steps,
  currentStep,
  completedSteps,
  onJumpTo
}: StepIndicatorProps): JSX.Element {
  return (
    <nav className="wizard-step-indicator" aria-label="Wizard progress">
      <ol className="wizard-step-list">
        {steps.map((step, index) => {
          const isComplete = completedSteps.has(index);
          const isActive = index === currentStep;
          const isClickable = isComplete || index < currentStep;

          let statusLabel = "pending";
          if (isActive) statusLabel = "active";
          else if (isComplete) statusLabel = "complete";

          return (
            <li
              key={step.id}
              className={[
                "wizard-step-item",
                isActive ? "wizard-step-active" : "",
                isComplete ? "wizard-step-complete" : "",
                isClickable ? "wizard-step-clickable" : ""
              ]
                .filter(Boolean)
                .join(" ")}
            >
              <button
                type="button"
                className="wizard-step-button"
                disabled={!isClickable}
                aria-current={isActive ? "step" : undefined}
                aria-label={`Step ${index + 1}: ${step.title} (${statusLabel})`}
                onClick={() => isClickable && onJumpTo(index)}
              >
                <span className="wizard-step-number">{index + 1}</span>
                <span className="wizard-step-title">{step.title}</span>
              </button>
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
