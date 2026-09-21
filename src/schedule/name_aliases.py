from __future__ import annotations

from schedule.models import normalize_employee_name


NAME_ALIASES = {
    "Амхадов Шамиль Ломайлович": ["Амхадов Шамиль Ломайлиевич"],
    "Лейман Гених Павлович": ["Лейман Генрих Павлович"],
    "Сергачев Владимир Владимирович": ["Сергачёв Владимир Владимирович"],
}


def candidate_names(employee_name: str) -> list[str]:
    names = [employee_name, *NAME_ALIASES.get(employee_name, [])]
    normalized = normalize_employee_name(employee_name)
    for canonical, aliases in NAME_ALIASES.items():
        if normalize_employee_name(canonical) == normalized:
            continue
        if any(normalize_employee_name(alias) == normalized for alias in aliases):
            names.append(canonical)
            names.extend(aliases)
    unique: dict[str, str] = {}
    for name in names:
        unique.setdefault(normalize_employee_name(name), name)
    return list(unique.values())
