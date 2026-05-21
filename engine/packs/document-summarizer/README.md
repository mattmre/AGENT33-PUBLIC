# document-summarizer

Document summarization pack for AGENT-33.

## Skills

- **chunk-and-summarize**: Map-reduce summarization for long documents
- **extract-key-points**: Extract and rank the most important takeaways
- **generate-abstract**: Produce a concise informative or executive abstract

## Usage

```bash
agent33 packs validate engine/packs/document-summarizer
agent33 packs apply document-summarizer
```

## Tool Requirements

- `file_ops` for reading document files
