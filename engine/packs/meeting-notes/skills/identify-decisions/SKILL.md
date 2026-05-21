---
name: identify-decisions
version: 1.0.0
description: Identify and record key decisions made during a meeting with rationale and stakeholders.
tags:
  - meetings
  - decisions
  - productivity
---

# Identify Decisions

Given a meeting transcript or notes, identify every decision that was made.
Decisions are distinct from action items (which are tasks) and discussion points
(which are still open).

## What Counts as a Decision

A decision is a commitment to a course of action or a resolution of an open
question. Indicators in transcript language:

- Explicit agreement: "We've decided to...", "The team agreed that..."
- Approval: "That's approved.", "Let's go with option B."
- Resolution: "We'll use X instead of Y.", "The deadline is set for..."
- Rejection: "We're not moving forward with...", "That's off the table."

## Procedure

1. Read the full transcript.
2. Identify every decision point using the indicators above.
3. For each decision, record:
   - **Decision**: a clear, definitive statement of what was decided
     (not a question or discussion point, but a resolution)
   - **Made by**: who made or approved the decision (person or group)
   - **Rationale**: why this decision was made (from the transcript context)
   - **Impact**: what changes as a result of this decision (if stated)
4. Distinguish between firm decisions and tentative ones:
   - Firm: "We decided X." → record as stated
   - Tentative: "We're leaning toward X, pending Y." → record with note
     "[pending Y]"
5. Sort decisions in the order they were made during the meeting.

## Output Format

```
## Decisions

### Decision 1: <brief title>
**Decided**: <full decision statement>
**Made by**: <person or "Group consensus">
**Rationale**: <reason given in transcript>
**Impact**: <what changes, or "Not stated">

### Decision 2: <brief title>
...
```

## Quality Rules

- Decisions must be stated definitively. Do not reframe a discussion point as
  a decision.
- If a decision was tentative or conditional, mark it clearly as "[tentative]"
  or "[pending <condition>]".
- Every decision must have a "Made by" attribution, even if it is "Group consensus."
- If no decisions were made, return "No decisions identified."
- Do not include action items in this list; they belong in the action items section.
