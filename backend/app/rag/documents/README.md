
# Curated travel knowledge format

Only short, verified, source-dated destination notes belong in this folder. Every
ingested Markdown file must start with front matter like this:

```yaml
---
title: Short descriptive title
destination: Canonical destination name
source_url: https://official.example/path
updated_at: 2026-10-01
license_note: Short note explaining reuse/paraphrase permission or source terms
example: false
---
```

Rules:

- Verify the content before ingestion and cite the official public HTTPS source.
- Keep notes short and paraphrased. Do not copy long copyrighted passages.
- Do not put live prices, availability, route duration, or feasibility claims in RAG notes.
- `source_url` and `updated_at` are mandatory; invalid or unsafe URLs are rejected.
- Use headings to separate topics. Ingestion chunks by heading and bounded size.
- Set `example: true` for templates or unverified examples; those files are skipped.
- Never place API keys, credentials, user prompts, or personal data in these files.

Run `python scripts/ingest_knowledge.py --dry-run` to validate and count documents
without loading the embedding model or contacting Qdrant.
