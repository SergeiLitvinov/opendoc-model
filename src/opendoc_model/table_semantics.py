"""Explicit captions, header associations and groups; no format or accessibility engine."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import Any, Literal, TypeVar, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, Paragraph, Table, TableCell, TableRow
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits
from opendoc_model.references import get_anchor
from opendoc_model.traversal import ModelNode, _walk_locations

TABLE_SEMANTICS_PROPERTY = "opendoc.table-semantics"
TABLE_ROW_SEMANTICS_PROPERTY = "opendoc.table-row-semantics"
TABLE_CELL_SEMANTICS_PROPERTY = "opendoc.table-cell-semantics"


def _error(path: str, message: str) -> Any:
    raise _DiagnosticError(path, message, "semantic.table.invalid")


def _id(value: str, path: str) -> None:
    if not isinstance(value, str) or not value:
        _error(path, "expected nonempty identifier")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError as error:
        raise _DiagnosticError(path, "identifier is not UTF-8", "semantic.table.invalid") from error


@dataclass(frozen=True)
class TableRowGroup(IntegrationRecord):
    """Table-local group; tuple order defines the explicit order of groups."""

    id: str
    kind: Literal["head", "body", "foot"]

    def __post_init__(self) -> None:
        _id(self.id, "row_group.id")
        if self.kind not in ("head", "body", "foot"):
            _error("row_group.kind", "expected head/body/foot")


@dataclass(frozen=True)
class TableColumnGroup(IntegrationRecord):
    """Non-overlapping zero-based logical column interval [start, start+span)."""

    id: str
    start: int
    span: int

    def __post_init__(self) -> None:
        _id(self.id, "column_group.id")
        if type(self.start) is not int or self.start < 0 or type(self.span) is not int or self.span < 1:
            _error("column_group", "expected nonnegative start and positive span")


@dataclass(frozen=True)
class TableSemantics(IntegrationRecord):
    """Explicit caption paragraph anchors and table-local row/column groups."""

    caption_ids: tuple[str, ...] = ()
    row_groups: tuple[TableRowGroup, ...] = ()
    column_groups: tuple[TableColumnGroup, ...] = ()


@dataclass(frozen=True)
class TableRowSemantics(IntegrationRecord):
    """Stable table-local row identity and optional explicitly declared group."""

    id: str
    group_id: str | None = None

    def __post_init__(self) -> None:
        _id(self.id, "row.id")
        if self.group_id is not None:
            _id(self.group_id, "row.group_id")


@dataclass(frozen=True)
class TableCellSemantics(IntegrationRecord):
    """Role and ordered local header references; omitted role stays unknown."""

    id: str
    role: Literal["header", "data"] | None = None
    scope: Literal["row", "column", "row-group", "column-group"] | None = None
    headers: tuple[str, ...] = ()
    column_group_id: str | None = None

    def __post_init__(self) -> None:
        _id(self.id, "cell.id")
        if self.role not in (None, "header", "data"):
            _error("cell.role", "expected header/data or unknown")
        if self.scope not in (None, "row", "column", "row-group", "column-group"):
            _error("cell.scope", "unsupported scope")
        if self.scope is not None and self.role != "header":
            _error("cell.scope", "scope requires header role")
        if self.column_group_id is not None:
            _id(self.column_group_id, "cell.column_group_id")
        if (self.scope == "column-group") != (self.column_group_id is not None):
            _error("cell.column_group_id", "column-group scope requires exactly one column group")


_RecordT = TypeVar("_RecordT", TableSemantics, TableRowSemantics, TableCellSemantics)
_OWNERS: dict[str, tuple[type[Any], type[Any]]] = {
    TABLE_SEMANTICS_PROPERTY: (Table, TableSemantics),
    TABLE_ROW_SEMANTICS_PROPERTY: (TableRow, TableRowSemantics),
    TABLE_CELL_SEMANTICS_PROPERTY: (TableCell, TableCellSemantics),
}


def _get(node: Any, key: str, limits: DocumentLimits | None) -> Any:
    budget = _resolve_limits(limits)
    owner, record = _OWNERS[key]
    if not isinstance(node, owner) or not isinstance(node.properties, Mapping):
        raise ValueError(f"expected {owner.__name__} with property mapping")
    raw = node.properties.get(key)
    if raw is None:
        return None
    _json_tree(raw, f"properties[{key!r}]", budget)
    if not isinstance(raw, dict) or raw.get("format") != key:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(f"properties[{key!r}].version", "unsupported table semantics version")
    try:
        result = _convert(
            {name: value for name, value in raw.items() if name not in {"format", "version"}}, record, key, encode=False
        )
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _local(result)
    return result


def _local(record: Any) -> None:
    if isinstance(record, TableSemantics):
        for identifier in record.caption_ids:
            _id(identifier, "table.caption_ids")
        if len(set(record.caption_ids)) != len(record.caption_ids):
            _error("table.caption_ids", "duplicate caption")
        for name in ("row_groups", "column_groups"):
            values = getattr(record, name)
            if len({value.id for value in values}) != len(values):
                _error(f"table.{name}", "duplicate group id")
        end = 0
        for group in sorted(record.column_groups, key=lambda value: value.start):
            if group.start < end:
                _error("table.column_groups", "overlapping column groups")
            end = group.start + group.span
    elif isinstance(record, TableCellSemantics):
        for identifier in record.headers:
            _id(identifier, "cell.headers")
        if len(set(record.headers)) != len(record.headers) or record.id in record.headers:
            _error("cell.headers", "duplicate or self-referencing header")


def _set(node: Any, key: str, record: IntegrationRecord | None, limits: DocumentLimits | None) -> None:
    budget = _resolve_limits(limits)
    owner, kind = _OWNERS[key]
    if not isinstance(node, owner) or not isinstance(node.properties, MutableMapping):
        raise ValueError(f"expected {owner.__name__} with mutable property mapping")
    previous = _get(node, key, budget)
    if key in node.properties and previous is None:
        raise ValueError("table semantics property is occupied by opaque data")
    if record is None:
        if previous is not None:
            del node.properties[key]
        return
    if type(record) is not kind:
        raise ValueError(f"expected {kind.__name__} or None")
    if previous is not None:
        record = replace(record, extra={**previous.extra, **record.extra})
    _guard_model(record, budget)
    raw = _convert(record, kind, key, encode=True)
    if {"format", "version"}.intersection(raw):
        _error(key, "extra cannot shadow format/version")
    raw.update(format=key, version=1)
    _json_tree(raw, key, budget)
    _local(record)
    node.properties[key] = raw


def get_table_semantics(table: Table, *, limits: DocumentLimits | None = None) -> TableSemantics | None:
    return cast(TableSemantics | None, _get(table, TABLE_SEMANTICS_PROPERTY, limits))


def set_table_semantics(table: Table, value: TableSemantics | None, *, limits: DocumentLimits | None = None) -> None:
    """Set a bounded independent declaration; document validation checks links."""
    _set(table, TABLE_SEMANTICS_PROPERTY, value, limits)


def get_table_row_semantics(row: TableRow, *, limits: DocumentLimits | None = None) -> TableRowSemantics | None:
    return cast(TableRowSemantics | None, _get(row, TABLE_ROW_SEMANTICS_PROPERTY, limits))


def set_table_row_semantics(row: TableRow, value: TableRowSemantics | None, *, limits: DocumentLimits | None = None) -> None:
    _set(row, TABLE_ROW_SEMANTICS_PROPERTY, value, limits)


def get_table_cell_semantics(cell: TableCell, *, limits: DocumentLimits | None = None) -> TableCellSemantics | None:
    return cast(TableCellSemantics | None, _get(cell, TABLE_CELL_SEMANTICS_PROPERTY, limits))


def set_table_cell_semantics(cell: TableCell, value: TableCellSemantics | None, *, limits: DocumentLimits | None = None) -> None:
    _set(cell, TABLE_CELL_SEMANTICS_PROPERTY, value, limits)


def _table_links(root: ModelNode, limits: DocumentLimits) -> Iterator[str]:
    """Caption dependencies; local header/group IDs never enter anchor namespace."""
    for location in _walk_locations(root, limits):
        if isinstance(location.node, Table):
            record = get_table_semantics(location.node, limits=limits)
            if record is not None:
                yield from record.caption_ids


def _remap_tables(root: ModelNode, anchors: dict[str, str], limits: DocumentLimits) -> None:
    seen: set[int] = set()
    for location in _walk_locations(root, limits):
        node = location.node
        if isinstance(node, Table) and id(node) not in seen:
            seen.add(id(node))
            record = get_table_semantics(node, limits=limits)
            if record is not None:
                set_table_semantics(
                    node, replace(record, caption_ids=tuple(anchors.get(key, key) for key in record.caption_ids)), limits=limits
                )


def _validate_tables(root: ModelNode, limits: DocumentLimits) -> None:
    if not _has_table_semantics(root, limits):
        return
    if isinstance(root, DocumentModel):
        for key in _OWNERS:
            raw = root.metadata.get(key)
            if isinstance(raw, dict) and raw.get("format") == key:
                _error(f"metadata[{key!r}]", "table semantics belong to structural properties")
    locations = list(_walk_locations(root, limits))
    anchors: dict[str, tuple[Any, str]] = {}
    for location in locations:
        if isinstance(location.node, (Paragraph, Table)):
            anchor = get_anchor(location.node, limits=limits)
            if anchor is not None:
                if anchor.id in anchors:
                    _error(location.path, "duplicate anchor in table semantics context")
                anchors[anchor.id] = (location.node, location.path)
    captions: dict[str, str] = {}
    for location in locations:
        node, path = location.node, location.path
        bag = getattr(node, "properties", {})
        if not isinstance(bag, Mapping):
            _error(path, "expected property mapping")
        for key, (owner, _) in _OWNERS.items():
            raw = bag.get(key)
            if isinstance(raw, dict) and raw.get("format") == key and not isinstance(node, owner):
                _error(f"{path}.properties[{key!r}]", "semantics attached to wrong owner")
        if not isinstance(node, Table):
            continue
        record = cast(TableSemantics | None, _get_at(node, TABLE_SEMANTICS_PROPERTY, path, limits))
        if record is None and not any(
            _tagged(row, TABLE_ROW_SEMANTICS_PROPERTY) or any(_tagged(cell, TABLE_CELL_SEMANTICS_PROPERTY) for cell in row.cells)
            for row in node.rows
        ):
            continue
        if record is not None:
            anchor = get_anchor(node, limits=limits)
            if record.caption_ids and anchor is None:
                _error(path, "caption owner table requires an anchor")
            for key in record.caption_ids:
                target = anchors.get(key)
                if isinstance(root, DocumentModel) and (target is None or not isinstance(target[0], Paragraph)):
                    _error(path, f"caption {key!r} must reference a paragraph")
                if key in captions and captions[key] != path:
                    _error(path, f"caption {key!r} already has an owner")
                captions[key] = path
        _validate_table(node, record or TableSemantics(), path, limits)


def _validate_table(table: Table, record: TableSemantics, path: str, limits: DocumentLimits) -> None:
    rows: list[TableRowSemantics | None] = [
        _get_at(row, TABLE_ROW_SEMANTICS_PROPERTY, f"{path}.rows[{index}]", limits) for index, row in enumerate(table.rows)
    ]
    group_indices = {value.id: index for index, value in enumerate(record.row_groups)}
    group_ids = set(group_indices)
    row_ids: set[str] = set()
    last_group = -1
    cells: dict[str, tuple[TableCellSemantics, str]] = {}
    group_columns = {value.id: value for value in record.column_groups}
    # Active column intervals keep rowspan validation bounded without expanding
    # potentially huge column_span/row_span into a dense matrix.
    occupied: list[tuple[int, int, int]] = []
    width = work = 0
    for row_index, row in enumerate(table.rows):
        row_record = rows[row_index]
        group = row_record.group_id if row_record else None
        if row_record:
            if row_record.id in row_ids:
                _error(path, "duplicate row id")
            row_ids.add(row_record.id)
            if group is not None and group not in group_ids:
                _error(path, "unknown row group")
            if group is not None:
                if group_indices[group] < last_group:
                    _error(path, "row group order is inconsistent")
                last_group = group_indices[group]
        occupied = [interval for interval in occupied if interval[2] > row_index]
        column = 0
        for cell_index, cell in enumerate(row.cells):
            cell_path = f"{path}.rows[{row_index}].cells[{cell_index}]"
            sem: TableCellSemantics | None = _get_at(cell, TABLE_CELL_SEMANTICS_PROPERTY, cell_path, limits)
            if type(cell.row_span) is not int or cell.row_span < 1 or type(cell.column_span) is not int or cell.column_span < 1:
                _error(cell_path, "spans must be positive integers")
            # Position a cell after all occupied logical intervals it touches.
            while True:
                blocking = None
                for first, last, until in occupied:
                    work += 1
                    if work > limits.max_nodes:
                        _quota(path, "table grid work", limits.max_nodes)
                    if first < column + cell.column_span and column < last:
                        blocking = last
                        break
                if blocking is None:
                    break
                column = blocking
            end = column + cell.column_span
            width = max(width, end)
            if row_index + cell.row_span > len(rows):
                _error(cell_path, "row span exceeds table")
            if cell.row_span > 1:
                for next_row in range(row_index + 1, min(row_index + cell.row_span, len(rows))):
                    work += 1
                    if work > limits.max_nodes:
                        _quota(path, "table grid work", limits.max_nodes)
                    next_record = rows[next_row]
                    next_group = next_record.group_id if next_record is not None else None
                    if next_group != group and (next_group is not None or group is not None):
                        _error(cell_path, "row span crosses group boundary")
            if sem is not None:
                if sem.id in cells:
                    _error(cell_path, "duplicate cell id")
                cells[sem.id] = (sem, cell_path)
                if sem.scope == "row-group" and group is None:
                    _error(cell_path, "row-group scope requires row membership")
                if sem.column_group_id is not None:
                    definition = group_columns.get(sem.column_group_id)
                    if definition is None or not definition.start <= column < end <= definition.start + definition.span:
                        _error(cell_path, "cell is outside its declared column group")
            occupied.append((column, end, row_index + cell.row_span))
            column = end
    for definition in record.column_groups:
        if definition.start + definition.span > width:
            _error(path, "column group exceeds table grid")
    for sem, cell_path in cells.values():
        for identifier in sem.headers:
            target = cells.get(identifier)
            if target is None or target[0].role != "header":
                _error(cell_path, f"headers target {identifier!r} is not a local header")
    depths: dict[str, int] = {}
    for identifier in cells:
        pending: list[tuple[str, bool]] = [(identifier, False)]
        active: set[str] = set()
        while pending:
            key, leaving = pending.pop()
            if leaving:
                active.remove(key)
                depth = 1 + max((depths[target] for target in cells[key][0].headers), default=0)
                if depth > limits.max_depth:
                    _quota(path, "headers depth", limits.max_depth)
                depths[key] = depth
            elif key not in depths:
                if key in active:
                    _error(cells[key][1], "cyclic headers association")
                if len(active) >= limits.max_depth:
                    _quota(path, "headers depth", limits.max_depth)
                active.add(key)
                pending.append((key, True))
                pending.extend((target, False) for target in reversed(cells[key][0].headers))


def _has_table_semantics(root: ModelNode, limits: DocumentLimits) -> bool:
    if isinstance(root, DocumentModel) and any(
        isinstance(root.metadata.get(key), dict) and root.metadata[key].get("format") == key for key in _OWNERS
    ):
        return True
    return any(
        isinstance(raw, dict) and raw.get("format") == key
        for location in _walk_locations(root, limits)
        if isinstance(getattr(location.node, "properties", {}), Mapping)
        for key in _OWNERS
        for raw in (getattr(location.node, "properties", {}).get(key),)
    )


def _tagged(node: TableRow | TableCell, key: str) -> bool:
    raw = node.properties.get(key)
    return isinstance(raw, dict) and raw.get("format") == key


def _get_at(node: Any, key: str, path: str, limits: DocumentLimits) -> Any:
    try:
        return _get(node, key, limits)
    except _DiagnosticError as error:
        _error(f"{path}.properties[{key!r}]", error.message)


def _table_snapshot(table: Table, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Comparable declarations; no role or association is inferred."""
    record = get_table_semantics(table, limits=limits)
    rows = []
    for row in table.rows:
        row_record = get_table_row_semantics(row, limits=limits)
        cells = []
        for cell in row.cells:
            cell_record = get_table_cell_semantics(cell, limits=limits)
            cells.append(_convert(cell_record, TableCellSemantics, "cell", encode=True) if cell_record else None)
        rows.append(
            {"record": _convert(row_record, TableRowSemantics, "row", encode=True) if row_record else None, "cells": cells}
        )
    return {"table": _convert(record, TableSemantics, "table", encode=True) if record else None, "rows": rows}


__all__ = [
    "TABLE_SEMANTICS_PROPERTY",
    "TABLE_ROW_SEMANTICS_PROPERTY",
    "TABLE_CELL_SEMANTICS_PROPERTY",
    "TableSemantics",
    "TableRowSemantics",
    "TableCellSemantics",
    "TableRowGroup",
    "TableColumnGroup",
    "get_table_semantics",
    "set_table_semantics",
    "get_table_row_semantics",
    "set_table_row_semantics",
    "get_table_cell_semantics",
    "set_table_cell_semantics",
]
