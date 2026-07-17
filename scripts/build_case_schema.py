from __future__ import annotations

import argparse
import json
from pathlib import Path

from failset.models import CasePack


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "case-pack.schema.json"


def _without_discriminator(value: object) -> object:
    if isinstance(value, dict):
        return {
            key: _without_discriminator(item)
            for key, item in value.items()
            if key != "discriminator"
        }
    if isinstance(value, list):
        return [_without_discriminator(item) for item in value]
    return value


def render_schema() -> str:
    schema = _without_discriminator(CasePack.model_json_schema())
    if not isinstance(schema, dict):
        raise TypeError("CasePack JSON Schema must be an object")
    schema["$schema"] = "https://json-schema.org/draft/2020-12/schema"
    schema["title"] = "Failset case pack"
    schema["description"] = (
        "Structural case-pack schema. Run failset verify for cross-field authoring invariants "
        "and fixture expectation checks."
    )
    return json.dumps(schema, indent=2, sort_keys=True) + "\n"


def require_current_schema(path: Path = OUTPUT) -> None:
    if not path.is_file() or path.read_text(encoding="utf-8") != render_schema():
        raise ValueError("case-pack.schema.json is stale; rebuild it before release")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the neutral Failset case-pack schema."
    )
    parser.add_argument(
        "--check", action="store_true", help="Fail when the schema is stale."
    )
    args = parser.parse_args()
    rendered = render_schema()
    if args.check:
        try:
            require_current_schema()
        except ValueError as error:
            raise SystemExit(str(error)) from error
        print("Verified case-pack.schema.json.")
        return
    OUTPUT.write_text(rendered, encoding="utf-8")
    print("Built case-pack.schema.json.")


if __name__ == "__main__":
    main()
