---
name: extract-action-items
version: 1.0.0
description: Extract action items from a meeting transcript with owners and deadlines.
tags:
  - meetings
  - action-items
  - productivity
---

# Extract Action Items

Given a meeting transcript or notes, identify every commitment, task, or
follow-up item that requires action after the meeting.

## What Counts as an Action Item

An action item is a statement where someone agrees to do something by a
specific time, or where the group assigns a task to a person. Indicators:

- Explicit assignment: "John will...", "Alice, can you...", "We need someone to..."
- Commitment: "I'll get that done by...", "I'll send the report..."
- Follow-up: "Let's circle back on...", "We need to revisit..."
- Decision implementation: "Bob will implement the decision to..."

## Procedure

1. Read the full transcript.
2. Scan for action item indicators (assignment verbs, deadline phrases, owner names).
3. For each action item, extract:
   - **Task**: what needs to be done (one clear sentence)
   - **Owner**: who is responsible (person's name or role)
   - **Deadline**: when it must be completed
   - **Context**: optional brief context from the discussion (1 sentence max)
4. If the owner is unclear, mark as `[owner TBD]`.
5. If the deadline is unclear, mark as `[deadline TBD]`.
6. Deduplicate: if the same task is mentioned multiple times, record it once
   with the most specific owner and deadline.
7. Sort action items by deadline (soonest first); items with `[deadline TBD]`
   go last.

## Output Format

```
## Action Items

| # | Task | Owner | Deadline | Context |
|---|------|-------|----------|---------|
| 1 | Send updated roadmap to stakeholders | Alice | 2026-04-15 | Discussed in Q2 planning section |
| 2 | Schedule follow-up with legal team | Bob | [deadline TBD] | Re: contract review |
| 3 | Prepare budget proposal | [owner TBD] | End of Q2 | Required for executive review |
```

## Quality Rules

- Do not invent action items not present in the transcript.
- Do not omit an action item because the owner or deadline is missing — use
  the `[TBD]` markers.
- Action items must be actionable. "Discuss X further" is not an action item
  unless there is a scheduled follow-up or an assigned person.
- If no action items are found, return "No action items identified."
