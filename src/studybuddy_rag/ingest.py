"""Offline ingestion: documents -> sections -> overlapping, sentence-aligned chunks with metadata.

The knowledge base is a folder of Markdown files (one per source) whose first lines carry a
small header::

    ---
    title: Fractions and decimals
    subject: mathematics
    license: CC BY 4.0 (written for this project)
    ---
    # Section heading
    Paragraph text ...

PDFs are supported through the optional ``pdf`` extra (PyMuPDF); every page keeps its number so
answers can cite it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .subjects import Subject
from .text import split_sentences

_HEADER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_HEADING_RE = re.compile(r"^#{1,6}\s+(.*)$")


@dataclass(frozen=True)
class Section:
    heading: str
    text: str
    page: int | None = None


@dataclass(frozen=True)
class Document:
    source_id: str
    title: str
    subject: Subject
    sections: tuple[Section, ...]
    license: str = ""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source_id: str
    title: str
    subject: Subject
    section: str
    text: str
    page: int | None = None
    position: int = 0
    metadata: dict = field(default_factory=dict, compare=False, hash=False)

    def citation_label(self) -> str:
        where = f", p. {self.page}" if self.page is not None else ""
        return f"{self.title} - {self.section}{where}"


def parse_markdown(text: str, *, source_id: str) -> Document:
    header: dict[str, str] = {}
    m = _HEADER_RE.match(text)
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                header[k.strip().lower()] = v.strip()
        text = text[m.end():]
    if "subject" not in header:
        raise ValueError(f"{source_id}: missing 'subject' in the document header")
    subject = Subject.parse(header["subject"])
    if not subject.has_corpus:
        raise ValueError(f"{source_id}: documents must belong to a corpus subject, not {subject.value!r}")

    sections: list[Section] = []
    heading, buf = "Introduction", []
    for line in text.splitlines():
        hm = _HEADING_RE.match(line.strip())
        if hm:
            if any(s.strip() for s in buf):
                sections.append(Section(heading, " ".join(s.strip() for s in buf if s.strip())))
            heading, buf = hm.group(1).strip(), []
        else:
            buf.append(line)
    if any(s.strip() for s in buf):
        sections.append(Section(heading, " ".join(s.strip() for s in buf if s.strip())))
    return Document(
        source_id=source_id,
        title=header.get("title", source_id),
        subject=subject,
        sections=tuple(sections),
        license=header.get("license", ""),
    )


def parse_pdf(path: Path, *, subject: Subject, title: str | None = None) -> Document:  # pragma: no cover
    """Parse a PDF page by page (needs ``pip install studybuddy-rag[pdf]``)."""
    try:
        import pymupdf  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("PDF ingestion needs the 'pdf' extra: pip install 'studybuddy-rag[pdf]'") from exc
    sections = []
    with pymupdf.open(path) as doc:
        for number, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()
            if text:
                sections.append(Section(heading=f"Page {number}", text=text, page=number))
    return Document(path.stem, title or path.stem, subject, tuple(sections))


def load_corpus(directory: str | Path) -> list[Document]:
    root = Path(directory)
    if not root.is_dir():
        raise FileNotFoundError(f"corpus directory not found: {root}")
    docs = [parse_markdown(p.read_text(encoding="utf-8"), source_id=p.stem) for p in sorted(root.glob("*.md"))]
    if not docs:
        raise ValueError(f"no .md documents in {root}")
    return docs


def chunk_document(doc: Document, *, max_words: int = 120, overlap_sentences: int = 1) -> list[Chunk]:
    """Pack whole sentences into chunks of at most ~``max_words`` words, never crossing a section.

    Consecutive chunks of a section share ``overlap_sentences`` sentences so an answer that spans a
    boundary is still retrievable. A single sentence longer than ``max_words`` becomes its own chunk.
    """
    if max_words < 10:
        raise ValueError("max_words must be >= 10")
    if overlap_sentences < 0:
        raise ValueError("overlap_sentences must be >= 0")
    chunks: list[Chunk] = []
    position = 0
    for section in doc.sections:
        sentences = split_sentences(section.text)
        i = 0
        while i < len(sentences):
            window: list[str] = []
            words = 0
            j = i
            while j < len(sentences):
                n = len(sentences[j].split())
                if window and words + n > max_words:
                    break
                window.append(sentences[j])
                words += n
                j += 1
            text = " ".join(window)
            digest = hashlib.sha1(f"{doc.source_id}|{section.heading}|{position}|{text}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=f"{doc.source_id}:{position}:{digest[:8]}",
                    source_id=doc.source_id,
                    title=doc.title,
                    subject=doc.subject,
                    section=section.heading,
                    text=text,
                    page=section.page,
                    position=position,
                )
            )
            position += 1
            if j >= len(sentences):
                break
            i = max(j - overlap_sentences, i + 1)
    return chunks


def chunk_corpus(docs: list[Document], **kwargs) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_document(doc, **kwargs))
    return out
