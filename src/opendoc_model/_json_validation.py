"""Validate the JSON boundary before constructing document objects."""

from __future__ import annotations

import base64
import math
from collections.abc import Callable
from typing import Any

from opendoc_model.color import ColorSpace
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import ConversionMode, FormulaFormat, ResourceKind
from opendoc_model.limits import DocumentLimits, _quota, _utf8_size

_Rule = Callable[[Any, str], None]
_SECTION_COLLECTIONS = (
    "blocks",
    "headers",
    "footers",
    "first_page_headers",
    "first_page_footers",
    "even_page_headers",
    "even_page_footers",
)


def _fail(path: str, message: str) -> None:
    raise _DiagnosticError(path, message)


def _json_tree(value: Any, path: str, limits: DocumentLimits) -> None:
    """Check extension values too, without coercing tuples, keys or objects."""
    pending = [(value, path, False)]
    active: set[int] = set()
    nodes, text_bytes = 0, 0
    while pending:
        item, location, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > limits.max_nodes:
            _quota(location, "nodes", limits.max_nodes)
        if isinstance(item, str):
            text_bytes += _utf8_size(item, limits.max_bytes, location, used=text_bytes)
        if item is None or type(item) in (str, bool, int):
            continue
        if type(item) is float:
            if not math.isfinite(item):
                _fail(location, "number must be finite")
            continue
        if not isinstance(item, (dict, list)):
            _fail(location, "expected a JSON value (object, array, string, number, boolean or null)")
        if id(item) in active:
            _fail(location, "cyclic JSON value")
        active.add(id(item))
        if len(active) > limits.max_depth:
            _quota(location, "depth", limits.max_depth)
        if len(item) > limits.max_nodes - nodes:
            _quota(location, "nodes", limits.max_nodes)
        pending.append((item, location, True))
        if isinstance(item, dict):
            for key, child in reversed(list(item.items())):
                if not isinstance(key, str):
                    _fail(location, "JSON object keys must be strings")
                text_bytes += _utf8_size(key, limits.max_bytes, location, used=text_bytes)
                pending.append((child, f"{location}[{key!r}]", False))
        else:
            pending.extend((child, f"{location}[{index}]", False) for index, child in reversed(list(enumerate(item))))


def _string(value: Any, path: str) -> None:
    if not isinstance(value, str):
        _fail(path, "expected a string")


def _nonempty(value: Any, path: str) -> None:
    _string(value, path)
    if not value:
        _fail(path, "string must not be empty")


def _boolean(value: Any, path: str) -> None:
    if type(value) is not bool:
        _fail(path, "expected a boolean")


def _integer(value: Any, path: str) -> None:
    if type(value) is not int:
        _fail(path, "expected an integer")


def _number(value: Any, path: str) -> None:
    if type(value) not in (int, float):
        _fail(path, "expected a finite number")
    if type(value) is float and not math.isfinite(value):
        _fail(path, "number must be finite")
    if type(value) is int:
        try:
            float(value)
        except OverflowError as error:
            raise ValueError(f"{path}: number is outside the finite float range") from error


def _fraction(value: Any, path: str) -> None:
    _number(value, path)
    if not 0 <= value <= 1:
        _fail(path, "number must be between 0 and 1")


def _bag(value: Any, path: str) -> None:
    if not isinstance(value, dict):
        _fail(path, "expected an object")


def _nullable(rule: _Rule) -> _Rule:
    def validate(value: Any, path: str) -> None:
        if value is not None:
            rule(value, path)

    return validate


def _array(rule: _Rule) -> _Rule:
    def validate(value: Any, path: str) -> None:
        if not isinstance(value, list):
            _fail(path, "expected an array")
        for index, item in enumerate(value):
            rule(item, f"{path}[{index}]")

    return validate


def _choice(choices: set[str]) -> _Rule:
    def validate(value: Any, path: str) -> None:
        if not isinstance(value, str) or value not in choices:
            _fail(path, f"unsupported value: {value!r}")

    return validate


def _record(
    value: Any,
    path: str,
    required: dict[str, _Rule],
    optional: dict[str, _Rule] | None = None,
    *,
    reject_unknown: bool = False,
) -> None:
    _bag(value, path)
    for name, rule in required.items():
        if name not in value:
            _fail(f"{path}.{name}", "required field is missing")
        rule(value[name], f"{path}.{name}")
    for name, rule in (optional or {}).items():
        if name in value:
            rule(value[name], f"{path}.{name}")
    if reject_unknown:
        for name in value.keys() - required.keys() - (optional or {}).keys():
            _fail(f"{path}.{name}", "unsupported field")


def _mapping(rule: _Rule, *, identity: str | None = None) -> _Rule:
    def validate(value: Any, path: str) -> None:
        _bag(value, path)
        for key, item in value.items():
            location = f"{path}[{key!r}]"
            rule(item, location)
            if identity is not None and item.get(identity, key) != key:
                _fail(f"{location}.{identity}", f"must match object key {key!r}")

    return validate


def _binary(value: Any, path: str) -> None:
    _string(value, path)
    try:
        base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError(f"{path}: invalid base64 data") from error


def _box(value: Any, path: str) -> None:
    _record(value, path, dict.fromkeys(("x", "y", "width", "height"), _number), {"rotation": _number}, reject_unknown=True)


def _crop(value: Any, path: str) -> None:
    _record(value, path, {}, dict.fromkeys(("left", "top", "right", "bottom"), _number), reject_unknown=True)


def _color(value: Any, path: str) -> None:
    if isinstance(value, str):
        return  # Legacy color strings are retained, not interpreted as CSS here.
    _record(
        value,
        path,
        {"space": _choice({item.value for item in ColorSpace}), "components": _array(_fraction)},
        {"alpha": _fraction, "icc_profile": _nullable(_string), "blend_mode": _nonempty},
    )
    expected = 3 if value["space"] == "srgb" else 4
    if len(value["components"]) != expected:
        _fail(f"{path}.components", f"expected {expected} components")
    if not value.get("blend_mode", "normal").strip():
        _fail(f"{path}.blend_mode", "blend mode must not be empty")


def _style(value: Any, path: str) -> None:
    optional = dict.fromkeys(("font_family", "language"), _nullable(_string))
    optional.update(dict.fromkeys(("bold", "italic", "underline", "superscript", "subscript"), _nullable(_boolean)))
    optional.update(dict.fromkeys(("color", "background"), _nullable(_color)))
    optional.update({"font_size_pt": _nullable(_number), "properties": _bag})
    _record(value, path, {}, optional)


def _event(value: Any, path: str) -> None:
    _record(value, path, {"operation": _string}, {"detail": _string, "fallback_reason": _nullable(_string)})


def _provenance(value: Any, path: str) -> None:
    optional = dict.fromkeys(("source_path", "object_id", "package_part"), _nullable(_string))
    optional.update({"page": _nullable(_integer), "events": _array(_event)})
    _record(value, path, {"source_format": _string}, optional)


def _surrogate(value: Any, path: str) -> None:
    _record(
        value,
        path,
        {"resource_id": _nonempty, "reason": _nonempty},
        {"media_type": _nullable(_string), "fidelity": _nullable(_fraction)},
    )


def _resource(value: Any, path: str) -> None:
    _record(
        value,
        path,
        {"id": _nonempty, "kind": _choice({item.value for item in ResourceKind}), "media_type": _string},
        {
            "data_base64": _nullable(_binary),
            "source": _nullable(_string),
            "filename": _nullable(_string),
            "properties": _bag,
            "provenance": _nullable(_provenance),
        },
    )
    if value.get("data_base64") is None and value.get("source") is None:
        _fail(path, "resource requires either data or source")


def _part(value: Any, path: str) -> None:
    _record(value, path, {"media_type": _string, "data_base64": _binary}, {"name": _string})
    if "name" in value and not value["name"].startswith("/"):
        _fail(f"{path}.name", "package part name must be absolute")


def _relationship(value: Any, path: str) -> None:
    _record(
        value,
        path,
        dict.fromkeys(("id", "relationship_type", "source", "target"), _string),
        {"external": _boolean},
    )


def _package(value: Any, path: str) -> None:
    _record(
        value,
        path,
        {},
        {"format": _string, "root": _string, "parts": _mapping(_part, identity="name"), "relationships": _array(_relationship)},
    )
    for name in value.get("parts", {}):
        if not name.startswith("/"):
            _fail(f"{path}.parts[{name!r}]", "package part name must be absolute")


def _cell(value: Any, path: str) -> None:
    _record(value, path, {}, {"blocks": _array(_block), "row_span": _integer, "column_span": _integer, "properties": _bag})


def _row(value: Any, path: str) -> None:
    _record(value, path, {}, {"cells": _array(_cell), "properties": _bag})


def _block_group_owner(value: Any, path: str) -> None:
    _record(value, path, {"paragraph_id": _string})


def _element(value: Any, path: str, *, inline: bool) -> None:
    _record(value, path, {"type": _string})
    kind = value["type"]
    supported = {"text", "image", "formula"} if inline else {"paragraph", "table", "image", "formula", "block_group"}
    if kind not in supported:
        _fail(f"{path}.type", f"unsupported element type: {kind!r}")
    optional = {"properties": _bag, "provenance": _nullable(_provenance), "visual_surrogate": _nullable(_surrogate)}
    required: dict[str, _Rule] = {}
    if kind == "text":
        optional.update({"text": _string, "style": _style, "link": _nullable(_string)})
    else:
        optional["box"] = _nullable(_box)
    if kind == "block_group":
        optional.update(
            {"children": _array(_block), "role": _choice({"generic", "quotation"}), "list_owner": _nullable(_block_group_owner)}
        )
    if kind == "paragraph":
        optional.update({"content": _array(_inline), "style_id": _nullable(_string), "alignment": _nullable(_string)})
    elif kind == "table":
        optional.update({"rows": _array(_row), "style_id": _nullable(_string)})
    elif kind == "image":
        required["resource_id"] = _string
        optional.update({"alt_text": _string, "crop": _nullable(_crop)})
    elif kind == "formula":
        required["format"] = _choice({item.value for item in FormulaFormat})
        optional.update({"value": _string, "display": _boolean, "fallback_text": _string})
    _record(value, path, required, optional)


def _inline(value: Any, path: str) -> None:
    _element(value, path, inline=True)


def _block(value: Any, path: str) -> None:
    _element(value, path, inline=False)


def _page(value: Any, path: str) -> None:
    _record(
        value,
        path,
        {},
        dict.fromkeys(
            ("width_pt", "height_pt", "margin_top_pt", "margin_right_pt", "margin_bottom_pt", "margin_left_pt"), _number
        ),
    )


def _section(value: Any, path: str) -> None:
    optional = dict.fromkeys(_SECTION_COLLECTIONS, _array(_block))
    optional.update({"page": _page, "properties": _bag, "provenance": _nullable(_provenance)})
    _record(value, path, {}, optional)


def _validate_document_payload(
    value: Any,
    *,
    format_name: str,
    format_versions: frozenset[int],
    property_schema_version: int,
    limits: DocumentLimits,
) -> None:
    _json_tree(value, "$", limits)
    _bag(value, "$")
    if value.get("format") != format_name:
        _fail("$.format", f"unsupported document format: {value.get('format')!r}")
    version = value.get("version")
    if type(version) is not int or version not in format_versions:
        _fail("$.version", f"unsupported document version: {version!r}")
    _record(value, "$", {"document": _bag})
    raw = value["document"]
    # Estimate canonical base64 sizes before the strict binary validator
    # decodes anything. Invalid short data is still rejected by _binary.
    embedded = 0
    groups = [(raw.get("resources"), "$.document.resources")]
    package = raw.get("package")
    if isinstance(package, dict):
        groups.append((package.get("parts"), "$.document.package.parts"))
    for group, path in groups:
        if not isinstance(group, dict):
            continue
        for name, item in group.items():
            encoded = item.get("data_base64") if isinstance(item, dict) else None
            if isinstance(encoded, str):
                embedded += len(encoded.rstrip("=")) * 3 // 4
                if embedded > limits.max_embedded_bytes:
                    _quota(f"{path}[{name!r}].data_base64", "embedded bytes", limits.max_embedded_bytes)
    schema = raw.get("property_schema_version", 1)
    if type(schema) is not int or schema != property_schema_version:
        _fail("$.document.property_schema_version", f"unsupported property schema version: {schema!r}")
    _record(
        raw,
        "$.document",
        {},
        {
            "mode": _choice({item.value for item in ConversionMode}),
            "source_format": _nullable(_string),
            "metadata": _bag,
            "package": _nullable(_package),
            "styles": _mapping(_style),
            "resources": _mapping(_resource, identity="id"),
            "sections": _array(_section),
        },
    )
