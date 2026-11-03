"""Explicit anchors and internal links, independent of URI interpretation."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, cast

from opendoc_model.diagnostics import ConversionIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import BlockGroup, DocumentModel, Formula, Image, Paragraph, Table, TextRun
from opendoc_model.limits import DocumentLimits, _resolve_limits
from opendoc_model.object_matching import _match_objects, _MatchingBudget, _MatchingLimitError
from opendoc_model.traversal import Element, ModelNode, NodeLocation, _walk_locations, iter_elements

ANCHOR_PROPERTY = "opendoc.anchor"
INTERNAL_LINK_PROPERTY = "opendoc.internal-link"
_ELEMENTS = (Paragraph, Table, TextRun, Formula, Image, BlockGroup)


def _identifier(value: Any, path: str) -> str:
    if not isinstance(value, str) or not value or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        raise _DiagnosticError(path, "expected a nonempty UTF-8 identifier", "semantic.reference.id")
    return value


@dataclass(frozen=True)
class Anchor:
    """A document-local identity at the beginning of an element occurrence."""

    id: str

    def __post_init__(self) -> None:
        _identifier(self.id, "anchor.id")


@dataclass(frozen=True)
class InternalLink:
    """A link to an anchor ID; no URI parsing or external lookup is involved."""

    target_id: str

    def __post_init__(self) -> None:
        _identifier(self.target_id, "internal_link.target_id")


def _payload(value: Any, path: str, key: str) -> Anchor | InternalLink | None:
    if not isinstance(value, dict) or value.get("format") != key:
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        raise _DiagnosticError(f"{path}.version", "unsupported reference version", "semantic.version")
    field = "id" if key == ANCHOR_PROPERTY else "target_id"
    identifier = _identifier(value.get(field), f"{path}.{field}")
    return Anchor(identifier) if key == ANCHOR_PROPERTY else InternalLink(identifier)


def _get(node: Element, key: str, limits: DocumentLimits | None) -> Anchor | InternalLink | None:
    from opendoc_model._json_validation import _json_tree

    expected = _ELEMENTS if key == ANCHOR_PROPERTY else (TextRun,)
    if not isinstance(node, expected) or not isinstance(node.properties, Mapping):
        raise ValueError("expected an anchor element or link TextRun with property mapping")
    resolved = _resolve_limits(limits)
    if key not in node.properties:
        return None
    value = node.properties[key]
    _json_tree(value, f"properties[{key!r}]", resolved)
    return _payload(value, f"properties[{key!r}]", key)


def _set(node: Element, key: str, item: Anchor | InternalLink | None, limits: DocumentLimits | None) -> None:
    from opendoc_model._json_validation import _json_tree

    existing = _get(node, key, limits)
    if not isinstance(node.properties, MutableMapping):
        raise ValueError("expected a mutable property mapping")
    expected = Anchor if key == ANCHOR_PROPERTY else InternalLink
    if item is not None and not isinstance(item, expected):
        raise ValueError(f"expected {expected.__name__} or None")
    if key in node.properties and existing is None:
        raise ValueError("reference property is occupied by an opaque extension")
    if item is None:
        if existing is not None:
            del node.properties[key]
        return
    if isinstance(node, TextRun) and key == INTERNAL_LINK_PROPERTY and node.link is not None:
        raise ValueError("an internal link cannot coexist with TextRun.link")
    if isinstance(node, TextRun) and key == INTERNAL_LINK_PROPERTY:
        from opendoc_model.footnotes import get_footnote_reference

        if get_footnote_reference(node, limits=limits) is not None:
            raise ValueError("an internal link cannot coexist with a footnote reference")
    value = deepcopy(node.properties[key]) if existing is not None else {}
    field = "id" if isinstance(item, Anchor) else "target_id"
    value.update(format=key, version=1, **{field: getattr(item, field)})
    _json_tree(value, f"properties[{key!r}]", _resolve_limits(limits))
    _payload(value, f"properties[{key!r}]", key)
    node.properties[key] = value


def get_anchor(node: Element, *, limits: DocumentLimits | None = None) -> Anchor | None:
    """Read a tagged anchor on a paragraph, table, run, formula or image."""
    return cast(Anchor | None, _get(node, ANCHOR_PROPERTY, limits))


def set_anchor(node: Element, anchor: Anchor | None, *, limits: DocumentLimits | None = None) -> None:
    """Set/remove one anchor atomically; document-wide uniqueness is validated separately."""
    _set(node, ANCHOR_PROPERTY, anchor, limits)


def get_internal_link(run: TextRun, *, limits: DocumentLimits | None = None) -> InternalLink | None:
    """Read explicit internal link data without interpreting TextRun.link."""
    return cast(InternalLink | None, _get(run, INTERNAL_LINK_PROPERTY, limits))


def set_internal_link(run: TextRun, link: InternalLink | None, *, limits: DocumentLimits | None = None) -> None:
    """Set/remove a run link atomically; target existence is checked on the whole model."""
    _set(run, INTERNAL_LINK_PROPERTY, link, limits)


def iter_anchors(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Element]]:
    """Yield anchor-bearing occurrences in common order, including tables and all headers."""
    for location in iter_elements(root, _ELEMENTS, limits=limits):
        if get_anchor(location.node, limits=limits) is not None:
            yield location


def iter_internal_links(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[TextRun]]:
    """Yield tagged run links, leaving external and legacy fragment strings untouched."""
    for location in iter_elements(root, TextRun, limits=limits):
        if get_internal_link(location.node, limits=limits) is not None:
            yield location


def resolve_anchor(
    document: DocumentModel, identifier: str, *, limits: DocumentLimits | None = None
) -> NodeLocation[Element] | None:
    """Resolve a unique ID in a valid document; return None when no anchor has that ID."""
    from opendoc_model._validation import _validate_model

    _identifier(identifier, "identifier")
    errors = _validate_model(document, limits)
    if errors:
        raise ValueError("; ".join(errors))
    for location in iter_anchors(document, limits=limits):
        anchor = get_anchor(location.node, limits=limits)
        assert anchor is not None
        if anchor.id == identifier:
            return location
    return None


def _reference_inventory(document: DocumentModel, limits: DocumentLimits) -> dict[str, Any]:
    anchors = []
    links = []
    for location in _walk_locations(document, limits):
        node = location.node
        if not isinstance(node, _ELEMENTS):
            continue
        anchor = get_anchor(node, limits=limits)
        if anchor is not None:
            anchors.append({"id": anchor.id, "location": location.path, "node_type": type(node).__name__.lower()})
        if isinstance(node, TextRun):
            link = get_internal_link(node, limits=limits)
            if link is not None:
                links.append(
                    {
                        "type": "internal-link",
                        "location": location.path,
                        "target_id": link.target_id,
                        "text": node.text,
                        "content_hash": hashlib.sha256(node.text.encode("utf-8")).hexdigest(),
                    }
                )
    paths = {item["id"]: item["location"] for item in anchors}
    for item in links:
        item["target_location"] = paths[item["target_id"]]
    return {"format": "opendoc.references", "version": 1, "anchors": anchors, "links": links}


def _inventory_valid(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("format") != "opendoc.references" or type(value.get("version")) is not int:
        return False
    if value["version"] != 1 or not isinstance(value.get("anchors"), list) or not isinstance(value.get("links"), list):
        return False
    paths: dict[str, str] = {}
    seen: set[str] = set()
    try:
        for item in value["anchors"]:
            if not isinstance(item, dict):
                return False
            for field in ("id", "location", "node_type"):
                _identifier(item.get(field), field)
            if item["node_type"] not in {"paragraph", "table", "textrun", "formula", "image", "blockgroup"}:
                return False
            if item["id"] in paths or item["location"] in seen:
                return False
            paths[item["id"]] = item["location"]
            seen.add(item["location"])
        seen.clear()
        for item in value["links"]:
            if not isinstance(item, dict) or item.get("type") != "internal-link" or not isinstance(item.get("text"), str):
                return False
            for field in ("location", "target_id", "target_location"):
                _identifier(item.get(field), field)
            if item["location"] in seen or paths.get(item["target_id"]) != item["target_location"]:
                return False
            if item.get("content_hash") != hashlib.sha256(item["text"].encode("utf-8")).hexdigest():
                return False
            seen.add(item["location"])
    except (ValueError, UnicodeEncodeError):
        return False
    return True


def _compare_references(
    source: Any, target: Any, available: bool, *, matching_budget: _MatchingBudget | None = None
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    if not available or not _inventory_valid(source) or not _inventory_valid(target):
        return {
            "available": False,
            "lost_anchors": None,
            "changed_anchors": None,
            "added_anchors": None,
            "lost_links": None,
            "changed_links": None,
            "added_links": None,
            "link_matches": [],
            "changes": [],
        }, []
    budget = matching_budget or _MatchingBudget()
    try:
        budget.charge(len(source["anchors"]) + len(target["anchors"]))
    except _MatchingLimitError as error:
        result, _ = _compare_references(source, target, False)
        result.update(reason="matching-budget-exceeded", matching_budget=error.measurement)
        return result, [ConversionIssue(IssueSeverity.INFO, "reference-matching-unavailable", str(error), "references")]
    before = {item["id"]: item for item in source["anchors"]}
    after = {item["id"]: item for item in target["anchors"]}
    changes = []
    issues = []

    def record(code: str, left: dict[str, Any], right: dict[str, Any] | None, loss: bool) -> None:
        changes.append({"code": code, "source": left, "target": right})
        issues.append(
            ConversionIssue(IssueSeverity.LOSS if loss else IssueSeverity.WARNING, code, code.replace("-", " "), left["location"])
        )

    for identifier, item in before.items():
        if identifier not in after:
            record("anchor-loss", item, None, True)
        elif item != after[identifier]:
            record("anchor-change", item, after[identifier], False)
    try:
        matches, lost, added = _match_objects(source["links"], target["links"], budget)
    except _MatchingLimitError as error:
        result, _ = _compare_references(source, target, False)
        result.update(reason="matching-budget-exceeded", matching_budget=error.measurement)
        return result, [ConversionIssue(IssueSeverity.INFO, "reference-matching-unavailable", str(error), "references")]
    for item in lost:
        record("internal-link-loss", item, None, True)
    changed = []
    for match in matches:
        left, right = match["source"], match["target"]
        if left != right:
            changed.append(match)
            record("internal-link-change", left, right, False)
    return {
        "available": True,
        "lost_anchors": sum(identifier not in after for identifier in before),
        "changed_anchors": sum(item["code"] == "anchor-change" for item in changes),
        "added_anchors": [item for identifier, item in after.items() if identifier not in before],
        "lost_links": len(lost),
        "changed_links": len(changed),
        "added_links": added,
        "link_matches": matches,
        "changes": changes,
    }, issues


__all__ = [
    "ANCHOR_PROPERTY",
    "INTERNAL_LINK_PROPERTY",
    "Anchor",
    "InternalLink",
    "get_anchor",
    "get_internal_link",
    "iter_anchors",
    "iter_internal_links",
    "resolve_anchor",
    "set_anchor",
    "set_internal_link",
]
