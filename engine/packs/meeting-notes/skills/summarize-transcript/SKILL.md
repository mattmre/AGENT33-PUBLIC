---
name: summarize-transcript
version: 1.0.0
description: Summarize a meeting transcript into structured, scannable meeting notes.
tags:
  - meetings
  - summarization
  - productivity
---

# Summarize Transcript

Given a meeting transcript, produce structured meeting notes that capture the
essential information without requiring the reader to read the full transcript.

## Procedure

1. Read the full transcript. Identify:
   - Attendees (by name and role if stated)
   - Meeting date, time, and duration
   - Main agenda items or topics discussed
   - Key discussion points for each topic
   - Decisions made (flagged for the `identify-decisions` skill)
   - Action items (flagged for the `extract-action-items` skill)
   - Next meeting or follow-up schedule
2. Organize the content into the standard meeting notes template below.
3. For each topic, write 2-5 sentences capturing the key discussion points.
   Prefer specific details (numbers, names, dates) over vague summaries.
4. Use neutral, factual language. Do not editorialize or add opinions not
   present in the transcript.
5. If the transcript is in audio-transcribed format with filler words
   ("um", "uh", "you know"), clean these from the summary without changing
   the substance.

## Output Format

```
## Meeting Notes

**Date**: <date>
**Duration**: <duration>
**Attendees**: <name (role), name (role), ...>

---

### Summary

<2-4 sentence high-level summary of what the meeting accomplished>

---

### Topics Discussed

#### <Topic 1>
<2-5 sentences covering the key discussion points>

#### <Topic 2>
<2-5 sentences covering the key discussion points>

---

### Decisions
<See identify-decisions output or list here>

### Action Items
<See extract-action-items output or list here>

---

### Next Steps
<Next meeting date, follow-up schedule, or pending items>
```

## Quality Rules

- Every section must be present; use "None identified" for empty sections.
- Do not quote the transcript verbatim — paraphrase to be concise.
- Attendee list must reflect who was actually present, not who was invited.
- Keep the summary section under 100 words.
