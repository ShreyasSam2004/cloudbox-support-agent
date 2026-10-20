"""Markdown → section tree.

A deliberately small parser for the subset of Markdown used by the knowledge base: YAML front
matter, ATX headings, pipe tables, fenced code, lists and paragraphs. It preserves the heading
hierarchy so chunks can carry their full breadcrumb, and it never splits tables or code blocks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Literal

import yaml

BlockKind = Literal["paragraph", "table", "code", "list"]

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_LIST_RE = re.compile(r"^\s*(?:[*+-]|\d+\.)\s+")
_XREF_RE = re.compile(r"\]\(([a-z0-9-]+)\.md(?:#([a-z0-9_-]+))?\)")


@dataclass
class Block:
    kind: BlockKind
    text: str


@dataclass
class Section:
    level: int
    title: str
    anchor: str
    path: list[str]
    blocks: list[Block] = field(default_factory=list)
    children: list[Section] = field(default_factory=list)

    @property
    def own_text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


@dataclass
class ParsedDocument:
    meta: dict[str, Any]
    title: str
    root: Section

    def iter_sections(self) -> list[Section]:
        out: list[Section] = []

        def walk(section: Section) -> None:
            out.append(section)
            for child in section.children:
                walk(child)

        walk(self.root)
        return out


def slugify(title: str) -> str:
    """GitHub-style heading anchor ("3.2 Charges after cancellation" → "32-charges-after-cancellation")."""
    text = title.strip().lower().replace("`", "")
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def split_front_matter(raw: str) -> tuple[dict[str, Any], str]:
    text = raw.lstrip("﻿")
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    meta = yaml.safe_load(text[3:end]) or {}
    body = text[end + 4 :].lstrip("\n")
    return (meta if isinstance(meta, dict) else {}), body


def extract_cross_references(text: str) -> list[str]:
    refs: list[str] = []
    for doc_id, anchor in _XREF_RE.findall(text):
        ref = f"{doc_id}#{anchor}" if anchor else doc_id
        if ref not in refs:
            refs.append(ref)
    return refs


def parse_markdown(raw: str) -> ParsedDocument:
    meta, body = split_front_matter(raw)
    title = str(meta.get("title") or "Untitled")
    root = Section(level=0, title=title, anchor="", path=[])
    stack: list[Section] = [root]

    buffer: list[str] = []
    buffer_kind: BlockKind | None = None
    in_code = False

    def flush() -> None:
        nonlocal buffer, buffer_kind
        if buffer and buffer_kind is not None:
            text = "\n".join(buffer).strip("\n")
            if text.strip():
                stack[-1].blocks.append(Block(kind=buffer_kind, text=text))
        buffer, buffer_kind = [], None

    for line in body.splitlines():
        stripped = line.strip()

        if in_code:
            buffer.append(line)
            if stripped.startswith("```"):
                in_code = False
                flush()
            continue
        if stripped.startswith("```"):
            flush()
            in_code = True
            buffer, buffer_kind = [line], "code"
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush()
            level = len(heading.group(1))
            heading_title = heading.group(2).strip()
            if level == 1 and stack[-1] is root and not root.children and not root.blocks:
                # The H1 is the document title; keep sections under the root.
                continue
            while len(stack) > 1 and stack[-1].level >= level:
                stack.pop()
            parent = stack[-1]
            section = Section(
                level=level,
                title=heading_title,
                anchor=slugify(heading_title),
                path=[*parent.path, heading_title],
            )
            parent.children.append(section)
            stack.append(section)
            continue

        if not stripped:
            if buffer_kind in ("paragraph", "table"):
                flush()
            elif buffer_kind == "list":
                buffer.append("")
            continue

        if stripped.startswith("|"):
            kind: BlockKind = "table"
        elif _LIST_RE.match(line) or (buffer_kind == "list" and line.startswith((" ", "\t"))):
            kind = "list"
        else:
            kind = "paragraph"

        if buffer_kind is not None and buffer_kind != kind:
            flush()
        buffer_kind = kind
        buffer.append(line)

    flush()
    return ParsedDocument(meta=meta, title=title, root=root)
