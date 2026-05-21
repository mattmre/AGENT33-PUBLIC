# SESSION WRAP + NEXT-SESSION HANDOFF (REPO CONTEXT)

**Version**: 1.0
**Purpose**: Ensure session continuity and auditable project history

---

## Objective

Before compacting a chat or starting a new session, capture an auditable session record and update project documentation so the next session can resume with minimal context loss.

---

## Required Actions (in order)

### 1) Session Log

Create/append a session log file under: `./docs/session-logs/`

**Filename convention**: `./docs/session-logs/YYYY-MM-DD_session.md`

**Log must include**:
- Date/time (local)
- High-level summary of what was accomplished/decided
- Key technical decisions and rationale
- Any paths/files/scripts created or modified (or intended)
- Open questions / risks / blockers
- Explicit "Next Steps" checklist

---

### 2) Documentation Updates

- Update `./CLAUDE.md` as the primary project handoff document
- Update any other project markdown files that the repo uses for onboarding/runbooks/architecture (as applicable)
- Ensure these docs reflect the **CURRENT** state after this session, including:
  - Repo purpose and current workstream
  - How to run/build/test locally (or what is still missing)
  - Current environment assumptions (OS, tools, containers, ports, etc.)
  - Current folder structure and where key components live
  - Known issues and TODOs

---

### 3) Next-Session Narrative (deliverable to the user)

Produce a concise "Next Session Kickoff Narrative" that can be pasted into a brand-new chat.

**It must include**:
- One-paragraph repo summary and current goal
- Current status snapshot (what exists now vs what's planned)
- "Pick up here" starting point (exact file(s)/module(s) to open first)
- A prioritized task list for the next session (5–10 bullets)
- Any required inputs needed (e.g., sample files, env vars, commands to run)

---

### 4) Save Next-Session Narrative (only when explicitly requested)

When explicitly asked to "save the next-session narrative", write it to:
```
./docs/next session/next-session-narrative.md
```

- If the folder does not exist, create it
- **Do not save it unless explicitly requested**

---

## Completion Criteria

- [ ] Session log exists in `./docs/session-logs/` (or appended correctly)
- [ ] `CLAUDE.md` and any necessary project `.md` docs are updated for continuity
- [ ] Next-session narrative is generated and ready to paste into a new chat
- [ ] If/when requested, the next-session narrative is saved under `./docs/next session/`

---

## Invocation

To trigger this protocol, say:
```
Run session wrap using docs/CLAUDE_SESSION_WRAP_CONTEXT_AGENT.md
```

Or simply:
```
Session wrap and handoff
```

---

## Session Log Template

```markdown
# Session Log: YYYY-MM-DD

**Date**: YYYY-MM-DD
**Time**: HH:MM (local)
**Session Duration**: ~X hours

## Summary
[High-level summary of what was accomplished]

## Technical Decisions
- [Decision 1]: [Rationale]
- [Decision 2]: [Rationale]

## Files Modified
- `path/to/file1` - [nature of change]
- `path/to/file2` - [nature of change]

## Files Created
- `path/to/new/file` - [purpose]

## Open Questions / Blockers
- [ ] [Question or blocker 1]
- [ ] [Question or blocker 2]

## Next Steps
- [ ] [Priority 1 task]
- [ ] [Priority 2 task]
- [ ] [Priority 3 task]
```

---

## Next-Session Narrative Template

```markdown
# Next Session Kickoff

## Repo Summary
[One paragraph describing the repo and current goal]

## Current Status
- **Completed**: [What exists now]
- **In Progress**: [What's partially done]
- **Planned**: [What's next]

## Pick Up Here
Start with: `path/to/file.ext`
Context: [Brief context on what to do with this file]

## Priority Tasks
1. [Task 1]
2. [Task 2]
3. [Task 3]
4. [Task 4]
5. [Task 5]

## Required Inputs
- [ ] [Any files, env vars, or commands needed]

## Useful Commands
```bash
# Build
[build command]

# Test
[test command]

# Run
[run command]
```
```

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-01-15 | Initial protocol |
