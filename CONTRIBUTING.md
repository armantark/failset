# Contributing

Bug reports and corrections to existing public cases are welcome after the repository launches.

Do not submit production logs, customer data, non-public organizational material, private conversations, prompts, credentials, model outputs, or transformed versions of private sources. A proposed fixture must be synthetic and reproducible from public protocol behavior.

A case correction should include its strict output schema, typed relational checks where needed, one passing fixture, one deliberately failing fixture, and the expected error code. Run these checks before opening a pull request:

```bash
uv sync --locked --extra dev
uv run failset verify
uv run pytest
```

If a change touches the case format or generated schema, also run the independent JavaScript validator:

```bash
npm ci --ignore-scripts
npm run check:schema
```

Use GitHub private vulnerability reporting for security issues. Do not include private input or output data in a security report.
