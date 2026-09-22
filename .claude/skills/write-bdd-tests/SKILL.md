---
name: write-bdd-tests
description: Conventions for writing and extending this project's pytest-bdd (Given/When/Then) test suite under tests/bdd/.
user-invocable: true
---

## Directory structure

```
tests/
  __init__.py
  test_placeholder.py
  bdd/
    __init__.py
    conftest.py                # registers shared step definitions
    actions/
      __init__.py
      shell.py                 # run commands, check exit code/output
      files.py                 # assert files exist / contain text
    example/
      __init__.py
      example.feature          # Gherkin scenarios
      test_example.py          # binds the feature file, nothing else
```

Every level needs an `__init__.py` (including `tests/` itself) so
`tests.bdd.actions.*` is importable as an absolute package path.

## Writing a feature file

- Scenario text must be literal and runnable: real CLI commands, real file
  paths, real substrings to check for — not paraphrased business language.
  A reader should be able to copy a `When`/`Then` line and run it by hand.
- Reuse the generic step vocabulary already in `tests/bdd/actions/`
  (`Given a temporary directory`, `When the user runs "<command>"`,
  `Then the command exits with code <n>`, `Then the command exits with a
  non-zero code`, `Then the output contains "<text>"`,
  `Then the following files exist: <a>, <b>`,
  `Then the file "<path>" contains "<text>"`) instead of inventing new
  scenario-specific phrasing.
- The binding file, e.g. `tests/bdd/example/test_example.py`, should
  normally contain nothing but:
  ```python
  from pytest_bdd import scenarios

  scenarios("example.feature")
  ```
  Prefer keeping step functions out of it — see "Adding or changing a step"
  below for where they usually belong and the narrow exception that allows
  otherwise.

## Adding or changing a step

Prefer putting `@given`/`@when`/`@then` decorators directly on the function
that implements the step, inside a `tests/bdd/actions/<concern>.py` module
grouped by what it operates on (shell commands, files, etc.), rather than as
a thin wrapper in the feature's binding file — this keeps steps reusable
across features. This is a strong default, not a strict rule: a step that is
genuinely specific to one feature and unlikely to be reused elsewhere may
live directly in that feature's own file instead.

```python
# tests/bdd/actions/files.py
@then(parsers.parse("the following files exist: {file_list}"))
def then_files_exist(file_list: str, project_root: Path, tmp_dir: Path) -> None:
    for raw_path in file_list.split(","):
        path = Path(resolve(raw_path.strip(), project_root, tmp_dir))
        assert path.is_file(), f"missing {path}"
```

## The registration gotcha (read before adding an action module)

pytest-bdd's `@given`/`@when`/`@then` register a step's fixture by
frame-inspecting the caller and injecting it into *the module where the
decorator is textually written* — not onto the function object. So:

- A plain `import` of a step-decorated function into another module brings
  the callable, but not the registered fixture. Collection succeeds but
  every scenario fails at runtime with `StepDefinitionNotFoundError`.
- `pytest_plugins = [...]` works, but only in a genuine root `conftest.py` —
  pytest forbids it in a non-root one, so it doesn't generalize once there's
  more than one `conftest.py`.

The fix used throughout this project: import each action module with a
wildcard import and **no `__all__`** directly inside `tests/bdd/conftest.py`
(a file pytest scans for fixtures at every level of the tree, regardless of
nesting):

```python
# tests/bdd/conftest.py
from tests.bdd.actions.files import *  # noqa: E402,F403
from tests.bdd.actions.shell import *  # noqa: E402,F403
```

If an action module defines `__all__`, it must not exclude anything —
simplest is to not define `__all__` at all, since it would silently hide the
mangled `pytestbdd_stepdef_*` fixture name the decorator injects.

When adding a new `tests/bdd/actions/<concern>.py` module, add its wildcard
import to `tests/bdd/conftest.py` in the same change — a new action module
with no import into `conftest.py` will collect fine but fail every scenario
at runtime.

## Adding a new feature

1. Create `tests/bdd/<feature_name>/` with an `__init__.py`, a
   `<feature_name>.feature`, and a `test_<feature_name>.py` containing only
   `scenarios("<feature_name>.feature")`.
2. Write scenarios using the existing generic steps first.
3. Only if a needed assertion can't be expressed generically (e.g., parsing
   YAML/structured content), add a small, dedicated `@then` step to the
   relevant `tests/bdd/actions/<concern>.py` module — scoped narrowly to
   that one kind of check, not to one scenario's exact wording.
4. Replace the shipped `tests/bdd/example/` feature once you have a real one
   to test.

## Verifying changes

```bash
uv run pytest --collect-only -q   # confirm scenarios collect with no "step not found" errors
uv run pytest -v                  # confirm they pass
uv run poe lint                   # unused imports/vars after moving code around
```
