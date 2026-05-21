import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { TemplateSelectionStep } from "./TemplateSelectionStep";
import type { WorkflowPresetDefinition } from "../../../types";

const MOCK_PRESETS: WorkflowPresetDefinition[] = [
  {
    id: "retrospective",
    workflowName: "improvement-cycle-retrospective",
    label: "Retrospective improvement cycle",
    description: "A retrospective scaffold.",
    sourcePath: "core/workflows/improvement-cycle/retrospective.workflow.yaml",
    workflowDefinition: {
      name: "improvement-cycle-retrospective",
      steps: [{ id: "validate" }, { id: "collect" }, { id: "summarize" }],
      inputs: { session_id: { type: "string" }, scope: { type: "string" } }
    },
    executePreset: {
      pathParams: { name: "improvement-cycle-retrospective" },
      body: { inputs: {} }
    }
  },
  {
    id: "metrics-review",
    workflowName: "improvement-cycle-metrics-review",
    label: "Metrics review improvement cycle",
    description: "A metrics review scaffold.",
    sourcePath: "core/workflows/improvement-cycle/metrics-review.workflow.yaml",
    workflowDefinition: {
      name: "improvement-cycle-metrics-review",
      steps: [{ id: "validate" }, { id: "collect" }, { id: "summarize" }],
      inputs: { review_period: { type: "string" } }
    },
    executePreset: {
      pathParams: { name: "improvement-cycle-metrics-review" },
      body: { inputs: {} }
    }
  }
];

describe("TemplateSelectionStep", () => {
  it("renders all preset cards plus custom option", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId=""
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    expect(screen.getByText("Retrospective improvement cycle")).toBeInTheDocument();
    expect(screen.getByText("Metrics review improvement cycle")).toBeInTheDocument();
    expect(screen.getByText("Custom")).toBeInTheDocument();
  });

  it("shows description and step count for each preset", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId=""
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    expect(screen.getByText("A retrospective scaffold.")).toBeInTheDocument();
    expect(screen.getAllByText("Steps: 3")).toHaveLength(2);
  });

  it("shows input names for presets", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId=""
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    expect(screen.getByText("Inputs: session_id, scope")).toBeInTheDocument();
    expect(screen.getByText("Inputs: review_period")).toBeInTheDocument();
  });

  it("marks selected preset with aria-checked", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId="retrospective"
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    const selected = screen.getByRole("radio", { name: "Retrospective improvement cycle" });
    expect(selected).toHaveAttribute("aria-checked", "true");
  });

  it("calls onSelect when clicking a preset", async () => {
    const onSelect = vi.fn();
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId=""
        onSelect={onSelect}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    await userEvent.click(screen.getByText("Metrics review improvement cycle"));
    expect(onSelect).toHaveBeenCalledWith("metrics-review");
  });

  it("shows custom YAML textarea when custom is selected", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId="custom"
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    expect(screen.getByLabelText("Custom workflow YAML")).toBeInTheDocument();
  });

  it("does not show custom YAML textarea for non-custom selection", () => {
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId="retrospective"
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={vi.fn()}
      />
    );
    expect(screen.queryByLabelText("Custom workflow YAML")).not.toBeInTheDocument();
  });

  it("calls onCustomYamlChange when typing in custom textarea", async () => {
    const onCustomYamlChange = vi.fn();
    render(
      <TemplateSelectionStep
        presets={MOCK_PRESETS}
        selectedPresetId="custom"
        onSelect={vi.fn()}
        customYaml=""
        onCustomYamlChange={onCustomYamlChange}
      />
    );
    await userEvent.type(screen.getByLabelText("Custom workflow YAML"), "name: test");
    expect(onCustomYamlChange).toHaveBeenCalled();
  });
});
