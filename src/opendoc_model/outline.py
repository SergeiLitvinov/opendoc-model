"""Inert, format-neutral outline entries with explicit hierarchy and destinations."""

from __future__ import annotations

import math
from collections.abc import Iterator
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, Formula, Provenance, ResourceKind, TextRun
from opendoc_model.integration_types import IntegrationModel, IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits
from opendoc_model.units import Point2D

OUTLINE_PROPERTY = "opendoc.outline"


def _error(path: str, message: str) -> Any:
    raise _DiagnosticError(path, message, "outline.invalid")


def _identifier(value: str | None, path: str) -> None:
    if type(value) is not str or not value:
        _error(path, "expected a nonempty identifier")


def _finite(value: float, path: str) -> None:
    if type(value) not in (int, float):
        _error(path, "expected a finite number")
    try:
        valid = math.isfinite(value)
    except OverflowError:
        _error(path, "number exceeds floating point range")
    if not valid:
        _error(path, "expected a finite number")


@dataclass(frozen=True)
class OutlineTarget(IntegrationRecord):
    """Anchor/page ID or inert external URI; page points are source coordinates in pt.

    Zoom is a positive ratio, not a percentage. Missing point/zoom means unknown.
    No URI, action, layout or destination is executed or resolved externally.
    """

    kind: Literal["anchor", "page", "external"]
    target_id: str | None = None
    uri: str | None = None
    point: Point2D | None = None
    zoom: float | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("anchor", "page", "external"):
            _error("outline.target.kind", "unsupported destination kind")
        if self.kind == "external":
            _identifier(self.uri, "outline.target.uri")
            if self.target_id is not None:
                _error("outline.target.target_id", "external destination has no local ID")
        else:
            _identifier(self.target_id, "outline.target.target_id")
            if self.uri is not None:
                _error("outline.target.uri", "local destination has no external URI")
        if self.kind != "page" and (self.point is not None or self.zoom is not None):
            _error("outline.target", "point and zoom require a page destination")
        if self.point is not None:
            if type(self.point) is not Point2D:
                _error("outline.target.point", "expected Point2D")
            _finite(self.point.x, "outline.target.point.x")
            _finite(self.point.y, "outline.target.point.y")
        if self.zoom is not None:
            _finite(self.zoom, "outline.target.zoom")
            if self.zoom <= 0:
                _error("outline.target.zoom", "zoom must be positive")


@dataclass(frozen=True)
class OutlineLabel(IntegrationRecord):
    """Separate rich caption with a caller-declared plain title binding, never body text."""

    title: str
    content: tuple[TextRun | Formula, ...] = ()


@dataclass(frozen=True)
class OutlineInlineLocation:
    """Detached outline-local occurrence; edit through set_outline, not body node APIs."""

    entry_id: str
    index: int
    node: TextRun | Formula
    path: str


@dataclass(frozen=True)
class OutlineEntry(IntegrationRecord):
    """Stable outline-local ID, plain title and explicit nonnegative sibling order."""

    id: str
    title: str
    order: int
    parent_id: str | None = None
    target: OutlineTarget | None = None
    provenance: Provenance | None = None
    label: OutlineLabel | None = field(default=None, kw_only=True, metadata={"omit_default": True})

    def __post_init__(self) -> None:
        _identifier(self.id, "outline.entry.id")
        if type(self.title) is not str:
            _error("outline.entry.title", "expected text (empty title is allowed)")
        if type(self.order) is not int or self.order < 0:
            _error("outline.entry.order", "expected a nonnegative integer")
        if self.parent_id is not None:
            _identifier(self.parent_id, "outline.entry.parent_id")


@dataclass(frozen=True)
class Outline(IntegrationRecord):
    """Entries are stored independently of tuple order; roots have parent_id=None."""

    entries: tuple[OutlineEntry, ...] = ()


def _hierarchy(outline: Outline, limits: DocumentLimits) -> None:
    entries: dict[str, OutlineEntry] = {}
    positions: set[tuple[str | None, int]] = set()
    for index, entry in enumerate(outline.entries):
        path = f"outline.entries[{index}]"
        if entry.label is not None:
            if entry.label.title != entry.title:
                _error(f"{path}.label.title", "rich label binding differs from plain title; replace or remove label explicitly")
            if not entry.label.content and entry.title:
                _error(f"{path}.label", "an explicit empty label requires an empty title")
            from opendoc_model.footnotes import get_footnote_reference
            from opendoc_model.references import get_anchor

            for offset, node in enumerate(entry.label.content):
                location = f"{path}.label.content[{offset}]"
                if isinstance(node, Formula) and (node.display or not node.fallback_text):
                    _error(location, "label formulas require inline display=False and a nonempty explicit fallback")
                if get_anchor(node, limits=limits) is not None:
                    _error(location, "label identities use entry ID/index; body anchors are not declared here")
                if isinstance(node, TextRun) and get_footnote_reference(node, limits=limits) is not None:
                    _error(location, "footnote references are not supported in outline labels")
        if entry.id in entries:
            _error(path, "duplicate entry ID")
        position = (entry.parent_id, entry.order)
        if position in positions:
            _error(path, "duplicate sibling order")
        entries[entry.id] = entry
        positions.add(position)
    depths: dict[str, int] = {}
    for entry in outline.entries:
        current: str | None = entry.id
        chain: list[str] = []
        seen: set[str] = set()
        while current is not None and current not in depths:
            if current not in entries:
                _error("outline.parent_id", f"unknown parent {current!r}")
            if current in seen:
                _error("outline.parent_id", "cyclic hierarchy")
            if len(chain) >= limits.max_depth:
                _quota("outline", "hierarchy depth", limits.max_depth)
            seen.add(current)
            chain.append(current)
            current = entries[current].parent_id
        depth = 0 if current is None else depths[current]
        for identifier in reversed(chain):
            depth += 1
            if depth > limits.max_depth:
                _quota("outline", "hierarchy depth", limits.max_depth)
            depths[identifier] = depth


def _read_outline(model: IntegrationModel, limits: DocumentLimits) -> Outline | None:
    raw = model.extra.get(OUTLINE_PROPERTY)
    if raw is None:
        return None
    _json_tree(raw, "outline", limits)
    if not isinstance(raw, dict) or raw.get("format") != OUTLINE_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error("outline.version", "unsupported outline schema version")
    try:
        result: Outline = _convert(
            {key: value for key, value in raw.items() if key not in {"format", "version"}}, Outline, "outline", encode=False
        )
    except _DiagnosticError as error:
        raise _DiagnosticError(error.location, error.message, "outline.invalid") from error
    _hierarchy(result, limits)
    return result


def _with_outline(model: IntegrationModel, outline: Outline | None, limits: DocumentLimits) -> IntegrationModel:
    previous = _read_outline(model, limits)
    if OUTLINE_PROPERTY in model.extra and previous is None:
        _error("outline", "occupied outline key contains opaque data")
    extra = deepcopy(model.extra)
    if outline is None:
        extra.pop(OUTLINE_PROPERTY, None)
    else:
        _guard_model(outline, limits)
        if type(outline) is not Outline:
            _error("outline", "expected Outline or None")
        if not isinstance(outline.extra, dict) or {"format", "version"}.intersection(outline.extra):
            _error("outline.extra", "unknown fields cannot shadow envelope fields")
        if previous is not None:
            outline = replace(outline, extra={**previous.extra, **outline.extra})
        encoded = _convert(outline, Outline, "outline", encode=True)
        _json_tree(encoded, "outline", limits)
        _hierarchy(outline, limits)
        extra[OUTLINE_PROPERTY] = {**encoded, "format": OUTLINE_PROPERTY, "version": 1}
    result = replace(model, extra=extra)
    _guard_model(result, limits)
    return result


def get_outline(document: DocumentModel, *, limits: DocumentLimits | None = None) -> Outline | None:
    """Read independent declarations and hierarchy; document validation checks targets."""
    from opendoc_model.integration import get_integration

    budget = _resolve_limits(limits)
    model = get_integration(document, limits=budget)
    return _read_outline(model, budget) if model is not None else None


def set_outline(document: DocumentModel, outline: Outline | None, *, limits: DocumentLimits | None = None) -> None:
    """Validate and atomically replace declarations in the existing integration envelope."""
    from opendoc_model.integration import get_integration, set_integration

    budget = _resolve_limits(limits)
    model = get_integration(document, limits=budget)
    if model is None and outline is None:
        return
    set_integration(document, _with_outline(model or IntegrationModel(), outline, budget), limits=budget)


def _validate_outline(model: IntegrationModel, anchors: dict[str, Any], limits: DocumentLimits, document: DocumentModel) -> None:
    outline = _read_outline(model, limits)
    if outline is None:
        return
    pages = {page.id for page in model.pages}
    for domain, identifier, path in _label_links(outline, limits):
        available = anchors if domain == "anchor" else document.styles if domain == "style" else document.resources
        if identifier not in available:
            _error(path, f"unknown {domain} reference {identifier!r}")
    for index, entry in enumerate(outline.entries):
        if entry.label is not None:
            from opendoc_model._validation import _Validator
            from opendoc_model.fonts import FONT_REFERENCE_PROPERTY, get_font_reference

            validator = _Validator(limits, resources=document.resources, styles=document.styles)
            for offset, node in enumerate(entry.label.content):
                path = f"outline.entries[{index}].label.content[{offset}]"
                validator.element(node, path)
                raw_font = node.properties.get(FONT_REFERENCE_PROPERTY)
                if isinstance(raw_font, dict) and raw_font.get("format") == FONT_REFERENCE_PROPERTY:
                    _error(path + ".properties", "FONT bindings belong to TextStyle")
                if isinstance(node, TextRun):
                    font = get_font_reference(node.style, limits=limits)
                    if font is not None:
                        resource = document.resources.get(font.resource_id)
                        if resource is None or resource.kind != ResourceKind.FONT:
                            _error(path + ".style", "expected an existing FONT resource")
            for identifier, path in validator.internal_links:
                if identifier not in anchors:
                    _error(path, "unknown internal-link target")
            if validator.errors:
                _error(f"outline.entries[{index}].label", "; ".join(validator.errors))
        target = entry.target
        if target is not None:
            destinations = anchors if target.kind == "anchor" else pages
            if target.kind != "external" and target.target_id not in destinations:
                _error(f"outline.entries[{index}].target", f"unknown {target.kind} destination {target.target_id!r}")
        if entry.provenance is not None:
            if not entry.provenance.source_format:
                _error(f"outline.entries[{index}].provenance", "expected source format")
            if entry.provenance.page is not None and (type(entry.provenance.page) is not int or entry.provenance.page < 0):
                _error(f"outline.entries[{index}].provenance.page", "expected nonnegative source page")


def remap_outline(
    outline: Outline,
    *,
    entry_ids: dict[str, str] | None = None,
    anchor_ids: dict[str, str] | None = None,
    page_ids: dict[str, str] | None = None,
    resource_ids: dict[str, str] | None = None,
    style_ids: dict[str, str] | None = None,
    limits: DocumentLimits | None = None,
) -> Outline:
    """Independently remap explicit IDs; missing map keys retain their IDs.

    This checks hierarchy and budgets, not destination existence in a document.
    It neither combines outlines nor modifies external URI or private extra fields.
    """
    budget = _resolve_limits(limits)
    checked = _read_outline(_with_outline(IntegrationModel(), outline, budget), budget)
    assert checked is not None
    for mapping in (entry_ids, anchor_ids, page_ids, resource_ids, style_ids):
        if mapping is not None:
            _json_tree(mapping, "outline.id_map", budget)
            if not isinstance(mapping, dict):
                _error("outline.id_map", "expected string ID mapping")
            for key, value in mapping.items():
                _identifier(key, "outline.id_map.key")
                _identifier(value, "outline.id_map.value")
    entries = []
    identifiers = entry_ids or {}
    for entry in checked.entries:
        if entry.label is not None:
            _remap_label(entry.label, anchor_ids or {}, resource_ids or {}, style_ids or {}, budget)
        target = entry.target
        if target is not None and target.kind != "external":
            assert target.target_id is not None
            mapping = (anchor_ids if target.kind == "anchor" else page_ids) or {}
            target = replace(target, target_id=mapping.get(target.target_id, target.target_id))
        entries.append(
            replace(
                entry,
                id=identifiers.get(entry.id, entry.id),
                parent_id=identifiers.get(entry.parent_id, entry.parent_id) if entry.parent_id is not None else None,
                target=target,
            )
        )
    result = replace(checked, entries=tuple(entries))
    _read_outline(_with_outline(IntegrationModel(), result, budget), budget)
    return result


def iter_outline_inlines(document: DocumentModel, *, limits: DocumentLimits | None = None) -> Iterator[OutlineInlineLocation]:
    """Walk independent rich-label occurrences, separately from body walk_model."""
    budget = _resolve_limits(limits)
    _guard_model(document, budget)
    outline = get_outline(document, limits=budget)
    if outline is not None:
        for index, entry in enumerate(outline.entries):
            if entry.label is not None:
                for offset, node in enumerate(entry.label.content):
                    yield OutlineInlineLocation(entry.id, offset, node, f"outline.entries[{index}].label.content[{offset}]")


def _label_links(outline: Outline, limits: DocumentLimits) -> Iterator[tuple[str, str, str]]:
    from opendoc_model.fonts import get_font_reference
    from opendoc_model.references import get_internal_link
    from opendoc_model.traversal import _resource_slots

    for index, entry in enumerate(outline.entries):
        if entry.label is None:
            continue
        for offset, node in enumerate(entry.label.content):
            path = f"outline.entries[{index}].label.content[{offset}]"
            for name, identifier, _ in _resource_slots(node):
                if not isinstance(identifier, str) or not identifier:
                    _error(f"{path}.{name}", "expected resource identifier")
                assert isinstance(identifier, str)
                yield "resource", identifier, f"{path}.{name}"
            if isinstance(node, TextRun):
                font = get_font_reference(node.style, limits=limits)
                if font is not None:
                    yield "resource", font.resource_id, f"{path}.style.font_reference"
                for name in ("base_style_id", "numbering_source_style_id"):
                    identifier = node.style.properties.get(name)
                    if identifier is not None:
                        yield "style", identifier, f"{path}.style.properties.{name}"
                link = get_internal_link(node, limits=limits)
                if link is not None:
                    yield "anchor", link.target_id, f"{path}.internal_link"


def _remap_label(
    label: OutlineLabel, anchors: dict[str, str], resources: dict[str, str], styles: dict[str, str], limits: DocumentLimits
) -> None:
    from opendoc_model.fonts import get_font_reference, set_font_reference
    from opendoc_model.references import get_internal_link, set_internal_link
    from opendoc_model.traversal import _resource_slots

    for node in label.content:
        # Snapshot before assignment, as in structural composition.
        slots = list(_resource_slots(node))
        if isinstance(node, TextRun):
            font = get_font_reference(node.style, limits=limits)
            if font is not None:
                set_font_reference(
                    node.style, replace(font, resource_id=resources.get(font.resource_id, font.resource_id)), limits=limits
                )
            for name in ("base_style_id", "numbering_source_style_id"):
                identifier = node.style.properties.get(name)
                if identifier is not None:
                    node.style.properties[name] = styles.get(identifier, identifier)
            link = get_internal_link(node, limits=limits)
            if link is not None:
                set_internal_link(node, replace(link, target_id=anchors.get(link.target_id, link.target_id)), limits=limits)
        for name, identifier, kind in slots:
            if not isinstance(identifier, str) or not identifier:
                _error(name, "expected resource identifier")
            assert isinstance(identifier, str)
            target = resources.get(identifier, identifier)
            if kind == "surrogate":
                assert node.visual_surrogate is not None
                node.visual_surrogate.resource_id = target
            else:
                node.properties[name.removeprefix("properties.")] = target


__all__ = [
    "OUTLINE_PROPERTY",
    "Outline",
    "OutlineEntry",
    "OutlineLabel",
    "OutlineInlineLocation",
    "OutlineTarget",
    "get_outline",
    "set_outline",
    "remap_outline",
    "iter_outline_inlines",
]
