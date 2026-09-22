# roundtable

## Development

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management.

```bash
uv sync
```

Run quality checks (formatting, type-checking, and tests) with a single
[Poe the Poet](https://poethepoet.natehaus.co/) task:

```bash
uv run poe check
```

Formatting and type-checking always run against the whole project. By
default the test step is scoped to tests affected by recent changes, via
[`pytest-testmon`](https://testmon.org/)'s coverage-based impact analysis, so
it's fast to run often. Pass `--full` to run the complete test suite instead,
with coverage enforced against the threshold in `.coveragerc`:

```bash
uv run poe check --full
```

CI always runs `uv run poe check --full`.

Individual tasks are also available: `uv run poe format`, `uv run poe lint`,
`uv run poe typecheck` always run against the whole project; `uv run poe test`
follows the same default/`--full` split as `check`.
