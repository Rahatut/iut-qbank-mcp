"""Unit tests for course code normalization. DEV-005, DEV-045."""

import pytest

from qbank.domain.course_normalization import (
    CourseCodeIndex,
    codes_are_equivalent,
    normalize_course_code,
)


@pytest.mark.unit
class TestNormalizeCourseCode:
    def test_canonical_form_unchanged(self) -> None:
        assert normalize_course_code("CSE3101") == "CSE3101"

    def test_space_removed(self) -> None:
        assert normalize_course_code("CSE 3101") == "CSE3101"

    def test_dash_removed(self) -> None:
        assert normalize_course_code("CSE-3101") == "CSE3101"

    def test_lowercase_upcased(self) -> None:
        assert normalize_course_code("cse3101") == "CSE3101"

    def test_mixed_case_with_separator(self) -> None:
        assert normalize_course_code("Cse 3101") == "CSE3101"

    def test_underscore_separator(self) -> None:
        assert normalize_course_code("CSE_3101") == "CSE3101"

    def test_three_digit_number(self) -> None:
        assert normalize_course_code("PHY101") == "PHY101"

    def test_suffix_preserved(self) -> None:
        assert normalize_course_code("CSE3101L") == "CSE3101L"

    def test_suffix_upcased(self) -> None:
        assert normalize_course_code("cse3101l") == "CSE3101L"

    def test_eee_department(self) -> None:
        assert normalize_course_code("EEE 2201") == "EEE2201"

    def test_invalid_returns_none(self) -> None:
        assert normalize_course_code("garbage") is None

    def test_empty_returns_none(self) -> None:
        assert normalize_course_code("") is None

    def test_digits_only_returns_none(self) -> None:
        assert normalize_course_code("3101") is None

    def test_leading_trailing_whitespace(self) -> None:
        assert normalize_course_code("  CSE3101  ") == "CSE3101"


@pytest.mark.unit
class TestCodesAreEquivalent:
    def test_same_canonical(self) -> None:
        assert codes_are_equivalent("CSE3101", "CSE3101") is True

    def test_space_vs_no_space(self) -> None:
        assert codes_are_equivalent("CSE 3101", "CSE3101") is True

    def test_dash_vs_no_dash(self) -> None:
        assert codes_are_equivalent("CSE-3101", "CSE3101") is True

    def test_lowercase_vs_uppercase(self) -> None:
        assert codes_are_equivalent("cse3101", "CSE3101") is True

    def test_different_courses(self) -> None:
        assert codes_are_equivalent("CSE3101", "CSE4105") is False

    def test_invalid_input(self) -> None:
        assert codes_are_equivalent("garbage", "CSE3101") is False


@pytest.mark.unit
class TestCourseCodeIndex:
    def test_register_and_resolve(self) -> None:
        index = CourseCodeIndex()
        index.register("course-1", "CSE3101", aliases=["CSE 3101", "CSE-3101"])
        assert index.resolve("CSE 3101") == "CSE3101"
        assert index.resolve("CSE-3101") == "CSE3101"
        assert index.resolve("cse3101") == "CSE3101"

    def test_get_course_id(self) -> None:
        index = CourseCodeIndex()
        index.register("course-abc", "EEE2201", aliases=["EEE 2201"])
        assert index.get_course_id("EEE 2201") == "course-abc"
        assert index.get_course_id("eee2201") == "course-abc"

    def test_unknown_returns_none(self) -> None:
        index = CourseCodeIndex()
        assert index.resolve("UNKNOWN999") is None
        assert index.get_course_id("UNKNOWN999") is None

    def test_invalid_canonical_raises(self) -> None:
        index = CourseCodeIndex()
        with pytest.raises(ValueError):
            index.register("id", "not-a-course-code")
