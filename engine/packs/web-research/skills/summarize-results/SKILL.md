---
name: summarize-results
version: 1.0.0
description: Synthesize multiple web search results into a coherent, source-cited summary.
allowed_tools:
  - web_fetch
tags:
  - web
  - summarization
  - research
---

# Summarize Results

Given a set of web search results or fetched page content, produce a coherent
narrative summary that:
- Integrates information from multiple sources
- Preserves attribution for each claim
- Highlights consensus and flags disagreements

## Procedure

1. Receive a list of search results or raw fetched content.
2. Read each source in order of relevance.
3. Identify the key claims and facts across all sources.
4. Group claims by theme or subtopic.
5. Write a flowing summary paragraph (or multiple paragraphs for complex topics)
   that integrates the grouped claims.
6. After each specific claim, add an inline citation in the form `[Source N]`.
7. Append a **References** section listing each cited source with its title and URL.

## Output Format

```
## Summary

<narrative summary with inline citations [Source N]>

## References

1. [Source title](url) — retrieved <date>
2. ...
```

## Quality Rules

- Prefer concrete, specific claims over vague generalizations.
- If two sources directly contradict each other, report both perspectives:
  "Source A states X, while Source B reports Y."
- Do not omit important caveats or limitations mentioned in the sources.
- Aim for 200-500 words for most topics; go longer only if the topic requires it.
- Never synthesize a claim that is not supported by at least one cited source.
