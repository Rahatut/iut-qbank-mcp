"""Semantic chunking engine. DEV-019, DEV-020, DEV-021.

Splits extracted document text into indexable chunks.

For question papers the chunker preserves:
  - page boundaries
  - question numbers (Q1, 1., 1(a), etc.)
  - sub-question structure

Architecture:
  Document
   ├── generic chunks  (ChunkData)
   └── structured questions (QuestionData) — DEV-021
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from qbank.processing.interfaces import ChunkData, Chunker, ExtractedDocument

# ── Question-paper patterns ───────────────────────────────────────────────────

# Matches: "1.", "Q1", "Q.1", "Question 1", "1(a)", "1a."
_QUESTION_START = re.compile(
    r"^(?:(?:Q(?:uestion)?\.?\s*)|(?=\d))(\d{1,2})\s*[\.\):]",
    re.IGNORECASE | re.MULTILINE,
)

# Sub-question: "(a)", "a)", "a."
_SUB_QUESTION = re.compile(
    r"^\s*\(([a-zA-Z])\)|\b([a-zA-Z])\)\s",
    re.MULTILINE,
)

# Maximum characters per chunk before forced split
_MAX_CHUNK_CHARS = 1500
# Minimum meaningful chunk length
_MIN_CHUNK_CHARS = 30
# Target token count (rough: 1 token ≈ 4 chars)
_CHARS_PER_TOKEN = 4


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // _CHARS_PER_TOKEN)


@dataclass
class QuestionData:
    """A structured question identified by the question-paper chunker. DEV-021.

    Exists alongside generic ChunkData. The architecture supports:
      Document
       ├── generic chunks
       └── structured questions
    """
    question_number: str          # e.g. "1", "3(a)", "Q4"
    text: str
    page: int | None
    chunk_index: int
    sub_questions: list[str] = field(default_factory=list)


class QuestionPaperChunker(Chunker):
    """Chunker optimised for academic question papers. DEV-019.

    Strategy:
      1. Split text at question boundaries (detected by regex).
      2. If a question is too long, split further at sub-question boundaries.
      3. Any text not matching a question marker becomes a generic chunk.
      4. Preserves page number from the source PageText.

    Falls back to fixed-size chunking for non-question-paper documents.
    """

    def __init__(
        self,
        max_chunk_chars: int = _MAX_CHUNK_CHARS,
        min_chunk_chars: int = _MIN_CHUNK_CHARS,
    ) -> None:
        self._max = max_chunk_chars
        self._min = min_chunk_chars

    # ── Public interface ──────────────────────────────────────────────────────

    def chunk(self, extracted: ExtractedDocument) -> list[ChunkData]:
        """Split the extracted document into chunks preserving question structure."""
        all_chunks: list[ChunkData] = []

        for page_text in extracted.pages:
            if not page_text.text.strip():
                continue

            page_chunks = self._chunk_page(
                text=page_text.text,
                page_number=page_text.page_number,
                start_index=len(all_chunks),
            )
            all_chunks.extend(page_chunks)

        return all_chunks

    def chunk_with_questions(
        self, extracted: ExtractedDocument
    ) -> tuple[list[ChunkData], list[QuestionData]]:
        """Return both generic chunks and structured questions. DEV-021.

        Callers that only need chunks should use chunk().
        Callers that need question-level structure use this method.
        """
        all_chunks: list[ChunkData] = []
        all_questions: list[QuestionData] = []

        for page_text in extracted.pages:
            if not page_text.text.strip():
                continue

            chunks, questions = self._chunk_page_with_questions(
                text=page_text.text,
                page_number=page_text.page_number,
                start_index=len(all_chunks),
            )
            all_chunks.extend(chunks)
            all_questions.extend(questions)

        return all_chunks, all_questions

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _chunk_page(
        self, text: str, page_number: int, start_index: int
    ) -> list[ChunkData]:
        chunks, _ = self._chunk_page_with_questions(text, page_number, start_index)
        return chunks

    def _chunk_page_with_questions(
        self,
        text: str,
        page_number: int,
        start_index: int,
    ) -> tuple[list[ChunkData], list[QuestionData]]:
        """Detect question boundaries and produce chunks + questions for one page."""
        chunks: list[ChunkData] = []
        questions: list[QuestionData] = []

        # Find all question start positions
        matches = list(_QUESTION_START.finditer(text))

        if not matches:
            # No question structure detected — generic chunking
            for i, chunk_text in enumerate(self._fixed_split(text)):
                if len(chunk_text.strip()) < self._min:
                    continue
                chunks.append(
                    ChunkData(
                        text=chunk_text.strip(),
                        page=page_number,
                        chunk_index=start_index + i,
                        token_count=_estimate_tokens(chunk_text),
                        question_number=None,
                    )
                )
            return chunks, questions

        # Extract preamble (text before first question)
        preamble = text[: matches[0].start()].strip()
        if len(preamble) >= self._min:
            chunks.append(
                ChunkData(
                    text=preamble,
                    page=page_number,
                    chunk_index=start_index + len(chunks),
                    token_count=_estimate_tokens(preamble),
                    question_number=None,
                )
            )

        # Process each question block
        for i, match in enumerate(matches):
            q_num = match.group(1)
            block_start = match.start()
            block_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            block_text = text[block_start:block_end].strip()

            question_chunks = self._split_question_block(
                text=block_text,
                question_number=q_num,
                page_number=page_number,
                start_index=start_index + len(chunks),
            )
            chunks.extend(question_chunks)

            # Build structured question (DEV-021)
            sub_q_matches = _SUB_QUESTION.findall(block_text)
            sub_labels = [m[0] or m[1] for m in sub_q_matches]
            questions.append(
                QuestionData(
                    question_number=q_num,
                    text=block_text,
                    page=page_number,
                    chunk_index=start_index + len(chunks) - len(question_chunks),
                    sub_questions=sub_labels,
                )
            )

        return chunks, questions

    def _split_question_block(
        self,
        text: str,
        question_number: str,
        page_number: int,
        start_index: int,
    ) -> list[ChunkData]:
        """Split a single question block. If long, split at sub-questions."""
        if len(text) <= self._max:
            return [
                ChunkData(
                    text=text,
                    page=page_number,
                    chunk_index=start_index,
                    token_count=_estimate_tokens(text),
                    question_number=question_number,
                )
            ]

        # Try splitting at sub-question boundaries
        sub_chunks = self._split_at_sub_questions(text)
        if len(sub_chunks) > 1:
            result = []
            for j, sub_text in enumerate(sub_chunks):
                if len(sub_text.strip()) < self._min:
                    continue
                # Detect sub-question label from text
                sub_match = _SUB_QUESTION.match(sub_text.strip())
                sub_label = sub_match.group(1) or sub_match.group(2) if sub_match else None
                q_label = f"{question_number}({sub_label})" if sub_label else question_number
                result.append(
                    ChunkData(
                        text=sub_text.strip(),
                        page=page_number,
                        chunk_index=start_index + j,
                        token_count=_estimate_tokens(sub_text),
                        question_number=q_label,
                    )
                )
            return result

        # Fall back to fixed-size splitting
        fixed = self._fixed_split(text)
        return [
            ChunkData(
                text=part.strip(),
                page=page_number,
                chunk_index=start_index + k,
                token_count=_estimate_tokens(part),
                question_number=question_number,
            )
            for k, part in enumerate(fixed)
            if len(part.strip()) >= self._min
        ]

    def _split_at_sub_questions(self, text: str) -> list[str]:
        """Split text at sub-question markers, returning segments."""
        positions = [m.start() for m in _SUB_QUESTION.finditer(text)]
        if not positions:
            return [text]

        segments = []
        prev = 0
        for pos in positions:
            seg = text[prev:pos]
            if seg.strip():
                segments.append(seg)
            prev = pos
        segments.append(text[prev:])
        return [s for s in segments if s.strip()]

    def _fixed_split(self, text: str) -> list[str]:
        """Split text into fixed-size chunks by character count."""
        chunks = []
        start = 0
        while start < len(text):
            end = start + self._max
            if end < len(text):
                # Try to break at sentence boundary
                boundary = text.rfind("\n", start, end)
                if boundary == -1 or boundary <= start:
                    boundary = text.rfind(". ", start, end)
                if boundary > start:
                    end = boundary + 1
            chunks.append(text[start:end])
            start = end
        return chunks
