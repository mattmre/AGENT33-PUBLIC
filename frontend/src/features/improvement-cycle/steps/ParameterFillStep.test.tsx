import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ParameterFillStep,
  buildDefaultValues,
  validateRequiredInputs,
  type ParameterDef
} from "./ParameterFillStep";

const MOCK_INPUTS: Record<string, ParameterDef> = {
  session_id: {
    type: "string",
    description: "Session identifier.",
    required: true
  },
  scope: {
    type: "string",
    description: "Review scope.",
    default: "full-delivery"
  },
  participants: {
    type: "array",
    description: "Participants.",
    default: ["reviewer", "implementer"]
  },
  threshold: {
    type: "integer",
    description: "Regression threshold.",
    default: 10
  },
  config: {
    type: "object",
    description: "Extra config.",
    default: { key: "value" }
  }
};

describe("ParameterFillStep", () => {
  it("renders a form field for each input", () => {
    render(
      <ParameterFillStep inputs={MOCK_INPUTS} values={{}} onChange={vi.fn()} />
    );
    expect(screen.getByLabelText("Session Id")).toBeInTheDocument();
    expect(screen.getByLabelText("Scope")).toBeInTheDocument();
    expect(screen.getByLabelText("Participants")).toBeInTheDocument();
    expect(screen.getByLabelText("Threshold")).toBeInTheDocument();
    expect(screen.getByLabelText("Config")).toBeInTheDocument();
  });

  it("marks required fields with asterisk", () => {
    render(
      <ParameterFillStep inputs={MOCK_INPUTS} values={{}} onChange={vi.fn()} />
    );
    const requiredMarkers = document.querySelectorAll(".wizard-required");
    expect(requiredMarkers.length).toBeGreaterThanOrEqual(1);
  });

  it("shows missing required fields warning", () => {
    render(
      <ParameterFillStep inputs={MOCK_INPUTS} values={{}} onChange={vi.fn()} />
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Missing required fields: Session Id");
  });

  it("does not show warning when all required fields are filled", () => {
    render(
      <ParameterFillStep
        inputs={MOCK_INPUTS}
        values={{ session_id: "session-1" }}
        onChange={vi.fn()}
      />
    );
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("calls onChange when a string field is edited", async () => {
    const onChange = vi.fn();
    render(
      <ParameterFillStep inputs={MOCK_INPUTS} values={{}} onChange={onChange} />
    );
    await userEvent.type(screen.getByLabelText("Session Id"), "s1");
    expect(onChange).toHaveBeenCalled();
    // Last call should include session_id key
    const lastCall = onChange.mock.calls[onChange.mock.calls.length - 1][0];
    expect(lastCall.session_id).toBeDefined();
  });

  it("renders number input for integer type", () => {
    render(
      <ParameterFillStep
        inputs={MOCK_INPUTS}
        values={{ threshold: 10 }}
        onChange={vi.fn()}
      />
    );
    const input = screen.getByLabelText("Threshold");
    expect(input).toHaveAttribute("type", "number");
    expect(input).toHaveValue(10);
  });

  it("renders textarea for object type", () => {
    render(
      <ParameterFillStep
        inputs={MOCK_INPUTS}
        values={{ config: { key: "value" } }}
        onChange={vi.fn()}
      />
    );
    const textarea = screen.getByLabelText("Config");
    expect(textarea.tagName.toLowerCase()).toBe("textarea");
  });

  it("renders comma-separated input for array type", async () => {
    const onChange = vi.fn();
    render(
      <ParameterFillStep
        inputs={MOCK_INPUTS}
        values={{ participants: ["a", "b"] }}
        onChange={onChange}
      />
    );
    const input = screen.getByLabelText("Participants");
    expect(input).toHaveValue("a, b");
  });

  it("shows empty state when no inputs", () => {
    render(
      <ParameterFillStep inputs={{}} values={{}} onChange={vi.fn()} />
    );
    expect(screen.getByText("This template has no configurable inputs.")).toBeInTheDocument();
  });
});

describe("buildDefaultValues", () => {
  it("extracts defaults from parameter definitions", () => {
    const defaults = buildDefaultValues(MOCK_INPUTS);
    expect(defaults).toEqual({
      scope: "full-delivery",
      participants: ["reviewer", "implementer"],
      threshold: 10,
      config: { key: "value" }
    });
  });

  it("skips parameters without defaults", () => {
    const defaults = buildDefaultValues(MOCK_INPUTS);
    expect(defaults).not.toHaveProperty("session_id");
  });
});

describe("validateRequiredInputs", () => {
  it("returns false when required fields are empty", () => {
    expect(validateRequiredInputs(MOCK_INPUTS, {})).toBe(false);
  });

  it("returns true when all required fields have values", () => {
    expect(
      validateRequiredInputs(MOCK_INPUTS, { session_id: "session-1" })
    ).toBe(true);
  });

  it("returns true when there are no required fields", () => {
    const inputs: Record<string, ParameterDef> = {
      optional: { type: "string" }
    };
    expect(validateRequiredInputs(inputs, {})).toBe(true);
  });
});
