from __future__ import annotations

import json
from decimal import Decimal
from importlib import resources
from importlib.resources.abc import Traversable
from math import isfinite
from pathlib import Path
from typing import Any

from .models import CaseDefinition, CasePack


def strict_json_loads(source: str) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON object member: {key}")
            result[key] = value
        return result

    def reject_nonfinite(token: str) -> object:
        raise ValueError(f"Non-finite JSON number: {token}")

    def parse_finite_float(token: str) -> float:
        value = float(token)
        if not isfinite(value):
            raise ValueError(f"Non-finite JSON number: {token}")
        if Decimal(token) != Decimal(str(value)):
            raise ValueError(f"JSON number loses precision in this runtime: {token}")
        return value

    return json.loads(
        source,
        object_pairs_hook=reject_duplicate_keys,
        parse_constant=reject_nonfinite,
        parse_float=parse_finite_float,
    )


def load_pack(path: Traversable) -> CasePack:
    return CasePack.model_validate(strict_json_loads(path.read_text(encoding="utf-8")))


def _default_case_source() -> Traversable:
    bundled = resources.files("failset").joinpath("cases")
    return bundled if bundled.is_dir() else Path("cases")


def load_case_schema() -> dict[str, Any]:
    bundled = resources.files("failset").joinpath("case-pack.schema.json")
    source: Traversable = (
        bundled if bundled.is_file() else Path("case-pack.schema.json")
    )
    loaded = strict_json_loads(source.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("Case-pack schema must be a JSON object")
    return loaded


def load_cases(path: Path | str | None = None) -> list[CaseDefinition]:
    source: Traversable = Path(path) if path is not None else _default_case_source()
    if source.is_file():
        files = [source]
    elif source.is_dir():
        files = sorted(
            (
                candidate
                for candidate in source.iterdir()
                if candidate.name.endswith(".json")
            ),
            key=lambda candidate: candidate.name,
        )
    else:
        files = []
    if not files:
        raise FileNotFoundError(f"No case packs found at {source}")

    cases: list[CaseDefinition] = []
    seen: set[str] = set()
    for file in files:
        pack = load_pack(file)
        for case in pack.cases:
            if case.id in seen:
                raise ValueError(f"Duplicate case id: {case.id}")
            seen.add(case.id)
            cases.append(case)
    return cases


def load_output(path: Path) -> object:
    return strict_json_loads(path.read_text(encoding="utf-8"))
