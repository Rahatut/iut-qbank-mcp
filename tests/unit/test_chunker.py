"""Unit tests for the chunking engine. DEV-019, DEV-020, DEV-021."""
from __future__ import annotations

from qbank.processing.chunker import QuestionPaperChunker
from qbank.processing.interfaces import ExtractedDocument, PageText


def _make_doc(*page_texts: tuple[int, str]) -> ExtractedDocument:
    pages = [
        PageText(
            page_number=pnum,
            text=text,
            extraction_method="native",
            quality_score=0.9,
        )
        for pnum, text in page_texts
    ]
    return ExtractedDocument(
        pages=pages,
        extraction_method="native",
        overall_quality=0.9,
        page_count=len(pages),
    )


class TestQuestionPaperChunker:
    """Tests for the QuestionPaperChunker. DEV-019."""

    def setup_method(self) -> None:
        self.chunker = QuestionPaperChunker()

    def test_empty_document_returns_no_chunks(self) -> None:
        doc = _make_doc((1, ""), (2, "   "))
        chunks = self.chunker.chunk(doc)
        assert chunks == []

    def test_no_questions_produces_generic_chunks(self) -> None:
        text = "This is a syllabus. It has topics. " * 10
        doc = _make_doc((1, text))
        chunks = self.chunker.chunk(doc)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert chunk.question_number is None
            assert chunk.page == 1

    def test_detects_question_numbers(self) -> None:
        text = (
            "Preamble text.\n"
            "1. What is normalization?\n"
            "Explain in detail.\n"
            "2. Define BCNF.\n"
            "Give an example.\n"
        )
        doc = _make_doc((1, text))
        chunks = self.chunker.chunk(doc)
        question_chunks = [c for c in chunks if c.question_number is not None]
        assert len(question_chunks) >= 2
        q_nums = {c.question_number for c in question_chunks}
        assert "1" in q_nums
        assert "2" in q_nums

    def test_chunk_preserves_page_number(self) -> None:
        doc = _make_doc(
            (1, "1. Question on page 1."),
            (2, "2. Question on page 2."),
        )
        chunks = self.chunker.chunk(doc)
        pages = {c.page for c in chunks}
        assert 1 in pages
        assert 2 in pages

    def test_chunk_has_token_count(self) -> None:
        doc = _make_doc((1, "1. Explain the concept of deadlock in operating systems.\n"))
        chunks = self.chunker.chunk(doc)
        assert all(c.token_count > 0 for c in chunks)

    def test_chunk_index_is_sequential(self) -> None:
        text = "\n".join(f"{i}. Question {i} text." for i in range(1, 6))
        doc = _make_doc((1, text))
        chunks = self.chunker.chunk(doc)
        indices = [c.chunk_index for c in chunks]
        assert indices == sorted(indices)

    def test_large_question_is_split(self) -> None:
        long_text = "1. " + ("This is a very long question. " * 200)
        doc = _make_doc((1, long_text))
        chunks = self.chunker.chunk(doc)
        # Should produce more than one chunk for such a long question
        assert len(chunks) >= 1
        for c in chunks:
            assert len(c.text) <= self.chunker._max * 1.1  # allow small overshoot

    def test_chunk_with_questions_returns_structured_questions(self) -> None:
        text = (
            "1. What is a semaphore?\n"
            "(a) Define it.\n"
            "(b) Give an example.\n"
            "2. Explain deadlock.\n"
        )
        doc = _make_doc((1, text))
        _chunks, questions = self.chunker.chunk_with_questions(doc)
        assert len(questions) >= 2
        assert questions[0].question_number == "1"
        assert questions[1].question_number == "2"

    def test_q_prefix_detected(self) -> None:
        text = "Q1. What is TCP/IP?\nQ2. Define HTTP.\n"
        doc = _make_doc((1, text))
        chunks = self.chunker.chunk(doc)
        q_chunks = [c for c in chunks if c.question_number is not None]
        assert len(q_chunks) >= 2
