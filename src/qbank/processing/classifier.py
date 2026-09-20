"""Document type classifier. DEV-018.

Rule-based implementation — replaceable with an ML/LLM classifier
without modifying the ingestion pipeline (DEV-050).
"""
from __future__ import annotations

import re

from qbank.processing.interfaces import Classifier

_QUESTION_PAPER_SIGNALS = re.compile(
    r"\b(question|exam|final|midterm|quiz|answer all|marks|time:?\s*\d|part[\s\-]?[a-c])\b",
    re.IGNORECASE,
)
_SYLLABUS_SIGNALS = re.compile(
    r"\b(syllabus|course outline|learning outcomes?|credit hours?|prerequisites?)\b",
    re.IGNORECASE,
)
_LECTURE_SIGNALS = re.compile(
    r"\b(lecture|slide|chapter|topic:)\b", re.IGNORECASE
)
_TUTORIAL_SIGNALS = re.compile(
    r"\b(tutorial|lab manual|experiment|worksheet)\b", re.IGNORECASE
)
_ASSIGNMENT_SIGNALS = re.compile(
    r"\b(assignment|homework|due date|submission)\b", re.IGNORECASE
)


class RuleBasedClassifier(Classifier):
    """Classifies documents using filename and text pattern matching. DEV-018."""

    def classify(
        self,
        filename: str | None,
        text_sample: str | None,
        repository_metadata: dict | None = None,  # type: ignore[type-arg]
    ) -> tuple[str, float]:
        """Return (document_type, confidence)."""
        combined = " ".join(filter(None, [filename, text_sample]))

        scores: dict[str, float] = {
            "question_paper": 0.0,
            "syllabus": 0.0,
            "lecture_material": 0.0,
            "tutorial": 0.0,
            "assignment": 0.0,
            "other": 0.1,  # default fallback
        }

        if _QUESTION_PAPER_SIGNALS.search(combined):
            matches = len(_QUESTION_PAPER_SIGNALS.findall(combined))
            scores["question_paper"] = min(0.95, 0.5 + matches * 0.1)

        if _SYLLABUS_SIGNALS.search(combined):
            scores["syllabus"] = 0.85

        if _LECTURE_SIGNALS.search(combined):
            scores["lecture_material"] = 0.8

        if _TUTORIAL_SIGNALS.search(combined):
            scores["tutorial"] = 0.8

        if _ASSIGNMENT_SIGNALS.search(combined):
            scores["assignment"] = 0.8

        # Filename hints take priority
        if filename:
            fl = filename.lower()
            if any(kw in fl for kw in ["question", "exam", "final", "mid", "quiz"]):
                scores["question_paper"] = max(scores["question_paper"], 0.8)
            if "syllabus" in fl:
                scores["syllabus"] = max(scores["syllabus"], 0.9)
            if "lecture" in fl or "slide" in fl:
                scores["lecture_material"] = max(scores["lecture_material"], 0.85)

        best_type = max(scores, key=lambda k: scores[k])
        return best_type, round(scores[best_type], 3)
