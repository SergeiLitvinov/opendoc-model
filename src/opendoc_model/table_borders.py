"""Explicit table/cell border declarations; no layout or native border conflict rules."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any, Literal, TypeAlias, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.color import ColorValue
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, Table, TableCell
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.traversal import ModelNode, _walk_locations

TABLE_BORDERS_PROPERTY = "opendoc.table-borders"
CELL_BORDERS_PROPERTY = "opendoc.cell-borders"
BorderSide: TypeAlias = Literal[
    "top", "right", "bottom", "left", "inside-horizontal", "inside-vertical", "diagonal-down", "diagonal-up"
]
BorderStyle: TypeAlias = Literal["solid", "dashed", "dotted", "double", "dash-dot", "dash-dot-dot"]
_OUTER = {"top", "right", "bottom", "left"}
_TABLE = _OUTER | {"inside-horizontal", "inside-vertical"}
_CELL = _OUTER | {"diagonal-down", "diagonal-up"}


def _error(path: str, message: str) -> Any:
    raise _DiagnosticError(path, message, "semantic.border.invalid")


@dataclass(frozen=True)
class Border(IntegrationRecord):
    """Line or explicit suppression. None/nil remain distinct and both block inheritance."""

    kind: Literal["line", "none", "nil"] = "line"
    style: BorderStyle | None = None
    color: ColorValue | None = None
    width_pt: float | None = None
    offset_pt: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("line", "none", "nil"):
            _error("border.kind", "expected line/none/nil")
        if self.style not in (None, "solid", "dashed", "dotted", "double", "dash-dot", "dash-dot-dot"):
            _error("border.style", "unsupported line style; preserve native data in extra")
        if self.kind != "line" and any(value is not None for value in (self.style, self.color, self.width_pt, self.offset_pt)):
            _error("border", "none/nil cannot declare line attributes")
        if self.color is not None and type(self.color) is not ColorValue:
            _error("border.color", "expected ColorValue or unknown")
        for name in ("width_pt", "offset_pt"):
            value = getattr(self, name)
            if value is not None:
                if type(value) not in (int, float) or value < 0:
                    _error(f"border.{name}", "expected finite nonnegative points or unknown")
                try:
                    finite = math.isfinite(value)
                except OverflowError:
                    finite = False
                if not finite:
                    _error(f"border.{name}", "expected finite nonnegative points or unknown")


@dataclass(frozen=True)
class BorderSet(IntegrationRecord):
    """Per-side declarations. Missing sides are unspecified, never an implicit no-line."""

    sides: dict[BorderSide, Border]

    def __post_init__(self) -> None:
        if type(self.sides) is not dict or not set(self.sides) <= _TABLE | _CELL:
            _error("borders.sides", "expected a mapping of supported sides")
        if any(type(value) is not Border for value in self.sides.values()):
            _error("borders.sides", "expected Border declarations")


def _key(node: Table | TableCell) -> str:
    if isinstance(node, Table):
        return TABLE_BORDERS_PROPERTY
    if isinstance(node, TableCell):
        return CELL_BORDERS_PROPERTY
    raise ValueError("expected Table or TableCell")


def _encode(record: BorderSet, node: Table | TableCell, budget: DocumentLimits) -> dict[str, Any]:
    if type(record) is not BorderSet:
        raise ValueError("expected BorderSet")
    _guard_model(record, budget)
    key = _key(node)
    try:
        raw = _convert(record, BorderSet, key, encode=True)
        _convert(raw, BorderSet, key, encode=False)
    except _DiagnosticError as error:
        _error(error.location, error.message)
    if {"format", "version"}.intersection(raw):
        _error(key, "extra cannot shadow format/version")
    allowed = _TABLE if isinstance(node, Table) else _CELL
    if not set(record.sides) <= allowed:
        _error(key + ".sides", "side is not supported by this owner")
    raw.update(format=key, version=1)
    _json_tree(raw, key, budget)
    return cast(dict[str, Any], raw)


def get_borders(node: Table | TableCell, *, limits: DocumentLimits | None = None) -> BorderSet | None:
    """Read a versioned declaration, preserving unknown fields; opaque unmarked data stays opaque."""
    key = _key(node)
    budget = _resolve_limits(limits)
    if not isinstance(node.properties, Mapping):
        raise ValueError("expected property mapping")
    raw = node.properties.get(key)
    if raw is None:
        return None
    _json_tree(raw, key, budget)
    if not isinstance(raw, dict) or raw.get("format") != key:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(key + ".version", "unsupported border version")
    try:
        record = _convert(
            {name: value for name, value in raw.items() if name not in {"format", "version"}}, BorderSet, key, encode=False
        )
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _encode(record, node, budget)
    return cast(BorderSet, record)


def set_borders(node: Table | TableCell, value: BorderSet | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically replace direct declarations or remove them; refuse occupied opaque keys."""
    key = _key(node)
    budget = _resolve_limits(limits)
    if not isinstance(node.properties, MutableMapping):
        raise ValueError("expected mutable property mapping")
    previous = get_borders(node, limits=budget)
    if key in node.properties and previous is None:
        raise ValueError("border property is occupied by opaque data")
    if value is None:
        node.properties.pop(key, None)
        return
    if type(value) is not BorderSet:
        raise ValueError("expected BorderSet or None")
    if previous is not None:
        value = replace(value, extra={**previous.extra, **value.extra})
    raw = _encode(value, node, budget)
    node.properties[key] = raw


def set_border(node: Table | TableCell, side: BorderSide, value: Border | None, *, limits: DocumentLimits | None = None) -> None:
    """Change/remove one direct side, preserving other sides and their unknown data."""
    budget = _resolve_limits(limits)
    previous = get_borders(node, limits=budget)
    sides = dict(previous.sides) if previous is not None else {}
    if side not in (_TABLE if isinstance(node, Table) else _CELL):
        _error("border.side", "side is not supported by this owner")
    if value is None:
        sides.pop(side, None)
    else:
        sides[side] = value
    set_borders(node, BorderSet(sides, extra=previous.extra if previous is not None else {}), limits=budget)


def resolve_borders(
    node: Table | TableCell, *, inherited: BorderSet | None = None, limits: DocumentLimits | None = None
) -> BorderSet:
    """Explicit per-side fallback; direct declarations replace whole sides, including none/nil."""
    budget = _resolve_limits(limits)
    direct = get_borders(node, limits=budget)
    fallback = _encode(inherited, node, budget) if inherited is not None else None
    # Decode through the schema to detach nested extras from the supplied records.
    inherited_copy = (
        _convert(
            {key: value for key, value in fallback.items() if key not in {"format", "version"}},
            BorderSet,
            "borders",
            encode=False,
        )
        if fallback is not None
        else BorderSet({})
    )
    result = BorderSet(
        {**inherited_copy.sides, **(direct.sides if direct is not None else {})},
        extra={**inherited_copy.extra, **(direct.extra if direct is not None else {})},
    )
    _encode(result, node, budget)
    return result


def _validate_borders(root: ModelNode, limits: DocumentLimits) -> None:
    for location in _walk_locations(root, limits=limits):
        node = location.node
        bags = [("properties", getattr(node, "properties", {}))]
        if isinstance(node, DocumentModel):
            bags.append(("metadata", node.metadata))
        for scope, bag in bags:
            if not isinstance(bag, Mapping):
                continue
            for key, owner in ((TABLE_BORDERS_PROPERTY, Table), (CELL_BORDERS_PROPERTY, TableCell)):
                raw = bag.get(key)
                if not isinstance(raw, dict) or raw.get("format") != key:
                    continue
                path = f"{location.path}.{scope}[{key!r}]"
                if scope != "properties" or not isinstance(node, owner):
                    _error(path, "border declaration has wrong owner")
                try:
                    get_borders(cast(Table | TableCell, node), limits=limits)
                except _DiagnosticError as error:
                    suffix = error.location[len(key) :] if error.location.startswith(key) else "." + error.location
                    _error(path + suffix, error.message)


def _border_snapshot(table: Table, limits: DocumentLimits | None) -> dict[str, Any]:
    def snapshot(node: Table | TableCell) -> Any:
        record = get_borders(node, limits=limits)
        return _convert(record, BorderSet, "borders", encode=True) if record is not None else None

    cells = {}
    for row_index, row in enumerate(table.rows):
        for cell_index, cell in enumerate(row.cells):
            record = snapshot(cell)
            if record is not None:
                cells[f"{row_index}:{cell_index}"] = record
    return {"table": snapshot(table), "cells": cells}


def _borders_removed(source: Any, target: Any) -> bool:
    if isinstance(source, dict):
        if not isinstance(target, dict):
            return True
        return any(
            key not in target
            or key == "kind"
            and value == "line"
            and target[key] in ("none", "nil")
            or _borders_removed(value, target[key])
            for key, value in source.items()
        )
    if isinstance(source, list):
        if not isinstance(target, list):
            return True
        return len(source) > len(target) or any(_borders_removed(value, target[index]) for index, value in enumerate(source))
    return source is not None and target is None


__all__ = [
    "TABLE_BORDERS_PROPERTY",
    "CELL_BORDERS_PROPERTY",
    "BorderSide",
    "BorderStyle",
    "Border",
    "BorderSet",
    "get_borders",
    "set_borders",
    "set_border",
    "resolve_borders",
]
