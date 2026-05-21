import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import {
  useWizardSteps,
  StepIndicator,
  type WizardStepConfig
} from "./WizardStepController";

const STEPS: WizardStepConfig[] = [
  { id: "step-0", title: "Select Template" },
  { id: "step-1", title: "Fill Parameters" },
  { id: "step-2", title: "Preview" },
  { id: "step-3", title: "Execute" }
];

describe("useWizardSteps", () => {
  it("starts at step 0 with no completed steps", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    expect(result.current.currentStep).toBe(0);
    expect(result.current.completedSteps.size).toBe(0);
    expect(result.current.canGoBack).toBe(false);
    expect(result.current.canAdvance).toBe(true);
  });

  it("advances to next step and marks current as complete", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.advance());
    expect(result.current.currentStep).toBe(1);
    expect(result.current.completedSteps.has(0)).toBe(true);
    expect(result.current.canGoBack).toBe(true);
  });

  it("goes back to previous step", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.advance());
    act(() => result.current.goBack());
    expect(result.current.currentStep).toBe(0);
  });

  it("does not advance past the last step", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.advance());
    act(() => result.current.advance());
    act(() => result.current.advance());
    expect(result.current.currentStep).toBe(3);
    expect(result.current.canAdvance).toBe(false);
    act(() => result.current.advance());
    expect(result.current.currentStep).toBe(3);
  });

  it("does not go back past step 0", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.goBack());
    expect(result.current.currentStep).toBe(0);
  });

  it("jumpTo only works for completed or prior steps", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.advance());
    act(() => result.current.advance());
    // Can jump back to completed step 0
    act(() => result.current.jumpTo(0));
    expect(result.current.currentStep).toBe(0);
    // Cannot jump forward to uncompleted step 3
    act(() => result.current.jumpTo(3));
    expect(result.current.currentStep).toBe(0);
  });

  it("respects prerequisite functions", () => {
    let prereqMet = false;
    const steps: WizardStepConfig[] = [
      { id: "a", title: "A" },
      { id: "b", title: "B", prerequisite: () => prereqMet }
    ];
    const { result, rerender } = renderHook(() => useWizardSteps(steps));
    expect(result.current.canAdvance).toBe(false);

    prereqMet = true;
    rerender();
    expect(result.current.canAdvance).toBe(true);
  });

  it("markComplete adds a step to completedSteps", () => {
    const { result } = renderHook(() => useWizardSteps(STEPS));
    act(() => result.current.markComplete(2));
    expect(result.current.completedSteps.has(2)).toBe(true);
  });
});

describe("StepIndicator", () => {
  it("renders all steps with correct labels", () => {
    render(
      <StepIndicator
        steps={STEPS}
        currentStep={0}
        completedSteps={new Set()}
        onJumpTo={vi.fn()}
      />
    );
    expect(
      screen.getByRole("button", { name: /Step 1: Select Template/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Step 2: Fill Parameters/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Step 3: Preview/ })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Step 4: Execute/ })
    ).toBeInTheDocument();
  });

  it("marks the active step with aria-current", () => {
    render(
      <StepIndicator
        steps={STEPS}
        currentStep={1}
        completedSteps={new Set([0])}
        onJumpTo={vi.fn()}
      />
    );
    const activeButton = screen.getByRole("button", {
      name: /Step 2: Fill Parameters \(active\)/
    });
    expect(activeButton).toHaveAttribute("aria-current", "step");
  });

  it("allows jumping to completed steps", async () => {
    const onJumpTo = vi.fn();
    render(
      <StepIndicator
        steps={STEPS}
        currentStep={2}
        completedSteps={new Set([0, 1])}
        onJumpTo={onJumpTo}
      />
    );
    const step1Button = screen.getByRole("button", {
      name: /Step 1: Select Template \(complete\)/
    });
    expect(step1Button).not.toBeDisabled();
    await userEvent.click(step1Button);
    expect(onJumpTo).toHaveBeenCalledWith(0);
  });

  it("disables future uncompleted steps", () => {
    render(
      <StepIndicator
        steps={STEPS}
        currentStep={0}
        completedSteps={new Set()}
        onJumpTo={vi.fn()}
      />
    );
    const step3Button = screen.getByRole("button", {
      name: /Step 3: Preview \(pending\)/
    });
    expect(step3Button).toBeDisabled();
  });
});
