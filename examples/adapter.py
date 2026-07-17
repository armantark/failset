"""Minimal boundary between Failset cases and an application under test."""

from collections.abc import Callable
from copy import deepcopy
from typing import Any

from failset import evaluate_output, load_cases


ApplicationRunner = Callable[[str, dict[str, Any], dict[str, Any]], Any]


def run_contract_suite(application: ApplicationRunner) -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {}
    for case in load_cases():
        output = application(case.id, deepcopy(case.input), deepcopy(case.context))
        violations = evaluate_output(case, output)
        if violations:
            failures[case.id] = [violation.code for violation in violations]
    return failures
