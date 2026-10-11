"""Format-neutral indentation, tab stops and line spacing; no layout engine."""

from __future__ import annotations

import math
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any, Literal, TypeVar, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, Paragraph, Table, TextRun, TextStyle
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.traversal import ModelNode, _walk_locations

TABLE_INDENT_PROPERTY = "opendoc.table-indent"
TAB_STOPS_PROPERTY = "opendoc.tab-stops"
LINE_SPACING_PROPERTY = "opendoc.line-spacing"
LineSpacingRule = Literal["minimum", "exact", "relative"]
TabAlignment = Literal["left", "right", "center", "decimal", "bar"]
TabLeader = Literal["none", "dot", "dash", "line", "heavy", "middle-dot"]


def _error(path: str, message: str) -> Any:
    raise _DiagnosticError(path, message, "semantic.spacing.invalid")


def _points(value: float, path: str) -> None:
    if type(value) not in (int, float):
        _error(path, "expected finite signed points")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _error(path, "expected finite signed points")


@dataclass(frozen=True)
class TableIndent(IntegrationRecord):
    """Signed displacement from the containing content area's logical start, in pt.

    None is a direct unknown value, distinct from zero and a missing declaration.
    Direction and physical coordinates are supplied by the consumer.
    """

    value_pt: float | None = None

    def __post_init__(self) -> None:
        if self.value_pt is not None:
            _points(self.value_pt, "table_indent.value_pt")


@dataclass(frozen=True)
class TabStop(IntegrationRecord):
    """Position from paragraph content area's logical start; clear suppresses fallback.

    Alignment names describe text alignment at the stop, not writing direction.
    Unknown alignment/leader is None; leader='none' explicitly requests no leader.
    """

    position_pt: float
    kind: Literal["stop", "clear"] = "stop"
    alignment: TabAlignment | None = None
    leader: TabLeader | None = None

    def __post_init__(self) -> None:
        _points(self.position_pt, "tab_stop.position_pt")
        if self.kind not in ("stop", "clear"):
            _error("tab_stop.kind", "expected stop or clear")
        if self.alignment not in (None, "left", "right", "center", "decimal", "bar"):
            _error("tab_stop.alignment", "unsupported alignment")
        if self.leader not in (None, "none", "dot", "dash", "line", "heavy", "middle-dot"):
            _error("tab_stop.leader", "unsupported leader")
        if self.kind == "clear" and (self.alignment is not None or self.leader is not None):
            _error("tab_stop", "clear cannot declare alignment or leader")


@dataclass(frozen=True)
class TabStops(IntegrationRecord):
    """Unique explicit positions; inherit=False replaces the supplied fallback set.

    An empty replacing set means no explicit stops, not removal of tab characters
    or suppression of an application's automatic/default tab interval.
    """

    stops: tuple[TabStop, ...] = ()
    inherit: bool = True

    def __post_init__(self) -> None:
        if type(self.inherit) is not bool or type(self.stops) is not tuple:
            _error("tab_stops", "expected boolean inherit and tuple of TabStop")
        if any(type(stop) is not TabStop for stop in self.stops):
            _error("tab_stops.stops", "expected TabStop records")
        if len({stop.position_pt for stop in self.stops}) != len(self.stops):
            _error("tab_stops.stops", "duplicate positions")


@dataclass(frozen=True)
class LineSpacing(IntegrationRecord):
    """Declared line advance: minimum/exact points or a relative natural-line multiplier.

    Both None mean explicit unknown, blocking inheritance. This is not a measured
    glyph height; natural line metrics and native layout belong to the consumer.
    """

    rule: LineSpacingRule | None = None
    value: float | None = None

    def __post_init__(self) -> None:
        if self.rule not in (None, "minimum", "exact", "relative"):
            _error("line_spacing.rule", "expected minimum, exact or relative")
        if (self.rule is None) != (self.value is None):
            _error("line_spacing", "rule and value must both be known or both unknown")
        if self.value is not None:
            _points(self.value, "line_spacing.value")
            if self.value <= 0:
                _error("line_spacing.value", "expected positive value")


_Record = TypeVar("_Record", TableIndent, TabStops, LineSpacing)


def _owner(node: Table | Paragraph | TextStyle, key: str) -> None:
    expected = (
        (Paragraph, TextStyle) if key == LINE_SPACING_PROPERTY else (Table,) if key == TABLE_INDENT_PROPERTY else (Paragraph,)
    )
    if not isinstance(node, expected):
        _error(key, "declaration has wrong owner")


def _encode(value: _Record, schema: type[_Record], key: str, budget: DocumentLimits) -> dict[str, Any]:
    if type(value) is not schema:
        _error(key, f"expected {schema.__name__}")
    _guard_model(value, budget)
    try:
        raw = _convert(value, schema, key, encode=True)
        _convert(raw, schema, key, encode=False)
    except _DiagnosticError as error:
        _error(error.location, error.message)
    if {"format", "version"}.intersection(raw):
        _error(key, "extra cannot shadow format/version")
    raw.update(format=key, version=1)
    _json_tree(raw, key, budget)
    return cast(dict[str, Any], raw)


def _get(node: Table | Paragraph | TextStyle, schema: type[_Record], key: str, budget: DocumentLimits) -> _Record | None:
    _owner(node, key)
    if not isinstance(node.properties, Mapping):
        _error(key, "expected property mapping")
    raw = node.properties.get(key)
    if raw is None:
        return None
    _json_tree(raw, key, budget)
    if not isinstance(raw, dict) or raw.get("format") != key:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(key + ".version", "unsupported declaration version")
    try:
        record = _convert(
            {name: item for name, item in raw.items() if name not in {"format", "version"}}, schema, key, encode=False
        )
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _encode(record, schema, key, budget)
    return cast(_Record, record)


def _set(
    node: Table | Paragraph | TextStyle, value: _Record | None, schema: type[_Record], key: str, budget: DocumentLimits
) -> None:
    previous = _get(node, schema, key, budget)
    if not isinstance(node.properties, MutableMapping):
        _error(key, "expected mutable property mapping")
    if key in node.properties and previous is None:
        _error(key, "property is occupied by opaque data")
    if value is None:
        node.properties.pop(key, None)
        return
    if type(value) is not schema:
        _error(key, f"expected {schema.__name__} or None")
    if type(value.extra) is not dict:
        _error(key + ".extra", "expected dictionary")
    if previous is not None:
        value = replace(value, extra={**previous.extra, **value.extra})
    raw = _encode(value, schema, key, budget)
    node.properties[key] = raw


def get_table_indent(node: Table, *, limits: DocumentLimits | None = None) -> TableIndent | None:
    """Read an independent tagged declaration; absent/opaque data returns None."""
    return _get(node, TableIndent, TABLE_INDENT_PROPERTY, _resolve_limits(limits))


def set_table_indent(node: Table, value: TableIndent | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically set direct indentation or remove it; preserve envelope extensions."""
    _set(node, value, TableIndent, TABLE_INDENT_PROPERTY, _resolve_limits(limits))


def resolve_table_indent(
    node: Table, *, inherited: TableIndent | None = None, limits: DocumentLimits | None = None
) -> TableIndent | None:
    """Use explicit fallback only when direct indentation is missing; no style cascade."""
    budget = _resolve_limits(limits)
    direct = get_table_indent(node, limits=budget)
    fallback = _encode(inherited, TableIndent, TABLE_INDENT_PROPERTY, budget) if inherited is not None else None
    if direct is not None or fallback is None:
        return direct
    return cast(
        TableIndent,
        _convert({k: v for k, v in fallback.items() if k not in {"format", "version"}}, TableIndent, "indent", encode=False),
    )


def get_tab_stops(node: Paragraph, *, limits: DocumentLimits | None = None) -> TabStops | None:
    """Read an independent direct set, including clear declarations and unknown fields."""
    return _get(node, TabStops, TAB_STOPS_PROPERTY, _resolve_limits(limits))


def set_tab_stops(node: Paragraph, value: TabStops | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically replace/remove direct tab declarations, retaining envelope extensions."""
    _set(node, value, TabStops, TAB_STOPS_PROPERTY, _resolve_limits(limits))


def set_tab_stop(node: Paragraph, position_pt: float, value: TabStop | None, *, limits: DocumentLimits | None = None) -> None:
    """Edit/remove one direct position; use kind='clear' to block its inheritance.

    Other positions and unknown fields of the edited declaration are preserved.
    """
    budget = _resolve_limits(limits)
    _points(position_pt, "position_pt")
    direct = get_tab_stops(node, limits=budget)
    stops = {stop.position_pt: stop for stop in direct.stops} if direct is not None else {}
    if value is None:
        stops.pop(position_pt, None)
    else:
        if type(value) is not TabStop or value.position_pt != position_pt:
            _error("tab_stop", "expected TabStop at the requested position")
        if type(value.extra) is not dict:
            _error("tab_stop.extra", "expected dictionary")
        if position_pt in stops:
            value = replace(value, extra={**stops[position_pt].extra, **value.extra})
        stops[position_pt] = value
    result = TabStops(
        tuple(sorted(stops.values(), key=lambda stop: stop.position_pt)),
        direct.inherit if direct else True,
        extra=direct.extra if direct else {},
    )
    set_tab_stops(node, result, limits=budget)


def resolve_tab_stops(node: Paragraph, *, inherited: TabStops | None = None, limits: DocumentLimits | None = None) -> TabStops:
    """Resolve only the supplied fallback by exact position, without default interval/layout.

    Direct stops replace whole fallback stops. Clear removes a fallback position.
    Result is sorted, detached, inherit=False and contains no clear declarations.
    """
    budget = _resolve_limits(limits)
    direct = get_tab_stops(node, limits=budget)
    fallback: TabStops | None = None
    if inherited is not None:
        raw = _encode(inherited, TabStops, TAB_STOPS_PROPERTY, budget)
        fallback = _convert({k: v for k, v in raw.items() if k not in {"format", "version"}}, TabStops, "tabs", encode=False)
    stops = {stop.position_pt: stop for stop in fallback.stops if stop.kind == "stop"} if fallback is not None else {}
    if direct is not None:
        if not direct.inherit:
            stops = {}
        for stop in direct.stops:
            if stop.kind == "clear":
                stops.pop(stop.position_pt, None)
            else:
                stops[stop.position_pt] = stop
    result = TabStops(
        tuple(sorted(stops.values(), key=lambda stop: stop.position_pt)),
        False,
        extra={**(fallback.extra if fallback else {}), **(direct.extra if direct else {})},
    )
    _encode(result, TabStops, TAB_STOPS_PROPERTY, budget)
    return result


def get_line_spacing(node: Paragraph | TextStyle, *, limits: DocumentLimits | None = None) -> LineSpacing | None:
    """Read an independent direct declaration; absent/opaque data returns None."""
    return _get(node, LineSpacing, LINE_SPACING_PROPERTY, _resolve_limits(limits))


def set_line_spacing(node: Paragraph | TextStyle, value: LineSpacing | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically replace/remove the declaration, preserving its unknown fields."""
    _set(node, value, LineSpacing, LINE_SPACING_PROPERTY, _resolve_limits(limits))


def resolve_line_spacing(
    node: Paragraph | TextStyle,
    *,
    document: DocumentModel | None = None,
    inherited: LineSpacing | None = None,
    limits: DocumentLimits | None = None,
) -> LineSpacing | None:
    """Resolve direct > named model style chain > explicit fallback, without native defaults.

    A document is required for style references. Run styles do not set paragraph
    line spacing. Unknown tagged values block fallback; removal permits it again.
    """
    from opendoc_model.styles import _require_document, _resolved

    budget = _resolve_limits(limits)
    direct = get_line_spacing(node, limits=budget)
    fallback = _encode(inherited, LineSpacing, LINE_SPACING_PROPERTY, budget) if inherited is not None else None
    if document is not None:
        _require_document(document, budget)
    reference = node.style_id if isinstance(node, Paragraph) else node.properties.get("base_style_id")
    if reference is not None and document is None:
        _error(LINE_SPACING_PROPERTY, "document required for style references")
    style = get_line_spacing(_resolved(document, reference, budget), limits=budget) if document is not None else None
    if direct is not None or style is not None:
        return direct if direct is not None else style
    if fallback is None:
        return None
    return cast(
        LineSpacing,
        _convert(
            {k: v for k, v in fallback.items() if k not in {"format", "version"}}, LineSpacing, "line_spacing", encode=False
        ),
    )


def _validate_spacing(root: ModelNode, limits: DocumentLimits) -> None:
    def line_owner(owner: Paragraph | TextStyle, path: str) -> None:
        try:
            get_line_spacing(owner, limits=limits)
        except _DiagnosticError as error:
            _error(path + "." + error.location, error.message)

    if isinstance(root, DocumentModel):
        for identifier, style in root.styles.items():
            line_owner(style, f"styles[{identifier!r}].properties")
    for location in _walk_locations(root, limits=limits):
        node = location.node
        if isinstance(node, TextRun):
            line_owner(node.style, location.path + ".style.properties")
        bags = [("properties", getattr(node, "properties", {}))]
        if isinstance(node, DocumentModel):
            bags.append(("metadata", node.metadata))
        for scope, bag in bags:
            if not isinstance(bag, Mapping):
                continue
            for key in (TABLE_INDENT_PROPERTY, TAB_STOPS_PROPERTY, LINE_SPACING_PROPERTY):
                raw = bag.get(key)
                if not isinstance(raw, dict) or raw.get("format") != key:
                    continue
                path = f"{location.path}.{scope}[{key!r}]"
                if scope != "properties":
                    _error(path, "declaration has wrong owner")
                try:
                    if key == TABLE_INDENT_PROPERTY:
                        get_table_indent(cast(Table, node), limits=limits)
                    elif key == TAB_STOPS_PROPERTY:
                        get_tab_stops(cast(Paragraph, node), limits=limits)
                    else:
                        get_line_spacing(cast(Paragraph, node), limits=limits)
                except _DiagnosticError as error:
                    _error(path + "." + error.location, error.message)


def _spacing_snapshot(node: Table | Paragraph, limits: DocumentLimits | None) -> dict[str, Any] | None:
    if isinstance(node, Table):
        indent = get_table_indent(node, limits=limits)
        return cast(dict[str, Any], _convert(indent, TableIndent, "indent", encode=True)) if indent is not None else None
    tabs = get_tab_stops(node, limits=limits)
    if tabs is None:
        return None
    # Declaration order does not change the position-keyed contract.
    tabs = replace(tabs, stops=tuple(sorted(tabs.stops, key=lambda stop: stop.position_pt)))
    return cast(dict[str, Any], _convert(tabs, TabStops, "tabs", encode=True))


def _spacing_removed(source: dict[str, Any] | None, target: dict[str, Any] | None, field: str) -> bool:
    if source is None:
        return False
    if target is None:
        return True
    if field == "table_indent":
        return source["value_pt"] is not None and target["value_pt"] is None
    stops = {stop["position_pt"]: stop for stop in target["stops"]}
    for before in source["stops"]:
        after = stops.get(before["position_pt"])
        if after is None or before["kind"] == "stop" and after["kind"] == "clear":
            return True
        if any(before[name] is not None and after[name] is None for name in ("alignment", "leader")):
            return True
        if before["leader"] not in (None, "none") and after["leader"] == "none":
            return True
    return False


class _LineSpacings:
    """Validated model style context; cache only within one inspection."""

    def __init__(self, document: DocumentModel, limits: DocumentLimits) -> None:
        self.document = document
        self.limits = limits
        self.cache: dict[str | None, TextStyle] = {None: TextStyle()}

    def paragraph(self, node: Paragraph) -> dict[str, Any] | None:
        from opendoc_model.styles import _resolved

        if node.style_id is not None and node.style_id not in self.document.styles:
            return None
        if node.style_id not in self.cache:
            self.cache[node.style_id] = _resolved(self.document, node.style_id, self.limits)
        style = self.cache[node.style_id]
        direct = get_line_spacing(node, limits=self.limits)
        inherited = get_line_spacing(style, limits=self.limits)
        for owner, declaration in ((node, direct), (style, inherited)):
            if declaration is None and (
                LINE_SPACING_PROPERTY in owner.properties
                or any(key in owner.properties for key in ("line_spacing", "line_spacing_pt", "docx_line_spacing_rule"))
            ):
                return None

        def value(item: LineSpacing | None) -> dict[str, Any] | None:
            return {"rule": item.rule, "value": item.value} if item is not None else None

        return {"direct": value(direct), "resolved": value(direct if direct is not None else inherited)}


def _line_spacing_valid(value: Any) -> bool:
    if not isinstance(value, dict) or not {"direct", "resolved"} <= value.keys():
        return False
    for key in ("direct", "resolved"):
        item = value[key]
        if item is None:
            continue
        if not isinstance(item, dict) or not {"rule", "value"} <= item.keys():
            return False
        try:
            LineSpacing(item["rule"], item["value"])
        except ValueError:
            return False
    return True


def _line_spacing_removed(source: dict[str, Any], target: dict[str, Any]) -> bool:
    return any(
        source[key] is not None and (target[key] is None or source[key]["rule"] is not None and target[key]["rule"] is None)
        for key in ("direct", "resolved")
    )


__all__ = [
    "LINE_SPACING_PROPERTY",
    "LineSpacingRule",
    "LineSpacing",
    "get_line_spacing",
    "set_line_spacing",
    "resolve_line_spacing",
    "TABLE_INDENT_PROPERTY",
    "TAB_STOPS_PROPERTY",
    "TableIndent",
    "TabAlignment",
    "TabLeader",
    "TabStop",
    "TabStops",
    "get_table_indent",
    "set_table_indent",
    "resolve_table_indent",
    "get_tab_stops",
    "set_tab_stops",
    "set_tab_stop",
    "resolve_tab_stops",
]
