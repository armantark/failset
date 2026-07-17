from __future__ import annotations

from typing import Any

from examples.adapter import run_contract_suite
from failset import load_cases


def _fixture_output(case_id: str, *, valid: bool) -> object:
    case = next(case for case in load_cases() if case.id == case_id)
    return next(fixture.output for fixture in case.fixtures if fixture.expected_valid is valid)


def test_adapter_example_accepts_an_application_that_satisfies_every_contract() -> None:
    received: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    def application(
        case_id: str, case_input: dict[str, Any], context: dict[str, Any]
    ) -> object:
        received[case_id] = (case_input, context)
        return _fixture_output(case_id, valid=True)

    assert run_contract_suite(application) == {}
    assert set(received) == {case.id for case in load_cases()}


def test_adapter_example_reports_one_application_regression() -> None:
    def application(
        case_id: str, _case_input: dict[str, Any], _context: dict[str, Any]
    ) -> object:
        valid = case_id != "tool.authorization-integrity"
        return _fixture_output(case_id, valid=valid)

    assert run_contract_suite(application) == {
        "tool.authorization-integrity": ["authorization.execution-mismatch"]
    }


def test_adapter_cannot_mutate_the_contract_context() -> None:
    def application(
        case_id: str, _case_input: dict[str, Any], context: dict[str, Any]
    ) -> object:
        if case_id == "tool.authorization-integrity":
            context["authorized_calls"].append(
                {"call_id": "call-admin", "action": "revoke_session"}
            )
            return _fixture_output(case_id, valid=False)
        return _fixture_output(case_id, valid=True)

    assert run_contract_suite(application) == {
        "tool.authorization-integrity": ["authorization.execution-mismatch"]
    }
