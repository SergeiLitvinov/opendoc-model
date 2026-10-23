"""Bounded adapter contracts, semantic references and transactional range-aware editing."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import fields, is_dataclass, replace
from typing import Any, NoReturn

from opendoc_model._integration_codec import _decode_integration, _encode_integration
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import CheckResult, DiagnosticIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import DocumentModel, Formula, Image, Paragraph, Resource, ResourceKind, Table, TextRun
from opendoc_model.integration_types import (
    CapabilityProfile,
    Field,
    IntegrationModel,
    PreservationState,
    SceneStyle,
    SheetCell,
    SourceSpan,
    TextPosition,
)
from opendoc_model.limits import DocumentLimits, _quota, _resolve_limits, _utf8_size
from opendoc_model.references import ANCHOR_PROPERTY, get_anchor
from opendoc_model.traversal import Element, _walk_locations

INTEGRATION_PROPERTY = "opendoc.integration"
INTEGRATION_VERSION = 1


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "integration.invalid")


def _nonempty(value: str, path: str) -> None:
    if not isinstance(value, str) or not value:
        _error(path, "expected a nonempty identifier")


def _integer(value: int, path: str, *, minimum: int = 0) -> None:
    if value < minimum:
        _error(path, f"expected an integer >= {minimum}")


def _index(items: Iterable[Any], path: str, *, attribute: str = "id") -> dict[str, Any]:
    result: dict[str, Any] = {}
    for index, item in enumerate(items):
        key = getattr(item, attribute)
        _nonempty(key, f"{path}[{index}].{attribute}")
        if key in result:
            _error(path, f"duplicate identifier {key!r}")
        result[key] = item
    return result


def _reference(value: str | None, registry: dict[str, Any], path: str) -> None:
    if value is not None:
        _nonempty(value, path)
        if value not in registry:
            _error(path, f"unknown reference {value!r}")


def _visual_reference(value: str | None, resources: dict[str, Resource], path: str) -> None:
    _reference(value, resources, path)
    if value is not None and resources[value].kind not in (ResourceKind.RASTER_IMAGE, ResourceKind.VECTOR_IMAGE):
        _error(path, "visual reference requires an image resource")


def _assessment(model: IntegrationModel) -> None:
    assessed = set(model.assessed_features)
    if len(assessed) != len(model.assessed_features) or any(not name for name in model.assessed_features):
        _error("assessed_features", "features must be nonempty and unique")
    for record in model.preservation:
        if record.issue.code not in assessed:
            _error("preservation", "diagnostic feature is not in assessed_features")
        if record.state is not PreservationState.SEMANTIC and not record.issue.reason:
            _error("preservation.issue.reason", "nonsemantic preservation requires an explicit reason")


def _acyclic(edges: dict[str, tuple[str, ...]], path: str, limits: DocumentLimits) -> None:
    """Iterative linear graph check, with separate depth and edge budgets."""
    finished: set[str] = set()
    active: set[str] = set()
    count = 0
    heights: dict[str, int] = {}
    for start in edges:
        pending = [(start, False)]
        while pending:
            node, leaving = pending.pop()
            if leaving:
                heights[node] = 1 + max((heights[child] for child in edges.get(node, ())), default=0)
                if heights[node] > limits.max_depth:
                    _quota(path, "graph depth", limits.max_depth)
                active.remove(node)
                finished.add(node)
                continue
            if node in active:
                _error(path, f"cyclic reference at {node!r}")
            if node in finished:
                continue
            count += 1
            if count > limits.max_nodes:
                _quota(path, "graph nodes", limits.max_nodes)
            active.add(node)
            if len(active) > limits.max_depth:
                _quota(path, "graph depth", limits.max_depth)
            pending.append((node, True))
            pending.extend((child, False) for child in reversed(edges.get(node, ())))


def _anchors(document: DocumentModel, limits: DocumentLimits) -> tuple[dict[str, Element], dict[str, int]]:
    nodes: dict[str, Element] = {}
    order: dict[str, int] = {}
    for location in _walk_locations(document, limits):
        node = location.node
        if not isinstance(node, (Paragraph, Table, TextRun, Image, Formula)) or ANCHOR_PROPERTY not in node.properties:
            continue
        anchor = get_anchor(node, limits=limits)
        if anchor is not None:
            if anchor.id in nodes:
                _error(location.path, f"duplicate anchor {anchor.id!r}")
            nodes[anchor.id] = node
            order[anchor.id] = len(order)
    return nodes, order


def _validate_integration(model: IntegrationModel, document: DocumentModel, limits: DocumentLimits) -> None:
    nodes, order = _anchors(document, limits)
    resources = document.resources
    registries: dict[str, dict[str, Any]] = {}
    collections = (
        "profiles",
        "unknown_fragments",
        "ranges",
        "fields",
        "bibliography",
        "comments",
        "revisions",
        "content_controls",
        "scenes",
        "charts",
        "diagrams",
        "scene_styles",
        "pages",
        "annotations",
        "forms",
        "media",
        "timing",
        "workbooks",
    )
    for name in collections:
        registries[name] = _index(getattr(model, name), name)
    from opendoc_model.outline import _validate_outline

    _validate_outline(model, nodes, limits)
    ranges, bibliography = registries["ranges"], registries["bibliography"]
    for profile in model.profiles:
        _integer(profile.version, "profile.version", minimum=1)
        for feature in _index(profile.features, "profile.features", attribute="feature").values():
            _integer(feature.schema_version, "feature.schema_version", minimum=1)
            if not feature.states or len(set(feature.states)) != len(feature.states):
                _error("profile.features", "states must be nonempty and unique")
    _assessment(model)
    for record in model.preservation:
        _nonempty(record.issue.code, "preservation.issue.code")
        _reference(record.node_id, nodes, "preservation.node_id")
        if record.provenance is not None:
            _nonempty(record.provenance.source_format, "preservation.provenance.source_format")
            if record.provenance.page is not None:
                _integer(record.provenance.page, "preservation.provenance.page")
            for event in record.provenance.events:
                _nonempty(event.operation, "preservation.provenance.events.operation")
    sources = _index(model.source_map.sources, "source_map.sources")
    expansions = _index(model.source_map.expansions, "source_map.expansions", attribute="object_id")
    for source in sources.values():
        _nonempty(source.uri, "source.uri")
        _reference(source.resource_id, resources, "source.resource_id")
        if source.size is not None:
            _integer(source.size, "source.size")
        if source.sha256 is not None and re.fullmatch(r"[0-9a-f]{64}", source.sha256) is None:
            _error("source.sha256", "expected a lowercase SHA-256 digest")
        if source.resource_id is not None:
            data = resources[source.resource_id].data
            if data is not None:
                import hashlib

                if source.sha256 is not None and hashlib.sha256(data).hexdigest() != source.sha256:
                    _error("source.sha256", "source snapshot digest mismatch")
                if source.offset_unit == "byte" and source.size is not None and len(data) != source.size:
                    _error("source.size", "byte size differs from the source snapshot")

    def span(value: SourceSpan) -> None:
        _reference(value.source_id, sources, "source_span.source_id")
        _integer(value.start, "source_span.start")
        if value.end < value.start or sources[value.source_id].size is not None and value.end > sources[value.source_id].size:
            _error("source_span.end", "invalid source interval")
        for name in ("line", "column"):
            coordinate = getattr(value, name)
            if coordinate is not None:
                _integer(coordinate, f"source_span.{name}", minimum=1)
        _reference(value.expansion_id, expansions, "source_span.expansion_id")

    for mapping in _index(model.source_map.mappings, "source_map.mappings", attribute="node_id").values():
        _reference(mapping.node_id, nodes, "source_map.node_id")
        for value in mapping.spans:
            span(value)
    for value in model.source_map.expansions:
        span(value)
    _acyclic(
        {key: (value.expansion_id,) if value.expansion_id else () for key, value in expansions.items()}, "source_map", limits
    )
    for fragment in model.unknown_fragments:
        _reference(fragment.node_id, nodes, "fragment.node_id")
        _reference(fragment.resource_id, resources, "fragment.resource_id")
        _visual_reference(fragment.visual_resource_id, resources, "fragment.visual_resource_id")
        _integer(fragment.max_bytes, "fragment.max_bytes")
        resource = resources[fragment.resource_id]
        if resource.media_type != fragment.media_type or not fragment.media_type:
            _error("fragment.media_type", "media type differs from the referenced resource")
        if resource.data is None:
            _error("fragment.resource_id", "unknown syntax requires embedded bytes; external sources are never opened")
        if len(resource.data) > min(fragment.max_bytes, limits.max_embedded_bytes):
            _quota("fragment", "embedded bytes", min(fragment.max_bytes, limits.max_embedded_bytes))
        if fragment.export_policy == "visual" and fragment.visual_resource_id is None:
            _error("fragment.visual_resource_id", "visual policy requires a visual resource")
        if fragment.source is not None:
            span(fragment.source)

    def position(value: TextPosition) -> tuple[int, int]:
        _reference(value.node_id, nodes, "range.node_id")
        node = nodes[value.node_id]
        if not isinstance(node, TextRun):
            _error("range.node_id", "range endpoint must reference a TextRun anchor")
        if not 0 <= value.offset <= len(node.text):
            _error("range.offset", "offset is outside the Unicode text")
        return order[value.node_id], value.offset

    for value in model.ranges:
        if position(value.start) > position(value.end):
            _error("range", "range endpoints are reversed in reading order")
    for value in model.fields:
        _reference(value.range_id, ranges, "field.range_id")
        _reference(value.target_id, nodes, "field.target_id")
        if value.kind == "reference" and value.target_id is None:
            _error("field.target_id", "reference field requires a target anchor")
        if value.kind == "citation" and not value.bibliography_ids:
            _error("field.bibliography_ids", "citation requires bibliography entries")
        for key in value.bibliography_ids:
            _reference(key, bibliography, "field.bibliography_ids")
    for name in ("comments", "revisions", "content_controls"):
        for value in getattr(model, name):
            _reference(value.range_id, ranges, f"{name}.range_id")
    for value in model.comments:
        _reference(value.reply_to, registries["comments"], "comment.reply_to")
    _acyclic({value.id: (value.reply_to,) if value.reply_to else () for value in model.comments}, "comments", limits)
    from opendoc_model.graphics import _validate_scene

    for scene_index, scene in enumerate(model.scenes):
        _validate_scene(scene, nodes, resources, limits, f"scenes[{scene_index}]")
    styles = registries["scene_styles"]
    for style in model.scene_styles:
        _reference(style.parent_id, styles, "scene_style.parent_id")
    _acyclic({value.id: (value.parent_id,) if value.parent_id else () for value in model.scene_styles}, "scene_styles", limits)
    for chart in model.charts:
        _reference(chart.node_id, nodes, "chart.node_id")
        _reference(chart.style_id, styles, "chart.style_id")
        _visual_reference(chart.visual_resource_id, resources, "chart.visual_resource_id")
        _index(chart.axes, "chart.axes")
        for axis in chart.axes:
            if axis.minimum is not None and axis.maximum is not None and axis.minimum > axis.maximum:
                _error("chart.axis", "minimum exceeds maximum")
        for series in chart.series:
            if series.categories and len(series.categories) != len(series.values):
                _error("chart.series", "category and value counts differ")
            if series.x_values and len(series.x_values) != len(series.values):
                _error("chart.series", "x and y value counts differ")
            if chart.kind == "scatter" and not series.x_values and series.values:
                _error("chart.series.x_values", "scatter series requires explicit x values")
    for diagram in model.diagrams:
        _reference(diagram.node_id, nodes, "diagram.node_id")
        _reference(diagram.scene_id, registries["scenes"], "diagram.scene_id")
        _reference(diagram.style_id, styles, "diagram.style_id")
        _visual_reference(diagram.visual_resource_id, resources, "diagram.visual_resource_id")
        scene = registries["scenes"][diagram.scene_id]
        shapes = _index((*scene.paths, *scene.groups), "diagram.shapes")
        for start, end in diagram.edges:
            _reference(start, shapes, "diagram.edges")
            _reference(end, shapes, "diagram.edges")
    from opendoc_model.page_geometry import get_page_geometry

    for page in model.pages:
        get_page_geometry(page, limits=limits)
        if page.width <= 0 or page.height <= 0 or len(set(page.reading_order)) != len(page.reading_order):
            _error("page", "invalid dimensions or duplicate reading-order entries")
        for key in page.reading_order:
            _reference(key, nodes, "page.reading_order")
    _index(model.accessibility, "accessibility", attribute="node_id")
    for value in model.accessibility:
        _reference(value.node_id, nodes, "accessibility.node_id")
        _nonempty(value.role, "accessibility.role")
    for name in ("annotations", "forms"):
        for value in getattr(model, name):
            _reference(value.page_id, registries["pages"], f"{name}.page_id")
            if value.box is not None and (value.box.width < 0 or value.box.height < 0):
                _error(f"{name}.box", "box dimensions must be nonnegative points")
    for value in model.annotations:
        _reference(value.range_id, ranges, "annotation.range_id")
    for value in model.media:
        _reference(value.node_id, nodes, "media.node_id")
        _reference(value.resource_id, resources, "media.resource_id")
        _visual_reference(value.poster_resource_id, resources, "media.poster_resource_id")
        if not resources[value.resource_id].media_type.startswith(value.kind + "/"):
            _error("media.resource_id", "resource media type differs from the declared audio/video kind")
        if value.duration is not None and value.duration < 0:
            _error("media.duration", "duration must be nonnegative seconds")
    targets = dict(nodes)
    for name in ("media", "scenes", "charts", "diagrams"):
        for key, value in registries[name].items():
            if key in targets:
                _error("timing.targets", f"ambiguous target identifier {key!r}")
            targets[key] = value
    for value in model.timing:
        _reference(value.target_id, targets, "timing.target_id")
        _reference(value.after_id, registries["timing"], "timing.after_id")
        if value.start < 0 or value.duration < 0:
            _error("timing", "timing values must be nonnegative seconds")
    _acyclic({value.id: (value.after_id,) if value.after_id else () for value in model.timing}, "timing", limits)
    for book in model.workbooks:
        _index(book.sheets, "workbook.sheets")
        for sheet in book.sheets:
            _nonempty(sheet.name, "sheet.name")
            occupied: list[SheetCell] = []
            work = 0
            for cell in sorted(sheet.cells, key=lambda value: (value.row, value.column)):
                _integer(cell.row, "cell.row")
                _integer(cell.column, "cell.column")
                _integer(cell.row_span, "cell.row_span", minimum=1)
                _integer(cell.column_span, "cell.column_span", minimum=1)
                _reference(cell.style_id, styles, "cell.style_id")
                occupied = [other for other in occupied if other.row + other.row_span > cell.row]
                for other in occupied:
                    work += 1
                    if work > limits.max_nodes:
                        _quota("sheet", "overlap comparisons", limits.max_nodes)
                    if other.column < cell.column + cell.column_span and cell.column < other.column + other.column_span:
                        _error("sheet.cells", "overlapping cells or merged ranges")
                occupied.append(cell)
    _index(model.formula_trees, "formula_trees", attribute="node_id")
    for formula in model.formula_trees:
        _reference(formula.node_id, nodes, "formula_tree.node_id")
        if not isinstance(nodes[formula.node_id], Formula):
            _error("formula_tree.node_id", "math AST requires a Formula anchor")
        for key in formula.original_resource_ids:
            _reference(key, resources, "formula_tree.original_resource_ids")
        pending = [formula.root]
        while pending:
            item = pending.pop()
            arity = {"fraction": (2,), "root": (1, 2), "script": (2, 3)}.get(item.kind)
            if arity is not None and len(item.children) not in arity:
                _error("math.children", "wrong mathematical node arity")
            if item.kind in ("identifier", "number", "operator", "text") and item.children:
                _error("math.children", "leaf node must not have children")
            if item.kind in ("identifier", "number", "operator") and not item.value:
                _error("math.value", "mathematical token must not be empty")
            if item.kind == "number" and re.fullmatch(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", item.value) is None:
                _error("math.value", "number must be a decimal mathematical literal")
            if item.kind == "matrix" and any(child.kind != "row" for child in item.children):
                _error("math.children", "matrix children must be rows")
            pending.extend(item.children)


def _read_integration(raw: Any, budget: DocumentLimits) -> IntegrationModel | None:
    _json_tree(raw, INTEGRATION_PROPERTY, budget)
    if not isinstance(raw, dict) or raw.get("format") != INTEGRATION_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != INTEGRATION_VERSION:
        _error(INTEGRATION_PROPERTY, "unsupported integration schema version")
    if "data" not in raw:
        _error(INTEGRATION_PROPERTY, "missing integration data")
    return _decode_integration(raw["data"], budget)


def integration_to_dict(value: IntegrationModel, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Encode an independent schema-v1 envelope, without resolving document references."""
    budget = _resolve_limits(limits)
    if not isinstance(value, IntegrationModel):
        _error(INTEGRATION_PROPERTY, "expected IntegrationModel")
    result = {"format": INTEGRATION_PROPERTY, "version": INTEGRATION_VERSION, "data": _encode_integration(value, budget)}
    _json_tree(result, INTEGRATION_PROPERTY, budget)
    return result


def integration_from_dict(data: dict[str, Any], *, limits: DocumentLimits | None = None) -> IntegrationModel:
    """Decode a schema-v1 envelope; owner/reference validation remains separate.

    Unknown record fields are retained in extra. Transport-envelope fields outside
    format/version/data belong to the owner, as with get_integration.
    """
    result = _read_integration(data, _resolve_limits(limits))
    if result is None:
        _error(INTEGRATION_PROPERTY, "expected an opendoc.integration envelope")
    return result


def get_integration(document: DocumentModel, *, limits: DocumentLimits | None = None) -> IntegrationModel | None:
    """Read schema v1 independently; no I/O, parsing, actions or implicit migration."""
    if not isinstance(document, DocumentModel) or not isinstance(document.metadata, Mapping):
        raise ValueError("expected DocumentModel with metadata mapping")
    return _read_integration(document.metadata.get(INTEGRATION_PROPERTY), _resolve_limits(limits))


def set_integration(document: DocumentModel, model: IntegrationModel | None, *, limits: DocumentLimits | None = None) -> None:
    """Validate and commit an independent envelope atomically; retain unknown fields."""
    from opendoc_model._validation import _validate_model

    budget = _resolve_limits(limits)
    existing = get_integration(document, limits=budget)
    if INTEGRATION_PROPERTY in document.metadata and existing is None:
        raise ValueError("integration key is occupied by opaque data")
    if model is not None and not isinstance(model, IntegrationModel):
        raise ValueError("expected IntegrationModel or None")
    previous = document.metadata
    metadata = deepcopy(previous)
    if model is None:
        metadata.pop(INTEGRATION_PROPERTY, None)
    else:
        raw = metadata.get(INTEGRATION_PROPERTY, {})
        raw.update(format=INTEGRATION_PROPERTY, version=INTEGRATION_VERSION, data=_encode_integration(model, budget))
        metadata[INTEGRATION_PROPERTY] = raw
    document.metadata = metadata
    committed = False
    try:
        errors = _validate_model(document, budget)
        if errors:
            raise ValueError("invalid integration: " + "; ".join(errors))
        committed = True
    finally:
        if not committed:
            document.metadata = previous


def _integration_issue(document: DocumentModel, limits: DocumentLimits) -> DiagnosticIssue | None:
    try:
        model = get_integration(document, limits=limits)
        if model is not None:
            _validate_integration(model, document, limits)
    except _DiagnosticError as error:
        return DiagnosticIssue(error.code, IssueSeverity.ERROR, error.message, error.location)
    return None


def preservation_result(model: IntegrationModel, *, limits: DocumentLimits | None = None) -> CheckResult:
    """Reuse CheckResult; explicit incomplete/opaque/visual assessments cannot prove losslessness."""
    budget = _resolve_limits(limits)
    model = _decode_integration(_encode_integration(model, budget), budget)
    _assessment(model)
    issues = [deepcopy(value.issue) for value in model.preservation]
    reported = {value.issue.code for value in model.preservation}
    complete = model.assessment_complete and bool(model.assessed_features) and reported == set(model.assessed_features)
    if not complete:
        issues.append(DiagnosticIssue("preservation.incomplete", IssueSeverity.LOSS, "feature assessment is incomplete"))
    for value in model.preservation:
        if value.state is not PreservationState.SEMANTIC:
            issues.append(
                DiagnosticIssue(
                    value.issue.code,
                    IssueSeverity.ERROR if value.state is PreservationState.REJECTED else IssueSeverity.LOSS,
                    value.issue.message,
                    value.issue.location,
                    {"state": value.state.value, "node_id": value.node_id},
                    value.issue.reason,
                )
            )
    result = CheckResult(issues, {"assessment_complete": complete, "assessed_features": list(model.assessed_features)})
    result.to_dict(limits=budget)
    return result


def negotiate_capabilities(
    source: CapabilityProfile, target: CapabilityProfile, *, limits: DocumentLimits | None = None
) -> dict[str, tuple[PreservationState, ...]]:
    """Return an explicit intersection per source feature; absent/version-mismatched features are unsupported."""
    budget = _resolve_limits(limits)
    holder = _decode_integration(_encode_integration(IntegrationModel(profiles=(source, target)), budget), budget)
    source, target = holder.profiles
    for profile in holder.profiles:
        _integer(profile.version, "profile.version", minimum=1)
        _index(profile.features, "profile.features", attribute="feature")
        for feature in profile.features:
            _integer(feature.schema_version, "feature.schema_version", minimum=1)
            if not feature.states or len(set(feature.states)) != len(feature.states):
                _error("feature.states", "states must be nonempty and unique")
    targets = {value.feature: value for value in target.features}
    return {
        value.feature: tuple(
            state
            for state in value.states
            if value.feature in targets
            and value.schema_version == targets[value.feature].schema_version
            and state in targets[value.feature].states
        )
        for value in source.features
    }


def resolve_scene_style(model: IntegrationModel, style_id: str, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Resolve explicit theme/master/layout/local inheritance on an independent snapshot."""
    budget = _resolve_limits(limits)
    model = _decode_integration(_encode_integration(model, budget), budget)
    _nonempty(style_id, "scene_style.id")
    styles = _index(model.scene_styles, "scene_styles")
    chain: list[SceneStyle] = []
    seen = set()
    current: str | None = style_id
    while current is not None:
        _reference(current, styles, "scene_style")
        if current in seen:
            _error("scene_style", "cyclic inheritance")
        seen.add(current)
        if len(seen) > budget.max_depth:
            _quota("scene_style", "depth", budget.max_depth)
        style = styles[current]
        chain.append(style)
        current = style.parent_id
    result: dict[str, Any] = {}
    for style in reversed(chain):
        result.update(style.properties)
    _json_tree(result, "scene_style", budget)
    return deepcopy(result)


def edit_anchored_text(
    document: DocumentModel, node_id: str, start: int, end: int, text: str, *, limits: DocumentLimits | None = None
) -> DocumentModel:
    """Return an independent edit with remapped ranges; immutable source spans retain original offsets.

    Endpoints within removed text collapse to the replacement boundary according
    to affinity. Structural anchor IDs stay stable. No field/formula code executes.
    """
    from opendoc_model._validation import _validate_model
    from opendoc_model.operations import clone_model

    budget = _resolve_limits(limits)
    errors = _validate_model(document, budget)
    if errors:
        raise ValueError("invalid document: " + "; ".join(errors))
    if type(start) is not int or type(end) is not int or not isinstance(text, str):
        raise ValueError("expected integer offsets and replacement text")
    _nonempty(node_id, "edit.node_id")
    _utf8_size(text, budget.max_bytes, "edit.text")
    nodes, _ = _anchors(document, budget)
    _reference(node_id, nodes, "edit.node_id")
    node = nodes[node_id]
    if not isinstance(node, TextRun) or not 0 <= start <= end <= len(node.text):
        raise ValueError("edit requires TextRun and a valid codepoint interval")
    result = clone_model(document, limits=budget)
    copied_nodes, _ = _anchors(result, budget)
    copied = copied_nodes[node_id]
    assert isinstance(copied, TextRun)
    copied.text = node.text[:start] + text + node.text[end:]
    model = get_integration(result, limits=budget)

    def remap(position: TextPosition) -> TextPosition:
        if position.node_id != node_id or position.offset < start:
            return position
        if position.offset > end:
            return replace(position, offset=position.offset + len(text) - (end - start))
        return replace(position, offset=start + (len(text) if position.affinity == "after" else 0))

    if model is not None:
        adjusted = []
        for value in model.ranges:
            first, last = remap(value.start), remap(value.end)
            if first.node_id == last.node_id and first.offset > last.offset:
                first = replace(first, offset=last.offset)
            adjusted.append(replace(value, start=first, end=last))
        set_integration(result, replace(model, ranges=tuple(adjusted)), limits=budget)
    else:
        errors = _validate_model(result, budget)
        if errors:
            raise ValueError("invalid edit: " + "; ".join(errors))
    return result


def _integration_links(document: DocumentModel, limits: DocumentLimits) -> tuple[tuple[str, str, str], ...]:
    model = get_integration(document, limits=limits)
    if model is None:
        return ()
    nodes, _ = _anchors(document, limits)
    result = []
    pending: list[tuple[Any, str]] = [(model, "metadata['opendoc.integration'].data")]
    resource_names = {"resource_id", "visual_resource_id", "mask_resource_id", "poster_resource_id", "profile_resource_id"}
    scene_targets = {value.id for name in ("media", "scenes", "charts", "diagrams") for value in getattr(model, name)}
    while pending:
        value, path = pending.pop()
        if is_dataclass(value) and not isinstance(value, type):
            for definition in fields(value):
                item = getattr(value, definition.name)
                location = f"{path}.{definition.name}"
                if definition.name in resource_names and item is not None:
                    result.append(("resource", item, location))
                elif definition.name == "original_resource_ids":
                    result.extend(("resource", key, f"{location}[{index}]") for index, key in enumerate(item))
                elif definition.name == "node_id" and item is not None:
                    result.append(("anchor", item, location))
                elif (
                    definition.name == "target_id"
                    and item is not None
                    and (isinstance(value, Field) or item not in scene_targets)
                ):
                    result.append(("anchor", item, location))
                elif definition.name == "reading_order":
                    result.extend(("anchor", key, f"{location}[{index}]") for index, key in enumerate(item))
                elif definition.name not in {"extra", "properties", "action", "measurement", "identifiers"}:
                    pending.append((item, location))
        elif isinstance(value, (tuple, list)):
            pending.extend((item, f"{path}[{index}]") for index, item in enumerate(value))
    from opendoc_model.outline import _read_outline

    outline = _read_outline(model, limits)
    if outline is not None:
        for index, entry in enumerate(outline.entries):
            if entry.target is not None and entry.target.kind == "anchor":
                assert entry.target.target_id is not None
                result.append(("anchor", entry.target.target_id, f"outline.entries[{index}].target"))
    return tuple(result)


def _integration_edit_snapshot(document: DocumentModel, limits: DocumentLimits) -> dict[str, str] | None:
    model = get_integration(document, limits=limits)
    if model is None:
        return None
    nodes, _ = _anchors(document, limits)
    endpoints = {value.node_id for item in model.ranges for value in (item.start, item.end)}
    return {key: value.text for key, value in nodes.items() if key in endpoints and isinstance(value, TextRun)}


def _guard_integration_edit(document: DocumentModel, snapshot: dict[str, str] | None, limits: DocumentLimits) -> None:
    if snapshot is None:
        return
    from opendoc_model._validation import _validate_model

    nodes, _ = _anchors(document, limits)
    for key, text in snapshot.items():
        node = nodes.get(key)
        if isinstance(node, TextRun) and node.text != text:
            raise ValueError("text with tracked ranges requires edit_anchored_text")
    errors = _validate_model(document, limits)
    if errors:
        raise ValueError("edit invalidates integration references: " + "; ".join(errors))


def integration_resource_uses(
    document: DocumentModel, resource_id: str, *, limits: DocumentLimits | None = None
) -> tuple[str, ...]:
    """Return typed optional-schema resource paths, complementing structural resource uses."""
    from opendoc_model._validation import _validate_model

    budget = _resolve_limits(limits)
    errors = _validate_model(document, budget)
    if errors:
        raise ValueError("invalid document: " + "; ".join(errors))
    _nonempty(resource_id, "resource_id")
    if resource_id not in document.resources:
        raise ValueError("unknown resource")
    return tuple(
        path for domain, key, path in _integration_links(document, budget) if domain == "resource" and key == resource_id
    )


def _remap_integration(
    document: DocumentModel, anchors: dict[str, str], resources: dict[str, str], limits: DocumentLimits
) -> None:
    model = get_integration(document, limits=limits)
    if model is None:
        return
    resource_names = {"resource_id", "visual_resource_id", "mask_resource_id", "poster_resource_id", "profile_resource_id"}

    def rewrite(value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            changes = {}
            for definition in fields(value):
                item = getattr(value, definition.name)
                if definition.name in resource_names and item is not None:
                    changes[definition.name] = resources.get(item, item)
                elif definition.name == "original_resource_ids":
                    changes[definition.name] = tuple(resources.get(key, key) for key in item)
                elif definition.name in {"node_id", "target_id"} and item is not None:
                    changes[definition.name] = anchors.get(item, item)
                elif definition.name == "reading_order":
                    changes[definition.name] = tuple(anchors.get(key, key) for key in item)
                elif definition.name not in {"extra", "properties", "action", "measurement", "identifiers"}:
                    changes[definition.name] = rewrite(item)
            return replace(value, **changes)
        if isinstance(value, tuple):
            return tuple(rewrite(item) for item in value)
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        return value

    from opendoc_model.outline import _read_outline, _with_outline, remap_outline

    rewritten = rewrite(model)
    outline = _read_outline(model, limits)
    if outline is not None:
        rewritten = _with_outline(rewritten, remap_outline(outline, anchor_ids=anchors, limits=limits), limits)
    document.metadata[INTEGRATION_PROPERTY]["data"] = _encode_integration(rewritten, limits)


__all__ = [
    "INTEGRATION_PROPERTY",
    "INTEGRATION_VERSION",
    "integration_to_dict",
    "integration_from_dict",
    "edit_anchored_text",
    "get_integration",
    "negotiate_capabilities",
    "integration_resource_uses",
    "preservation_result",
    "resolve_scene_style",
    "set_integration",
]
