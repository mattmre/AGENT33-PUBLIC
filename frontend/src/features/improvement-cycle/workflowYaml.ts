type YamlValue = string | number | boolean | YamlValue[] | { [key: string]: YamlValue };

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

export function parseCanonicalWorkflowYaml(source: string): Record<string, unknown> {
  const normalizedSource = source.replace(/\r\n/g, "\n");
  const [value] = parseYamlBlock(normalizedSource.split("\n"), 0, 0);
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Expected workflow YAML to parse into an object");
  }
  return value as Record<string, unknown>;
}
