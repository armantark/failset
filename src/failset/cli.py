from __future__ import annotations

import argparse
import json
from pathlib import Path

from .loader import load_case_schema, load_cases, load_output
from .runner import evaluate_output, verify_fixture


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="failset")
    parser.add_argument("--cases", type=Path, help="Override the bundled case directory or pack")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List bundled case identifiers")
    commands.add_parser("verify", help="Verify every bundled fixture")
    commands.add_parser("schema", help="Print the bundled case-pack JSON Schema")
    check = commands.add_parser("check", help="Check one JSON output against one case")
    check.add_argument("case_id")
    check.add_argument("output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "schema":
        print(json.dumps(load_case_schema(), indent=2, sort_keys=True))
        return 0

    cases = load_cases(args.cases)
    if args.command == "list":
        for case in cases:
            print(f"{case.id}\t{case.title}")
        return 0
    if args.command == "verify":
        fixture_count = 0
        for case in cases:
            for fixture in case.fixtures:
                verify_fixture(case, fixture)
                fixture_count += 1
        print(f"Verified {fixture_count} fixtures across {len(cases)} cases.")
        return 0

    selected = next((case for case in cases if case.id == args.case_id), None)
    if selected is None:
        raise SystemExit(f"Unknown case id: {args.case_id}")
    try:
        output = load_output(args.output)
    except (json.JSONDecodeError, ValueError) as error:
        raise SystemExit(f"Invalid JSON output: {error}") from error
    violations = evaluate_output(selected, output)
    print(json.dumps([violation.model_dump() for violation in violations], indent=2))
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
