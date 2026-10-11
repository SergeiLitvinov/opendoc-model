"""Declared occurrence mappings; no conversion, file publication or native locator interpretation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Literal, NoReturn, TypeAlias, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import DiagnosticIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import DocumentModel, Provenance, ResourceKind
from opendoc_model.integration_types import IntegrationRecord, PreservationState
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.references import get_anchor, iter_anchors

OBJECT_MAPPING_FORMAT = "opendoc.object-mapping"
MappingPublication: TypeAlias = Literal["unknown", "attempted", "staged", "published", "rejected", "invalidated"]


@dataclass(frozen=True)
class NativeObjectLocator(IntegrationRecord):
    """Opaque, measured address scoped to a format; never parsed or executed by the model."""

    format: str
    value: str


@dataclass(frozen=True)
class ObjectOccurrence(IntegrationRecord):
    """Report-local stable occurrence ID; a resource ID alone is not occurrence identity."""

    id: str
    node_id: str | None = None
    resource_id: str | None = None
    provenance: Provenance | None = None
    native_locator: NativeObjectLocator | None = None


@dataclass(frozen=True)
class MappingReplacement(IntegrationRecord):
    """Declared intermediate representation, referring to an explicitly scoped model resource."""

    kind: Literal["raster", "vector", "opaque"]
    resource_id: str
    scope: Literal["source", "target"]


@dataclass(frozen=True)
class ObjectMappingEntry(IntegrationRecord):
    """One group: explicit many-to-many correspondence, or unknown/confirmed absent targets."""

    id: str
    source_ids: tuple[str, ...]
    state: PreservationState
    issue: DiagnosticIssue
    target_ids: tuple[str, ...] | None = None
    replacement: MappingReplacement | None = None


@dataclass(frozen=True)
class ObjectMapping(IntegrationRecord):
    """Standalone caller-declared evidence. Validity does not verify output publication or fidelity."""

    sources: tuple[ObjectOccurrence, ...] = ()
    targets: tuple[ObjectOccurrence, ...] = ()
    entries: tuple[ObjectMappingEntry, ...] = ()
    publication: MappingPublication = "unknown"
    output_format: str | None = None
    assessment_complete: bool = False
    result_id: str | None = None
    publication_issue: DiagnosticIssue | None = None


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "mapping.invalid")


def _identifier(value: str, path: str) -> None:
    if not isinstance(value, str) or not value:
        _error(path, "expected nonempty string")


def _index(values: tuple[Any, ...], path: str) -> dict[str, Any]:
    result = {}
    for index, value in enumerate(values):
        _identifier(value.id, f"{path}[{index}].id")
        if value.id in result:
            _error(path, "duplicate occurrence/entry identifier")
        result[value.id] = value
    return result


def _local(mapping: ObjectMapping) -> None:
    sources = _index(mapping.sources, "sources")
    targets = _index(mapping.targets, "targets")
    _index(mapping.entries, "entries")
    if mapping.output_format is not None:
        _identifier(mapping.output_format, "output_format")
    active = mapping.publication in ("staged", "published")
    if mapping.result_id is not None:
        _identifier(mapping.result_id, "result_id")
    if active and mapping.output_format is None:
        _error("output_format", "materialized mapping requires a declared output format")
    if not active and mapping.targets:
        _error("targets", "unpublished attempt cannot claim actual output occurrences")
    for scope, objects in (("sources", sources), ("targets", targets)):
        nodes = set()
        for occurrence in objects.values():
            if all(
                value is None
                for value in (occurrence.node_id, occurrence.resource_id, occurrence.provenance, occurrence.native_locator)
            ):
                _error(scope, "occurrence requires a known handle or provenance")
            for name in ("node_id", "resource_id"):
                value = getattr(occurrence, name)
                if value is not None:
                    _identifier(value, f"{scope}.{name}")
            if occurrence.node_id is not None:
                if occurrence.node_id in nodes:
                    _error(scope, "one anchored node cannot denote two distinct occurrences")
                nodes.add(occurrence.node_id)
            if occurrence.provenance is not None:
                _identifier(occurrence.provenance.source_format, f"{scope}.provenance.source_format")
                if occurrence.provenance.page is not None and occurrence.provenance.page < 0:
                    _error(scope, "provenance page must be nonnegative")
                for event in occurrence.provenance.events:
                    _identifier(event.operation, f"{scope}.provenance.events.operation")
            if occurrence.native_locator is not None:
                _identifier(occurrence.native_locator.format, f"{scope}.native_locator.format")
                _identifier(occurrence.native_locator.value, f"{scope}.native_locator.value")
                if scope == "targets" and occurrence.native_locator.format != mapping.output_format:
                    _error(scope, "target locator format differs from output format")
    used_sources: set[str] = set()
    used_targets: set[str] = set()
    for index, entry in enumerate(mapping.entries):
        path = f"entries[{index}]"
        if not entry.source_ids:
            _error(path + ".source_ids", "mapping group requires at least one source")
        for ids, objects, used, name in (
            (entry.source_ids, sources, used_sources, "source_ids"),
            (entry.target_ids or (), targets, used_targets, "target_ids"),
        ):
            if len(set(ids)) != len(ids) or any(identifier not in objects or identifier in used for identifier in ids):
                _error(path + "." + name, "unknown, duplicate or multiply grouped occurrence")
            used.update(ids)
        if not active and entry.target_ids is not None:
            _error(path + ".target_ids", "unpublished result must remain unknown")
        if entry.target_ids == () and entry.state not in (PreservationState.LOST, PreservationState.REJECTED):
            _error(path, "confirmed absent targets require lost/rejected state")
        if entry.state in (PreservationState.LOST, PreservationState.REJECTED) and entry.target_ids:
            _error(path, "lost/rejected entry cannot claim surviving output objects")
        if entry.state is not PreservationState.SEMANTIC and entry.issue.reason is None:
            _error(path + ".issue.reason", "nonsemantic mapping requires a machine reason")
        if entry.state is PreservationState.SEMANTIC and entry.issue.severity in (IssueSeverity.LOSS, IssueSeverity.ERROR):
            _error(path, "semantic state contradicts a loss/error diagnostic")
        if entry.replacement is not None:
            _identifier(entry.replacement.resource_id, path + ".replacement.resource_id")
            if entry.replacement.scope == "target" and not active:
                _error(path, "unpublished replacement cannot refer to actual target resources")
            if entry.replacement.kind == "raster" and entry.state is PreservationState.SEMANTIC:
                _error(path, "raster replacement cannot claim semantic preservation")
    if mapping.assessment_complete and (
        not active
        or not sources
        or used_sources != set(sources)
        or used_targets != set(targets)
        or any(
            entry.target_ids is None or entry.state is PreservationState.VISUAL and entry.replacement is None
            for entry in mapping.entries
        )
    ):
        _error("assessment_complete", "complete mapping requires materialized and fully assessed declared occurrences")


def object_mapping_to_dict(mapping: ObjectMapping, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Return an independent, bounded v1 JSON envelope; never mutate input on failure."""
    budget = _resolve_limits(limits)
    _guard_model(mapping, budget)
    try:
        raw: dict[str, Any] = _convert(mapping, ObjectMapping, "mapping", encode=True)
        checked: ObjectMapping = _convert(raw, ObjectMapping, "mapping", encode=False)
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _local(checked)
    if {"format", "version"}.intersection(raw):
        _error("mapping.extra", "unknown fields cannot shadow format/version")
    raw.update(format=OBJECT_MAPPING_FORMAT, version=1)
    _json_tree(raw, "mapping", budget)
    return raw


def object_mapping_from_dict(data: Any, *, limits: DocumentLimits | None = None) -> ObjectMapping:
    """Read only the explicit v1 schema; no names in data select imports or executable code."""
    budget = _resolve_limits(limits)
    _json_tree(data, "mapping", budget)
    if type(data) is not dict or data.get("format") != OBJECT_MAPPING_FORMAT:
        _error("mapping.format", "expected opendoc.object-mapping")
    if type(data.get("version")) is not int or data["version"] != 1:
        _error("mapping.version", "unsupported object mapping version")
    try:
        result = cast(
            ObjectMapping,
            _convert(
                {key: value for key, value in data.items() if key not in {"format", "version"}},
                ObjectMapping,
                "mapping",
                encode=False,
            ),
        )
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _local(result)
    return result


def validate_object_mapping(
    mapping: ObjectMapping,
    *,
    source: DocumentModel | None = None,
    target: DocumentModel | None = None,
    limits: DocumentLimits | None = None,
) -> None:
    """Validate declarations and references against supplied snapshots, without native/file I/O."""
    budget = _resolve_limits(limits)
    checked = object_mapping_from_dict(object_mapping_to_dict(mapping, limits=budget), limits=budget)
    documents = {"source": source, "target": target}
    for scope, document in documents.items():
        if document is None:
            continue
        errors = document.validate(limits=budget)
        if errors:
            _error(scope, errors[0])
        anchors = {}
        for location in iter_anchors(document, limits=budget):
            anchor = get_anchor(location.node, limits=budget)
            if anchor is not None:
                anchors[anchor.id] = location.node
        occurrences = checked.sources if scope == "source" else checked.targets
        for occurrence in occurrences:
            if occurrence.node_id is not None and occurrence.node_id not in anchors:
                _error(scope + ".node_id", "dangling anchor reference")
            if occurrence.resource_id is not None and occurrence.resource_id not in document.resources:
                _error(scope + ".resource_id", "dangling resource reference")
            if occurrence.node_id is not None and occurrence.resource_id is not None:
                bound_resource = getattr(anchors[occurrence.node_id], "resource_id", None)
                if bound_resource is not None and bound_resource != occurrence.resource_id:
                    _error(scope + ".resource_id", "resource differs from the anchored object's declared resource")
        for entry in checked.entries:
            replacement = entry.replacement
            if replacement is None or replacement.scope != scope:
                continue
            resource = document.resources.get(replacement.resource_id)
            if resource is None:
                _error(scope + ".replacement.resource_id", "dangling replacement resource")
            if replacement.kind == "raster" and resource.kind is not ResourceKind.RASTER_IMAGE:
                _error(scope + ".replacement.kind", "raster replacement requires a declared raster resource")
            if replacement.kind == "vector" and resource.kind is not ResourceKind.VECTOR_IMAGE:
                _error(scope + ".replacement.kind", "vector replacement requires a declared vector resource")


def remap_object_mapping(
    mapping: ObjectMapping,
    *,
    source_nodes: dict[str, str] | None = None,
    target_nodes: dict[str, str] | None = None,
    source_resources: dict[str, str] | None = None,
    target_resources: dict[str, str] | None = None,
    target_locators: dict[str, NativeObjectLocator | None] | None = None,
    limits: DocumentLimits | None = None,
) -> ObjectMapping:
    """Explicit independent remap; occurrence IDs stay stable. Native addresses require fresh evidence."""
    budget = _resolve_limits(limits)
    copied = object_mapping_from_dict(object_mapping_to_dict(mapping, limits=budget), limits=budget)
    for values in (source_nodes, target_nodes, source_resources, target_resources):
        if values is not None:
            _json_tree(values, "remap", budget)
            if type(values) is not dict or any(
                type(key) is not str or type(value) is not str or not value for key, value in values.items()
            ):
                _error("remap", "expected nonempty identifier substitutions")
    if target_locators is not None and (
        type(target_locators) is not dict or set(target_locators) - {item.id for item in copied.targets}
    ):
        _error("target_locators", "unknown target occurrence")

    def occurrences(
        values: tuple[ObjectOccurrence, ...], nodes: dict[str, str], resources: dict[str, str], target_side: bool
    ) -> tuple[ObjectOccurrence, ...]:
        return tuple(
            replace(
                item,
                node_id=nodes.get(item.node_id, item.node_id) if item.node_id is not None else None,
                resource_id=resources.get(item.resource_id, item.resource_id) if item.resource_id is not None else None,
                native_locator=(
                    target_locators.get(item.id, item.native_locator)
                    if target_side and target_locators is not None
                    else item.native_locator
                ),
            )
            for item in values
        )

    result = replace(
        copied,
        sources=occurrences(copied.sources, source_nodes or {}, source_resources or {}, False),
        targets=occurrences(copied.targets, target_nodes or {}, target_resources or {}, True),
        entries=tuple(
            replace(
                entry,
                replacement=replace(
                    entry.replacement,
                    resource_id=(source_resources or {} if entry.replacement.scope == "source" else target_resources or {}).get(
                        entry.replacement.resource_id, entry.replacement.resource_id
                    ),
                )
                if entry.replacement is not None
                else None,
            )
            for entry in copied.entries
        ),
    )
    return object_mapping_from_dict(object_mapping_to_dict(result, limits=budget), limits=budget)


def with_mapping_publication(
    mapping: ObjectMapping,
    publication: MappingPublication,
    *,
    issue: DiagnosticIssue | None = None,
    target_locators: dict[str, NativeObjectLocator | None] | None = None,
    limits: DocumentLimits | None = None,
) -> ObjectMapping:
    """Copy caller-declared lifecycle evidence; never publish a file or revive an invalidated result."""
    budget = _resolve_limits(limits)
    copied = object_mapping_from_dict(object_mapping_to_dict(mapping, limits=budget), limits=budget)
    active = publication in ("staged", "published")
    if active and copied.publication in ("rejected", "invalidated"):
        _error("publication", "a new result requires a fresh mapping")
    if not active and target_locators:
        _error("target_locators", "inactive result cannot retain target locators")
    if target_locators is not None and (
        type(target_locators) is not dict or set(target_locators) - {item.id for item in copied.targets}
    ):
        _error("target_locators", "unknown target occurrence")
    changed = publication != copied.publication
    result = replace(
        copied,
        publication=publication,
        publication_issue=issue,
        targets=tuple(
            replace(
                item,
                native_locator=(target_locators or {}).get(item.id, None if changed else item.native_locator),
            )
            for item in copied.targets
        )
        if active
        else (),
        entries=copied.entries
        if active
        else tuple(
            replace(
                entry,
                target_ids=None,
                replacement=None if entry.replacement is not None and entry.replacement.scope == "target" else entry.replacement,
            )
            for entry in copied.entries
        ),
        assessment_complete=copied.assessment_complete if active else False,
    )
    return object_mapping_from_dict(object_mapping_to_dict(result, limits=budget), limits=budget)


__all__ = [
    "OBJECT_MAPPING_FORMAT",
    "MappingPublication",
    "NativeObjectLocator",
    "ObjectOccurrence",
    "MappingReplacement",
    "ObjectMappingEntry",
    "ObjectMapping",
    "object_mapping_to_dict",
    "object_mapping_from_dict",
    "validate_object_mapping",
    "remap_object_mapping",
    "with_mapping_publication",
]
