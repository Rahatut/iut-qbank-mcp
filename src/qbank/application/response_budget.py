"""Response size budgeting for MCP tool output.

MCP tool results are inserted verbatim into the client's context window. A
semantic search returning 50 chunks of 1500 characters each is ~75k characters
— enough to blow the model's usable context and cause the host to refuse or
truncate the response.

This module enforces a character budget per response:
  - per-result text is capped at MAX_CHARS_PER_RESULT
  - the total across all results is capped at MAX_CHARS_TOTAL
  - truncation is always explicit, never silent

Clients receive the same structure with a `truncated` flag and a `total_chars`
count, so the model knows to call `get_question` for full content rather than
guessing what was cut.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from qbank.infrastructure.vector.qdrant_store import SearchResult

# Max characters of chunk text per result in a list response.
MAX_CHARS_PER_RESULT = 1200

# Max characters of chunk text summed across every result in one response.
MAX_CHARS_TOTAL = 12000

# Max characters for a single-result response (get_question), which is the
# full content of one chunk and has no siblings competing for budget.
MAX_CHARS_SINGLE = 8000


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Return (text, truncated). Cuts on a word boundary when one is nearby."""
    if len(text) <= max_chars:
        return text, False

    cut = text[:max_chars]
    # Prefer a word boundary in the last 15% of the budget.
    floor = int(max_chars * 0.85)
    space = cut.rfind(" ", floor)
    if space > 0:
        cut = cut[:space]

    return f"{cut.rstrip()}... [truncated, {len(text)} chars total]", True


@dataclass
class ResultBudget:
    """Tracks the remaining character budget for one tool response."""

    total: int = MAX_CHARS_TOTAL
    per_result: int = MAX_CHARS_PER_RESULT
    used: int = 0

    def take(self, text: str) -> tuple[str, bool]:
        """Spend from the remaining budget for one result's text."""
        remaining = max(0, self.total - self.used)
        capped = min(self.per_result, remaining)
        if capped <= 0:
            return "", len(text) > 0

        out, truncated = truncate_text(text, capped)
        self.used += len(out)
        return out, truncated or len(text) > len(out)


def result_to_dict(r: SearchResult, budget: ResultBudget) -> dict[str, Any]:
    """Serialise one SearchResult within the given budget.

    Field semantics:
      text              truncated chunk text
      truncated         True when text was cut (caller should call get_question)
      original_chars    length of the untruncated text
    """
    text, truncated = budget.take(r.text)

    payload: dict[str, Any] = {
        "id": r.id,
        "score": round(r.score, 4),
        "text": text,
        "truncated": truncated,
        "original_chars": len(r.text),
    }

    # Only include populated metadata — nulls waste context for no benefit.
    optional = {
        "course_code": r.course_code,
        "year": r.year,
        "semester": r.semester,
        "page": r.page,
        "question_number": r.question_number,
        "department": r.department,
        "document_type": r.document_type,
    }
    payload.update({k: v for k, v in optional.items() if v is not None})

    payload["source"] = {
        "document_id": r.document_id,
        "title": r.document_title,
        "url": r.document_url,
    }
    return payload


def single_result_to_dict(r: SearchResult) -> dict[str, Any]:
    """Serialise a lone result (get_question) with the full-content budget."""
    text, truncated = truncate_text(r.text, MAX_CHARS_SINGLE)

    payload: dict[str, Any] = {
        "id": r.id,
        "score": round(r.score, 4),
        "text": text,
        "truncated": truncated,
        "original_chars": len(r.text),
    }
    optional = {
        "course_code": r.course_code,
        "year": r.year,
        "semester": r.semester,
        "page": r.page,
        "question_number": r.question_number,
        "department": r.department,
        "document_type": r.document_type,
    }
    payload.update({k: v for k, v in optional.items() if v is not None})
    payload["source"] = {
        "document_id": r.document_id,
        "title": r.document_title,
        "url": r.document_url,
    }
    return payload


def empty_notice(hint: str) -> list[dict[str, Any]]:
    """Return an empty result list with an actionable explanation.

    A bare [] gives the model nothing to work with; it cannot tell an index
    gap apart from a bad filter and will retry blindly.
    """
    return [{"notice": hint, "results": []}]


def results_payload(
    results: list[SearchResult],
    *,
    per_result: int = MAX_CHARS_PER_RESULT,
    total: int = MAX_CHARS_TOTAL,
) -> list[dict[str, Any]]:
    """Serialise a list of results under a shared character budget."""
    budget = ResultBudget(total=total, per_result=per_result)
    return [result_to_dict(r, budget) for r in results]
