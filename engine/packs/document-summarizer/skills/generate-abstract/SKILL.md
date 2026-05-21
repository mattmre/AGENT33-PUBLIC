---
name: generate-abstract
version: 1.0.0
description: Generate a concise abstract suitable for academic or executive audiences.
allowed_tools:
  - file_ops
tags:
  - summarization
  - abstract
  - documents
  - academic
---

# Generate Abstract

Produce a self-contained abstract for a document. The abstract should allow a
reader to decide whether to read the full document without requiring them to
read any of it first.

## Abstract Types

Choose the appropriate abstract type based on the document:

- **Informative abstract** (default): Summarizes the purpose, methods, results, and
  conclusions. Used for research papers, technical reports, and studies.
- **Descriptive abstract**: Describes what the document covers without summarizing
  findings. Used for books, review articles, or documents without discrete results.
- **Executive summary style**: Opens with the recommendation or conclusion, then
  provides supporting context. Used for business reports and proposals.

If the document type is ambiguous, produce an informative abstract.

## Structure (Informative Abstract)

An informative abstract covers:
1. **Purpose/Background**: What problem or question does the document address? (1-2 sentences)
2. **Methods/Approach**: How was the problem studied or the solution developed? (1-2 sentences)
3. **Results/Findings**: What did the document find or produce? Include key figures. (2-3 sentences)
4. **Conclusions/Implications**: What are the main takeaways and their significance? (1-2 sentences)

Total target length: 150-250 words.

## Procedure

1. Read the document using `file_ops` (or use provided chunk summaries).
2. Identify:
   - The document's stated purpose or research question
   - The methodology or approach
   - The primary results or deliverables
   - The main conclusions
3. Draft the abstract following the structure above.
4. Check:
   - Does it stand alone? A reader with no other context should understand it.
   - Is it accurate? Every claim must be directly supported by the document.
   - Is it concise? Cut any sentence that doesn't add information.
   - Does it include key figures and quantitative results?
5. Finalize the abstract with the document metadata header.

## Output Format

```
## Abstract

**Title**: <document title>
**Author(s)**: <author(s) or "Unknown">
**Date**: <document date or "Unknown">
**Type**: <Informative | Descriptive | Executive Summary>
**Word count**: <abstract word count>

---

<abstract text>
```

## Quality Rules

- The abstract must not introduce information not present in the document.
- Avoid jargon not used in the document itself; match the document's vocabulary.
- Use past tense for completed work ("The study found..."), present tense for
  general truths ("The framework provides...").
- Do not include citations in the abstract — it must be self-contained.
- If the document has its own abstract, compare it to yours and note any
  significant differences rather than simply copying it.
