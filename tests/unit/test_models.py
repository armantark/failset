from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from failset.models import CasePack


def _pack() -> dict[str, object]:
    return json.loads(Path("cases/tool-calls.json").read_text(encoding="utf-8"))


def test_case_rejects_an_invalid_json_schema() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"]["type"] = "not-a-json-schema-type"

    with pytest.raises(ValidationError, match="invalid Draft 2020-12 output schema"):
        CasePack.model_validate(pack)


def test_pack_requires_a_public_clean_room_source() -> None:
    pack = _pack()
    pack["pack"]["provenance"]["public_sources"] = []

    with pytest.raises(ValidationError, match="at least 1 item"):
        CasePack.model_validate(pack)


def test_strict_models_do_not_coerce_boolean_flags() -> None:
    pack = _pack()
    pack["pack"]["provenance"]["contains_customer_data"] = 0

    with pytest.raises(ValidationError, match="must be the boolean false"):
        CasePack.model_validate(pack)


def test_case_requires_fixture_names_to_be_distinct() -> None:
    pack = _pack()
    fixtures = pack["cases"][0]["fixtures"]
    fixtures[1]["name"] = fixtures[0]["name"]

    with pytest.raises(ValidationError, match="fixture names must be distinct"):
        CasePack.model_validate(pack)


def test_case_requires_both_passing_and_failing_fixtures() -> None:
    pack = _pack()
    valid_fixture = pack["cases"][0]["fixtures"][0]
    pack["cases"][0]["fixtures"] = [valid_fixture, deepcopy(valid_fixture)]
    pack["cases"][0]["fixtures"][1]["name"] = "also-valid"

    with pytest.raises(ValidationError, match="both a valid and an invalid fixture"):
        CasePack.model_validate(pack)


def test_invalid_fixture_requires_an_expected_violation() -> None:
    pack = _pack()
    pack["cases"][0]["fixtures"][1]["expected_violations"] = []

    with pytest.raises(ValidationError, match="invalid fixtures must expect"):
        CasePack.model_validate(pack)


def test_valid_fixture_cannot_expect_a_violation() -> None:
    pack = _pack()
    pack["cases"][0]["fixtures"][0]["expected_violations"] = [
        {"code": "schema.enum", "path": "/name"}
    ]

    with pytest.raises(ValidationError, match="valid fixtures cannot expect"):
        CasePack.model_validate(pack)


def test_fixture_can_expect_repeated_violations() -> None:
    pack = _pack()
    repeated = {"code": "schema.enum", "path": "/name"}
    pack["cases"][0]["fixtures"][1]["expected_violations"] = [repeated, repeated]

    assert (
        len(CasePack.model_validate(pack).cases[0].fixtures[1].expected_violations) == 2
    )


def test_relational_check_must_have_a_failing_fixture() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["fixtures"][1]["expected_violations"] = [
        {"code": "schema.required", "path": ""}
    ]

    with pytest.raises(
        ValidationError, match="relational checks lack a failing fixture"
    ):
        CasePack.model_validate(pack)


def test_fixture_cannot_expect_an_undeclared_relational_error() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["fixtures"][1]["expected_violations"] = [
        {"code": "batch.not-declared", "path": "/calls"}
    ]

    with pytest.raises(ValidationError, match="fixtures expect undeclared error codes"):
        CasePack.model_validate(pack)


def test_relational_check_codes_must_be_distinct() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["contract"]["checks"].append(deepcopy(case["contract"]["checks"][0]))

    with pytest.raises(ValidationError, match="check codes must be distinct"):
        CasePack.model_validate(pack)


def test_relational_field_selector_cannot_be_empty() -> None:
    pack = _pack()
    case = next(item for item in pack["cases"] if item["id"] == "tool.unique-call-ids")
    case["contract"]["checks"][0]["field"] = ""

    with pytest.raises(ValidationError, match="at least 1 character"):
        CasePack.model_validate(pack)


def test_relational_check_cannot_impersonate_schema_violation() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["contract"]["checks"][0]["code"] = "schema.required"

    with pytest.raises(ValidationError, match=r"reserved schema\.\* namespace"):
        CasePack.model_validate(pack)


@pytest.mark.parametrize(
    "reference", ["https://example.com/schema.json", "data:application/json,{}"]
)
def test_output_schema_rejects_nonlocal_references(reference: str) -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"] = {"$ref": reference}

    with pytest.raises(ValidationError, match="must be a local fragment"):
        CasePack.model_validate(pack)


def test_output_schema_rejects_another_dialect() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"]["$schema"] = (
        "http://json-schema.org/draft-07/schema#"
    )

    with pytest.raises(ValidationError, match="must use JSON Schema Draft 2020-12"):
        CasePack.model_validate(pack)


def test_output_schema_rejects_dangling_local_reference() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$ref": "#/$defs/missing",
        "$defs": {},
    }

    with pytest.raises(ValidationError, match="does not resolve"):
        CasePack.model_validate(pack)


def test_output_schema_resolves_references_in_nested_resource_scope() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": {"root": {"type": "string"}},
        "properties": {
            "nested": {
                "$id": "nested",
                "$defs": {"local": {"type": "integer"}},
                "$ref": "#/$defs/local",
            }
        },
    }

    CasePack.model_validate(pack)

    pack["cases"][0]["contract"]["output_schema"]["properties"]["nested"]["$ref"] = (
        "#/$defs/root"
    )
    with pytest.raises(ValidationError, match="does not resolve"):
        CasePack.model_validate(pack)


def test_output_schema_does_not_treat_literal_data_as_a_schema() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["output_schema"] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "const": {"$ref": "literal data, not a schema reference"},
    }

    CasePack.model_validate(pack)


def test_model_rejects_non_collection_context_pointer() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["context"]["requests"] = "three requests"

    with pytest.raises(ValidationError, match="must select an array"):
        CasePack.model_validate(pack)


def test_reference_context_requires_the_selected_id_field() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.correlation-integrity"
    )
    del case["context"]["requests"][0]["id"]

    with pytest.raises(ValidationError, match="context is missing field 'id'"):
        CasePack.model_validate(pack)


def test_projection_context_requires_every_selected_field() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.effect-receipt-integrity"
    )
    del case["context"]["receipts"][0]["status"]

    with pytest.raises(ValidationError, match="missing a selected projection field"):
        CasePack.model_validate(pack)


def test_context_pointer_can_traverse_a_canonical_array_index() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    requests = case["context"]["requests"]
    case["context"] = {"groups": [requests]}
    case["contract"]["checks"] = [
        {
            "kind": "same_length",
            "code": "batch.cardinality-mismatch",
            "output_collection_pointer": "/calls",
            "context_collection_pointer": "/groups/0",
        }
    ]

    assert CasePack.model_validate(pack)


def test_model_rejects_unicode_array_index_before_runtime() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.batch-cardinality"
    )
    case["context"] = {"outer": [[{"request_id": "request-1"}]]}
    case["contract"]["checks"][0]["context_collection_pointer"] = "/outer/١"

    with pytest.raises(ValidationError, match="does not resolve"):
        CasePack.model_validate(pack)


def test_model_rejects_invalid_json_pointer_escape() -> None:
    pack = _pack()
    pack["cases"][0]["contract"]["checks"] = [
        {
            "kind": "unique_by",
            "code": "collection.invalid-pointer",
            "output_collection_pointer": "/~2",
        }
    ]

    with pytest.raises(ValidationError, match="String should match pattern"):
        CasePack.model_validate(pack)


def test_exactly_one_fields_must_be_distinct() -> None:
    pack = _pack()
    case = next(item for item in pack["cases"] if item["id"] == "tool.result-xor-error")
    case["contract"]["checks"][0]["fields"] = ["result", "result"]

    with pytest.raises(ValidationError, match="exactly_one fields must be distinct"):
        CasePack.model_validate(pack)


def test_projection_fields_must_have_matching_lengths() -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.effect-receipt-integrity"
    )
    case["contract"]["checks"][0]["context_fields"] = ["operation_id"]

    with pytest.raises(ValidationError, match="must have equal length"):
        CasePack.model_validate(pack)


@pytest.mark.parametrize("field_list", ["output_fields", "context_fields"])
def test_projection_fields_must_be_distinct(field_list: str) -> None:
    pack = _pack()
    case = next(
        item for item in pack["cases"] if item["id"] == "tool.effect-receipt-integrity"
    )
    case["contract"]["checks"][0][field_list] = ["operation_id", "operation_id"]

    with pytest.raises(ValidationError, match=f"{field_list} must be distinct"):
        CasePack.model_validate(pack)
