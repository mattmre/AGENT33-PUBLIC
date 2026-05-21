export const ARTIFACT_DRAWER_SECTIONS = [
  {
    id: "plan",
    label: "Plan",
    title: "Plan artifact",
    body: "Checklist, assumptions, risks, and validation commands will appear here before execution."
  },
  {
    id: "commands",
    label: "Command Blocks",
    title: "Command blocks",
    body: "Tool and command runs will be grouped with source agent, status, duration, and redaction state."
  },
  {
    id: "logs",
    label: "Logs",
    title: "Run logs",
    body: "Readable logs will summarize important output instead of forcing users into terminal walls."
  },
  {
    id: "tests",
    label: "Tests",
    title: "Validation evidence",
    body: "Test, lint, build, and smoke results will show pass/fail status and next repair action."
  },
  {
    id: "risks",
    label: "Risks",
    title: "Risk register",
    body: "Known blockers, secrets warnings, destructive actions, and uncertainty notes will collect here."
  },
  {
    id: "approval",
    label: "Approval",
    title: "Approval gate",
    body: "Permission requests will explain what runs, why it is needed, and what can be safely skipped."
  },
  {
    id: "activity",
    label: "Activity / Mailbox",
    title: "Agent mailbox",
    body: "Coordinator, Builder, Scout, and Reviewer handoffs will be typed events, not transcript noise."
  },
  {
    id: "outcome",
    label: "Outcome",
    title: "Done state",
    body: "Completed sessions should end as PR ready, artifact package ready, or blocked with a clear action."
  }
] as const;

export type ArtifactDrawerSection = (typeof ARTIFACT_DRAWER_SECTIONS)[number];
export type ArtifactDrawerSectionId = ArtifactDrawerSection["id"];

export const DEFAULT_ARTIFACT_DRAWER_SECTION_ID: ArtifactDrawerSectionId = "plan";
export const ARTIFACT_DRAWER_SECTION_IDS: ReadonlyArray<ArtifactDrawerSectionId> = ARTIFACT_DRAWER_SECTIONS.map(
  (section) => section.id
);

const ARTIFACT_DRAWER_SECTION_ID_SET = new Set<string>(ARTIFACT_DRAWER_SECTION_IDS);

export function isArtifactDrawerSectionId(value: string | null): value is ArtifactDrawerSectionId {
  return value !== null && ARTIFACT_DRAWER_SECTION_ID_SET.has(value);
}
