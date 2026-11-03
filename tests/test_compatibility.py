"""Saved contracts catch accidental API and persisted-schema breakage."""

import ast
import importlib
import inspect
import json
import types
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import get_args, get_origin, get_type_hints

import pytest

import opendoc_model
from opendoc_model import ColorValue, FormulaFormat, document_from_json, document_to_json

FIXTURES = Path(__file__).parent / "fixtures/compatibility"


def _default(value):
    if value is inspect.Parameter.empty:
        return None
    if type(value) is object:
        return "<object sentinel>"
    if isinstance(value, frozenset):
        return "frozenset({" + ", ".join(sorted(repr(item) for item in value)) + "})" if value else "frozenset()"
    return repr(value)


def _parameters(value):
    return [
        {
            "name": parameter.name,
            "kind": parameter.kind.name,
            "default": _default(parameter.default),
        }
        for parameter in inspect.signature(value).parameters.values()
    ]


def _exports(module):
    if hasattr(module, "__all__"):
        return module.__all__
    tree = ast.parse(Path(module.__file__).read_text(encoding="utf-8-sig"))
    return [
        node.name for node in tree.body if isinstance(node, (ast.ClassDef, ast.FunctionDef)) and not node.name.startswith("_")
    ]


def _describe(value):
    if inspect.isclass(value) and issubclass(value, Enum):
        return {"enum": {name: item.value for name, item in value.__members__.items()}}
    if inspect.isclass(value) and issubclass(value, BaseException):
        return {"exception_bases": [base.__name__ for base in value.__mro__[1:]]}
    if inspect.isfunction(value) or (inspect.isclass(value) and value.__module__.startswith("opendoc_model")):
        # TypedDict classes expose a mapping schema rather than a runtime signature.
        if hasattr(value, "__required_keys__"):
            return {
                "required_keys": sorted(value.__required_keys__),
                "optional_keys": sorted(value.__optional_keys__),
                "field_types": {name: _type_contract(annotation) for name, annotation in get_type_hints(value).items()},
            }
        result = {"parameters": _parameters(value)}
        if inspect.isclass(value):
            result["members"] = {}
            for name in dir(value):
                if name.startswith("_"):
                    continue
                member = inspect.getattr_static(value, name)
                if isinstance(member, property):
                    result["members"][name] = {"property": True, "writable": member.fset is not None}
                elif isinstance(member, (classmethod, staticmethod)) or inspect.isfunction(member):
                    result["members"][name] = {"parameters": _parameters(getattr(value, name))}
            if is_dataclass(value):
                result["factories"] = {
                    item.name: repr(item.default_factory()) for item in fields(value) if callable(item.default_factory)
                }
        return result
    if isinstance(value, frozenset):
        return {"constant": sorted(value)}
    if isinstance(value, types.UnionType) or get_origin(value) is not None:
        return {"constant": str(value)}
    return {"constant": str(value)}


def _type_contract(annotation):
    """Stable type trees, independent of annotation spelling or union ordering."""
    origin = get_origin(annotation)
    if origin is types.UnionType:
        return {"union": sorted((_type_contract(item) for item in get_args(annotation)), key=lambda item: json.dumps(item))}
    if origin is not None:
        return {"origin": _type_contract(origin), "arguments": [_type_contract(item) for item in get_args(annotation)]}
    if not hasattr(annotation, "__qualname__"):
        return {"literal": repr(annotation)}
    module = annotation.__module__
    return f"{module}.{annotation.__qualname__}"


def _saved_module(name):
    """Resolve the explicitly saved public module."""
    return importlib.import_module(name)


def _assert_parameters_compatible(expected, actual, label):
    assert actual[: len(expected)] == expected, label
    assert all(
        item["default"] is not None or item["kind"] in {"VAR_POSITIONAL", "VAR_KEYWORD"} for item in actual[len(expected) :]
    ), label


def _assert_contract(expected, actual, label):
    if "parameters" in expected:
        _assert_parameters_compatible(expected["parameters"], actual["parameters"], label)
    for category in ("enum", "members", "factories"):
        for name, contract in expected.get(category, {}).items():
            assert name in actual[category], f"{label}.{name}"
            if category == "members" and "parameters" in contract:
                _assert_parameters_compatible(contract["parameters"], actual[category][name]["parameters"], f"{label}.{name}")
            else:
                assert actual[category][name] == contract, f"{label}.{name}"
    for category in ("exception_bases", "required_keys", "optional_keys", "field_types", "constant"):
        if category in expected:
            assert actual[category] == expected[category], label


def test_saved_public_api_contract():
    baseline = json.loads((FIXTURES / "api-0.1.json").read_text(encoding="utf-8"))
    for module_name, exports in baseline["modules"].items():
        module = _saved_module(module_name)
        assert set(exports) <= set(_exports(module)), module_name
        for name, contract in exports.items():
            value = getattr(module, name)
            _assert_contract(contract, _describe(value), f"{module_name}.{name}")
    for name, source_module in baseline["root_identities"].items():
        assert getattr(opendoc_model, name) is getattr(_saved_module(source_module), name), name
    for class_name, expected in baseline.get("result_returns", {}).items():
        annotations = get_type_hints(
            getattr(opendoc_model, class_name).to_dict, localns={"DocumentLimits": opendoc_model.DocumentLimits}
        )
        assert _type_contract(annotations["return"]) == expected, class_name


@pytest.mark.parametrize("version", [1, 2])
def test_saved_document_schemas_are_read_without_regenerating_input(version):
    document = document_from_json((FIXTURES / f"document-v{version}.json").read_bytes())
    assert document.version == 2
    assert document.validate() == []
    paragraph = document.sections[0].blocks[0]
    if version == 1:
        assert paragraph.content[0].text == "Архивный документ"
        assert paragraph.content[0].style.bold is False
        assert paragraph.content[0].properties["custom"] == {"source": "v1"}
        assert paragraph.style_id == "body"
        assert document.styles["body"].color == "#123456"
        assert document.resources["photo"].data == b"\x00\x01\xff"
        assert document.resources["docx-footnotes"].data == b"<notes/>"
        assert document.package is None
        assert document.metadata["custom"]["tags"] == ["архив", None, True]
        assert document.sections[0].headers[0].plain_text == "Архив"
    else:
        paragraph = paragraph.rows[0].cells[0].blocks[0]
        assert paragraph.content[1].format is FormulaFormat.LATEX
        assert paragraph.content[1].value == "x^2"
        assert paragraph.provenance.events[0].operation == "normalize"
        assert paragraph.visual_surrogate.fidelity == 0.9
        assert document.resources["empty"].data == b""
        assert document.resources["external"].source == "assets/data.bin"
        assert document.resources["preview"].data == b"<svg/>"
        assert document.package.parts["/main"].data == b"\x00\x01\xff"
        assert document.package.relationships[1].external is True
        assert isinstance(document.styles["accent"].color, ColorValue)
        assert document.styles["accent"].color.components == (0.25, 0.5, 0.75)
        assert document.metadata["custom"]["unknown"] == [1, "текст", None]
        assert document.sections[0].footers[0].plain_text == "Конец"
    written = document_to_json(document)
    assert json.loads(written)["version"] == 2
    assert document_to_json(document_from_json(written)) == written


@pytest.mark.parametrize("breaking_change", ["remove", "default", "kind", "required"])
def test_contract_comparison_rejects_incompatible_signatures(breaking_change):
    expected = [{"name": "path", "kind": "POSITIONAL_OR_KEYWORD", "default": "None"}]
    actual = [dict(expected[0])]
    if breaking_change == "remove":
        actual.clear()
    elif breaking_change == "default":
        actual[0]["default"] = "'new'"
    elif breaking_change == "kind":
        actual[0]["kind"] = "KEYWORD_ONLY"
    else:
        actual.append({"name": "new", "kind": "KEYWORD_ONLY", "default": None})
    with pytest.raises(AssertionError):
        _assert_parameters_compatible(expected, actual, "example")


def test_contract_comparison_permits_optional_addition():
    expected = [{"name": "path", "kind": "POSITIONAL_OR_KEYWORD", "default": "None"}]
    _assert_parameters_compatible(expected, [*expected, {"name": "new", "kind": "KEYWORD_ONLY", "default": "False"}], "example")


@pytest.mark.parametrize("actual", [{}, {"valid": "builtins.str"}, {"valid": "typing.Any"}])
def test_contract_comparison_rejects_removed_or_weakened_result_fields(actual):
    with pytest.raises(AssertionError):
        _assert_contract({"field_types": {"valid": "builtins.bool"}}, {"field_types": actual}, "InspectionData")


def test_all_explicit_root_reexports_are_available_to_star_import():
    tree = ast.parse(Path(opendoc_model.__file__).read_text(encoding="utf-8"))
    declared = {
        alias.asname or alias.name
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 1
        for alias in node.names
    }
    namespace = {}
    exec("from opendoc_model import *", namespace)
    assert declared <= set(opendoc_model.__all__) <= namespace.keys()
    assert all(namespace[name] is getattr(opendoc_model, name) for name in declared)
