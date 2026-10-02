"""Unit tests for MCP response size budgeting.

Context overflow is the failure this guards: an unbounded result list gets
inserted verbatim into the client context and the host refuses to render it.
"""

import pytest

from qbank.application.response_budget import (
    MAX_CHARS_PER_RESULT,
    MAX_CHARS_SINGLE,
    MAX_CHARS_TOTAL,
    ResultBudget,
    empty_notice,
    result_to_dict,
    single_result_to_dict,
    truncate_text,
)
from qbank.infrastructure.vector.qdrant_store import SearchResult


def _result(text: str) -> SearchResult:
    return SearchResult(
        id="chunk-1",
        score=0.87,
        document_id="doc-1",
        document_title="CSE question papers",
        document_url="https://example.test/paper.pdf",
        text=text,
        course_code="SWE4201",
        department="CSE",
        document_type="question_paper",
        page=3,
        question_number="4(a)",
        year=2019,
        semester="Summer",
    )


@pytest.mark.unit
class TestTruncateText:
    def test_short_text_untouched(self) -> None:
        out, truncated = truncate_text("short text", 100)
        assert out == "short text"
        assert truncated is False

    def test_long_text_truncated_with_count(self) -> None:
        text = "word " * 500
        out, truncated = truncate_text(text, 200)
        assert truncated is True
        assert len(out) < len(text)
        assert "truncated" in out
        assert str(len(text)) in out

    def test_truncation_respects_limit(self) -> None:
        out, _ = truncate_text("x" * 5000, 300)
        # Marker adds a small suffix, but the body stays bounded.
        assert len(out) < 500

    def test_cuts_on_word_boundary(self) -> None:
        text = "alpha beta gamma delta epsilon " * 40
        out, _ = truncate_text(text, 200)
        body = out.split("...")[0]
        assert not body.rstrip().endswith("alph")


@pytest.mark.unit
class TestResultBudget:
    def test_budget_is_shared_across_results(self) -> None:
        budget = ResultBudget()
        first, t1 = budget.take("y" * 3000)
        assert t1 is True
        assert len(first) <= MAX_CHARS_PER_RESULT + 60

        _, t2 = budget.take("y" * 3000)
        assert t2 is True
        assert budget.used > MAX_CHARS_PER_RESULT

    def test_budget_exhausts_and_empties_later_results(self) -> None:
        budget = ResultBudget(total=100, per_result=50)
        for _ in range(10):
            budget.take("z" * 200)
        text, truncated = budget.take("z" * 200)
        assert text == ""
        assert truncated is True

    def test_take_counts_marker_length(self) -> None:
        budget = ResultBudget()
        out, _ = budget.take("q" * 5000)
        assert budget.used == len(out)


@pytest.mark.unit
class TestResultSerialisation:
    def test_result_keeps_provenance_and_flags_truncation(self) -> None:
        payload = result_to_dict(_result("w" * 4000), ResultBudget())
        assert payload["truncated"] is True
        assert payload["original_chars"] == 4000
        assert payload["source"]["document_id"] == "doc-1"
        assert payload["source"]["title"] == "CSE question papers"
        assert payload["course_code"] == "SWE4201"

    def test_result_omits_absent_metadata(self) -> None:
        bare = SearchResult(
            id="chunk-2",
            score=0.1,
            document_id="doc-2",
            document_title="Untitled",
            document_url="",
            text="body",
            course_code=None,
            year=None,
            semester=None,
            page=None,
        )
        payload = result_to_dict(bare, ResultBudget())
        for absent in ("course_code", "year", "semester", "page", "question_number"):
            assert absent not in payload
        assert payload["id"] == "chunk-2"

    def test_single_result_uses_larger_budget(self) -> None:
        payload = single_result_to_dict(_result("w" * (MAX_CHARS_PER_RESULT + 200)))
        assert payload["truncated"] is False
        assert len(payload["text"]) == MAX_CHARS_PER_RESULT + 200

    def test_single_result_under_single_cap_is_complete(self) -> None:
        payload = single_result_to_dict(_result("w" * 100))
        assert payload["truncated"] is False
        assert payload["text"] == "w" * 100


@pytest.mark.unit
class TestTotalBudget:
    def test_defaults_are_documented_limits(self) -> None:
        assert MAX_CHARS_PER_RESULT < MAX_CHARS_TOTAL
        assert MAX_CHARS_SINGLE > MAX_CHARS_PER_RESULT


@pytest.mark.unit
class TestEmptyNotice:
    def test_notice_is_actionable(self) -> None:
        notice = empty_notice("No IUT course matched 'CSE3200'. Try a department filter.")
        assert isinstance(notice, list)
        assert len(notice) == 1
        assert notice[0]["results"] == []
        assert "cse3200" in notice[0]["notice"].lower()

    def test_notice_always_reports_empty_results(self) -> None:
        assert empty_notice("anything")[0]["results"] == []
