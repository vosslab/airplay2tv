"""Behavioral equivalence tests for check_function_annotations and check_no_typing_import.

Pins the accept/reject behavior of the two top-level check functions in
tests/test_function_typing.py so a later refactor of messages or structure
cannot silently change the gate.

Imports the check functions directly from the sibling test module. The meta
conftest.py adds tests/ to sys.path, making test_function_typing importable
as a plain module name.
"""
# Standard Library
import ast
import pathlib

# local repo modules
import test_function_typing


#============================================
# Helpers
#============================================

def _parse(source: str, tmp_path: pathlib.Path) -> ast.Module:
	"""Write source to a tmp file and parse it into an ast.Module.

	Args:
		source: Python source text.
		tmp_path: pytest tmp_path fixture directory.

	Returns:
		ast.Module: Parsed AST module.
	"""
	# Use a stable filename so the rel string in violations is deterministic.
	tmp_file = tmp_path / "subject.py"
	tmp_file.write_text(source, encoding="utf-8")
	tree = ast.parse(source, filename=str(tmp_file))
	return tree


#============================================
# check_function_annotations: violation cases
#============================================

def test_missing_return_annotation_yields_violation(tmp_path: pathlib.Path) -> None:
	"""A def with no return annotation produces a non-empty violation list."""
	source = "def foo(x: int):\n\tpass\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_function_annotations(tree, "subject.py")
	assert violations


def test_missing_param_annotation_yields_violation(tmp_path: pathlib.Path) -> None:
	"""A def with an unannotated parameter produces a non-empty violation list."""
	source = "def foo(x) -> int:\n\treturn x\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_function_annotations(tree, "subject.py")
	assert violations


#============================================
# check_function_annotations: clean cases
#============================================

def test_bare_type_annotation_is_clean(tmp_path: pathlib.Path) -> None:
	"""A def annotated with bare types (x: object, -> list) yields no violation."""
	source = "def foo(x: object) -> list:\n\treturn [x]\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_function_annotations(tree, "subject.py")
	assert not violations


def test_parametrized_generic_annotation_is_clean(tmp_path: pathlib.Path) -> None:
	"""A def annotated with a parametrized generic (-> list[str]) yields no violation."""
	source = "def foo(x: dict) -> list[str]:\n\treturn []\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_function_annotations(tree, "subject.py")
	assert not violations


def test_self_cls_exempt_from_annotation(tmp_path: pathlib.Path) -> None:
	"""self and cls are exempt from annotation and do not cause a violation."""
	source = (
		"class MyClass:\n"
		"\tdef method(self) -> None:\n"
		"\t\tpass\n"
		"\t@classmethod\n"
		"\tdef klass(cls) -> None:\n"
		"\t\tpass\n"
	)
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_function_annotations(tree, "subject.py")
	assert not violations


#============================================
# check_no_typing_import: violation cases
#============================================

def test_from_typing_import_yields_violation(tmp_path: pathlib.Path) -> None:
	"""A `from typing import ...` line produces a non-empty violation list."""
	source = "from typing import List\ndef foo(x: int) -> int:\n\treturn x\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_no_typing_import(tree, "subject.py")
	assert violations


def test_import_typing_yields_violation(tmp_path: pathlib.Path) -> None:
	"""A `import typing` line produces a non-empty violation list."""
	source = "import typing\ndef foo(x: int) -> int:\n\treturn x\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_no_typing_import(tree, "subject.py")
	assert violations


#============================================
# check_no_typing_import: clean cases
#============================================

def test_no_typing_import_is_clean(tmp_path: pathlib.Path) -> None:
	"""A file with no typing import yields no violation."""
	source = "import os\ndef foo(x: int) -> int:\n\treturn x\n"
	tree = _parse(source, tmp_path)
	violations = test_function_typing.check_no_typing_import(tree, "subject.py")
	assert not violations
