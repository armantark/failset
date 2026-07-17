# Failset

Failset is a clean-room corpus of deterministic contract tests for LLM tool calls and structured outputs. The public sampler contains 16 synthetic cases and 32 self-verifying fixtures for failures such as unauthorized actions, dropped work, broken correlations, and success claims that disagree with tool receipts. It is an application regression corpus, not a model leaderboard or document-extraction benchmark.

It is deliberately small and runner-neutral. The included Python CLI uses JSON Schema Draft 2020-12 plus typed relational checks, and the JSON case packs can be adapted to another test runner. Failset does not call a model or send telemetry.

Snapshot tools catch drift from behavior a team has already accepted. Failset's explicit passing and failing fixtures cover invariants that should not become a baseline in the first place. The approaches are complementary.

## Run it

Requirements: Python 3.11+ and [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync --locked --extra dev
uv run failset verify
uv run failset list
uv run pytest
```

The optional PyPI command is added only after a brand-owned release is published and its attestation is independently verified. Until then, use the repository commands above; the package name is not reserved.

To check a saved model output against one case:

```bash
uv run failset check tool.effect-receipt-integrity path/to/output.json
```

JSON object members must be unique, numbers must be finite, and fractional numbers must round-trip through Python's JSON runtime without losing decimal precision. Encode arbitrary-precision identifiers or amounts as strings.

## Wire it to an application

The adapter boundary passes only a case ID, synthetic input, and synthetic context into your application. Expected fixtures and contracts remain on the test side:

```python
from examples.adapter import run_contract_suite


def run_application(case_id, case_input, context):
    return application_under_test(case_input, context=context)


failures = run_contract_suite(run_application)
assert failures == {}, failures
```

Replace `application_under_test` with an existing test seam or mocked-tool harness. Failset then evaluates the returned output and execution receipts locally. [`tests/unit/test_adapter_example.py`](https://github.com/armantark/failset/blob/main/tests/unit/test_adapter_example.py) proves the passing path and an authorization regression.

The generated [`case-pack.schema.json`](https://github.com/armantark/failset/blob/main/case-pack.schema.json) is the language-neutral structural contract for the case format. Non-Python consumers can validate shapes and translate discriminated check types without importing the runner; `failset verify` still enforces the cross-field authoring invariants.

An installed package prints the same artifact with `failset schema`.

## What is included

The sampler contains passing and failing fixtures for sixteen synthetic cases, the generated language-neutral case schema, a local Python runner, an adapter example, and the tests that verify them. There is no paid edition, hosted service, account, checkout, or support commitment attached to this repository.

## Data boundary

All fixtures are synthetic. Do not submit production logs, customer data, employer material, private conversations, prompts, credentials, or model outputs to this repository. The runner has no network client, analytics, account system, or credential handling.

## Contributing

Read [CONTRIBUTING.md](https://github.com/armantark/failset/blob/main/CONTRIBUTING.md) before proposing a case. Security-sensitive reports should use [GitHub private vulnerability reporting](https://github.com/armantark/failset/security/advisories/new), not a public issue.

## License

The public sampler is available under the [MIT License](https://github.com/armantark/failset/blob/main/LICENSE).
