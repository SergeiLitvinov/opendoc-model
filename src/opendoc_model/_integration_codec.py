"""Closed typed codec: JSON never selects Python classes, imports or callbacks."""

from __future__ import annotations

import math
import types
from copy import deepcopy
from dataclasses import MISSING, fields, is_dataclass
from enum import Enum
from functools import lru_cache
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.integration_types import IntegrationModel, IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model


def _fail(path: str, message: str) -> Any:
    raise _DiagnosticError(path, message, "integration.invalid")


@lru_cache(maxsize=64)
def _hints(kind: type[Any]) -> dict[str, Any]:
    return get_type_hints(kind)


def _convert(value: Any, annotation: Any, path: str, *, encode: bool) -> Any:
    if annotation is Any:
        return deepcopy(value)
    origin, arguments = get_origin(annotation), get_args(annotation)
    if origin in (types.UnionType, Union):
        # Prefer exact primitive types: bool is not a number, numeric strings are not coerced.
        candidates = sorted(arguments, key=lambda kind: kind is not type(value))
        for kind in candidates:
            try:
                return _convert(value, kind, path, encode=encode)
            except _DiagnosticError:
                pass
        return _fail(path, "value does not match the declared union")
    if origin is Literal:
        if not any(type(value) is type(item) and value == item for item in arguments):
            return _fail(path, f"expected one of {arguments!r}")
        return value
    if annotation is type(None):
        return None if value is None else _fail(path, "expected null")
    if annotation in (str, int, bool):
        return value if type(value) is annotation else _fail(path, f"expected {annotation.__name__}")
    if annotation is float:
        if type(value) not in (int, float):
            return _fail(path, "expected a finite number")
        try:
            converted = float(value)
        except OverflowError:
            return _fail(path, "number exceeds the finite floating point range")
        return converted if math.isfinite(converted) else _fail(path, "expected a finite number")
    if origin is tuple:
        if type(value) not in ((tuple,) if encode else (list,)):
            return _fail(path, "expected tuple" if encode else "expected array")
        variable = len(arguments) == 2 and arguments[1] is Ellipsis
        if not variable and len(value) != len(arguments):
            return _fail(path, "wrong tuple length")
        sequence = [
            _convert(item, arguments[0] if variable else arguments[index], f"{path}[{index}]", encode=encode)
            for index, item in enumerate(value)
        ]
        return sequence if encode else tuple(sequence)
    if origin in (dict, list):
        if type(value) is not origin:
            return _fail(path, f"expected {origin.__name__}")
        if origin is list:
            return [_convert(item, arguments[0], f"{path}[{index}]", encode=encode) for index, item in enumerate(value)]
        return {
            _convert(key, arguments[0], path, encode=encode): _convert(item, arguments[1], f"{path}[{key!r}]", encode=encode)
            for key, item in value.items()
        }
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        if encode:
            return value.value if isinstance(value, annotation) else _fail(path, "expected declared enum")
        try:
            return annotation(value)
        except (ValueError, TypeError) as error:
            return _fail(path, str(error))
    if isinstance(annotation, type) and is_dataclass(annotation):
        if encode and type(value) is not annotation or not encode and type(value) is not dict:
            return _fail(path, f"expected {annotation.__name__}" if encode else "expected object")
        definitions = fields(annotation)
        names = {item.name for item in definitions if item.name != "extra"}
        extensible = issubclass(annotation, IntegrationRecord)
        if not encode and "extra" in value:
            return _fail(path, "extra is reserved for the Python unknown-field carrier")
        result = {}
        if encode:
            extras = value.extra if extensible else {}
            if not isinstance(extras, dict) or names.intersection(extras) or "extra" in extras:
                return _fail(path, "extra fields must not shadow schema fields")
            result.update(deepcopy(extras))
        elif not extensible and set(value) - names:
            return _fail(path, "unknown fields in existing core record")
        hints = _hints(annotation)
        for item in definitions:
            if item.name == "extra":
                continue
            if encode:
                raw = getattr(value, item.name)
                if item.metadata.get("omit_default") and raw == item.default:
                    continue
            elif item.name in value:
                raw = value[item.name]
            elif item.default is not MISSING or item.default_factory is not MISSING:
                continue
            else:
                return _fail(f"{path}.{item.name}", "missing required field")
            result[item.name] = _convert(raw, hints[item.name], f"{path}.{item.name}", encode=encode)
        if encode:
            return result
        if extensible:
            result["extra"] = deepcopy({key: raw for key, raw in value.items() if key not in names})
        try:
            return annotation(**result)
        except (ValueError, TypeError) as error:
            return _fail(path, str(error))
    return _fail(path, "unsupported internal schema type")


def _encode_integration(model: IntegrationModel, limits: DocumentLimits) -> dict[str, Any]:
    _guard_model(model, limits)
    data: dict[str, Any] = _convert(model, IntegrationModel, "integration", encode=True)
    _json_tree(data, "integration", limits)
    return data


def _decode_integration(data: Any, limits: DocumentLimits) -> IntegrationModel:
    _json_tree(data, "integration", limits)
    result: IntegrationModel = _convert(data, IntegrationModel, "integration", encode=False)
    return result
