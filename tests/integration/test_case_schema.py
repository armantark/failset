from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_neutral_schema_validates_every_public_pack() -> None:
    schema = json.loads(Path("case-pack.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert "Run failset verify for cross-field" in schema["description"]
    assert "discriminator" not in json.dumps(schema)
    validator = Draft202012Validator(schema)

    for path in sorted(Path("cases").glob("*.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        errors = sorted(validator.iter_errors(pack), key=lambda error: list(error.path))
        assert errors == [], f"{path}: {[error.message for error in errors]}"


def test_neutral_schema_rejects_an_unknown_case_field() -> None:
    schema = json.loads(Path("case-pack.schema.json").read_text(encoding="utf-8"))
    pack = json.loads(Path("cases/tool-calls.json").read_text(encoding="utf-8"))
    pack["cases"][0]["private_note"] = "must not cross the public format"

    errors = list(Draft202012Validator(schema).iter_errors(pack))

    assert any(error.validator == "additionalProperties" for error in errors)
