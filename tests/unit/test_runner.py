import pytest

from failset import evaluate_output, load_cases
from failset.models import SameLengthCheck
from failset.runner import _json_key, _pointer


def _case(case_id: str):
    return next(case for case in load_cases() if case.id == case_id)


def test_schema_violation_is_typed_and_located() -> None:
    violations = evaluate_output(
        _case("structured.numeric-not-string"),
        {"confidence": "92%"},
    )

    assert [violation.code for violation in violations] == ["schema.type"]
    assert violations[0].path == "/confidence"


def test_decimal_multiple_of_uses_json_number_semantics() -> None:
    case = _case("structured.numeric-not-string").model_copy(deep=True)
    case.contract.output_schema["properties"]["confidence"] = {
        "type": "number",
        "multipleOf": 0.1,
    }

    assert evaluate_output(case, {"confidence": 0.3}) == []
    assert [
        violation.code for violation in evaluate_output(case, {"confidence": 0.31})
    ] == ["schema.multipleOf"]

    assert [
        violation.code for violation in evaluate_output(case, {"confidence": "0.3"})
    ] == ["schema.type"]


@pytest.mark.parametrize("value", [10**27, 1e27])
def test_decimal_multiple_of_handles_numbers_larger_than_decimal_context(
    value: int | float,
) -> None:
    case = _case("structured.numeric-not-string").model_copy(deep=True)
    case.contract.output_schema["properties"]["confidence"] = {
        "type": "number",
        "multipleOf": 0.1,
    }

    assert evaluate_output(case, {"confidence": value}) == []

    case.contract.output_schema["properties"]["confidence"]["multipleOf"] = 0.3
    assert [
        violation.code for violation in evaluate_output(case, {"confidence": value})
    ] == ["schema.multipleOf"]


def test_reference_integrity_rejects_unknown_context_id() -> None:
    violations = evaluate_output(
        _case("structured.citation-integrity"),
        {"answer": "02:00 UTC", "citations": [{"source_id": "source-Z"}]},
    )

    assert [violation.code for violation in violations] == ["reference.unknown-source"]


def test_unique_by_reports_duplicate_index() -> None:
    violations = evaluate_output(
        _case("tool.unique-call-ids"),
        {
            "calls": [
                {"id": "call-1", "tracking_number": "PKG-14"},
                {"id": "call-1", "tracking_number": "PKG-15"},
            ]
        },
    )

    assert violations[0].path == "/calls/1"


def test_exactly_one_accepts_null_branch() -> None:
    violations = evaluate_output(
        _case("tool.result-xor-error"),
        {"result": None, "error": {"code": "provider_error"}},
    )

    assert violations == []


def test_batch_identity_catches_silently_dropped_item() -> None:
    violations = evaluate_output(
        _case("tool.batch-cardinality"),
        {"calls": [{"request_id": "renewal-domain"}]},
    )

    assert [violation.code for violation in violations] == [
        "batch.cardinality-mismatch"
    ]


def test_batch_identity_catches_duplicates_that_preserve_length() -> None:
    violations = evaluate_output(
        _case("tool.batch-cardinality"),
        {
            "calls": [
                {"request_id": "renewal-domain"},
                {"request_id": "renewal-domain"},
                {"request_id": "renewal-domain"},
            ]
        },
    )

    assert [violation.code for violation in violations] == [
        "batch.cardinality-mismatch"
    ]


def test_generic_same_length_check_still_reports_the_collection() -> None:
    case = _case("tool.batch-cardinality").model_copy(deep=True)
    case.contract.checks = [
        SameLengthCheck(
            kind="same_length",
            code="batch.length-mismatch",
            output_collection_pointer="/calls",
            context_collection_pointer="/requests",
        )
    ]

    violations = evaluate_output(case, {"calls": [{"request_id": "renewal-domain"}]})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("batch.length-mismatch", "/calls")
    ]

    assert (
        evaluate_output(
            case,
            {
                "calls": [
                    {"request_id": "renewal-domain"},
                    {"request_id": "renewal-insurance"},
                    {"request_id": "renewal-parking"},
                ]
            },
        )
        == []
    )


def test_same_length_rejects_a_schema_valid_string_collection() -> None:
    case = _case("tool.batch-cardinality").model_copy(deep=True)
    case.contract.output_schema["properties"]["calls"] = {"type": "string"}

    violations = evaluate_output(case, {"calls": "abc"})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("batch.cardinality-mismatch", "/calls")
    ]
    assert "array" in violations[0].message


def test_missing_optional_relational_collection_is_a_violation_not_an_exception() -> (
    None
):
    case = _case("tool.batch-cardinality").model_copy(deep=True)
    case.contract.output_schema["required"].remove("calls")

    violations = evaluate_output(case, {})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("batch.cardinality-mismatch", "/calls")
    ]
    assert "does not resolve" in violations[0].message


def test_missing_optional_unique_collection_is_a_violation_not_an_exception() -> None:
    case = _case("tool.unique-call-ids").model_copy(deep=True)
    case.contract.output_schema["required"].remove("calls")

    violations = evaluate_output(case, {})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("collection.duplicate-call-id", "/calls")
    ]
    assert "does not resolve" in violations[0].message


def test_json_values_keep_boolean_and_number_identity_distinct() -> None:
    case = _case("structured.citation-integrity").model_copy(deep=True)
    case.context = {"sources": [{"id": 1}]}
    case.contract.output_schema["properties"]["citations"]["items"]["properties"][
        "source_id"
    ]["type"] = ["integer", "boolean"]
    output = {"answer": "No", "citations": [{"source_id": True}]}

    assert [violation.code for violation in evaluate_output(case, output)] == [
        "reference.unknown-source"
    ]


def test_whole_object_uniqueness_supports_json_objects() -> None:
    case = _case("structured.unique-citations").model_copy(deep=True)
    case.contract.checks[0].field = None
    output = {
        "citations": [{"source_id": "source-A"}, {"source_id": "source-A"}],
    }

    assert [violation.code for violation in evaluate_output(case, output)] == [
        "collection.duplicate-source"
    ]


def test_missing_optional_relational_selector_becomes_a_violation() -> None:
    case = _case("tool.unique-call-ids").model_copy(deep=True)
    item_schema = case.contract.output_schema["properties"]["calls"]["items"]
    item_schema["required"].remove("id")

    violations = evaluate_output(
        case,
        {"calls": [{"tracking_number": "PKG-14"}]},
    )

    assert [(violation.code, violation.path) for violation in violations] == [
        ("collection.duplicate-call-id", "/calls/0")
    ]
    assert "missing" in violations[0].message


def test_missing_optional_reference_selector_becomes_a_violation() -> None:
    case = _case("structured.citation-integrity").model_copy(deep=True)
    item_schema = case.contract.output_schema["properties"]["citations"]["items"]
    item_schema["required"].remove("source_id")

    violations = evaluate_output(case, {"answer": "No", "citations": [{}]})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("reference.unknown-source", "/citations/0")
    ]
    assert "missing" in violations[0].message


def test_missing_optional_reference_collection_is_a_violation_not_an_exception() -> (
    None
):
    case = _case("structured.citation-integrity").model_copy(deep=True)
    case.contract.output_schema["required"].remove("citations")

    violations = evaluate_output(case, {"answer": "No"})

    assert [(violation.code, violation.path) for violation in violations] == [
        ("reference.unknown-source", "/citations")
    ]
    assert "does not resolve" in violations[0].message


def test_mutated_reference_context_missing_selected_field_fails_closed() -> None:
    case = _case("structured.citation-integrity").model_copy(deep=True)
    case.context["sources"][0].pop("id")

    violations = evaluate_output(
        case,
        {"answer": "No", "citations": [{"source_id": "source-A"}]},
    )

    assert [(violation.code, violation.path) for violation in violations] == [
        ("reference.unknown-source", "/citations")
    ]
    assert "Contract context" in violations[0].message


@pytest.mark.parametrize(
    ("output", "message"),
    [({}, "does not resolve"), ({"result": "not-an-object"}, "select an object")],
)
def test_exactly_one_reports_an_invalid_output_object_pointer(
    output: object,
    message: str,
) -> None:
    case = _case("tool.result-xor-error").model_copy(deep=True)
    case.contract.output_schema = {}
    case.contract.checks[0].output_object_pointer = "/result"

    violations = evaluate_output(case, output)

    assert [(violation.code, violation.path) for violation in violations] == [
        ("terminal.exactly-one-branch", "/result")
    ]
    assert message in violations[0].message


def test_fixture_verification_requires_the_expected_path() -> None:
    case = _case("tool.argument-type").model_copy(deep=True)
    failing = next(fixture for fixture in case.fixtures if not fixture.expected_valid)
    failing.expected_violations[0].path = "/arguments/memo"

    from failset import verify_fixture

    with pytest.raises(AssertionError, match="/arguments/memo"):
        verify_fixture(case, failing)


@pytest.mark.parametrize("pointer", ["/-1", "/01", "/~2"])
def test_pointer_rejects_invalid_array_index_or_escape(pointer: str) -> None:
    with pytest.raises(ValueError, match="Invalid JSON Pointer"):
        _pointer([10, 20], pointer)


def test_pointer_supports_root_zero_and_escaped_object_members() -> None:
    value = {"a/b": {"~key": ["first"]}}

    assert _pointer(value, "") is value
    assert _pointer(value, "/a~1b/~0key/0") == "first"


def test_output_dependent_invalid_array_index_becomes_a_violation() -> None:
    case = _case("tool.batch-cardinality").model_copy(deep=True)
    case.contract.output_schema = {"type": "array"}
    case.contract.checks = [
        SameLengthCheck(
            kind="same_length",
            code="batch.length-mismatch",
            output_collection_pointer="/١",
            context_collection_pointer="/requests",
        )
    ]

    violations = evaluate_output(case, [])

    assert [(violation.code, violation.path) for violation in violations] == [
        ("batch.length-mismatch", "/١")
    ]
    assert "does not resolve" in violations[0].message


@pytest.mark.parametrize(
    "output, path, message",
    [
        ({"confidence": float("nan")}, "/confidence", "finite"),
        ({1: "not-json"}, "", "member names"),
        ({"confidence": object()}, "/confidence", "Unsupported"),
        ([{"confidence": float("inf")}], "/0/confidence", "finite"),
    ],
)
def test_direct_evaluation_rejects_non_json_values(
    output: object,
    path: str,
    message: str,
) -> None:
    violations = evaluate_output(_case("structured.numeric-not-string"), output)

    assert [(violation.code, violation.path) for violation in violations] == [
        ("schema.json-value", path)
    ]
    assert message in violations[0].message


def test_json_identity_key_supports_every_json_composite() -> None:
    assert _json_key(None) == ("null",)
    assert _json_key(1.5) == ("number", 1.5)
    assert _json_key([{"a": 1}])[0] == "array"

    with pytest.raises(ValueError, match="finite"):
        _json_key(float("inf"))
    with pytest.raises(TypeError, match="Not a JSON value"):
        _json_key(object())

    assert _json_key(10**10000) == ("number", 10**10000)


def test_pointer_requires_a_leading_slash() -> None:
    with pytest.raises(ValueError, match="Invalid JSON Pointer"):
        _pointer({}, "missing-slash")


def test_projection_equality_rejects_schema_valid_false_success_claim() -> None:
    violations = evaluate_output(
        _case("tool.effect-receipt-integrity"),
        {
            "reported_operations": [
                {"operation_id": "op-domain", "status": "completed"},
                {"operation_id": "op-insurance", "status": "completed"},
            ]
        },
    )

    assert [violation.code for violation in violations] == ["effect.receipt-mismatch"]
    assert "('op-insurance', 'failed')" in violations[0].message


def test_projection_equality_rejects_execution_of_rejected_call() -> None:
    case = _case("tool.authorization-integrity")
    passing = next(
        fixture for fixture in case.fixtures if fixture.name == "approved-call-only"
    )
    failing = next(
        fixture for fixture in case.fixtures if fixture.name == "rejected-call-executed"
    )

    assert evaluate_output(case, passing.output) == []
    violations = evaluate_output(case, failing.output)

    assert [violation.code for violation in violations] == [
        "authorization.execution-mismatch"
    ]
    assert "('call-admin', 'revoke_session')" in violations[0].message


def test_projection_equality_reports_missing_selected_fields() -> None:
    case = _case("tool.effect-receipt-integrity").model_copy(deep=True)
    item_schema = case.contract.output_schema["properties"]["reported_operations"][
        "items"
    ]
    item_schema["required"].remove("status")

    output_violations = evaluate_output(
        case,
        {
            "reported_operations": [
                {"operation_id": "op-domain"},
                {"operation_id": "op-insurance", "status": "failed"},
            ]
        },
    )
    assert [(item.code, item.path) for item in output_violations] == [
        ("effect.receipt-mismatch", "/reported_operations/0")
    ]

    case.context["receipts"][0].pop("status")
    context_violations = evaluate_output(
        case,
        {
            "reported_operations": [
                {"operation_id": "op-domain", "status": "completed"},
                {"operation_id": "op-insurance", "status": "failed"},
            ]
        },
    )
    assert [(item.code, item.path) for item in context_violations] == [
        ("effect.receipt-mismatch", "/reported_operations")
    ]
    assert "Contract context" in context_violations[0].message
