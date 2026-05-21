---
name: search-web
version: 1.0.0
description: Search the web for information on a topic and return ranked, cited results.
allowed_tools:
  - web_fetch
tags:
  - web
  - search
  - research
---

# Search Web

Given a search query, retrieve relevant information from the web and return a
structured list of results with titles, URLs, and brief excerpts.

## Procedure

1. Formulate a precise search query from the user's intent. Remove filler words;
   prefer specific nouns, version numbers, and technical terms.
2. Fetch search results using `web_fetch`. Prefer authoritative domains (official
   docs, peer-reviewed sources, established news outlets) when available.
3. For each result, record:
   - **Title**: the page title or headline
   - **URL**: the canonical URL
   - **Excerpt**: a 1-3 sentence description of the relevant content
   - **Date**: the publication or last-updated date if available
4. Return results sorted by relevance, with the most directly applicable result
   first.
5. If fewer than 3 results are found, broaden the query and retry once.

## Output Format

Return a structured list:

```
Result 1:
  Title: <title>
  URL: <url>
  Date: <date or "unknown">
  Excerpt: <excerpt>

Result 2:
  ...
```

## Quality Rules

- Do not fabricate URLs or excerpts. Only report what was actually fetched.
- Flag results older than 2 years with a `[DATED]` marker.
- If a page requires login or returns an error, skip it and note the skip.
- Cite the URL in any answer that uses information from this search.
