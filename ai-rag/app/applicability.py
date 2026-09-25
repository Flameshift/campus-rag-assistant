"""Applicability and cohort matching helpers."""

from __future__ import annotations

import re


YEAR_COHORT_PATTERN = re.compile(r"(20\d{2})\s*级")
SHORT_COHORT_PATTERN = re.compile(r"(?<!\d)(\d{2})\s*级")
CHINESE_YEAR_PATTERN = re.compile(
    r"(?P<value>[〇零一二三四五六七八九]{4})\s*级"
)

CHINESE_DIGITS = {
    "〇": 0,
    "零": 0,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}

GENERAL_PATTERN = re.compile(
    r"(?:通用|全校|全体|所有|全日制本科|本科生|本科学生)"
)


def extract_cohorts(value: str | None) -> set[int]:
    """Extract enrollment cohorts such as 2024 from applicability text."""
    text = str(value or "")
    cohorts = {int(match.group(1)) for match in YEAR_COHORT_PATTERN.finditer(text)}
    cohorts.update(
        2000 + int(match.group(1))
        for match in SHORT_COHORT_PATTERN.finditer(text)
    )
    for match in CHINESE_YEAR_PATTERN.finditer(text):
        digits = [CHINESE_DIGITS[char] for char in match.group("value")]
        cohorts.add(int("".join(str(value) for value in digits)))
    return cohorts


def is_general_applicability(value: str | None) -> bool:
    """Return whether a scope applies broadly rather than to one cohort."""
    text = str(value or "")
    return not extract_cohorts(text) and bool(GENERAL_PATTERN.search(text))


def cohort_matches(applicability: str | None, cohort: int | None) -> bool:
    if cohort is None:
        return False
    return cohort in extract_cohorts(applicability)


def format_applicability(value: str | None) -> str:
    return str(value or "").strip() or "未配置"
