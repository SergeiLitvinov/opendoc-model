"""Production imports stay inside the independent library boundary."""

import ast
import sys
from pathlib import Path

import pytest

import opendoc_model


def _check_imports(root):
    paths = list(root.rglob("*.py"))
    assert paths
    allowed = sys.stdlib_module_names | {"opendoc_model", "lxml"}
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [item.name.split(".")[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [(node.module or "").split(".")[0]]
            else:
                continue
            assert set(names) <= allowed, (str(path.relative_to(root)), names)


def test_production_imports_are_standard_library_or_document_modules():
    _check_imports(Path(opendoc_model.__file__).parent)


def test_example_names_do_not_shadow_standard_library_modules():
    examples = Path(__file__).resolve().parent.parent / "examples"
    names = {path.stem for path in examples.glob("*.py")}
    assert not names & sys.stdlib_module_names


@pytest.mark.parametrize("statement", ["import consumer_app", "from consumer_app.queue import Task"])
def test_import_boundary_rejects_consumers_in_nested_packages(tmp_path, statement):
    nested = tmp_path / "subsystem" / "nested"
    nested.mkdir(parents=True)
    (tmp_path / "__init__.py").write_text("from .subsystem import nested\n", encoding="utf-8")
    (nested / "worker.py").write_text(statement, encoding="utf-8")
    with pytest.raises(AssertionError, match="worker.py"):
        _check_imports(tmp_path)
