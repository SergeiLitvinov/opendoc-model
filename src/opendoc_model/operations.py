"""Standalone copying, structural edits, text extraction and transformations."""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from typing import TypeVar, cast

from opendoc_model.document_model import (
    DocumentModel,
    Footnote,
    Formula,
    Image,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from opendoc_model.limits import DocumentLimits, _resolve_limits, _utf8_size
from opendoc_model.traversal import (
    Element,
    ModelNode,
    NodeKind,
    NodeLocation,
    _child_fields,
    _root_kind,
    iter_elements,
    walk_model,
)

_RootT = TypeVar("_RootT", bound=ModelNode)
_ElementT = TypeVar("_ElementT", bound=Element)


def _check_tree(root: ModelNode, limits: DocumentLimits) -> None:
    for _ in walk_model(root, limits=limits):
        pass


def clone_model(root: _RootT, *, limits: DocumentLimits | None = None) -> _RootT:
    """Deep-copy a document or subtree, preserving internal aliases and provenance.

    Mutable data is independent of the input. Resource/style identifiers and
    opaque package bytes are preserved; subtree copies do not gather dependencies.
    Cycles, malformed structure and exhausted budgets fail before copying.
    """
    _check_tree(root, _resolve_limits(limits))
    return deepcopy(root)


def _collection(parent: ModelNode, field: str) -> tuple[list[ModelNode], tuple[type[ModelNode], ...], NodeKind]:
    for name, expected, kind in _child_fields(parent):
        if name == field:
            values = getattr(parent, name)
            if not isinstance(values, list):
                raise ValueError(f"{field}: expected list")
            return values, expected, kind
    raise ValueError(f"{field}: not a structural collection of {type(parent).__name__}")


def _attached(root: ModelNode, location: NodeLocation[ModelNode]) -> None:
    if not isinstance(location, NodeLocation):
        raise ValueError("location: expected NodeLocation")
    current = location
    visited: set[int] = set()
    while current.parent is not None:
        if id(current) in visited:
            raise ValueError("location: cyclic parent chain")
        visited.add(id(current))
        if type(current.index) is not int or not isinstance(current.field, str):
            raise ValueError("location: invalid structural position")
        values, _, kind = _collection(current.parent.node, current.field)
        if current.kind != kind:
            raise ValueError("location: inconsistent node kind")
        if not 0 <= current.index < len(values) or values[current.index] is not current.node:
            raise ValueError(f"{current.path}: stale location; walk the model again")
        expected_path = f"{current.parent.path}.{current.field}" if current.parent.path else current.field
        if current.path != f"{expected_path}[{current.index}]":
            raise ValueError("location: inconsistent path")
        current = current.parent
    if current.node is not root or current.path or current.field is not None or current.index is not None:
        raise ValueError("location: does not belong to the supplied root")
    if current.kind != _root_kind(root):
        raise ValueError("location: inconsistent root kind")


def _position(index: int, size: int, *, insert: bool) -> None:
    if type(index) is not int or not 0 <= index < size + int(insert):
        raise ValueError(f"index: expected integer between 0 and {size if insert else size - 1}")


def _copy_for_slot(node: ModelNode, expected: tuple[type[ModelNode], ...], limits: DocumentLimits) -> ModelNode:
    if not isinstance(node, expected):
        raise ValueError(f"node: expected {', '.join(item.__name__ for item in expected)}")
    return clone_model(node, limits=limits)


def _commit_edit(
    root: ModelNode,
    values: list[ModelNode],
    index: int,
    removed: int,
    added: list[ModelNode],
    limits: DocumentLimits,
) -> None:
    previous = values[index : index + removed]
    from opendoc_model.integration import _guard_integration_edit, _integration_edit_snapshot

    snapshot = _integration_edit_snapshot(root, limits) if isinstance(root, DocumentModel) else None
    from opendoc_model.table_semantics import _has_table_semantics, _validate_tables

    table_semantics = _has_table_semantics(root, limits) or any(_has_table_semantics(node, limits) for node in added)
    committed = False
    values[index : index + removed] = added
    try:
        _check_tree(root, limits)
        from opendoc_model.table_borders import _validate_borders

        _validate_borders(root, limits)
        if table_semantics:
            _validate_tables(root, limits)
        if isinstance(root, DocumentModel):
            _guard_integration_edit(root, snapshot, limits)
        committed = True
    finally:
        if not committed:
            values[index : index + len(added)] = previous


def _child_location(
    parent: NodeLocation[ModelNode], field: str, index: int, node: ModelNode, kind: NodeKind
) -> NodeLocation[ModelNode]:
    path = f"{parent.path}.{field}" if parent.path else field
    return NodeLocation(node, f"{path}[{index}]", parent, field, index, kind)


def insert_node(
    root: ModelNode,
    parent: NodeLocation[ModelNode],
    field: str,
    index: int,
    node: ModelNode,
    *,
    limits: DocumentLimits | None = None,
) -> NodeLocation[ModelNode]:
    """Insert an independent copy into a structural collection, in place.

    Indices are explicit (0 through length); negative/bool indices are rejected.
    Failure restores the collection. Semantic references are checked separately.
    """
    budget = _resolve_limits(limits)
    _check_tree(root, budget)
    _attached(root, parent)
    values, expected, kind = _collection(parent.node, field)
    _position(index, len(values), insert=True)
    copied = _copy_for_slot(node, expected, budget)
    _commit_edit(root, values, index, 0, [copied], budget)
    return _child_location(parent, field, index, copied, kind)


def replace_node(
    root: ModelNode,
    location: NodeLocation[ModelNode],
    node: ModelNode,
    *,
    limits: DocumentLimits | None = None,
) -> NodeLocation[ModelNode]:
    """Replace a non-root occurrence with an independent copy, in place."""
    budget = _resolve_limits(limits)
    _check_tree(root, budget)
    _attached(root, location)
    if location.parent is None:
        raise ValueError("location: cannot replace the root; use a new root binding")
    values, expected, kind = _collection(location.parent.node, cast(str, location.field))
    copied = _copy_for_slot(node, expected, budget)
    index = cast(int, location.index)
    _commit_edit(root, values, index, 1, [copied], budget)
    return _child_location(location.parent, cast(str, location.field), index, copied, kind)


def remove_node(root: ModelNode, location: NodeLocation[_RootT], *, limits: DocumentLimits | None = None) -> _RootT:
    """Remove a non-root occurrence in place and return the detached live node."""
    budget = _resolve_limits(limits)
    _check_tree(root, budget)
    _attached(root, location)
    if location.parent is None:
        raise ValueError("location: cannot remove the root")
    values, _, _ = _collection(location.parent.node, cast(str, location.field))
    _commit_edit(root, values, cast(int, location.index), 1, [], budget)
    return location.node


def extract_text(
    root: ModelNode,
    *,
    block_separator: str = "\n",
    cell_separator: str = "\t",
    row_separator: str = "\n",
    include_alt_text: bool = True,
    include_formula_source: bool = False,
    limits: DocumentLimits | None = None,
) -> str:
    """Extract text in traversal order, with block/cell/row boundaries.

    Formula fallback text is preferred; source is opt-in when fallback is absent.
    Image alt text is optional. UTF-8 output is bounded by limits.max_bytes.
    Empty containers retain their structural separators; no XML/I/O is involved.
    """
    budget = _resolve_limits(limits)
    for name, value in (
        ("block_separator", block_separator),
        ("cell_separator", cell_separator),
        ("row_separator", row_separator),
    ):
        if not isinstance(value, str):
            raise ValueError(f"{name}: expected string")
    for name, flag in (("include_alt_text", include_alt_text), ("include_formula_source", include_formula_source)):
        if type(flag) is not bool:
            raise ValueError(f"{name}: expected bool")
    pieces: list[str] = []
    encountered: set[str] = set()
    used = 0

    def append(text: str, path: str) -> None:
        nonlocal used
        if not isinstance(text, str):
            raise ValueError(f"{path or 'root'}: expected text string")
        used += _utf8_size(text, budget.max_bytes, path or "root", used=used)
        pieces.append(text)

    for reference in walk_model(root, limits=budget):
        parent = reference.parent
        if parent is not None:
            separator = None
            if isinstance(parent.node, (DocumentModel, Section, TableCell, Footnote)):
                separator = block_separator
            elif isinstance(parent.node, Table):
                separator = row_separator
            elif isinstance(parent.node, TableRow):
                separator = cell_separator
            if separator is not None:
                if parent.path in encountered:
                    append(separator, reference.path)
                encountered.add(parent.path)
        node = reference.node
        if isinstance(node, TextRun):
            append(node.text, reference.path)
        elif isinstance(node, Image) and include_alt_text:
            append(node.alt_text, reference.path)
        elif isinstance(node, Formula):
            if not isinstance(node.fallback_text, str):
                raise ValueError(f"{reference.path or 'root'}.fallback_text: expected text string")
            append(node.fallback_text or (node.value if include_formula_source else ""), reference.path)
    return "".join(pieces)


def transform_elements(
    root: _RootT,
    types: type[_ElementT] | tuple[type[_ElementT], ...],
    transform: Callable[[NodeLocation[_ElementT]], Element | None],
    *,
    predicate: Callable[[NodeLocation[_ElementT]], bool] | None = None,
    limits: DocumentLimits | None = None,
) -> _RootT:
    """Transform selected occurrences on a deep copy, returning an independent root.

    Selection is captured before callbacks; reverse preorder handles descendants
    before parents and later siblings before earlier ones. Return an element to
    retain/replace the occurrence, None to delete it. New nodes are not revisited.
    Root deletion or replacement by another class is rejected. Callback failures
    propagate; no partial result is returned, and library edits never touch input.
    """
    if not callable(transform) or (predicate is not None and not callable(predicate)):
        raise ValueError("transform/predicate: expected callable")
    budget = _resolve_limits(limits)
    result = clone_model(root, limits=budget)
    from opendoc_model.integration import _guard_integration_edit, _integration_edit_snapshot

    snapshot = _integration_edit_snapshot(root, budget) if isinstance(root, DocumentModel) else None
    from opendoc_model.table_semantics import _has_table_semantics, _validate_tables

    table_semantics = _has_table_semantics(root, budget)
    selected = list(iter_elements(result, types, limits=budget))
    if predicate is not None:
        selected = [reference for reference in selected if predicate(reference)]
    for reference in reversed(selected):
        _attached(result, reference)
        replacement = transform(reference)
        if reference.parent is None:
            if replacement is None or not isinstance(replacement, type(root)):
                raise ValueError("transform: root must retain its node type")
            if replacement is not reference.node:
                result = cast(_RootT, clone_model(replacement, limits=budget))
            continue
        # A callback may update its own subtree, but moving its ancestors or
        # siblings invalidates the selection and must not silently edit a peer.
        _attached(result, reference)
        values, expected, _ = _collection(reference.parent.node, cast(str, reference.field))
        index = cast(int, reference.index)
        if replacement is None:
            del values[index]
        elif replacement is not reference.node:
            values[index] = _copy_for_slot(replacement, expected, budget)
    _check_tree(result, budget)
    if table_semantics or _has_table_semantics(result, budget):
        _validate_tables(result, budget)
    from opendoc_model.table_borders import _validate_borders

    _validate_borders(result, budget)
    if isinstance(result, DocumentModel):
        _guard_integration_edit(result, snapshot, budget)
    return result


__all__ = ["clone_model", "extract_text", "insert_node", "remove_node", "replace_node", "transform_elements"]
