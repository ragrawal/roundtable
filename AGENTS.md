# AGENTS.md

Guidance for AI coding assistants working in this repository.

## Project

roundtable

## Tooling

- Dependency management: [`uv`](https://docs.astral.sh/uv/) (`uv sync`, `uv add`)
- Lint + format: `ruff` (config: `ruff.toml`)
- Type checking: `pyright` (config: `pyrightconfig.json`)
- Tests + coverage: `pytest` + `pytest-cov` (config: `pytest.ini`, `.coveragerc`; minimum coverage 80%)
- Task runner: [Poe the Poet](https://poethepoet.natehaus.co/) (config: `poe_tasks.toml`)

## Running quality checks

Run the quality-check task before considering a change complete:

```bash
uv run poe check --full
```

See the `run-quality-checks` skill for the individual steps, the default
testmon-scoped vs. `--full` behavior, and per-step commands.

## Coding Principles

These are defaults, not strict rules. If a case genuinely warrants an
exception, ask for approval before deviating rather than silently doing so.

- **Domain-model-first, thin controllers**: identify the key domain concepts
  and push validation and business logic onto domain objects — Pydantic for
  validation-heavy models, `dataclasses` for simpler value objects. Keep
  controllers/handlers/routes minimal, delegating to the domain layer.
- **DRY for business logic**: don't duplicate logic; extract functions that
  each do one specific, meaningful thing.
- **Fail fast and loud, no defensive programming**: validate hard at
  domain-model construction/boundaries; never silently default or swallow
  errors downstream. For example, index into `os.environ[...]` rather than
  assume a default via `os.environ.get(...)`. Trust an invariant once
  established instead of re-checking it everywhere downstream.
- **Deliberate dependency choice**: before writing a workaround for a
  library's limitation, check whether it's being misused or a leaner option
  already exists. When adding a new dependency, consider whether a single
  more comprehensive library would replace one or more existing
  dependencies — if so, recommend consolidating onto it and removing the
  superseded ones.
- **Domain-language naming**: name types, functions, and variables after the
  domain concepts they represent, not generic or purely technical terms.
- **Test-driven, easy to extend**: structure tests so a human can add a new
  scenario easily — favor `pytest.mark.parametrize` over one bespoke test
  function per case where the cases share shape, pairing it with
  `pytest.param(..., id="...")` so each case gets a descriptive,
  human-readable name instead of a positional index.
- **Discuss algorithm complexity**: before implementing non-trivial logic,
  briefly discuss the algorithm options considered and their
  time/space complexity, rather than silently picking one.
- **Document public classes and methods**: every public class and
  function/method must have a Google-style docstring describing its
  purpose, enforced by the bundled lint step's docstring rules (`ruff`'s
  `D` rules, configured with `convention = "google"`); private
  (leading-underscore) helpers and test functions are exempt.
- **Self-documenting Pydantic models**: define every Pydantic `BaseModel`
  field via `Field(..., description="...")`, even when no other validation
  is needed, so the model's JSON schema documents itself.

## Conventions

- Source code lives under `src/roundtable/`.
- Tests live under `tests/`.
- Each tool's configuration lives in its own dedicated file — don't merge them
  into `pyproject.toml`.
