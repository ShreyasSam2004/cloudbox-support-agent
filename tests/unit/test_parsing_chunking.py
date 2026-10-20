from __future__ import annotations

from backend.retrieval.chunking import chunk_document, linearize_table
from backend.retrieval.ingestion import build_records
from backend.retrieval.parsing import extract_cross_references, parse_markdown, slugify
from tests.conftest import DATA

DOC = """---
doc_id: sample
title: Sample Policy
doc_type: policy
---

# Sample Policy

Intro paragraph that states the scope of the whole document.

## 1. Rules

The general rule applies to everyone.

### 1.1 Exception for Enterprise

Enterprise is different. See [Refund Policy §3](refund-policy.md#3-monthly-plans).

## 2. Table

| Plan | Limit |
|---|---|
| Pro | 1,000 |
| Business | 3,000 |

```bash
cloudbox keys rotate --key-id key_1
```
"""


def test_front_matter_and_heading_tree() -> None:
    doc = parse_markdown(DOC)
    assert doc.meta["doc_id"] == "sample"
    assert doc.title == "Sample Policy"
    titles = [s.title for s in doc.iter_sections()]
    assert titles == ["Sample Policy", "1. Rules", "1.1 Exception for Enterprise", "2. Table"]


def test_slugify_matches_github_anchors() -> None:
    assert slugify("3.2 Charges after cancellation") == "32-charges-after-cancellation"
    assert slugify("3.1 `rate_limit_exceeded` (CBX-4291)") == "31-rate_limit_exceeded-cbx-4291"


def test_cross_references_extracted() -> None:
    refs = extract_cross_references("see [x](refund-policy.md#32-charges) and [y](sla.md)")
    assert refs == ["refund-policy#32-charges", "sla"]


def test_chunks_carry_breadcrumbs_and_parent_context() -> None:
    drafts = chunk_document(parse_markdown(DOC))
    paths = [" > ".join(d.section_path) for d in drafts]
    assert "Sample Policy" in paths  # document intro is its own chunk
    exception = next(d for d in drafts if d.section_path[-1] == "1.1 Exception for Enterprise")
    # The short parent rule travels with the exception so they are retrieved together.
    assert "general rule applies" in exception.content
    assert exception.references == ["refund-policy#3-monthly-plans"]


def test_tables_and_code_are_atomic_and_linearised() -> None:
    drafts = chunk_document(parse_markdown(DOC))
    table_chunk = next(d for d in drafts if "table" in d.block_kinds)
    assert "| Pro | 1,000 |" in table_chunk.content
    assert "Plan: Pro; Limit: 1,000" in table_chunk.embedding_text
    assert "cloudbox keys rotate" in table_chunk.content  # code block kept intact in its section


def test_oversized_table_split_repeats_header() -> None:
    rows = "\n".join(f"| Plan {i} | {i * 100} requests per minute and more text |" for i in range(60))
    doc = parse_markdown(
        f"---\ndoc_id: t\ntitle: T\ndoc_type: policy\n---\n## Limits\n\n| Plan | Limit |\n|---|---|\n{rows}\n"
    )
    drafts = chunk_document(doc, max_chars=800)
    assert len(drafts) > 1
    assert all(d.content.startswith("| Plan | Limit |") for d in drafts)


def test_linearize_table_skips_separator() -> None:
    assert linearize_table("| A | B |\n|---|---|\n| 1 | 2 |") == "A: 1; B: 2"


def test_faq_produces_one_chunk_per_question() -> None:
    raw = (DATA / "knowledge_base" / "faq.md").read_text(encoding="utf-8")
    _, chunks = build_records(raw, "faq.md", "hashing-256")
    questions = [c for c in chunks if " > Q: " in c.section_path]
    assert len(questions) == raw.count("### Q:")
    assert all(c.content.startswith("A:") for c in questions)


def test_corpus_builds_with_metadata() -> None:
    for path in sorted((DATA / "knowledge_base").glob("*.md")):
        document, chunks = build_records(path.read_text(encoding="utf-8"), path.name, "hashing-256")
        assert chunks, path
        assert document.metadata.get("authority"), path
        assert all(c.metadata["doc_type"] == document.doc_type for c in chunks)
