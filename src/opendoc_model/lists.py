"""Explicit list membership and deterministic per-level numbering."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, TypeAlias

from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import Paragraph
from opendoc_model.limits import DocumentLimits, _quota, _resolve_limits
from opendoc_model.references import _identifier, get_anchor, iter_anchors
from opendoc_model.traversal import ModelNode, NodeLocation, iter_elements

LIST_PROPERTY = "opendoc.list-item"
ListKind: TypeAlias = Literal["ordered", "unordered"]


def _list_fields(values: dict[str, Any], path: str) -> None:
    identifier = values.get("list_id")
    if not isinstance(identifier, str) or not identifier or any(0xD800 <= ord(char) <= 0xDFFF for char in identifier):
        raise _DiagnosticError(f"{path}.list_id", "expected a nonempty UTF-8 list ID", "semantic.list.id")
    if type(values.get("level")) is not int or not 0 <= values["level"] <= 8:
        raise _DiagnosticError(f"{path}.level", "list level must be an integer between 0 and 8", "semantic.list.level")
    if values.get("kind") not in ("ordered", "unordered"):
        raise _DiagnosticError(f"{path}.kind", "unsupported list kind", "semantic.list.kind")
    for name in ("start", "restart"):
        value = values.get(name)
        if name == "restart" and value is None:
            continue
        if type(value) is not int or value < 1:
            raise _DiagnosticError(f"{path}.{name}", "expected a positive integer", "semantic.list.number")
    if values["kind"] == "unordered" and (values["start"] != 1 or values["restart"] is not None):
        raise _DiagnosticError(path, "unordered lists cannot specify numbering", "semantic.list.number")
    for name in ("continuation_of", "parent_id"):
        if values.get(name) is not None:
            _identifier(values[name], f"{path}.{name}")
    if values.get("continuation_of") is not None and values["restart"] is not None:
        raise _DiagnosticError(path, "a continuation cannot restart numbering", "semantic.list.number")


@dataclass(frozen=True)
class ListItem:
    """Membership in an implicit list group; levels are 0–8.

    Kind/start agree within (list_id, level). Keyword-only continuation_of and
    parent_id reference anchors on earlier primary list paragraphs. A continuation
    shares its primary item's configuration and parent, without a new number.
    """

    list_id: str
    level: int = 0
    kind: ListKind = "ordered"
    start: int = 1
    restart: int | None = None
    continuation_of: str | None = field(default=None, kw_only=True)
    parent_id: str | None = field(default=None, kw_only=True)

    def __post_init__(self) -> None:
        _list_fields(
            {
                "list_id": self.list_id,
                "level": self.level,
                "kind": self.kind,
                "start": self.start,
                "restart": self.restart,
                "continuation_of": self.continuation_of,
                "parent_id": self.parent_id,
            },
            "list_item",
        )


@dataclass(frozen=True)
class ListNumber:
    """One paragraph and its number; unordered items/continuations have None."""

    location: NodeLocation[Paragraph]
    item: ListItem
    number: int | None


def _list_payload(value: Any, path: str) -> ListItem | None:
    if not isinstance(value, dict) or value.get("format") != "opendoc.list-item":
        return None
    if type(value.get("version")) is not int or value["version"] not in (1, 2):
        raise _DiagnosticError(f"{path}.version", "unsupported list item version", "semantic.version")
    fields = {
        "list_id": value.get("list_id"),
        "level": value.get("level", 0),
        "kind": value.get("kind", "ordered"),
        "start": value.get("start", 1),
        "restart": value.get("restart"),
    }
    if value["version"] == 2:
        fields.update(continuation_of=value.get("continuation_of"), parent_id=value.get("parent_id"))
    _list_fields(fields, path)
    return ListItem(**fields)


def _list_inventory_valid(value: Any) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict) or not {"list_id", "level", "kind", "start", "restart"} <= value.keys():
        return False
    try:
        _list_fields(value, "inventory")
    except ValueError:
        return False
    return True


def get_list_item(paragraph: Paragraph, *, limits: DocumentLimits | None = None) -> ListItem | None:
    """Read only the explicitly tagged list-item bag, preserving opaque extensions."""
    from opendoc_model._json_validation import _json_tree

    if not isinstance(paragraph, Paragraph) or not isinstance(paragraph.properties, Mapping):
        raise ValueError("paragraph must be Paragraph with property mapping")
    resolved = _resolve_limits(limits)
    if LIST_PROPERTY not in paragraph.properties:
        return None
    value = paragraph.properties[LIST_PROPERTY]
    path = f"properties[{LIST_PROPERTY!r}]"
    _json_tree(value, path, resolved)
    return _list_payload(value, path)


def set_list_item(paragraph: Paragraph, item: ListItem | None, *, limits: DocumentLimits | None = None) -> None:
    """Set/remove membership in place after checking; do not overwrite opaque data."""
    from opendoc_model._json_validation import _json_tree

    if not isinstance(paragraph, Paragraph) or not isinstance(paragraph.properties, MutableMapping):
        raise ValueError("paragraph must be Paragraph with property mapping")
    if item is not None and not isinstance(item, ListItem):
        raise ValueError("item must be ListItem or None")
    resolved = _resolve_limits(limits)
    existing = get_list_item(paragraph, limits=resolved)
    if LIST_PROPERTY in paragraph.properties and existing is None:
        raise ValueError("list property is occupied by an opaque extension")
    if item is None:
        if existing is not None:
            del paragraph.properties[LIST_PROPERTY]
        return
    value = deepcopy(paragraph.properties[LIST_PROPERTY]) if existing is not None else {}
    if value.get("version") == 2 or item.continuation_of is not None or item.parent_id is not None:
        for name in ("continuation_of", "parent_id"):
            value.pop(name, None)
    fields = {
        name: value for name, value in asdict(item).items() if name not in ("continuation_of", "parent_id") or value is not None
    }
    version = 2 if item.continuation_of is not None or item.parent_id is not None else 1
    value.update(format="opendoc.list-item", version=version, **fields)
    path = f"properties[{LIST_PROPERTY!r}]"
    _json_tree(value, path, resolved)
    _list_payload(value, path)
    paragraph.properties[LIST_PROPERTY] = value


def iter_list_items(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Paragraph]]:
    """Find marked list paragraphs in the common traversal order."""
    for location in iter_elements(root, Paragraph, limits=limits):
        if get_list_item(location.node, limits=limits) is not None:
            yield location


def _list_links(root: ModelNode, limits: DocumentLimits) -> Iterator[str]:
    for location in iter_list_items(root, limits=limits):
        item = get_list_item(location.node, limits=limits)
        assert item is not None
        for identifier in (item.continuation_of, item.parent_id):
            if identifier is not None:
                yield identifier


def _validate_list_links(
    selected: list[tuple[NodeLocation[Paragraph], ListItem]], root: ModelNode, limits: DocumentLimits
) -> None:
    if not any(item.continuation_of is not None or item.parent_id is not None for _, item in selected):
        return
    anchors = {}
    for location in iter_anchors(root, limits=limits):
        anchor = get_anchor(location.node, limits=limits)
        assert anchor is not None
        if anchor.id in anchors:
            raise _DiagnosticError(location.path, "duplicate list-context anchor", "semantic.anchor.duplicate")
        anchors[anchor.id] = location.node
    items = {id(location.node): (index, item) for index, (location, item) in enumerate(selected)}
    edges: dict[str, str] = {}
    paths: dict[str, str] = {}
    for location, item in selected:
        anchor = get_anchor(location.node, limits=limits)
        owner = item.continuation_of or item.parent_id
        if anchor is not None and owner is not None:
            edges[anchor.id] = owner
            name = "continuation_of" if item.continuation_of is not None else "parent_id"
            paths[anchor.id] = f"{location.path}.properties[{LIST_PROPERTY!r}].{name}"
        for name in ("continuation_of", "parent_id"):
            identifier = getattr(item, name)
            if identifier is not None and (identifier not in anchors or id(anchors[identifier]) not in items):
                raise _DiagnosticError(
                    f"{location.path}.properties[{LIST_PROPERTY!r}].{name}",
                    "reference requires an anchored list paragraph",
                    "semantic.list.reference",
                )
    heights: dict[str, int] = {}
    for start in edges:
        chain: list[str] = []
        active: set[str] = set()
        current = start
        while current not in heights:
            if current in active:
                raise _DiagnosticError(paths[current], "cyclic list ownership", "semantic.list.cycle")
            active.add(current)
            chain.append(current)
            if len(chain) > limits.max_depth:
                _quota("list_items", "graph depth", limits.max_depth)
            if current not in edges:
                break
            current = edges[current]
        height = heights.get(current, 0)
        for identifier in reversed(chain):
            height += 1
            if height > limits.max_depth:
                _quota("list_items", "graph depth", limits.max_depth)
            heights[identifier] = height
    for index, (location, item) in enumerate(selected):
        for name in ("continuation_of", "parent_id"):
            identifier = getattr(item, name)
            if identifier is None:
                continue
            position, target = items[id(anchors[identifier])]
            path = f"{location.path}.properties[{LIST_PROPERTY!r}].{name}"
            if position >= index or target.continuation_of is not None:
                raise _DiagnosticError(path, "target must be an earlier primary list paragraph", "semantic.list.reference")
            if name == "continuation_of" and (item.list_id, item.level, item.kind, item.start, item.parent_id) != (
                target.list_id,
                target.level,
                target.kind,
                target.start,
                target.parent_id,
            ):
                raise _DiagnosticError(path, "continuation must agree with its primary item", "semantic.list.config")


def _validate_lists(root: ModelNode, limits: DocumentLimits) -> None:
    # Exhaust the iterator: numbering validates the whole sequence before yielding.
    for _ in iter_list_numbers(root, limits=limits):
        pass


def iter_list_numbers(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[ListNumber]:
    """Compute primary-item numbers in traversal order, validating all groups first.

    Groups can interleave and resume across sections. Plain paragraphs do not
    reset them. Levels need not have a parent occurrence; only the current
    level's decimal number is returned, never a guessed hierarchical label.
    Continuations yield None without changing counters. Explicit parent links do
    not infer levels, marker styles or counter resets for a different list ID.
    """
    selected: list[tuple[NodeLocation[Paragraph], ListItem]] = []
    budget = _resolve_limits(limits)
    configs: dict[tuple[str, int], tuple[str, int]] = {}
    for location in iter_list_items(root, limits=limits):
        item = get_list_item(location.node, limits=limits)
        assert item is not None
        key = (item.list_id, item.level)
        config = (item.kind, item.start)
        if key in configs and configs[key] != config:
            raise _DiagnosticError(location.path, "conflicting list kind/start for the same level", "semantic.list.config")
        configs[key] = config
        selected.append((location, item))
    _validate_list_links(selected, root, budget)
    counters: dict[str, dict[int, int]] = {}
    for location, item in selected:
        if item.continuation_of is not None:
            yield ListNumber(location, item, None)
            continue
        levels = counters.setdefault(item.list_id, {})
        for level in tuple(levels):
            if level > item.level:
                del levels[level]
        number = None
        if item.kind == "ordered":
            number = item.restart if item.restart is not None else levels.get(item.level, item.start - 1) + 1
            levels[item.level] = number
        yield ListNumber(location, item, number)


__all__ = [
    "LIST_PROPERTY",
    "ListItem",
    "ListKind",
    "ListNumber",
    "get_list_item",
    "iter_list_items",
    "iter_list_numbers",
    "set_list_item",
]
