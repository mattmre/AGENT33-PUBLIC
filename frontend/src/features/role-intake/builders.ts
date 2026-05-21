import type { WorkflowStarterDraft } from "../workflow-starter/types";
import { getRoleProfile } from "./data";
import type { ProductBrief } from "./types";

function slugifyTitle(title: string): string {
  return title
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "")
    .slice(0, 64);
}

export function buildWorkflowDraftFromBrief(brief: ProductBrief): WorkflowStarterDraft {
  const roleProfile = getRoleProfile(brief.roleId);
  const name = slugifyTitle(brief.title) || `guided-brief-${brief.id}`;

  return {
    id: `guided-${brief.id}`,
    name,
    goal: [
      `Role path: ${roleProfile?.title ?? brief.roleId}`,
      `Idea: ${brief.idea}`,
      `Primary users: ${brief.audience}`,
      `Starting point: ${brief.startingPoint}`,
      `Desired output: ${brief.desiredOutput}`,
      `Safety and scope: ${brief.safetyScope}`
    ].join("\n"),
    kind: roleProfile?.starterKind ?? "automation-loop",
    output:
      "Plain-language product brief, required inputs, scoped workflow plan, safety gates, first deliverables, and validation checklist.",
    schedule: "",
    author: "role-intake",
    sourceLabel: `Guided intake: ${brief.title}`,
    lifecyclePlan: {
      brief: [
        brief.idea,
        `Audience: ${brief.audience}`,
        `Starting point: ${brief.startingPoint}`
      ],
      plan: [
        `Prepare ${brief.desiredOutput}.`,
        "Convert the role path into a scoped workflow plan with required inputs and review gates.",
        `Safety boundary: ${brief.safetyScope}`
      ],
      preview: [
        "Validate the role, audience, starting assets, and success criteria.",
        "Draft the product brief and first workflow plan without running host tools.",
        "Ask for approval before execution handoff."
      ],
      handoff: [
        "Open Workflow Starter with the guided brief prefilled.",
        "Create an editable workflow only after the preview is accepted.",
        "Route the operator to Operations for run visibility and recovery."
      ]
    }
  };
}
