"""Metadata normalization. DEV-017.

Layered extraction:
    Repository metadata → directory/path → filename →
    PDF metadata → extracted text → classifier

Does not require perfect metadata before indexing.
Retains confidence values for every field.
"""

from __future__ import annotations

import re

from qbank.domain.course_normalization import normalize_course_code
from qbank.processing.interfaces import MetadataExtractor, NormalizedMetadata

# ── Patterns ──────────────────────────────────────────────────────────────────
_YEAR_PATTERN = re.compile(r"\b(20\d{2})\b")
_SEMESTER_PATTERNS = {
    "Spring": re.compile(r"\b(spring)\b", re.IGNORECASE),
    "Summer": re.compile(r"\b(summer)\b", re.IGNORECASE),
    "Fall": re.compile(r"\b(fall|autumn)\b", re.IGNORECASE),
    "Winter": re.compile(r"\b(winter)\b", re.IGNORECASE),
}
_EXAM_TYPE_PATTERNS = {
    "final": re.compile(r"\b(final|end[\s\-]?term|end[\s\-]?semester)\b", re.IGNORECASE),
    "midterm": re.compile(r"\b(mid[\s\-]?term|mid[\s\-]?semester)\b", re.IGNORECASE),
    "quiz": re.compile(r"\b(quiz|class[\s\-]?test)\b", re.IGNORECASE),
}
_DEPT_PATTERNS = {
    "CSE": re.compile(r"\bCSE\b"),
    "EEE": re.compile(r"\bEEE\b"),
    "MCE": re.compile(r"\bMCE\b"),
    "CE": re.compile(r"\bCE\b"),
    "TVE": re.compile(r"\bTVE\b"),
    "BTM": re.compile(r"\bBTM\b"),
}
_COURSE_CODE_PATTERN = re.compile(r"\b([A-Za-z]{2,4})[\s\-_]?(\d{3,4}[A-Za-z]?)\b")


def _find_year(text: str) -> tuple[int | None, float]:
    m = _YEAR_PATTERN.search(text)
    if m:
        return int(m.group(1)), 0.8
    return None, 0.0


def _find_semester(text: str) -> tuple[str | None, float]:
    for name, pattern in _SEMESTER_PATTERNS.items():
        if pattern.search(text):
            return name, 0.8
    return None, 0.0


def _find_exam_type(text: str) -> tuple[str | None, float]:
    for exam_type, pattern in _EXAM_TYPE_PATTERNS.items():
        if pattern.search(text):
            return exam_type, 0.8
    return None, 0.0


def _find_department(text: str) -> tuple[str | None, float]:
    for dept, pattern in _DEPT_PATTERNS.items():
        if pattern.search(text):
            return dept, 0.7
    return None, 0.0


def _find_course_code(text: str) -> tuple[str | None, float]:
    for m in _COURSE_CODE_PATTERN.finditer(text):
        canonical = normalize_course_code(m.group(0))
        if canonical:
            return canonical, 0.7
    return None, 0.0


class RuleBasedMetadataExtractor(MetadataExtractor):
    """Rule-based metadata extractor using regex patterns. DEV-017.

    Merges results from multiple text sources; higher-confidence sources win.
    """

    def extract(
        self,
        *,
        repository_metadata: dict | None = None,
        filename: str | None = None,
        pdf_metadata: dict | None = None,
        text_sample: str | None = None,
    ) -> NormalizedMetadata:
        result = NormalizedMetadata()

        sources = [
            text_sample or "",
            filename or "",
            self._flatten(pdf_metadata or {}),
            self._flatten_repo(repository_metadata or {}),
        ]

        course_conf = year_conf = sem_conf = dept_conf = exam_conf = 0.0

        for text in sources:
            if not text:
                continue

            cc, c = _find_course_code(text)
            if cc and c > course_conf:
                result.course_code = cc
                course_conf = c

            yr, c = _find_year(text)
            if yr and c > year_conf:
                result.year = yr
                year_conf = c

            sem, c = _find_semester(text)
            if sem and c > sem_conf:
                result.semester = sem
                sem_conf = c

            dept, c = _find_department(text)
            if dept and c > dept_conf:
                result.department = dept
                dept_conf = c

            exam, c = _find_exam_type(text)
            if exam and c > exam_conf:
                result.exam_type = exam
                exam_conf = c

        found = [c for c in [course_conf, year_conf, sem_conf, dept_conf] if c > 0]
        result.confidence = sum(found) / len(found) if found else 0.0
        return result

    def _flatten(self, meta: dict) -> str:  # type: ignore[type-arg]
        return " ".join(str(v) for v in meta.values() if v)

    def _flatten_repo(self, meta: dict) -> str:  # type: ignore[type-arg]
        parts: list[str] = []
        for values in meta.values():
            if isinstance(values, list):
                parts.extend(str(v) for v in values)
            else:
                parts.append(str(values))
        return " ".join(parts)
