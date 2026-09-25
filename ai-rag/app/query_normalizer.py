"""Deterministic query normalization for retrieval.

The normalizer only performs low-risk transformations: whitespace and
full-width normalization, removal of conversational fillers, configurable
domain aliases, and adding Arabic equivalents for Chinese numeric phrases.
It never answers the user's question or invents new entities.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import config


DEFAULT_ALIASES = {
    "挂科": "考核不合格",
    "翘课": "旷课",
    "保研": "推荐免试研究生",
    "绩点": "平均学分绩点",
    "延毕": "延长修业年限",
    "大一": "本科一年级",
    "大二": "本科二年级",
    "大三": "本科三年级",
    "大四": "本科四年级",
}

FILLER_PATTERNS = (
    r"^(?:呃|嗯|那个|就是)[，,：:\s]+",
    r"^(?:我想|想问|请问|麻烦)?(?:问一下|咨询一下|问下)[，,：:\s]*",
    r"^(?:请)?(?:帮我|给我)看看[，,：:\s]*",
)

CHINESE_NUMERAL_PATTERN = re.compile(
    r"(?P<number>[零〇一二两三四五六七八九十百]+)\s*"
    r"(?P<unit>个工作日|工作日|小时|学时|个月|月|天|日|年|人|次|门|名|分|元|%)"
)

CHINESE_DIGITS = {
    "零": 0,
    "〇": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}


def _chinese_numeral_to_int(value: str) -> int | None:
    """Parse the small Chinese numerals used in policy questions."""
    if not value:
        return None
    if value in CHINESE_DIGITS:
        return CHINESE_DIGITS[value]

    total = 0
    section = 0
    current = 0
    for character in value:
        if character in CHINESE_DIGITS:
            current = CHINESE_DIGITS[character]
            continue
        if character == "十":
            if current == 0:
                current = 1
            section += current * 10
            current = 0
            continue
        if character == "百":
            if current == 0:
                current = 1
            section += current * 100
            current = 0
            continue
        return None
    total += section + current
    return total if total > 0 else None


def _configured_aliases() -> dict[str, str]:
    aliases = dict(DEFAULT_ALIASES)
    raw = getattr(config, "QUERY_ALIASES", "")
    for item in raw.split(";"):
        if "=" not in item:
            continue
        source, target = item.split("=", 1)
        source = source.strip()
        target = target.strip()
        if source and target:
            aliases[source] = target
    return aliases


def _append_arabic_numerals(text: str, changes: list[str]) -> str:
    def replace(match: re.Match[str]) -> str:
        number_text = match.group("number")
        unit = match.group("unit")
        number = _chinese_numeral_to_int(number_text)
        if number is None:
            return match.group(0)
        appended = f"（{number}{unit}）"
        following = text[match.end() : match.end() + len(appended) + 4]
        if appended in following:
            return match.group(0)
        changes.append(f"number:{number_text}{unit}->{number}{unit}")
        return f"{match.group(0)}{appended}"

    return CHINESE_NUMERAL_PATTERN.sub(replace, text)


def normalize_query(text: str) -> dict[str, Any]:
    """Return a normalized retrieval query and a list of applied changes."""
    original = str(text or "").strip()
    normalized = unicodedata.normalize("NFKC", original)
    changes: list[str] = []

    for pattern in FILLER_PATTERNS:
        updated = re.sub(pattern, "", normalized, count=1)
        if updated != normalized:
            changes.append(f"filler:{pattern}")
            normalized = updated

    for source, target in sorted(
        _configured_aliases().items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if source and source in normalized:
            normalized = normalized.replace(source, target)
            changes.append(f"alias:{source}->{target}")

    normalized = _append_arabic_numerals(normalized, changes)
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()

    return {
        "query": normalized or original,
        "changes": changes,
        "original": original,
    }
