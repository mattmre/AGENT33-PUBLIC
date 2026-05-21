import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  buildWorkflowCreatePresetBody,
  buildWorkflowExecutePreset,
  getImprovementCyclePresetById,
  improvementCyclePresetBinding,
  improvementCycleWorkflowPresets
} from "./presets";

type YamlValue = string | number | boolean | YamlValue[] | { [key: string]: YamlValue };

const repoRoot = resolve(process.cwd(), "..");

function isYamlObject(value: unknown): value is { [key: string]: YamlValue } {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isBlankLine(line: string): boolean {
  return line.trim() === "";
}

function getIndentation(line: string): number {
  let indentation = 0;
  while (indentation < line.length && line[indentation] === " ") {
    indentation += 1;
  }
  return indentation;
}

function parseYamlScalar(rawValue: string): YamlValue {
  const value = rawValue.trim();

  if (value === "true") {
    return true;
  }
  if (value === "false") {
    return false;
  }
  if (/^-?\d+$/.test(value)) {
    return Number(value);
  }
  if (value === "[]") {
    return [];
  }
  if (value === "{}") {
    return {};
  }
  if (value.startsWith("\"") && value.endsWith("\"")) {
    return JSON.parse(value) as string;
  }
  if (value.startsWith("'") && value.endsWith("'")) {
    return value.slice(1, -1).replace(/''/g, "'");
  }

  return value;
}

function splitYamlKeyValue(line: string): { key: string; rawValue: string } {
  const separatorIndex = line.indexOf(":");
  if (separatorIndex === -1) {
    throw new Error(`Expected YAML key/value pair but received "${line}"`);
  }

  return {
    key: line.slice(0, separatorIndex).trim(),
    rawValue: line.slice(separatorIndex + 1).trimStart()
  };
}

function parseYamlBlockScalar(
  lines: string[],
  startIndex: number,
  indentation: number
): [string, number] {
  const content: string[] = [];
  let index = startIndex;

  while (index < lines.length) {
    const line = lines[index];
    if (isBlankLine(line)) {
      content.push("");
      index += 1;
      continue;
    }

    const lineIndentation = getIndentation(line);
    if (lineIndentation < indentation) {
      break;
    }

    content.push(line.slice(indentation));
    index += 1;
  }

  return [content.join("\n"), index];
}

function parseYamlBlock(
  lines: string[],
  startIndex: number,
  indentation: number
): [YamlValue, number] {
  let index = startIndex;
  while (index < lines.length && isBlankLine(lines[index])) {
    index += 1;
  }

  if (index >= lines.length) {
    return [{}, index];
  }

  const lineIndentation = getIndentation(lines[index]);
  if (lineIndentation < indentation) {
    return [{}, index];
  }

  const trimmed = lines[index].slice(indentation);
  return trimmed.startsWith("- ")
    ? parseYamlArray(lines, index, indentation)
    : parseYamlObject(lines, index, indentation);
}

function parseYamlObject(
  lines: string[],
  startIndex: number,
  indentation: number,
  firstInlineLine?: string
): [{ [key: string]: YamlValue }, number] {
  const result: { [key: string]: YamlValue } = {};
  let index = startIndex;
  let inlineLine = firstInlineLine;

  while (true) {
    let currentLine: string;

    if (inlineLine !== undefined) {
      currentLine = inlineLine;
      inlineLine = undefined;
    } else {
      while (index < lines.length && isBlankLine(lines[index])) {
        index += 1;
      }
      if (index >= lines.length) {
        break;
      }

      const lineIndentation = getIndentation(lines[index]);
      if (lineIndentation < indentation) {
        break;
      }
      if (lineIndentation !== indentation) {
        throw new Error(`Unexpected indentation in YAML object at line ${index + 1}`);
      }

      currentLine = lines[index].slice(indentation);
      index += 1;
    }

    if (currentLine.startsWith("- ")) {
      break;
    }

    const { key, rawValue } = splitYamlKeyValue(currentLine);
    if (rawValue === "|") {
      const [value, nextIndex] = parseYamlBlockScalar(lines, index, indentation + 2);
      result[key] = value;
      index = nextIndex;
      continue;
    }
    if (rawValue === "") {
      const [value, nextIndex] = parseYamlBlock(lines, index, indentation + 2);
      result[key] = value;
      index = nextIndex;
      continue;
    }

    result[key] = parseYamlScalar(rawValue);
  }

  return [result, index];
}

function parseYamlArray(
  lines: string[],
  startIndex: number,
  indentation: number
): [YamlValue[], number] {
  const result: YamlValue[] = [];
  let index = startIndex;

  while (index < lines.length) {
    while (index < lines.length && isBlankLine(lines[index])) {
      index += 1;
    }
    if (index >= lines.length) {
      break;
    }

    const lineIndentation = getIndentation(lines[index]);
    if (lineIndentation < indentation) {
      break;
    }
    if (lineIndentation !== indentation) {
      throw new Error(`Unexpected indentation in YAML array at line ${index + 1}`);
    }

    const trimmed = lines[index].slice(indentation);
    if (!trimmed.startsWith("- ")) {
      break;
    }

    const inlineValue = trimmed.slice(2);
    if (inlineValue.trim() === "") {
      const [value, nextIndex] = parseYamlBlock(lines, index + 1, indentation + 2);
      result.push(value);
      index = nextIndex;
      continue;
    }

    if (inlineValue.includes(":")) {
      const [value, nextIndex] = parseYamlObject(
        lines,
        index + 1,
        indentation + 2,
        inlineValue
      );
      result.push(value);
      index = nextIndex;
      continue;
    }

    result.push(parseYamlScalar(inlineValue));
    index += 1;
  }

  return [result, index];
}

function parseCanonicalWorkflowYaml(source: string): YamlValue {
  const normalizedSource = source.replace(/\r\n/g, "\n");
  const [value] = parseYamlBlock(normalizedSource.split("\n"), 0, 0);
  return value;
}

function formatDriftValue(value: unknown): string {
  return typeof value === "string" ? JSON.stringify(value) : JSON.stringify(value, null, 2);
}

function findWorkflowDefinitionDrift(
  canonical: unknown,
  preset: unknown,
  path = "workflow"
): string | null {
  if (Array.isArray(canonical) || Array.isArray(preset)) {
    if (!Array.isArray(canonical) || !Array.isArray(preset)) {
      return `${path}: expected ${formatDriftValue(canonical)} but received ${formatDriftValue(preset)}`;
    }
    if (canonical.length !== preset.length) {
      return `${path}: expected ${canonical.length} items but received ${preset.length}`;
    }
    for (let index = 0; index < canonical.length; index += 1) {
      const drift = findWorkflowDefinitionDrift(
        canonical[index],
        preset[index],
        `${path}[${index}]`
      );
      if (drift) {
        return drift;
      }
    }
    return null;
  }

  if (isYamlObject(canonical) || isYamlObject(preset)) {
    if (!isYamlObject(canonical) || !isYamlObject(preset)) {
      return `${path}: expected ${formatDriftValue(canonical)} but received ${formatDriftValue(preset)}`;
    }

    const canonicalKeys = Object.keys(canonical).sort();
    const presetKeys = Object.keys(preset).sort();
    if (canonicalKeys.length !== presetKeys.length) {
      return `${path}: expected keys ${canonicalKeys.join(", ")} but received ${presetKeys.join(", ")}`;
    }
    for (const key of canonicalKeys) {
      if (!(key in preset)) {
        return `${path}.${key}: missing from preset definition`;
      }
      const drift = findWorkflowDefinitionDrift(canonical[key], preset[key], `${path}.${key}`);
      if (drift) {
        return drift;
      }
    }
    return null;
  }

  return canonical === preset
    ? null
    : `${path}: expected ${formatDriftValue(canonical)} but received ${formatDriftValue(preset)}`;
}

describe("improvementCycleWorkflowPresets", () => {
  it("projects the canonical improvement-cycle workflow names and source paths", () => {
    expect(improvementCycleWorkflowPresets.map((preset) => preset.workflowName)).toEqual([
      "improvement-cycle-retrospective",
      "improvement-cycle-metrics-review"
    ]);

    expect(improvementCycleWorkflowPresets.map((preset) => preset.sourcePath)).toEqual([
      "core/workflows/improvement-cycle/retrospective.workflow.yaml",
      "core/workflows/improvement-cycle/metrics-review.workflow.yaml"
    ]);

    expect(new Set(improvementCycleWorkflowPresets.map((preset) => preset.id)).size).toBe(
      improvementCycleWorkflowPresets.length
    );
  });

  it("builds create preset payloads that preserve the canonical workflow steps", () => {
    const retrospective = JSON.parse(buildWorkflowCreatePresetBody("retrospective"));
    expect(retrospective.name).toBe("improvement-cycle-retrospective");
    expect(retrospective.steps.map((step: { id: string }) => step.id)).toEqual([
      "validate",
      "collect",
      "summarize"
    ]);
    expect(retrospective.steps.map((step: { action: string }) => step.action)).toEqual([
      "validate",
      "transform",
      "transform"
    ]);

    const metrics = JSON.parse(buildWorkflowCreatePresetBody("metrics-review"));
    expect(metrics.name).toBe("improvement-cycle-metrics-review");
    expect(metrics.inputs.review_period.required).toBe(true);
    expect(metrics.execution.mode).toBe("dependency-aware");
  });

  it("matches each preset definition to its canonical YAML workflow source", () => {
    for (const preset of improvementCycleWorkflowPresets) {
      const canonicalWorkflow = parseCanonicalWorkflowYaml(
        readFileSync(resolve(repoRoot, preset.sourcePath), "utf8")
      );
      const createPayload = JSON.parse(buildWorkflowCreatePresetBody(preset.id));

      expect(findWorkflowDefinitionDrift(canonicalWorkflow, createPayload)).toBeNull();
    }
  });

  it("reports drift when a preset no longer matches the canonical YAML", () => {
    const retrospectivePreset = getImprovementCyclePresetById("retrospective");
    expect(retrospectivePreset).toBeDefined();

    const canonicalWorkflow = parseCanonicalWorkflowYaml(
      readFileSync(resolve(repoRoot, retrospectivePreset!.sourcePath), "utf8")
    );
    const driftedPreset = structuredClone(retrospectivePreset!.workflowDefinition) as Record<
      string,
      unknown
    >;
    driftedPreset.name = "improvement-cycle-retrospective-drifted";

    expect(findWorkflowDefinitionDrift(canonicalWorkflow, driftedPreset)).toBe(
      'workflow.name: expected "improvement-cycle-retrospective" but received "improvement-cycle-retrospective-drifted"'
    );
  });

  it("builds execute presets with canonical workflow names and deterministic sample inputs", () => {
    const retrospective = buildWorkflowExecutePreset("retrospective");
    expect(retrospective.pathParams).toEqual({ name: "improvement-cycle-retrospective" });
    expect(retrospective.body.inputs).toMatchObject({
      session_id: "session-57",
      scope: "frontend"
    });
    expect(retrospective.executionMode).toBe("single");

    const metrics = buildWorkflowExecutePreset("metrics-review");
    expect(metrics.pathParams).toEqual({ name: "improvement-cycle-metrics-review" });
    expect(metrics.body.inputs).toMatchObject({
      review_period: "2026-03-01 to 2026-03-07"
    });
    expect(metrics.body).not.toHaveProperty("repeat_count");
  });

  it("exposes a shared operation binding and lookup helper", () => {
    expect(improvementCyclePresetBinding.group).toBe("improvement-cycle");
    expect(improvementCyclePresetBinding.presetIds).toEqual([
      "retrospective",
      "metrics-review"
    ]);
    expect(getImprovementCyclePresetById("metrics-review")?.label).toContain("Metrics review");
  });
});
