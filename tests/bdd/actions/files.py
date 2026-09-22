"""Reusable file/content step definitions shared across feature files."""

from __future__ import annotations

from pathlib import Path

from pytest_bdd import parsers, then

from tests.bdd.actions.shell import resolve


@then(parsers.parse("the following files exist: {file_list}"))
def then_files_exist(file_list: str, project_root: Path, tmp_dir: Path) -> None:
    for raw_path in file_list.split(","):
        path = Path(resolve(raw_path.strip(), project_root, tmp_dir))
        assert path.is_file(), f"missing {path}"


@then(parsers.parse('the file "{path}" contains "{text}"'))
def then_file_contains(path: str, text: str, project_root: Path, tmp_dir: Path) -> None:
    resolved_path = Path(resolve(path, project_root, tmp_dir))
    assert resolved_path.is_file(), f"missing {resolved_path}"
    assert text in resolved_path.read_text()
