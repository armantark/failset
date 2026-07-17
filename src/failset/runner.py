from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from math import isfinite
from typing import Any

from jsonschema import Draft202012Validator, ValidationError, validators
from referencing import Registry

from .models import (
    CaseDefinition,
    CollectionProjectionEqualityCheck,
    ExactlyOneCheck,
    Fixture,
    ReferenceIntegrityCheck,
    SameLengthCheck,
    UniqueByCheck,
    Violation,
)


def _decimal_parts(value: object) -> tuple[int, int]:
    decimal = Decimal(value) if isinstance(value, int) else Decimal(str(value))
    sign, digits, exponent = decimal.as_tuple()
    if not isinstance(exponent, int):
        raise ValueError("multipleOf operands must be finite numbers")
    coefficient = 0
    for digit in digits:
        coefficient = coefficient * 10 + digit
    return (-coefficient if sign else coefficient), exponent


def _validate_multiple_of(
    validator: Any,
    divisor: object,
    instance: object,
    schema: dict[str, Any],
) -> Iterable[ValidationError]:
    del schema
    if not validator.is_type(instance, "number"):
        return
    instance_coefficient, instance_exponent = _decimal_parts(instance)
    divisor_coefficient, divisor_exponent = _decimal_parts(divisor)
    exponent_delta = instance_exponent - divisor_exponent
    if exponent_delta >= 0:
        numerator = instance_coefficient * (10**exponent_delta)
        denominator = divisor_coefficient
    else:
        numerator = instance_coefficient
        denominator = divisor_coefficient * (10 ** -exponent_delta)
    if numerator % denominator:
        yield ValidationError(f"{instance!r} is not a multiple of {divisor}")


ContractValidator = validators.extend(  # type: ignore[no-untyped-call]
    Draft202012Validator,
    {"multipleOf": _validate_multiple_of},
)


def _pointer(value: Any, pointer: str) -> Any:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise ValueError(f"Invalid JSON Pointer: {pointer}")

    current = value
    for token in pointer[1:].split("/"):
        if "~" in token.replace("~0", "").replace("~1", ""):
            raise ValueError(f"Invalid JSON Pointer escape: {pointer}")
        token = token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not re.fullmatch(r"0|[1-9][0-9]*", token):
                raise ValueError(f"Invalid JSON Pointer array index: {pointer}")
            current = current[int(token)]
        else:
            current = current[token]
    return current


def _path(parts: Iterable[object]) -> str:
    encoded = [str(part).replace("~", "~0").replace("/", "~1") for part in parts]
    return "/" + "/".join(encoded) if encoded else ""


def _present_fields(value: dict[str, Any], fields: list[str]) -> list[str]:
    return [field for field in fields if field in value and value[field] is not None]


def _selected(value: Any, field: str | None) -> tuple[bool, Any]:
    if field is None:
        return True, value
    if not isinstance(value, dict) or field not in value:
        return False, None
    return True, value[field]


def _json_key(value: Any) -> tuple[Any, ...]:
    if value is None:
        return ("null",)
    if isinstance(value, bool):
        return ("boolean", value)
    if isinstance(value, int):
        return ("number", value)
    if isinstance(value, float):
        if not isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return ("number", value)
    if isinstance(value, str):
        return ("string", value)
    if isinstance(value, list):
        return ("array", tuple(_json_key(item) for item in value))
    if isinstance(value, dict):
        return (
            "object",
            tuple(sorted((key, _json_key(item)) for key, item in value.items())),
        )
    raise TypeError(f"Not a JSON value: {type(value).__name__}")


def _selected_value(value: Any, pointer: str) -> tuple[bool, Any]:
    try:
        return True, _pointer(value, pointer)
    except (IndexError, KeyError, TypeError, ValueError):
        return False, None


def _selected_collection(
    value: Any,
    pointer: str,
    *,
    code: str,
    path: str,
    label: str,
    violations: list[Violation],
) -> list[Any] | None:
    found, selected = _selected_value(value, pointer)
    if not found:
        violations.append(
            Violation(
                code=code,
                path=path,
                message=f"{label} collection pointer does not resolve: {pointer}",
            )
        )
        return None
    if not isinstance(selected, list):
        violations.append(
            Violation(
                code=code,
                path=path,
                message=f"{label} collection pointer must select an array",
            )
        )
        return None
    return selected


def _non_json_value(
    value: Any, path: tuple[object, ...] = ()
) -> tuple[str, str] | None:
    if value is None or isinstance(value, (bool, str, int)):
        return None
    if isinstance(value, float):
        return None if isfinite(value) else (_path(path), "JSON numbers must be finite")
    if isinstance(value, list):
        for index, item in enumerate(value):
            invalid = _non_json_value(item, (*path, index))
            if invalid:
                return invalid
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                return _path(path), "JSON object member names must be strings"
            invalid = _non_json_value(item, (*path, key))
            if invalid:
                return invalid
        return None
    return _path(path), f"Unsupported JSON value type: {type(value).__name__}"


def evaluate_output(case: CaseDefinition, output: Any) -> list[Violation]:
    invalid = _non_json_value(output)
    if invalid:
        path, message = invalid
        return [Violation(code="schema.json-value", path=path, message=message)]
    validator = ContractValidator(case.contract.output_schema, registry=Registry())
    violations = [
        Violation(
            code=f"schema.{error.validator}",
            path=_path(error.absolute_path),
            message=error.message,
        )
        for error in sorted(
            validator.iter_errors(output), key=lambda item: list(item.absolute_path)
        )
    ]

    if violations:
        return violations

    for check in case.contract.checks:
        if isinstance(check, ReferenceIntegrityCheck):
            output_items = _selected_collection(
                output,
                check.output_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Output",
                violations=violations,
            )
            context_items = _selected_collection(
                case.context,
                check.context_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Contract context",
                violations=violations,
            )
            if output_items is None or context_items is None:
                continue
            selected_context = [
                _selected(item, check.context_id_field) for item in context_items
            ]
            if not all(found for found, _ in selected_context):
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_collection_pointer,
                        message="Contract context is missing a selected reference field",
                    )
                )
                continue
            allowed = {_json_key(value) for _, value in selected_context}
            for index, item in enumerate(output_items):
                found, reference = _selected(item, check.output_reference_field)
                if not found:
                    violations.append(
                        Violation(
                            code=check.code,
                            path=f"{check.output_collection_pointer}/{index}",
                            message="Output item is missing the selected reference field",
                        )
                    )
                    continue
                if _json_key(reference) not in allowed:
                    violations.append(
                        Violation(
                            code=check.code,
                            path=f"{check.output_collection_pointer}/{index}",
                            message=f"Reference {reference!r} is not present in the supplied context",
                        )
                    )
        elif isinstance(check, UniqueByCheck):
            output_items = _selected_collection(
                output,
                check.output_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Output",
                violations=violations,
            )
            if output_items is None:
                continue
            seen: set[tuple[Any, ...]] = set()
            for index, item in enumerate(output_items):
                found, value = _selected(item, check.field)
                if not found:
                    violations.append(
                        Violation(
                            code=check.code,
                            path=f"{check.output_collection_pointer}/{index}",
                            message="Output item is missing the selected uniqueness field",
                        )
                    )
                    continue
                key = _json_key(value)
                if key in seen:
                    violations.append(
                        Violation(
                            code=check.code,
                            path=f"{check.output_collection_pointer}/{index}",
                            message=f"Duplicate value {value!r}",
                        )
                    )
                seen.add(key)
        elif isinstance(check, ExactlyOneCheck):
            found, value = _selected_value(output, check.output_object_pointer)
            if not found or not isinstance(value, dict):
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_object_pointer,
                        message=(
                            "Output object pointer does not resolve"
                            if not found
                            else "Output object pointer must select an object"
                        ),
                    )
                )
                continue
            present = _present_fields(value, check.fields)
            if len(present) != 1:
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_object_pointer,
                        message=f"Expected exactly one of {check.fields}; found {present}",
                    )
                )
        elif isinstance(check, SameLengthCheck):
            output_items = _selected_collection(
                output,
                check.output_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Output",
                violations=violations,
            )
            context_items = _selected_collection(
                case.context,
                check.context_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Contract context",
                violations=violations,
            )
            if output_items is None or context_items is None:
                continue
            if len(output_items) != len(context_items):
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_collection_pointer,
                        message=f"Expected {len(context_items)} items; found {len(output_items)}",
                    )
                )
        elif isinstance(check, CollectionProjectionEqualityCheck):
            output_items = _selected_collection(
                output,
                check.output_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Output",
                violations=violations,
            )
            context_items = _selected_collection(
                case.context,
                check.context_collection_pointer,
                code=check.code,
                path=check.output_collection_pointer,
                label="Contract context",
                violations=violations,
            )
            if output_items is None or context_items is None:
                continue
            missing_output = [
                index
                for index, item in enumerate(output_items)
                if not isinstance(item, dict)
                or any(field not in item for field in check.output_fields)
            ]
            missing_context = any(
                not isinstance(item, dict)
                or any(field not in item for field in check.context_fields)
                for item in context_items
            )
            for index in missing_output:
                violations.append(
                    Violation(
                        code=check.code,
                        path=f"{check.output_collection_pointer}/{index}",
                        message="Output item is missing a selected projection field",
                    )
                )
            if missing_context:
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_collection_pointer,
                        message="Contract context is missing a selected projection field",
                    )
                )
            if missing_output or missing_context:
                continue
            actual_rows = [
                tuple(item[field] for field in check.output_fields)
                for item in output_items
            ]
            expected_rows = [
                tuple(item[field] for field in check.context_fields)
                for item in context_items
            ]
            actual_keys = [
                tuple(_json_key(value) for value in row) for row in actual_rows
            ]
            expected_keys = [
                tuple(_json_key(value) for value in row) for row in expected_rows
            ]
            actual = Counter(actual_keys)
            expected = Counter(expected_keys)
            if actual != expected:
                actual_values = dict(zip(actual_keys, actual_rows, strict=True))
                expected_values = dict(zip(expected_keys, expected_rows, strict=True))
                missing = [
                    expected_values[key] for key in (expected - actual).elements()
                ]
                unexpected = [
                    actual_values[key] for key in (actual - expected).elements()
                ]
                violations.append(
                    Violation(
                        code=check.code,
                        path=check.output_collection_pointer,
                        message=f"Collection does not match observed records; missing={missing}, unexpected={unexpected}",
                    )
                )
    return violations


def verify_fixture(case: CaseDefinition, fixture: Fixture) -> list[Violation]:
    violations = evaluate_output(case, fixture.output)
    actual = Counter((violation.code, violation.path) for violation in violations)
    expected = Counter(
        (violation.code, violation.path) for violation in fixture.expected_violations
    )
    if fixture.expected_valid != (not violations) or expected != actual:
        raise AssertionError(
            f"{case.id}/{fixture.name}: expected valid={fixture.expected_valid} "
            f"and violations={sorted(expected.elements())}, "
            f"got violations={sorted(actual.elements())}"
        )
    return violations
