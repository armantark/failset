from pathlib import Path

import pytest

from failset import load_cases, verify_fixture
from failset.loader import load_case_schema


def test_all_public_fixtures_self_verify() -> None:
    cases = load_cases()

    assert len(cases) == 16
    assert sum(len(case.fixtures) for case in cases) == 32
    for case in cases:
        for fixture in case.fixtures:
            verify_fixture(case, fixture)


def test_duplicate_case_ids_fail_loading(tmp_path: Path) -> None:
    pack = Path("cases/structured-output.json").read_text(encoding="utf-8")
    (tmp_path / "one.json").write_text(pack, encoding="utf-8")
    (tmp_path / "two.json").write_text(pack, encoding="utf-8")

    with pytest.raises(ValueError, match="Duplicate case id"):
        load_cases(tmp_path)


def test_missing_case_directory_fails_clearly(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="No case packs"):
        load_cases(tmp_path / "missing")


def test_one_pack_file_can_be_loaded_directly() -> None:
    cases = load_cases(Path("cases/tool-calls.json"))

    assert len(cases) == 9


def test_case_schema_loader_rejects_non_object_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "case-pack.schema.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr("failset.loader.resources.files", lambda _: tmp_path)

    with pytest.raises(ValueError, match="must be a JSON object"):
        load_case_schema()
