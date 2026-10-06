"""Reference problem 2: real chunks (not '.'-split sentences), top-k retrieval, a persistent index."""
import pytest

from studybuddy_rag.index import HybridIndex
from studybuddy_rag.ingest import Document, Section, chunk_document, parse_markdown
from studybuddy_rag.providers.embeddings import HashingEmbedder
from studybuddy_rag.subjects import Subject
from studybuddy_rag.text import split_sentences


def test_sentence_split_keeps_decimals_and_abbreviations():
    text = "Pi is about 3.14 in value. See e.g. Fig. 2 for details. Dr. Lee agreed! Is 0.5 half? Yes."
    assert split_sentences(text) == [
        "Pi is about 3.14 in value.",
        "See e.g. Fig. 2 for details.",
        "Dr. Lee agreed!",
        "Is 0.5 half?",
        "Yes.",
    ]


def test_chunks_respect_size_overlap_and_sections():
    body = " ".join(f"Sentence number {i} talks about fractions and decimals." for i in range(30))
    doc = Document("d", "Doc", Subject.MATHEMATICS, (Section("A", body), Section("B", "Short section.")))
    chunks = chunk_document(doc, max_words=40, overlap_sentences=1)
    assert len(chunks) > 3
    assert all(len(c.text.split()) <= 40 for c in chunks if c.section == "A")
    a_chunks = [c for c in chunks if c.section == "A"]
    # consecutive chunks share exactly the overlapping sentence
    last_of_first = split_sentences(a_chunks[0].text)[-1]
    assert split_sentences(a_chunks[1].text)[0] == last_of_first
    assert chunks[-1].section == "B" and chunks[-1].text == "Short section."
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_markdown_header_is_validated():
    with pytest.raises(ValueError, match="subject"):
        parse_markdown("# Title\nNo header here.", source_id="x")
    with pytest.raises(ValueError):
        parse_markdown("---\nsubject: general\n---\ntext", source_id="x")


def test_retrieval_returns_several_chunks_with_subject_filter(index):
    hits = index.search("How does photosynthesis use light and chlorophyll?", k=3, subject=Subject.SCIENCE)
    assert 1 < len(hits) <= 3
    assert hits[0].chunk.section == "Photosynthesis"
    assert all(h.chunk.subject is Subject.SCIENCE for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_subject_filter_excludes_other_subjects(index):
    hits = index.search("photosynthesis chlorophyll", k=5, subject=Subject.ARTS, min_score=0.2)
    assert all(h.chunk.subject is Subject.ARTS for h in hits)


def test_index_round_trips_through_sqlite(tmp_path, index, embedder):
    path = tmp_path / "idx.db"
    index.save(path)
    loaded = HybridIndex.load(path, embedder)
    assert len(loaded) == len(index)
    q = "What do the angles of a triangle add up to?"
    assert [h.chunk.chunk_id for h in loaded.search(q)] == [h.chunk.chunk_id for h in index.search(q)]


def test_index_refuses_a_different_embedder(tmp_path, index):
    path = tmp_path / "idx.db"
    index.save(path)
    with pytest.raises(ValueError, match="rebuild"):
        HybridIndex.load(path, HashingEmbedder(dim=256))


def test_hashing_embedder_is_deterministic_and_normalised(embedder):
    a, b = embedder.embed(["fractions and decimals", "fractions and decimals"])
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9
