---
name: chunk-and-summarize
version: 1.0.0
description: Chunk a long document into sections and summarize each before synthesizing a full summary.
allowed_tools:
  - file_ops
tags:
  - summarization
  - documents
  - chunking
---

# Chunk and Summarize

For long documents that exceed a single context window, use a map-reduce summarization
strategy: chunk the document, summarize each chunk, then synthesize the chunk
summaries into a coherent whole.

## When to Use This Skill

Use this skill when the document:
- Exceeds approximately 50,000 tokens (roughly 40,000 words or 200 pages)
- Has a clear section structure (chapters, sections, headings)
- Requires a complete summary, not just a representative excerpt

For shorter documents, use `extract-key-points` or `generate-abstract` directly.

## Procedure

### Phase 1: Chunking

1. Read the document using `file_ops`.
2. Identify natural boundaries: headings, section breaks, chapter markers.
3. Split the document into chunks of 10,000-15,000 characters (roughly 2,000-3,000 words) each, splitting at
   sentence or paragraph boundaries — never mid-sentence.
4. Number each chunk and record its source location (section name / page range).

### Phase 2: Chunk Summarization

5. For each chunk, produce a focused summary:
   - Identify the main topic of the chunk
   - Record 3-7 key points as bullet points
   - Preserve all numerical data, proper nouns, and technical terms verbatim
   - Target 100-200 words per chunk summary

### Phase 3: Synthesis

6. Combine all chunk summaries.
7. Identify overarching themes across chunks.
8. Write a synthesis narrative (500-1,000 words for most documents) that:
   - Opens with the document's central argument or purpose
   - Covers each major section in order
   - Notes relationships and progressions between sections
   - Concludes with the document's main conclusions or recommendations
9. Append a section list showing which chunks map to which sections.

## Output Format

```
## Document Summary: <title>

**Source**: <file path or URL>
**Author**: <author or "Unknown">
**Date**: <document date or "Unknown">
**Length**: <word count or page count>

---

### Full Summary

<synthesis narrative>

---

### Section Summaries

#### Section 1: <heading> (Chunk 1-2)
<100-200 word chunk summary>

#### Section 2: <heading> (Chunk 3)
<100-200 word chunk summary>
```

## Quality Rules

- Do not hallucinate content not present in the document.
- Preserve all statistics, figures, and measurements exactly as they appear.
- If a chunk cannot be reliably summarized (e.g., it is a table of raw data),
  describe its content type and purpose instead.
