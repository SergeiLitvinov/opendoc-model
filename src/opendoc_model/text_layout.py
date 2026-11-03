"""Placed glyph observations and explicit text bindings, without shaping or rendering."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal, NoReturn, TypeAlias

import opendoc_model.integration_types as _integration_types
from opendoc_model._integration_codec import _encode_integration
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import (
    Box,
    DocumentModel,
    Length,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    TextRun,
    TextStyle,
)
from opendoc_model.fonts import FontReference
from opendoc_model.integration_types import AffineTransform, IntegrationModel, IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits, _utf8_size
from opendoc_model.properties import VersionedProperties
from opendoc_model.references import _identifier, get_anchor
from opendoc_model.traversal import _walk_locations

# font table index, glyph ID, then a,b,c,d,e,f: glyph-local points to layout-local points.
GlyphPlacement: TypeAlias = tuple[int | None, int | None, float, float, float, float, float, float]


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "text-layout.invalid")


def _binding_index(values: Iterable[Any], path: str) -> dict[str, Any]:
    result = {}
    for value in values:
        if value.id in result:
            _error(path, f"ambiguous binding identifier {value.id!r}")
        result[value.id] = value
    return result


@dataclass(frozen=True)
class TextCluster(IntegrationRecord):
    """Many logical ranges to many placed glyphs; empty ranges mean unknown mapping."""

    glyph_indices: tuple[int, ...]
    range_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class TextLayout(IntegrationRecord):
    """One independent placement occurrence, never a text or reading-order replacement.

    transform maps layout-local points into scene coordinates, or page coordinates
    without a scene. Missing membership remains unknown. Glyph matrices use the
    same affine convention. Glyph design-unit conversion belongs to the producer.
    """

    id: str
    glyphs: tuple[GlyphPlacement, ...] = ()
    fonts: tuple[FontReference, ...] = ()
    clusters: tuple[TextCluster, ...] = ()
    page_id: str | None = None
    scene_id: str | None = None
    transform: AffineTransform = field(default_factory=AffineTransform)
    state: Literal["verified", "unknown", "stale"] = "unknown"
    binding_sha256: str | None = None
    provenance: Provenance | None = None
    binding_version: Literal[1, 2] = field(default=1, kw_only=True, metadata={"omit_default": True})


def _invalidate_layouts(model: IntegrationModel) -> IntegrationModel:
    if not model.text_layouts:
        return model
    return replace(
        model,
        text_layouts=tuple(replace(value, state="stale") if value.state == "verified" else value for value in model.text_layouts),
    )


def _shape(layout: TextLayout, path: str) -> None:
    if not layout.id:
        _error(path + ".id", "expected nonempty layout occurrence ID")
    if layout.provenance is not None and layout.provenance.page is not None and layout.provenance.page < 0:
        _error(path + ".provenance.page", "expected nonnegative page index")
    if layout.binding_sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", layout.binding_sha256) is None:
        _error(path + ".binding_sha256", "expected SHA256 or unknown")
    for index, glyph in enumerate(layout.glyphs):
        font, identifier = glyph[:2]
        here = f"{path}.glyphs[{index}]"
        if font is not None and not 0 <= font < len(layout.fonts):
            _error(here + "[0]", "font table index is out of bounds")
        if identifier is not None:
            if identifier < 0:
                _error(here + "[1]", "glyph ID must be nonnegative or unknown")
            if font is None or layout.fonts[font].face_index is None:
                _error(here + "[1]", "glyph ID requires explicit font program and face index")
    for index, cluster in enumerate(layout.clusters):
        here = f"{path}.clusters[{index}]"
        if len(set(cluster.glyph_indices)) != len(cluster.glyph_indices):
            _error(here + ".glyph_indices", "duplicate glyph index")
        if any(not 0 <= value < len(layout.glyphs) for value in cluster.glyph_indices):
            _error(here + ".glyph_indices", "glyph index is out of bounds")
        if len(set(cluster.range_ids)) != len(cluster.range_ids) or any(not value for value in cluster.range_ids):
            _error(here + ".range_ids", "range IDs must be nonempty and distinct")
    if layout.state == "verified" and (
        layout.binding_sha256 is None
        or not layout.clusters
        or any(not value.range_ids or not value.glyph_indices for value in layout.clusters)
    ):
        _error(path + ".state", "verified binding requires a snapshot and mapped clusters")
    if layout.state == "verified" and {index for cluster in layout.clusters for index in cluster.glyph_indices} != set(
        range(len(layout.glyphs))
    ):
        _error(path + ".state", "verified binding requires an explicit mapping for every glyph placement")


def _fingerprint(
    document: DocumentModel,
    model: IntegrationModel,
    layout: TextLayout,
    limits: DocumentLimits,
    cache: dict[str, Any] | None = None,
) -> str:
    from opendoc_model.document_codec import _box_to_dict, _style_to_dict

    def properties_wire(value: Any) -> dict[str, Any]:
        if isinstance(value, VersionedProperties):
            return value.to_dict()
        if isinstance(value, dict):
            return dict(value)
        _error("text_layout.binding.properties", "expected a property mapping")

    def style_wire(style: Any) -> dict[str, Any]:
        if not isinstance(style, TextStyle):
            _error("text_layout.binding.style", "expected TextStyle")
        if style.font_size is not None and not isinstance(style.font_size, Length):
            _error("text_layout.binding.style.font_size", "expected Length or unknown")
        properties_wire(style.properties)
        raw = _style_to_dict(style)
        if raw["font_size_pt"] is not None:
            if type(raw["font_size_pt"]) not in (int, float):
                _error("text_layout.binding.style.font_size", "expected a numeric point length")
            try:
                raw["font_size_pt"] = float(raw["font_size_pt"])
            except (OverflowError, ValueError, TypeError) as error:
                raise _DiagnosticError(
                    "text_layout.binding.style.font_size",
                    "point length is outside the supported numeric range",
                    "text-layout.invalid",
                ) from error
        return raw

    cache = {} if cache is None else cache
    if "runs" not in cache:
        if not isinstance(document.styles, dict) or not isinstance(document.resources, dict):
            _error("text_layout.binding", "expected document style and resource mappings")
        runs: list[tuple[TextRun, Paragraph | None]] = []
        anchors: dict[str, int] = {}
        for location in _walk_locations(document, limits):
            if not isinstance(location.node, TextRun):
                continue
            anchor = get_anchor(location.node, limits=limits)
            if anchor is not None:
                if anchor.id in anchors:
                    _error(location.path, f"ambiguous text owner {anchor.id!r}")
                anchors[anchor.id] = len(runs)
            parent = location.parent.node if location.parent is not None else None
            if isinstance(parent, Paragraph) and parent.box is not None and not isinstance(parent.box, Box):
                _error(location.path, "expected paragraph Box or unknown")
            runs.append((location.node, parent if isinstance(parent, Paragraph) else None))
        cache.update(
            runs=runs,
            anchors=anchors,
            fonts={},
            work=0,
            styles={key: style_wire(value) for key, value in document.styles.items()},
            ranges=_binding_index(model.ranges, "text_layout.binding.ranges"),
            pages=_binding_index(model.pages, "text_layout.binding.pages"),
            scenes=_binding_index(model.scenes, "text_layout.binding.scenes"),
        )
    runs, anchors = cache["runs"], cache["anchors"]
    ranges = cache["ranges"]
    selections = []
    owners: list[dict[str, Any]] = []
    owner_indices: dict[int, int] = {}

    def owner_wire(run: TextRun, parent: Paragraph | None) -> dict[str, Any]:
        return {
            "text": run.text,
            "style": style_wire(run.style),
            "paragraph_style": parent.style_id if parent else None,
            "paragraph_properties": properties_wire(parent.properties) if parent else {},
            "paragraph_alignment": parent.alignment if parent else None,
            "paragraph_box": _box_to_dict(parent.box) if parent else None,
        }

    selected_work = 0
    for key in dict.fromkeys(key for cluster in layout.clusters for key in cluster.range_ids):
        if key not in ranges:
            _error("text_layout.binding", f"unknown range {key!r}")
        value = ranges[key]
        if value.start.node_id not in anchors or value.end.node_id not in anchors:
            _error("text_layout.binding", "missing text owner")
        first, last = anchors[value.start.node_id], anchors[value.end.node_id]
        selected_work += max(0, last - first + 1)
        if cache["work"] + selected_work > limits.max_nodes:
            _quota("text_layout.binding", "layout binding work", limits.max_nodes)
        selected_owners: list[Any] = []
        for index in range(first, last + 1):
            if layout.binding_version == 1:
                selected_owners.append(owner_wire(*runs[index]))
            else:
                if index not in owner_indices:
                    owner_indices[index] = len(owners)
                    owners.append(owner_wire(*runs[index]))
                selected_owners.append(owner_indices[index])
        selections.append(
            {
                "range": [
                    key,
                    value.start.node_id,
                    value.start.offset,
                    value.start.affinity,
                    value.end.node_id,
                    value.end.offset,
                    value.end.affinity,
                ],
                "owners": selected_owners,
            }
        )
    fonts = []
    for font in layout.fonts:
        resource = document.resources.get(font.resource_id)
        if not isinstance(resource, Resource) or resource.kind is not ResourceKind.FONT:
            _error("text_layout.fonts", "expected an existing FONT resource")
        if resource.id != font.resource_id:
            _error("text_layout.fonts", "font resource ID does not match its registry key")
        if font.resource_id not in cache["fonts"]:
            cache["fonts"][font.resource_id] = hashlib.sha256(resource.data).hexdigest() if resource.data is not None else None
        fonts.append(
            [
                font.resource_id,
                font.face_index,
                resource.media_type,
                properties_wire(resource.properties),
                resource.source,
                cache["fonts"][font.resource_id],
            ]
        )
    declaration = replace(layout, state="unknown", binding_sha256=None)
    page = cache["pages"].get(layout.page_id)
    scene = cache["scenes"].get(layout.scene_id)
    payload = {
        "layout": _encode_integration(IntegrationModel(text_layouts=(declaration,)), limits),
        "selections": selections,
        "fonts": fonts,
        "styles": cache["styles"],
        "membership": {
            "page": [page.width, page.height, page.extra] if page is not None else None,
            "scene": [scene.width, scene.height, scene.extra] if scene is not None else None,
        },
    }
    if layout.binding_version == 2:
        payload["owners"] = owners
    _json_tree(payload, "text_layout.binding", limits)
    cache["work"] += _guard_model(payload, limits)[0]
    if cache["work"] > limits.max_nodes:
        _quota("text_layout.binding", "layout binding work", limits.max_nodes)
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    _utf8_size(encoded, limits.max_bytes, "text_layout.binding")
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_layouts(model: IntegrationModel, document: DocumentModel, limits: DocumentLimits) -> None:
    identifiers: set[str] = set()
    ranges = {value.id for value in model.ranges}
    pages, scenes = {value.id for value in model.pages}, {value.id for value in model.scenes}
    cache: dict[str, Any] = {}
    for index, layout in enumerate(model.text_layouts):
        path = f"text_layouts[{index}]"
        _shape(layout, path)
        if layout.id in identifiers:
            _error(path + ".id", "duplicate layout occurrence ID")
        identifiers.add(layout.id)
        for name, available in (("page_id", pages), ("scene_id", scenes)):
            key = getattr(layout, name)
            if key is not None and key not in available:
                _error(path + "." + name, "unknown membership reference")
        for font_index, font in enumerate(layout.fonts):
            resource = document.resources.get(font.resource_id)
            if not isinstance(resource, Resource) or resource.kind is not ResourceKind.FONT:
                _error(f"{path}.fonts[{font_index}].resource_id", "expected an existing FONT resource")
        for cluster_index, cluster in enumerate(layout.clusters):
            if any(key not in ranges for key in cluster.range_ids):
                _error(f"{path}.clusters[{cluster_index}].range_ids", "unknown text range")
        if layout.state == "verified" and layout.binding_sha256 != _fingerprint(document, model, layout, limits, cache):
            _error(path + ".state", "text layout is stale; explicitly invalidate or replace its binding")


def get_text_layout(document: DocumentModel, layout_id: str, *, limits: DocumentLimits | None = None) -> TextLayout | None:
    """Read a detached occurrence, reporting stale snapshots without modifying the owner."""
    from opendoc_model.integration import get_integration

    budget = _resolve_limits(limits)
    _guard_model(document, budget)
    if not isinstance(layout_id, str) or not layout_id:
        raise ValueError("expected nonempty layout ID")
    model = get_integration(document, limits=budget)
    if model is None:
        return None
    matches = [value for value in model.text_layouts if value.id == layout_id]
    if len(matches) > 1:
        _error("text_layout.id", "duplicate layout occurrence ID")
    if not matches:
        return None
    layout = matches[0]
    if layout.state == "verified":
        try:
            current = _fingerprint(document, model, layout, budget)
        except _DiagnosticError:
            return replace(layout, state="stale")
        if current != layout.binding_sha256:
            return replace(layout, state="stale")
    return layout


def set_text_layout(
    document: DocumentModel, layout: TextLayout, *, verify: bool = False, limits: DocumentLimits | None = None
) -> None:
    """Commit atomically. verify explicitly asserts the supplied mapping, not native fidelity."""
    set_text_layouts(document, (layout,), verify=verify, limits=limits)


def set_text_layouts(
    document: DocumentModel, layouts: Iterable[TextLayout], *, verify: bool = False, limits: DocumentLimits | None = None
) -> None:
    """Merge a bounded batch by ID, asserting supplied bindings only when verify=True.

    Preserve other occurrences and old extra fields. Normalize the batch together,
    share snapshot context and commit through full owner validation once.
    """
    from opendoc_model.integration import get_integration, integration_from_dict, integration_to_dict, set_integration

    budget = _resolve_limits(limits)
    _guard_model(document, budget)
    if type(verify) is not bool:
        raise ValueError("verify must be bool")
    try:
        iterator = iter(layouts)
    except TypeError as error:
        raise ValueError("layouts must be an iterable of TextLayout") from error
    supplied = []
    for index, layout in enumerate(iterator):
        if index >= budget.max_nodes:
            _quota("text_layouts.input", "nodes", budget.max_nodes)
        if type(layout) is not TextLayout:
            _error(f"text_layouts.input[{index}]", "expected TextLayout")
        supplied.append(layout)
    normalized = integration_from_dict(
        integration_to_dict(IntegrationModel(text_layouts=tuple(supplied)), limits=budget), limits=budget
    ).text_layouts
    model = get_integration(document, limits=budget) or IntegrationModel()
    existing = _binding_index(model.text_layouts, "text_layouts")
    # Reject duplicate declarations before calculating any producer snapshots.
    _binding_index(normalized, "text_layouts.input")
    updates = {}
    cache: dict[str, Any] = {}
    for layout in normalized:
        if layout.id in existing:
            layout = replace(layout, extra={**existing[layout.id].extra, **layout.extra})
        if verify:
            candidate = replace(layout, state="unknown", binding_sha256=None, binding_version=2)
            layout = replace(candidate, state="verified", binding_sha256=_fingerprint(document, model, candidate, budget, cache))
        updates[layout.id] = layout
    values = tuple(updates.get(value.id, value) for value in model.text_layouts)
    values += tuple(value for key, value in updates.items() if key not in existing)
    set_integration(document, replace(model, text_layouts=values), limits=budget)


def invalidate_text_layout(
    document: DocumentModel, layout_id: str, *, detach: bool = False, limits: DocumentLimits | None = None
) -> None:
    """Invalidate one occurrence; use the batch API when several snapshots are stale."""
    invalidate_text_layouts(document, (layout_id,), detach=detach, limits=limits)


def invalidate_text_layouts(
    document: DocumentModel,
    layout_ids: Iterable[str] | None = None,
    *,
    detach: bool = False,
    limits: DocumentLimits | None = None,
) -> None:
    """Invalidate selected occurrences atomically; None selects all, unknown stays unknown.

    Other invalid references still fail full owner validation. The identifier
    iterable is bounded, even when repeatedly yielding the same identifier.
    """
    from opendoc_model.integration import get_integration, set_integration

    budget = _resolve_limits(limits)
    _guard_model(document, budget)
    if type(detach) is not bool:
        raise ValueError("detach must be bool")
    model = get_integration(document, limits=budget)
    available = {value.id for value in model.text_layouts} if model is not None else set()
    if layout_ids is None:
        selected = available
    else:
        if isinstance(layout_ids, (str, bytes)):
            raise ValueError("layout_ids must be an iterable of IDs, not a string")
        try:
            iterator = iter(layout_ids)
        except TypeError as error:
            raise ValueError("layout_ids must be an iterable of IDs or None") from error
        selected = set()
        for index, key in enumerate(iterator):
            if index >= budget.max_nodes:
                _quota("text_layout.ids", "nodes", budget.max_nodes)
            _identifier(key, f"text_layout.ids[{index}]")
            if key not in available:
                _error(f"text_layout.ids[{index}]", "unknown text layout")
            selected.add(key)
    if model is None:
        return
    values = []
    for value in model.text_layouts:
        if value.id in selected:
            value = replace(value, state="stale" if value.state == "verified" else value.state)
            if detach:
                value = replace(
                    value, clusters=tuple(replace(cluster, range_ids=()) for cluster in value.clusters), binding_sha256=None
                )
        values.append(value)
    set_integration(document, replace(model, text_layouts=tuple(values)), limits=budget)


def remove_text_layout(document: DocumentModel, layout_id: str, *, limits: DocumentLimits | None = None) -> None:
    """Remove one occurrence atomically; ranges, font resources and text remain owned separately."""
    from opendoc_model.integration import get_integration, set_integration

    budget = _resolve_limits(limits)
    model = get_integration(document, limits=budget)
    if model is None or not any(value.id == layout_id for value in model.text_layouts):
        raise ValueError("unknown text layout")
    set_integration(
        document,
        replace(model, text_layouts=tuple(value for value in model.text_layouts if value.id != layout_id)),
        limits=budget,
    )


__all__ = [
    "GlyphPlacement",
    "TextCluster",
    "TextLayout",
    "get_text_layout",
    "set_text_layout",
    "set_text_layouts",
    "invalidate_text_layout",
    "invalidate_text_layouts",
    "remove_text_layout",
]

# Resolve the forward annotation for runtime introspection as well as the closed codec.
setattr(_integration_types, "TextLayout", TextLayout)
