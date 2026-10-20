"""Dependency-complete extraction and explicit, independent document merging."""

from __future__ import annotations

from collections import deque
from collections.abc import Collection, Iterable, Iterator
from copy import deepcopy
from dataclasses import dataclass, field, replace
from typing import Literal, TypeAlias, cast

from opendoc_model._validation import _validate_model
from opendoc_model.document_model import (
    Block,
    ConversionMode,
    DocumentModel,
    Footnote,
    Formula,
    Image,
    PackageGraph,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
)
from opendoc_model.footnotes import FOOTNOTE_REFERENCE_PROPERTY, get_footnote_reference, iter_footnote_references
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits
from opendoc_model.lists import LIST_PROPERTY, get_list_item, iter_list_items
from opendoc_model.operations import _attached
from opendoc_model.references import (
    ANCHOR_PROPERTY,
    INTERNAL_LINK_PROPERTY,
    get_anchor,
    get_internal_link,
    iter_anchors,
    iter_internal_links,
)
from opendoc_model.storage import ArtifactLimitError
from opendoc_model.traversal import (
    ModelNode,
    NodeLocation,
    _set_resource_reference,
    _walk_locations,
    iter_resource_references,
)

IdentifierConflictPolicy: TypeAlias = Literal["error", "rename"]
MetadataConflictPolicy: TypeAlias = Literal["error", "keep_first", "keep_last"]
PackagePolicy: TypeAlias = Literal["error", "preserve", "drop"]


@dataclass(frozen=True)
class DocumentIdMap:
    """Original-to-result identifiers for one input, including unchanged IDs."""

    styles: dict[str, str]
    resources: dict[str, str]
    lists: dict[str, str] = field(default_factory=dict)
    anchors: dict[str, str] = field(default_factory=dict)
    footnotes: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class DocumentMerge:
    """Independent merged model and per-input identifier snapshots."""

    document: DocumentModel
    id_maps: tuple[DocumentIdMap, ...]


@dataclass(frozen=True)
class _StyleLink:
    owner: Paragraph | Table | TextStyle
    field: str
    identifier: str
    path: str

    def set(self, identifier: str) -> None:
        if self.field == "style_id" and isinstance(self.owner, (Paragraph, Table)):
            self.owner.style_id = identifier
        else:
            self.owner.properties[self.field] = identifier


def _link(owner: Paragraph | Table | TextStyle, field: str, value: object, path: str) -> Iterator[_StyleLink]:
    if value is not None:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: expected nonempty style identifier")
        yield _StyleLink(owner, field, value, path)


def _text_style_links(style: TextStyle, path: str) -> Iterator[_StyleLink]:
    for name in ("base_style_id", "numbering_source_style_id"):
        yield from _link(style, name, style.properties.get(name), f"{path}.properties.{name}")


def _model_style_links(root: ModelNode, limits: DocumentLimits) -> Iterator[_StyleLink]:
    for reference in _walk_locations(root, limits):
        node, path = reference.node, reference.path
        if isinstance(node, (Paragraph, Table)):
            yield from _link(node, "style_id", node.style_id, f"{path}.style_id")
        if isinstance(node, Paragraph):
            name = "numbering_source_style_id"
            yield from _link(node, name, node.properties.get(name), f"{path}.properties.{name}")
        elif isinstance(node, TextRun):
            yield from _text_style_links(node.style, f"{path}.style")


def _all_style_links(document: DocumentModel, limits: DocumentLimits) -> Iterator[_StyleLink]:
    yield from _model_style_links(document, limits)
    for identifier, style in document.styles.items():
        yield from _text_style_links(style, f"styles[{identifier!r}]")


def _require_document(document: DocumentModel, limits: DocumentLimits, label: str) -> tuple[int, int]:
    if not isinstance(document, DocumentModel):
        raise ValueError(f"{label}: expected DocumentModel")
    try:
        size = _guard_model(document, limits)
    except ArtifactLimitError as error:
        path = None if error.path is None else label + error.path[1:] if error.path.startswith("$") else f"{label}.{error.path}"
        raise ArtifactLimitError(f"{label}: {error}", path=path, quota=error.quota, maximum=error.maximum) from error
    except ValueError as error:
        raise ValueError(f"{label}: {error}") from error
    errors = _validate_model(document, limits, preflight=False)
    if errors:
        raise ValueError(f"{label}: {'; '.join(errors)}")
    return size


def _policy(value: str, choices: tuple[str, ...], name: str) -> None:
    if value not in choices:
        raise ValueError(f"{name}: expected {', '.join(choices)}")


def _inputs(documents: Iterable[DocumentModel], limits: DocumentLimits) -> list[DocumentModel]:
    try:
        iterator = iter(documents)
    except TypeError as error:
        raise ValueError("documents: expected an iterable of DocumentModel") from error
    result: list[DocumentModel] = []
    nodes, embedded = 0, 0
    for index, document in enumerate(iterator):
        if nodes == limits.max_nodes:
            _quota("documents", "nodes", limits.max_nodes)
        remaining = replace(limits, max_nodes=limits.max_nodes - nodes, max_embedded_bytes=limits.max_embedded_bytes - embedded)
        count, byte_count = _require_document(document, remaining, f"documents[{index}]")
        nodes += count
        embedded += byte_count
        for link in _all_style_links(document, limits):
            if link.identifier not in document.styles:
                raise ValueError(f"documents[{index}].{link.path}: unknown style {link.identifier!r}")
        result.append(document)
    if not result:
        raise ValueError("documents: expected at least one document")
    return result


def _anchor_ids(document: ModelNode, limits: DocumentLimits | None) -> list[str]:
    identifiers = []
    for location in iter_anchors(document, limits=limits):
        anchor = get_anchor(location.node, limits=limits)
        assert anchor is not None
        identifiers.append(anchor.id)
    return identifiers


def _definition_ids(
    document: DocumentModel,
    domain: Literal["styles", "resources", "lists", "anchors", "footnotes"],
    limits: DocumentLimits | None = None,
) -> Iterable[str]:
    if domain == "footnotes":
        return [note.id for note in document.footnotes]
    if domain == "anchors":
        return _anchor_ids(document, limits)
    if domain == "lists":
        identifiers: dict[str, None] = {}
        for location in iter_list_items(document, limits=limits):
            item = get_list_item(location.node, limits=limits)
            assert item is not None
            identifiers[item.list_id] = None
        return identifiers
    return document.styles if domain == "styles" else document.resources


def _id_maps(
    documents: list[DocumentModel],
    domain: Literal["styles", "resources", "lists", "anchors", "footnotes"],
    policy: IdentifierConflictPolicy,
    limits: DocumentLimits | None = None,
) -> list[dict[str, str]]:
    reserved = {identifier for document in documents for identifier in _definition_ids(document, domain, limits)}
    used: set[str] = set()
    next_suffix: dict[str, int] = {}
    maps: list[dict[str, str]] = []
    for index, document in enumerate(documents):
        identifiers: dict[str, str] = {}
        for identifier in _definition_ids(document, domain, limits):
            target = identifier
            if target in used:
                if policy == "error":
                    raise ValueError(f"documents[{index}].{domain}[{identifier!r}]: identifier conflict")
                suffix = next_suffix.get(identifier, 2)
                while f"{identifier}~{suffix}" in reserved or f"{identifier}~{suffix}" in used:
                    suffix += 1
                target = f"{identifier}~{suffix}"
                next_suffix[identifier] = suffix + 1
            identifiers[identifier] = target
            used.add(target)
        maps.append(identifiers)
    return maps


def _package(documents: list[DocumentModel], policy: PackagePolicy) -> PackageGraph | None:
    if policy == "drop":
        return None
    packages = [document.package for document in documents]
    if not any(package is not None for package in packages):
        return None
    if len(documents) == 1:
        return packages[0]
    if policy == "error":
        raise ValueError("package: merging opaque packages requires an explicit preserve/drop policy")
    first = packages[0]
    if first is None or any(package is None or package != first for package in packages[1:]):
        raise ValueError("package: preserve requires identical graphs in every input; parts cannot be renamed safely")
    return first


def _rewrite(document: DocumentModel, identifiers: DocumentIdMap, limits: DocumentLimits) -> None:
    from opendoc_model.fonts import _font_links

    font_links = list(_font_links(document, limits))
    # Snapshot values before writing: repeated nodes and shared property bags
    # must not apply a mapping again to an already rewritten identifier.
    styles = list(_all_style_links(document, limits))
    resources = list(iter_resource_references(document, limits=limits))
    lists = [
        (location.node.properties[LIST_PROPERTY], get_list_item(location.node, limits=limits))
        for location in iter_list_items(document, limits=limits)
    ]
    anchors = [
        (location.node.properties[ANCHOR_PROPERTY], get_anchor(location.node, limits=limits))
        for location in iter_anchors(document, limits=limits)
    ]
    internal_links = [
        (location.node.properties[INTERNAL_LINK_PROPERTY], get_internal_link(location.node, limits=limits))
        for location in iter_internal_links(document, limits=limits)
    ]
    note_definitions = [(note, note.id) for note in document.footnotes]
    note_links = [
        (location.node.properties[FOOTNOTE_REFERENCE_PROPERTY], get_footnote_reference(location.node, limits=limits))
        for location in iter_footnote_references(document, limits=limits)
    ]
    for note, identifier in note_definitions:
        note.id = identifiers.footnotes[identifier]
    for value, note_link in note_links:
        assert note_link is not None
        value["note_id"] = identifiers.footnotes[note_link.note_id]
    for value, anchor in anchors:
        assert anchor is not None
        value["id"] = identifiers.anchors[anchor.id]
    for value, link in internal_links:
        assert link is not None
        value["target_id"] = identifiers.anchors[link.target_id]
    for value, item in lists:
        assert item is not None
        value["list_id"] = identifiers.lists[item.list_id]
        for name in ("continuation_of", "parent_id"):
            target = getattr(item, name)
            if target is not None:
                value[name] = identifiers.anchors[target]
    for style_link in styles:
        style_link.set(identifiers.styles[style_link.identifier])
    for resource_link in resources:
        _set_resource_reference(resource_link, identifiers.resources[resource_link.resource_id])
    for font_link in font_links:
        font_link._set(identifiers.resources[font_link.reference.resource_id], limits)
    document.styles = {identifiers.styles[identifier]: style for identifier, style in document.styles.items()}
    remapped_resources = {}
    for identifier, resource in document.resources.items():
        resource.id = identifiers.resources[identifier]
        remapped_resources[resource.id] = resource
    document.resources = remapped_resources
    from opendoc_model.integration import _remap_integration

    _remap_integration(document, identifiers.anchors, identifiers.resources, limits)
    from opendoc_model.table_semantics import _remap_tables

    _remap_tables(document, identifiers.anchors, limits)


def merge_documents(
    documents: Iterable[DocumentModel],
    *,
    conflicts: IdentifierConflictPolicy = "error",
    metadata_conflicts: MetadataConflictPolicy = "error",
    package_policy: PackagePolicy = "error",
    mode: ConversionMode | None = None,
    limits: DocumentLimits | None = None,
) -> DocumentMerge:
    """Concatenate sections, preserving independent definitions and known links.

    Conflicting IDs either fail or get deterministic reserved-name-safe suffixes.
    All definitions, including unused ones, are retained. Metadata overlap and
    differing modes require explicit decisions. Opaque packages are never rewritten.
    Input value/embedded-byte counts share a budget; output is validated separately.
    """
    _policy(conflicts, ("error", "rename"), "conflicts")
    _policy(metadata_conflicts, ("error", "keep_first", "keep_last"), "metadata_conflicts")
    _policy(package_policy, ("error", "preserve", "drop"), "package_policy")
    if mode is not None and not isinstance(mode, ConversionMode):
        raise ValueError("mode: expected ConversionMode or None")
    budget = _resolve_limits(limits)
    inputs = _inputs(documents, budget)
    result_mode = mode or inputs[0].mode
    if mode is None and any(document.mode != result_mode for document in inputs[1:]):
        raise ValueError("mode: input modes differ; select an explicit result mode")
    package = _package(inputs, package_policy)
    style_maps = _id_maps(inputs, "styles", conflicts)
    resource_maps = _id_maps(inputs, "resources", conflicts)
    list_maps = _id_maps(inputs, "lists", conflicts, budget)
    anchor_maps = _id_maps(inputs, "anchors", conflicts, budget)
    note_maps = _id_maps(inputs, "footnotes", conflicts, budget)
    maps = tuple(
        DocumentIdMap(styles, resources, lists, anchors, notes)
        for styles, resources, lists, anchors, notes in zip(
            style_maps, resource_maps, list_maps, anchor_maps, note_maps, strict=True
        )
    )
    result = DocumentModel(mode=result_mode, source_format=inputs[0].source_format, package=deepcopy(package))
    if any(document.source_format != result.source_format for document in inputs[1:]):
        result.source_format = None
    for index, document in enumerate(inputs):
        copied = deepcopy(document)
        _rewrite(copied, maps[index], budget)
        result.sections.extend(copied.sections)
        result.footnotes.extend(copied.footnotes)
        result.styles.update(copied.styles)
        result.resources.update(copied.resources)
        for key, value in copied.metadata.items():
            if key in result.metadata:
                if metadata_conflicts == "error":
                    raise ValueError(f"documents[{index}].metadata[{key!r}]: metadata conflict")
                if metadata_conflicts == "keep_first":
                    continue
            result.metadata[key] = value
        for key, value in copied.footnote_properties.items():
            if key in result.footnote_properties:
                if metadata_conflicts == "error":
                    raise ValueError(f"documents[{index}].footnote_properties[{key!r}]: metadata conflict")
                if metadata_conflicts == "keep_first":
                    continue
            result.footnote_properties[key] = value
        for key, value in copied.footnote_extensions.items():
            if key in result.footnote_extensions:
                if metadata_conflicts == "error":
                    raise ValueError(f"documents[{index}].footnote_extensions[{key!r}]: metadata conflict")
                if metadata_conflicts == "keep_first":
                    continue
            result.footnote_extensions[key] = value
    _require_document(result, budget, "result")
    return DocumentMerge(result, maps)


def _ancestor(location: NodeLocation[ModelNode], expected: type[ModelNode]) -> ModelNode:
    current = location.parent
    while current is not None:
        if isinstance(current.node, expected):
            return current.node
        current = current.parent
    raise ValueError(f"{location.path}: missing structural ancestor {expected.__name__}")


def _section_shell(location: NodeLocation[ModelNode]) -> tuple[Section, str]:
    section = location.section
    if section is None:
        raise ValueError(f"{location.path}: missing containing section")
    top = location
    while top.parent is not None and not isinstance(top.parent.node, Section):
        top = top.parent
    field = cast(str, top.field)
    return replace(
        section,
        headers=[],
        first_page_headers=[],
        even_page_headers=[],
        blocks=[],
        footers=[],
        first_page_footers=[],
        even_page_footers=[],
    ), field


def _selected_sections(location: NodeLocation[ModelNode]) -> list[Section]:
    node = location.node
    if isinstance(node, Section):
        return [node]
    section, field = _section_shell(location)
    getattr(section, field).append(_selected_block(location))
    return [section]


def _selected_block(location: NodeLocation[ModelNode]) -> Block:
    node = location.node
    block: Block
    if isinstance(node, TableCell):
        row = replace(cast(TableRow, _ancestor(location, TableRow)), cells=[node])
        block = replace(cast(Table, _ancestor(location, Table)), rows=[row])
    elif isinstance(node, TableRow):
        block = replace(cast(Table, _ancestor(location, Table)), rows=[node])
    elif isinstance(node, TextRun) or isinstance(node, (Image, Formula)) and location.kind == "inline":
        block = replace(cast(Paragraph, _ancestor(location, Paragraph)), content=[node])
    elif isinstance(node, (Paragraph, Table, Image, Formula)):
        block = node
    else:
        raise ValueError(f"{location.path}: unsupported extraction node")
    return block


def _extra_ids(values: Iterable[str], available: Collection[str], name: str, limits: DocumentLimits) -> set[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name}: expected an iterable of identifiers, not a string")
    try:
        iterator = iter(values)
    except TypeError as error:
        raise ValueError(f"{name}: expected an iterable of identifiers") from error
    identifiers: set[str] = set()
    for index, identifier in enumerate(iterator):
        if index >= limits.max_nodes:
            _quota(name, "nodes", limits.max_nodes)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError(f"{name}[{index}]: expected nonempty identifier")
        if identifier not in available:
            raise ValueError(f"{name}[{index}]: unknown identifier {identifier!r}")
        identifiers.add(identifier)
    return identifiers


def _dependencies(
    selected: DocumentModel,
    source: DocumentModel,
    additional_styles: set[str],
    additional_resources: set[str],
    limits: DocumentLimits,
) -> tuple[set[str], set[str]]:
    _guard_model(selected, limits)
    needed_styles: set[str] = set()
    pending = deque((link.identifier, link.path) for link in _model_style_links(selected, limits))
    pending.extend((identifier, f"additional_styles[{identifier!r}]") for identifier in sorted(additional_styles))
    while pending:
        identifier, path = pending.popleft()
        if identifier in needed_styles:
            continue
        if identifier not in source.styles:
            raise ValueError(f"{path}: unknown style {identifier!r}")
        needed_styles.add(identifier)
        pending.extend(
            (link.identifier, link.path) for link in _text_style_links(source.styles[identifier], f"styles[{identifier!r}]")
        )
    needed_resources = {
        reference.resource_id for reference in iter_resource_references(selected, limits=limits)
    } | additional_resources
    from opendoc_model.fonts import get_font_reference

    for identifier in needed_styles:
        font = get_font_reference(source.styles[identifier], limits=limits)
        if font is not None:
            needed_resources.add(font.resource_id)
    from opendoc_model.fonts import _font_links

    needed_resources.update(link.reference.resource_id for link in _font_links(selected, limits))
    from opendoc_model.integration import _integration_links

    needed_resources.update(key for domain, key, _ in _integration_links(selected, limits) if domain == "resource")
    return needed_styles, needed_resources


def _owner(location: NodeLocation[ModelNode]) -> tuple[str, str | int]:
    current: NodeLocation[ModelNode] | None = location
    while current is not None:
        if isinstance(current.node, Footnote):
            return "footnote", current.node.id
        if isinstance(current.node, Section):
            assert current.index is not None
            return "section", current.index
        current = current.parent
    raise ValueError(f"{location.path}: missing containing section or footnote")


def _semantic_links(root: ModelNode, limits: DocumentLimits) -> Iterator[tuple[str, str]]:
    from opendoc_model.lists import _list_links
    from opendoc_model.table_semantics import _table_links

    yield from (("anchor", key) for key in _list_links(root, limits))
    yield from (("anchor", key) for key in _table_links(root, limits))
    if isinstance(root, DocumentModel):
        from opendoc_model.integration import _integration_links

        yield from ((domain, key) for domain, key, _ in _integration_links(root, limits) if domain == "anchor")
    for location in iter_internal_links(root, limits=limits):
        link = get_internal_link(location.node, limits=limits)
        assert link is not None
        yield "anchor", link.target_id
    for location in iter_footnote_references(root, limits=limits):
        reference = get_footnote_reference(location.node, limits=limits)
        assert reference is not None
        yield "footnote", reference.note_id


def _anchor_dependencies(
    selected: DocumentModel, source: DocumentModel, location: NodeLocation[ModelNode], limits: DocumentLimits
) -> None:
    """Close note/anchor dependencies, expanding each original container at most once."""
    containers: dict[tuple[str, str | int], Section | Footnote] = {}
    if selected.sections:
        containers[_owner(location)] = selected.sections[0]
    if selected.footnotes:
        containers[_owner(location)] = selected.footnotes[0]
    originals: dict[tuple[str, str | int], Section | Footnote] = {
        ("section", index): section for index, section in enumerate(source.sections)
    }
    originals.update({("footnote", note.id): note for note in source.footnotes})
    targets: dict[str, tuple[str, str | int]] = {}
    for reference in iter_anchors(source, limits=limits):
        anchor = get_anchor(reference.node, limits=limits)
        assert anchor is not None
        targets[anchor.id] = _owner(reference)
    from opendoc_model.table_semantics import get_table_semantics

    caption_owners: dict[str, str] = {}
    for table_location in _walk_locations(source, limits):
        if isinstance(table_location.node, Table):
            record = get_table_semantics(table_location.node, limits=limits)
            if record is not None and record.caption_ids:
                owner_anchor = get_anchor(table_location.node, limits=limits)
                assert owner_anchor is not None
                caption_owners.update({key: owner_anchor.id for key in record.caption_ids})
    available = set(_anchor_ids(selected, limits))
    available_notes = {note.id for note in selected.footnotes}
    pending = deque(_semantic_links(selected, limits))
    pending.extend(("anchor", caption_owners[key]) for key in available if key in caption_owners)
    expanded: set[tuple[str, str | int]] = set()
    while pending:
        kind, identifier = pending.popleft()
        if identifier in (available if kind == "anchor" else available_notes):
            continue
        target = targets[identifier] if kind == "anchor" else ("footnote", identifier)
        if target in expanded:
            continue
        expanded.add(target)
        container = originals[target]
        containers[target] = container
        if isinstance(container, Footnote):
            available_notes.add(container.id)
        added_anchors = _anchor_ids(container, limits)
        available.update(added_anchors)
        pending.extend(("anchor", caption_owners[key]) for key in added_anchors if key in caption_owners)
        pending.extend(_semantic_links(container, limits))
    selected.sections = [
        cast(Section, containers[("section", index)]) for index in range(len(source.sections)) if ("section", index) in containers
    ]
    selected.footnotes = [
        cast(Footnote, containers[("footnote", note.id)]) for note in source.footnotes if ("footnote", note.id) in containers
    ]


def extract_document(
    document: DocumentModel,
    location: NodeLocation[ModelNode],
    *,
    package_policy: PackagePolicy = "error",
    additional_styles: Iterable[str] = (),
    additional_resources: Iterable[str] = (),
    limits: DocumentLimits | None = None,
) -> DocumentModel:
    """Extract a dependency-complete independent document from a live occurrence.

    Sections retain all content; smaller subtrees get minimal container shells
    preserving page/section, paragraph or row/table context and header collection.
    Used styles (including transitive links) and resources are copied. Metadata is
    retained; unused definitions are omitted. Package preservation is explicit for
    partial extraction and keeps the entire opaque graph, without pruning bytes.
    """
    _policy(package_policy, ("error", "preserve", "drop"), "package_policy")
    budget = _resolve_limits(limits)
    _require_document(document, budget, "document")
    _attached(document, location)
    extra_styles = _extra_ids(additional_styles, document.styles, "additional_styles", budget)
    extra_resources = _extra_ids(additional_resources, document.resources, "additional_resources", budget)
    if isinstance(location.node, DocumentModel):
        selected = replace(document, version=2, package=_package([document], package_policy))
    else:
        if document.package is not None and package_policy == "error":
            raise ValueError("package: partial extraction requires an explicit preserve/drop policy")
        if isinstance(location.node, Footnote):
            selected_notes = [location.node]
        elif location.section is None:
            note = cast(Footnote, _ancestor(location, Footnote))
            selected_notes = [replace(note, blocks=[_selected_block(location)])]
        else:
            selected_notes = []
        selected = DocumentModel(
            sections=[] if selected_notes else _selected_sections(location),
            footnotes=selected_notes,
            footnote_properties=document.footnote_properties,
            footnote_extensions=document.footnote_extensions,
            metadata=document.metadata,
            package=None if package_policy == "drop" else document.package,
            mode=document.mode,
            source_format=document.source_format,
        )
        _anchor_dependencies(selected, document, location, budget)
        styles, resources = _dependencies(selected, document, extra_styles, extra_resources, budget)
        selected.styles = {identifier: style for identifier, style in document.styles.items() if identifier in styles}
        selected.resources = {
            identifier: resource for identifier, resource in document.resources.items() if identifier in resources
        }
    _require_document(selected, budget, "result")
    return deepcopy(selected)


__all__ = [
    "DocumentIdMap",
    "DocumentMerge",
    "IdentifierConflictPolicy",
    "MetadataConflictPolicy",
    "PackagePolicy",
    "extract_document",
    "merge_documents",
]
