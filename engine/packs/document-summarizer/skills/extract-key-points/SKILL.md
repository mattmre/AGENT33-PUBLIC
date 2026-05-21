---
name: extract-key-points
version: 1.0.0
description: Extract the most important takeaways from a document as a prioritized list.
allowed_tools:
  - file_ops
tags:
  - summarization
  - key-points
  - documents
---

# Extract Key Points

Given a document, identify and rank the most important takeaways that a reader
must understand to grasp the document's value. Key points are distinct from a
sequential summary — they are the insights and conclusions that matter most,
regardless of where they appear in the document.

## What Makes a Good Key Point

A key point should:
- Express a single complete idea in one or two sentences
- Be specific enough to be useful (not "the document discusses X")
- Be important enough that omitting it would mislead the reader
- Preserve technical precision: exact figures, claims, and qualifications

A key point should NOT:
- Restate obvious background information
- Be a procedure or step (those belong in a summary)
- Duplicate another key point

## Procedure

1. Read the full document (or chunk summaries if the document is very long).
2. As you read, collect candidate key points — statements that are:
   - Main arguments or thesis statements
   - Surprising or counterintuitive findings
   - Quantified claims (with numbers)
   - Conclusions and recommendations
   - Important caveats, limitations, or exceptions
3. After reading, review all candidates and cull:
   - Remove redundant or derivative points
   - Merge closely related points
   - Prioritize points by their importance to the document's central purpose
4. Rank the surviving points (most important first).
5. Limit to 10 key points for most documents; technical reports may warrant
   up to 15.

## Output Format

```
## Key Points: <document title>

1. **<Short title>**: <One to two sentence statement of the key point.
   Include specific figures or qualifications exactly as stated.>

2. **<Short title>**: <...>

...

*Source: <file path or document reference>*
```

## Quality Rules

- Each key point must be independently understandable without reading the others.
- Do not pad the list to reach a minimum count. Fewer precise points beat more
  vague ones.
- If the document is a technical specification, key points should include
  the most important requirements and constraints.
- If the document is an argument or essay, key points should include the main
  thesis and the strongest supporting evidence.
