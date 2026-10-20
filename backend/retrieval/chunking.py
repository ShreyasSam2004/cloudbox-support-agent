"""Structure-aware chunking.

Rules (see docs/retrieval.md for the reasoning):

1. Chunks never cross a section boundary; every chunk is prefixed with its breadcrumb
   ("Refund Policy > 3. Monthly plans > 3.2 Charges after cancellation").
2. Tables and code blocks are atomic. Oversized tables are split by rows and the header row is
   repeated in every part. Tables are additionally *linearised* ("Plan: Pro; Rate limit: …") in the
   indexed text so both lexical and semantic search can match individual cells.
3. A short section intro (typically the general rule) is carried into each child section's first
   chunk as context, so an exception is never retrieved without the rule it modifies.
4. FAQ documents produce exactly one chunk per question/answer pair (they are H3 sections).
5. Cross-references to other documents are extracted into metadata so the agent can follow them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from backend.retrieval.parsing import Block, ParsedDocument, Section, extract_cross_references

CHUNKER_VERSION = "3"
DEFAULT_MAX_CHARS = 1600

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


@dataclass
class ChunkDraft:
    section_path: list[str]
    anchor: str
    content: str
    embedding_text: str
    block_kinds: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


def _table_rows(table: str) -> tuple[list[str], list[list[str]]]:
    lines = [ln for ln in table.splitlines() if ln.strip().startswith("|")]
    rows = [[cell.strip() for cell in ln.strip().strip("|").split("|")] for ln in lines]
    rows = [r for r in rows if not all(re.fullmatch(r":?-{2,}:?", c or "--") for c in r)]
    if not rows:
        return [], []
    return rows[0], rows[1:]


def linearize_table(table: str) -> str:
    header, rows = _table_rows(table)
    out: list[str] = []
    for row in rows:
        pairs = [f"{h}: {v}" for h, v in zip(header, row, strict=False) if v]
        if pairs:
            out.append("; ".join(pairs))
    return "\n".join(out)


def _split_table(table: str, max_chars: int) -> list[str]:
    lines = [ln for ln in table.splitlines() if ln.strip()]
    if len(lines) <= 3:
        return [table]
    head, body = lines[:2], lines[2:]
    parts: list[str] = []
    current: list[str] = []
    for line in body:
        candidate = "\n".join([*head, *current, line])
        if current and len(candidate) > max_chars:
            parts.append("\n".join([*head, *current]))
            current = []
        current.append(line)
    if current:
        parts.append("\n".join([*head, *current]))
    return parts


def _split_text(text: str, max_chars: int) -> list[str]:
    pieces: list[str] = []
    current = ""
    units = text.split("\n") if "\n" in text else _SENTENCE_SPLIT_RE.split(text)
    for unit in units:
        candidate = f"{current}\n{unit}" if current else unit
        if current and len(candidate) > max_chars:
            pieces.append(current)
            current = unit
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces


def _atomize(block: Block, max_chars: int) -> list[Block]:
    if len(block.text) <= max_chars:
        return [block]
    if block.kind == "table":
        return [Block("table", part) for part in _split_table(block.text, max_chars)]
    if block.kind == "code":
        return (
            [block]
            if len(block.text) <= 2 * max_chars
            else [Block("code", part) for part in _split_text(block.text, max_chars)]
        )
    return [Block(block.kind, part) for part in _split_text(block.text, max_chars)]


def chunk_document(
    doc: ParsedDocument,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    context_max_chars: int = 420,
) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    doc_title = doc.title

    def emit(section: Section, blocks: list[Block], context: str | None) -> None:
        breadcrumb = " > ".join([doc_title, *section.path])
        body = "\n\n".join(b.text for b in blocks)
        content = f"(Context from the parent section: {context})\n\n{body}" if context else body
        tables = [linearize_table(b.text) for b in blocks if b.kind == "table"]
        embedding_text = "\n".join(part for part in (breadcrumb, context or "", body, *tables) if part)
        drafts.append(
            ChunkDraft(
                section_path=[doc_title, *section.path],
                anchor=section.anchor,
                content=content,
                embedding_text=embedding_text,
                block_kinds=sorted({b.kind for b in blocks}),
                references=extract_cross_references(body),
            )
        )

    def walk(section: Section, inherited_context: str | None) -> None:
        own = section.own_text
        has_children = bool(section.children)
        # The document-level intro is always its own chunk (it often states scope or supersession).
        short_intro = section is not doc.root and has_children and 0 < len(own) <= context_max_chars

        if section.blocks and not short_intro:
            atoms = [atom for block in section.blocks for atom in _atomize(block, max_chars)]
            group: list[Block] = []
            size = 0
            first = True
            for atom in atoms:
                if group and size + len(atom.text) > max_chars:
                    emit(section, group, inherited_context if first else None)
                    first = False
                    group, size = [], 0
                group.append(atom)
                size += len(atom.text)
            if group:
                emit(section, group, inherited_context if first else None)

        if short_intro:
            child_context: str | None = f"{inherited_context} {own}" if inherited_context else own
        elif not section.blocks:
            child_context = inherited_context  # heading-only section: pass context through
        else:
            child_context = None
        for child in section.children:
            walk(child, child_context)

    walk(doc.root, None)
    return drafts
