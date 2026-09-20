"""Course code normalization. DEV-005.

All variants of a course code must resolve to the same canonical form so that
search filters work consistently regardless of how users format the code.

Examples:
    "CSE3101"  → "CSE3101"
    "CSE 3101" → "CSE3101"
    "CSE-3101" → "CSE3101"
    "cse3101"  → "CSE3101"
    "cse 3101" → "CSE3101"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# Matches: optional prefix letters, optional separator, digits, optional suffix
_COURSE_PATTERN = re.compile(
    r"^([A-Za-z]+)"        # department prefix  e.g. CSE, EEE, PHY
    r"[\s\-_]?"            # optional separator
    r"(\d{3,4})"           # course number      e.g. 3101, 101
    r"([A-Za-z]?)$"        # optional suffix    e.g. L (lab)
)


def normalize_course_code(raw: str) -> str | None:
    """Return the canonical course code, or None if unrecognisable.

    Canonical form: uppercase prefix + digits + uppercase suffix, no separator.
    Examples:
        "CSE 3101"  → "CSE3101"
        "eee-2201"  → "EEE2201"
        "PHY101L"   → "PHY101L"
        "garbage"   → None
    """
    cleaned = raw.strip()
    m = _COURSE_PATTERN.match(cleaned)
    if not m:
        return None
    prefix, number, suffix = m.groups()
    return f"{prefix.upper()}{number}{suffix.upper()}"


def codes_are_equivalent(a: str, b: str) -> bool:
    """Return True if two raw course code strings resolve to the same canonical code."""
    ca = normalize_course_code(a)
    cb = normalize_course_code(b)
    return ca is not None and cb is not None and ca == cb


@dataclass
class CourseCodeIndex:
    """In-memory index for fast alias → canonical course_id lookups.

    Populated from the courses table at startup (or lazily).
    """
    # canonical_code → course_id
    _canonical_to_id: dict[str, str] = field(default_factory=dict, repr=False)
    # any raw alias → canonical code
    _alias_to_canonical: dict[str, str] = field(default_factory=dict, repr=False)

    def register(
        self,
        course_id: str,
        course_code: str,
        aliases: list[str] | None = None,
    ) -> None:
        """Register a course with its canonical code and any known aliases."""
        canonical = normalize_course_code(course_code)
        if canonical is None:
            raise ValueError(f"Invalid canonical course code: {course_code!r}")
        self._canonical_to_id[canonical] = course_id
        self._alias_to_canonical[canonical] = canonical
        for alias in aliases or []:
            normalized = normalize_course_code(alias)
            if normalized:
                self._alias_to_canonical[normalized] = canonical

    def resolve(self, raw: str) -> str | None:
        """Resolve a raw course code string to a canonical code."""
        canonical = normalize_course_code(raw)
        if canonical is None:
            return None
        return self._alias_to_canonical.get(canonical)

    def get_course_id(self, raw: str) -> str | None:
        """Return the course_id for a raw course code string, or None."""
        canonical = self.resolve(raw)
        if canonical is None:
            return None
        return self._canonical_to_id.get(canonical)
