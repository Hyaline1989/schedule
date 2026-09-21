from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from schedule.models import normalize_employee_name


AUTO_MATCH_THRESHOLD = 0.92
AMBIGUOUS_GAP = 0.03


@dataclass(frozen=True, slots=True)
class NameMatch:
    name: str
    score: float
    method: str


def normalize_for_fuzzy_match(value: str) -> str:
    return normalize_employee_name(value).replace("ё", "е")


def find_smart_name_match(
    employee_name: str,
    candidate_names: list[str],
    *,
    threshold: float = AUTO_MATCH_THRESHOLD,
    ambiguous_gap: float = AMBIGUOUS_GAP,
) -> NameMatch | None:
    without_patronymic = _match_without_patronymic(employee_name, candidate_names)
    if without_patronymic is not None:
        return without_patronymic

    needle = normalize_for_fuzzy_match(employee_name)
    scored = sorted(
        (
            (
                SequenceMatcher(None, needle, normalize_for_fuzzy_match(candidate)).ratio(),
                candidate,
            )
            for candidate in candidate_names
        ),
        reverse=True,
    )
    if not scored:
        return None

    best_score, best_name = scored[0]
    if best_score < threshold:
        return None
    if len(scored) > 1 and best_score - scored[1][0] < ambiguous_gap:
        return None
    return NameMatch(best_name, best_score, "smart_fio")


def _match_without_patronymic(
    employee_name: str,
    candidate_names: list[str],
) -> NameMatch | None:
    employee_parts = _name_parts(employee_name)
    if len(employee_parts) != 2:
        return None

    direct = tuple(employee_parts)
    reversed_parts = tuple(reversed(employee_parts))
    matches = []
    for candidate in candidate_names:
        candidate_parts = _name_parts(candidate)
        if len(candidate_parts) < 3:
            continue
        candidate_prefix = tuple(candidate_parts[:2])
        if candidate_prefix in {direct, reversed_parts}:
            matches.append(candidate)

    unique: dict[str, str] = {}
    for match in matches:
        unique.setdefault(normalize_for_fuzzy_match(match), match)
    if len(unique) != 1:
        return None
    return NameMatch(next(iter(unique.values())), 1.0, "fio_without_patronymic")


def _name_parts(value: str) -> list[str]:
    return normalize_for_fuzzy_match(value).split()


def top_name_matches(
    employee_name: str,
    candidate_names: list[str],
    *,
    limit: int = 5,
) -> list[NameMatch]:
    needle = normalize_for_fuzzy_match(employee_name)
    matches = sorted(
        (
            NameMatch(
                candidate,
                SequenceMatcher(
                    None, needle, normalize_for_fuzzy_match(candidate)
                ).ratio(),
                "smart_fio",
            )
            for candidate in candidate_names
        ),
        key=lambda item: item.score,
        reverse=True,
    )
    return matches[:limit]
