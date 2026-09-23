# roundtable

Multi-agent adversarial review for OpenSpec changes and their code. A
developer agent drafts a specification (or an implementation), a panel of
reviewer agents critiques it in parallel, and rounds continue until the
panel reaches consensus, declares a deadlock, or the round limit is
reached. Agents run in isolated terminal panes managed by
[`herdr`](https://github.com/anthropics/herdr), and every drafted artifact,
critique, and decision is recorded as an append-only event log per
specification.

## Installation

Requires `git` and [`herdr`](https://github.com/anthropics/herdr) on `PATH`.

```bash
uv tool install roundtable
```

or, from a checkout:

```bash
uv sync
uv run roundtable --help
```

## Usage

### `roundtable init`

Turn a directory into a review workspace: a Git repository (if not already
one), an OpenSpec layout, a gitignored `.roundtable/` event store and
scratch directory, and an agent roster configuration (`roundtable.toml`).

```bash
roundtable init ./my-project
```

Run without `--config`, `init` prompts interactively for the roster (agent
count, each agent's role and LLM kind) and round limit, pre-populating its
prompts from `./my-project/roundtable.toml` if one already exists. To skip
every prompt, pass a config file shaped like `roundtable.toml`:

```bash
roundtable init ./my-project --config roster.toml
```

`init` refuses to overwrite an existing workspace unless `--reinit` is
passed, and refuses to run at all if `git` or a compatible `herdr` is not
on `PATH` — in both cases no files are written.

### `roundtable review spec|code`

Start a review round for a specification id, keyed by `--path` (the
workspace root, defaulting to `.`):

```bash
roundtable review spec widget-api --description "a self-sealing stem bolt"
```

`review spec` requires a build context, given either inline with
`--description` or read from a file with `--context-file`; without one of
these, the command exits `1` and starts no agent turn. Once the spec phase
reaches consensus, start the code phase, which seeds the developer's first
draft from the approved specification:

```bash
roundtable review code widget-api
```

`review code` requires the spec phase to have already reached consensus
for that specification id; if it hasn't, the command exits `1` and starts
no agent turn. The spec and code phases are recorded as independent event
histories (`widget-api` and `widget-api:code`), so the code phase can be
started as a separate invocation at any later time.

If a round ends in a deadlock, `review` asks whether to resume with a new
round; declining ends the run at that deadlock.

Exit codes, for either target:

| Code | Meaning |
| ---- | ------- |
| `0`  | Consensus reached |
| `1`  | Orchestration failed, or the target's prerequisites (build context for `spec`, prior consensus for `code`) were not met |
| `2`  | The run ended in an unresolved deadlock |

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
