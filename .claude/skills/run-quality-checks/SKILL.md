---
name: run-quality-checks
description: Run this project's quality-check suite (formatting, type-checking, coverage-enforced tests) via Poe the Poet.
user-invocable: true
---

## Instructions

Run the project's combined quality-check task:

```bash
uv run poe check
```

1. `ruff format --check` — verifies formatting (does not modify files), against the entire project
2. `pyright` — static type checking, against the entire project
3. `pytest` — by default, tests are scoped to those affected by recent changes via `pytest-testmon`'s coverage-based impact analysis, with no coverage enforcement; pass `--full` (`uv run poe check --full`) to run the complete suite with coverage enforced against the threshold in `.coveragerc` (minimum 80%)

Report the result to the user. If it fails, the output names the specific
step that failed — fix that issue, then re-run `uv run poe check` until it
passes. Before considering a change complete, run `uv run poe check --full`
at least once to get the same full-project, coverage-enforced guarantee CI
enforces (CI always runs `uv run poe check --full`).

Individual steps can also be run on their own when narrowing down an issue:

- `uv run poe format` — apply formatting, against the entire project
- `uv run poe lint` — lint checks, against the entire project
- `uv run poe typecheck` — type checking only, against the entire project
- `uv run poe test` — tests only, following the same default (testmon-scoped) / `--full` (whole suite, coverage enforced) split as `check`
