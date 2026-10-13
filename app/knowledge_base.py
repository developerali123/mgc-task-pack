"""
Local Markdown knowledge base for MGC Aurora Heights documents.

Chunks each file by Markdown ## section headings. Every chunk keeps:
  - document title (first # heading)
  - section heading
  - source filename
  - body text

No external APIs. Citations always come from these stored fields.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"

KNOWN_FILES = (
    "01_mgc_aurora_heights_brochure.md",
    "02_price_list_payment_plan.md",
    "03_booking_policy_faq.md",
)


@dataclass(frozen=True)
class SourceRef:
    filename: str
    document_title: str
    section: str
    excerpt: str = ""

    def citation(self) -> str:
        return f"{self.document_title} — § {self.section} ({self.filename})"


@dataclass
class DocumentChunk:
    filename: str
    document_title: str
    section: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.section}\n{self.body}".strip()

    def to_ref(self, excerpt: str = "") -> SourceRef:
        snippet = excerpt or _first_useful_line(self.body)
        return SourceRef(
            filename=self.filename,
            document_title=self.document_title,
            section=self.section,
            excerpt=snippet,
        )


def _first_useful_line(body: str, max_len: int = 180) -> str:
    for line in body.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if cleaned and not cleaned.startswith("|---") and cleaned != "|":
            if len(cleaned) > max_len:
                return cleaned[: max_len - 1] + "…"
            return cleaned
    return body.strip()[:max_len]


def _parse_markdown(path: Path) -> list[DocumentChunk]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()

    title = path.stem
    for line in lines:
        if line.startswith("# "):
            title = line[2:].strip()
            break

    chunks: list[DocumentChunk] = []
    current_section = "Document header"
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body or current_section != "Document header":
            chunks.append(
                DocumentChunk(
                    filename=path.name,
                    document_title=title,
                    section=current_section,
                    body=body,
                )
            )

    for line in lines:
        if line.startswith("## "):
            flush()
            current_section = line[3:].strip()
            buf = []
        else:
            # Skip the top-level title line from body noise
            if line.startswith("# ") and not chunks and not buf:
                continue
            buf.append(line)
    flush()
    return chunks


class KnowledgeBase:
    """In-memory section index over the three assessment documents."""

    def __init__(self, docs_dir: Optional[Path] = None) -> None:
        self.docs_dir = Path(docs_dir) if docs_dir else DOCS_DIR
        self.chunks: list[DocumentChunk] = []
        self._load()

    def _load(self) -> None:
        self.chunks.clear()
        for name in KNOWN_FILES:
            path = self.docs_dir / name
            if not path.exists():
                raise FileNotFoundError(f"Missing source document: {path}")
            self.chunks.extend(_parse_markdown(path))

    def get_section(self, filename: str, section: str) -> DocumentChunk:
        needle = section.strip().lower()
        for chunk in self.chunks:
            if chunk.filename == filename and chunk.section.lower() == needle:
                return chunk
        raise KeyError(f"Section {section!r} not found in {filename}")

    def find_sections(
        self,
        *,
        filename: Optional[str] = None,
        section_contains: Optional[str] = None,
        body_contains: Optional[str] = None,
    ) -> list[DocumentChunk]:
        results = self.chunks
        if filename:
            results = [c for c in results if c.filename == filename]
        if section_contains:
            s = section_contains.lower()
            results = [c for c in results if s in c.section.lower()]
        if body_contains:
            b = body_contains.lower()
            results = [c for c in results if b in c.body.lower()]
        return results

    def search(self, query: str, limit: int = 5) -> list[DocumentChunk]:
        """Simple keyword overlap ranking — deterministic, no LLM."""
        tokens = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2}
        if not tokens:
            return []

        scored: list[tuple[int, DocumentChunk]] = []
        for chunk in self.chunks:
            hay = chunk.text.lower()
            score = sum(1 for t in tokens if t in hay)
            # Prefer section-title hits
            score += sum(2 for t in tokens if t in chunk.section.lower())
            if score:
                scored.append((score, chunk))
        scored.sort(key=lambda x: (-x[0], x[1].filename, x[1].section))
        return [c for _, c in scored[:limit]]


def load_knowledge_base(docs_dir: Optional[Path] = None) -> KnowledgeBase:
    return KnowledgeBase(docs_dir=docs_dir)
