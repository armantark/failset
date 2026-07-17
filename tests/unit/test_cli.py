import json
from pathlib import Path

import pytest

from failset.cli import main


def test_list_prints_case_ids(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["list"]) == 0

    output = capsys.readouterr().out
    assert "structured.no-extra-fields" in output
    assert "tool.known-name" in output


def test_schema_prints_the_bundled_language_neutral_contract(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["schema"]) == 0

    schema = json.loads(capsys.readouterr().out)
    assert schema["title"] == "Failset case pack"
    assert "Run failset verify for cross-field" in schema["description"]
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_check_returns_zero_for_valid_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output.json"
    output.write_text(json.dumps({"confidence": 0.92}), encoding="utf-8")

    assert main(["check", "structured.numeric-not-string", str(output)]) == 0
    assert capsys.readouterr().out.strip() == "[]"


def test_check_returns_one_and_json_for_invalid_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "output.json"
    output.write_text(json.dumps({"confidence": "92%"}), encoding="utf-8")

    assert main(["check", "structured.numeric-not-string", str(output)]) == 1
    violations = json.loads(capsys.readouterr().out)
    assert violations[0]["code"] == "schema.type"


def test_check_rejects_unknown_case(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="Unknown case id"):
        main(["check", "missing.case", str(output)])


@pytest.mark.parametrize(
    "payload, message",
    [
        ('{"confidence": NaN}', "Non-finite JSON number"),
        ('{"confidence": 1e9999}', "Non-finite JSON number"),
        ('{"confidence": 0.123456789012345678901}', "JSON number loses precision"),
        ('{"confidence": 0.92, "confidence": "92%"}', "Duplicate JSON object member"),
    ],
)
def test_check_rejects_non_strict_json(
    tmp_path: Path,
    payload: str,
    message: str,
) -> None:
    output = tmp_path / "output.json"
    output.write_text(payload, encoding="utf-8")

    with pytest.raises(SystemExit, match=f"Invalid JSON output: {message}"):
        main(["check", "structured.numeric-not-string", str(output)])


def test_check_rejects_malformed_json(tmp_path: Path) -> None:
    output = tmp_path / "output.json"
    output.write_text("{", encoding="utf-8")

    with pytest.raises(SystemExit, match="Invalid JSON output"):
        main(["check", "structured.numeric-not-string", str(output)])
