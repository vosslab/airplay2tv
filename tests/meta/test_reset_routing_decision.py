"""Focused test of the reset keep/remove decision for submit_to_pypi.py.

reset_repo.py decides whether to keep or git-rm devel/submit_to_pypi.py from the
result of repolib.model.select_overlay_dirs(project_type, repo_root): the
'python/_pypi' overlay is selected exactly when the repo has a pyproject.toml,
and the tool is kept only when that overlay applies (reset_repo.py computes
`pypi_applies = publish_pypi or f"{project_type}/_pypi" in overlay_dirs`).

Rather than run a full interactive bootstrap, this exercises that shared rule
directly against synthetic tmp_path repos. select_overlay_dirs is the single
source of truth reset reuses, so testing it covers the reset decision without
the slow end-to-end path.
"""

import pathlib

import repolib.model


PYPI_OVERLAY = 'python/_pypi'


def test_python_with_pyproject_selects_pypi_overlay(tmp_path: pathlib.Path) -> None:
	"""python repo WITH pyproject.toml selects the _pypi overlay (tool kept)."""
	(tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
	overlay_dirs = repolib.model.select_overlay_dirs('python', str(tmp_path))
	assert PYPI_OVERLAY in overlay_dirs


def test_python_without_pyproject_omits_pypi_overlay(tmp_path: pathlib.Path) -> None:
	"""python repo WITHOUT pyproject.toml omits the _pypi overlay (tool removed)."""
	overlay_dirs = repolib.model.select_overlay_dirs('python', str(tmp_path))
	assert PYPI_OVERLAY not in overlay_dirs


def test_non_python_omits_pypi_overlay_even_with_pyproject(tmp_path: pathlib.Path) -> None:
	"""A non-python repo never selects the python/_pypi overlay (tool removed)."""
	(tmp_path / 'pyproject.toml').write_text('[project]\nname = "x"\n')
	for project_type in ('typescript', 'other'):
		overlay_dirs = repolib.model.select_overlay_dirs(project_type, str(tmp_path))
		assert PYPI_OVERLAY not in overlay_dirs
