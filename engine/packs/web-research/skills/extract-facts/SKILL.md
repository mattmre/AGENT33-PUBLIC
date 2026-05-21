---
name: extract-facts
version: 1.0.0
description: Extract discrete, verifiable facts from web content with source citations.
allowed_tools:
  - web_fetch
tags:
  - web
  - extraction
  - facts
  - research
---

# Extract Facts

Given web content or a URL, extract a set of discrete, independently verifiable
facts. Each fact must be atomic (one claim per fact), attributed to its source,
and accompanied by a confidence indicator.

## Procedure

1. Receive source content (raw text, URL, or list of URLs).
2. If URLs are provided, fetch each one using `web_fetch`.
3. Parse the content and identify factual statements. Distinguish:
   - **Hard facts**: specific figures, dates, names, events with a clear source
   - **Soft facts**: general statements of consensus that are widely accepted
   - **Opinion/editorial**: explicitly exclude these
4. For each hard fact, record:
   - The fact statement (one sentence, active voice)
   - The source URL
   - The source date
   - A confidence level: `high`, `medium`, or `low`
5. Cross-check facts against other sources when possible. Upgrade confidence if
   confirmed by a second independent source.
6. Return the extracted facts as a structured list.

## Output Format

```
Fact 1:
  Statement: <one-sentence factual claim>
  Source: <url>
  Date: <publication date or "unknown">
  Confidence: high | medium | low
  Notes: <optional context or caveat>

Fact 2:
  ...
```

## Quality Rules

- Each fact must be independently verifiable from its cited source.
- Avoid compound facts; split "X happened in Y and caused Z" into two facts.
- Mark speculation or prediction as `Confidence: low` with a note.
- If a URL cannot be fetched, record the fact as `Confidence: low` with a note
  indicating the source was inaccessible.
- Do not include the agent's own inferences as facts; attribute all claims to
  an external source.
