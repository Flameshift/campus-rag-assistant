"""Per-query source-file scope shared by all retrieval stages."""

from __future__ import annotations

from dataclasses import dataclass

from .applicability import (
    cohort_matches,
    extract_cohorts,
    format_applicability,
    is_general_applicability,
)


@dataclass(frozen=True)
class RetrievalScope:
    """Resolved source files allowed for one query plan."""

    allowed_source_ids: frozenset[int]
    time_intent: str
    as_of_date: str = ""
    user_cohort: str = ""
    applicability_mode: str = "exact"
    applicability: str = ""
    applicability_title: str = ""

    def to_trace_dict(self) -> dict:
        return {
            "time_intent": self.time_intent,
            "as_of_date": self.as_of_date,
            "user_cohort": self.user_cohort,
            "applicability_mode": self.applicability_mode,
            "applicability": self.applicability,
            "applicability_title": self.applicability_title,
            "allowed_source_count": len(self.allowed_source_ids),
            "allowed_source_ids": sorted(self.allowed_source_ids),
        }


@dataclass(frozen=True)
class ApplicabilitySelection:
    source_ids: frozenset[int]
    mode: str
    applicability: str = ""
    title: str = ""


def select_source_ids(
    rows: list,
    time_intent: str,
    as_of_date: str,
) -> set[int]:
    """Select valid source-file IDs from database rows."""
    if time_intent == "current":
        return {int(row[0]) for row in rows}
    if time_intent != "as_of" or not as_of_date:
        return {int(row[0]) for row in rows}

    by_document: dict[str, list] = {}
    for row in rows:
        by_document.setdefault(str(row[1] or f"source-{row[0]}"), []).append(row)

    selected: set[int] = set()
    for candidates in by_document.values():
        dated = [
            row
            for row in candidates
            if row[3] and str(row[3]) <= as_of_date
        ]
        if dated:
            selected.add(int(max(dated, key=lambda row: int(row[2] or 0))[0]))
            continue
        selected.update(int(row[0]) for row in candidates if not row[3])
    return selected


def select_applicability_sources(
    rows: list,
    candidate_ids: set[int],
    user_cohort: str = "",
    preserve_all_without_cohort: bool = False,
) -> ApplicabilitySelection:
    """Resolve exact, general, latest-current, or fallback source files."""
    candidates = [
        row
        for row in rows
        if int(row[0]) in candidate_ids
    ]
    if not candidates:
        return ApplicabilitySelection(frozenset(), "none")

    cohort = _cohort_value(user_cohort)
    if preserve_all_without_cohort and cohort is None:
        return ApplicabilitySelection(
            source_ids=frozenset(int(row[0]) for row in candidates),
            mode="time_scoped",
            applicability=_join_applicability(candidates),
            title=_join_titles(candidates),
        )
    exact = [
        row for row in candidates
        if cohort_matches(_applicability(row), cohort)
    ]
    general = [
        row for row in candidates
        if is_general_applicability(_applicability(row))
    ]

    if cohort is not None:
        if exact:
            selected = exact
            mode = "exact"
        elif general:
            selected = general
            mode = "general"
        else:
            selected = [_latest_row(candidates)]
            mode = "fallback"
    elif general:
        selected = general
        mode = "general"
    else:
        selected = [_latest_row(candidates)]
        mode = "latest_current"

    return ApplicabilitySelection(
        source_ids=frozenset(int(row[0]) for row in selected),
        mode=mode,
        applicability=_join_applicability(selected),
        title=_join_titles(selected),
    )


def _cohort_value(value: str | None) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None
    cohorts = extract_cohorts(text)
    if cohorts:
        return max(cohorts)
    try:
        number = int(text)
    except ValueError:
        return None
    return number if number >= 2000 else 2000 + number


def _applicability(row: list | tuple) -> str:
    return str(_row_value(row, 5, ""))


def _latest_row(rows: list) -> list | tuple:
    return max(
        rows,
        key=lambda row: (
            int(bool(_row_value(row, 4, False))),
            int(_row_value(row, 2, 0) or 0),
            str(_row_value(row, 3, "") or ""),
            int(row[0]),
        ),
    )


def _join_applicability(rows: list) -> str:
    values = sorted({
        format_applicability(_applicability(row))
        for row in rows
    })
    return " | ".join(values)


def _join_titles(rows: list) -> str:
    values = []
    for row in rows:
        title = str(
            _row_value(row, 6, "")
            or _row_value(row, 7, "")
        ).strip()
        if title and title not in values:
            values.append(title)
    return " | ".join(values)


def _row_value(row: list | tuple, index: int, default):
    return row[index] if index < len(row) else default
