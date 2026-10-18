"""Bounded resource management and explicit local-file embedding."""

from __future__ import annotations

import os
import re
import stat
from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Literal, TypeAlias
from urllib.parse import urlsplit

from opendoc_model._validation import _validate_model
from opendoc_model.document_model import DocumentModel, Resource
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits
from opendoc_model.traversal import ResourceReference, _set_resource_reference, iter_resource_references

ResourceConflictPolicy: TypeAlias = Literal["error", "rename", "replace"]


def _require_document(document: DocumentModel, limits: DocumentLimits) -> int:
    if not isinstance(document, DocumentModel):
        raise ValueError("document must be DocumentModel")
    _, embedded = _guard_model(document, limits)
    errors = _validate_model(document, limits, preflight=False)
    if errors:
        raise ValueError("invalid document: " + "; ".join(errors))
    return embedded


def _identifier(value: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError("resource ID must be a nonempty string")


def _existing(document: DocumentModel, identifier: str) -> Resource:
    _identifier(identifier)
    if identifier not in document.resources:
        raise ValueError(f"unknown resource {identifier!r}")
    return document.resources[identifier]


def _incoming(resource: Resource, limits: DocumentLimits, identifier: str | None = None) -> Resource:
    if not isinstance(resource, Resource):
        raise ValueError("resource must be Resource")
    _identifier(resource.id)
    _require_document(DocumentModel(resources={resource.id: resource}), limits)
    copied = deepcopy(resource)
    if identifier is not None:
        copied.id = identifier
    return copied


def _assign(document: DocumentModel, resource: Resource, limits: DocumentLimits) -> None:
    candidate = replace(document, resources={**document.resources, resource.id: resource})
    _require_document(candidate, limits)
    document.resources[resource.id] = resource


def add_resource(
    document: DocumentModel,
    resource: Resource,
    *,
    conflicts: ResourceConflictPolicy = "error",
    limits: DocumentLimits | None = None,
) -> str:
    """Add an independent copy in place; return its actual ID.

    Conflicts error, rename with the first free ~2/~3 suffix, or replace the
    existing definition keeping its links. No data-based deduplication or
    inference of custom references occurs. Failure leaves the model intact.
    """
    if conflicts not in ("error", "rename", "replace"):
        raise ValueError("conflicts must be error, rename or replace")
    resolved = _resolve_limits(limits)
    _require_document(document, resolved)
    copied = _incoming(resource, resolved)
    if copied.id in document.resources:
        if conflicts == "error":
            raise ValueError(f"duplicate resource id: {copied.id}")
        if conflicts == "rename":
            suffix = 2
            while f"{resource.id}~{suffix}" in document.resources:
                suffix += 1
            copied.id = f"{resource.id}~{suffix}"
    _assign(document, copied, resolved)
    return copied.id


def find_resource_uses(
    document: DocumentModel, resource_id: str, *, limits: DocumentLimits | None = None
) -> tuple[ResourceReference, ...]:
    """Return structural resource slots; font-style bindings use iter_font_references."""
    resolved = _resolve_limits(limits)
    _require_document(document, resolved)
    _existing(document, resource_id)
    return tuple(link for link in iter_resource_references(document, limits=resolved) if link.resource_id == resource_id)


def replace_resource(
    document: DocumentModel,
    resource_id: str,
    resource: Resource,
    *,
    limits: DocumentLimits | None = None,
) -> Resource:
    """Replace a definition in place, normalizing the copy's ID to the target.

    All links keep their ID. Return the detached original Resource; the caller's
    replacement and existing structural nodes remain unchanged.
    """
    resolved = _resolve_limits(limits)
    _require_document(document, resolved)
    old = _existing(document, resource_id)
    copied = _incoming(resource, resolved, resource_id)
    _assign(document, copied, resolved)
    return old


def remove_resource(
    document: DocumentModel,
    resource_id: str,
    *,
    replacement_id: str | None = None,
    limits: DocumentLimits | None = None,
) -> Resource:
    """Remove an unused definition or explicitly redirect all known uses.

    Referenced removal without a distinct existing replacement is an error.
    Snapshots preserve repeated nodes and shared property/surrogate objects.
    Failed final validation rolls back the links before returning control.
    """
    resolved = _resolve_limits(limits)
    _require_document(document, resolved)
    old = _existing(document, resource_id)
    if replacement_id is not None:
        _existing(document, replacement_id)
        if replacement_id == resource_id:
            raise ValueError("replacement_id must differ from resource_id")
    links = tuple(link for link in iter_resource_references(document, limits=resolved) if link.resource_id == resource_id)
    from opendoc_model.fonts import FONT_REFERENCE_PROPERTY, _font_links

    fonts = tuple(link for link in _font_links(document, resolved) if link.reference.resource_id == resource_id)
    font_values = [(link.style, deepcopy(link.style.properties[FONT_REFERENCE_PROPERTY])) for link in fonts]
    if fonts and replacement_id is None:
        raise ValueError(f"resource {resource_id!r} is used at {fonts[0].path}")
    from opendoc_model.integration import _integration_links, _remap_integration

    integration_links = [
        path for domain, key, path in _integration_links(document, resolved) if domain == "resource" and key == resource_id
    ]
    if integration_links and replacement_id is None:
        raise ValueError(f"resource {resource_id!r} is used at {integration_links[0]}")
    if links and replacement_id is None:
        raise ValueError(f"resource {resource_id!r} is used at {links[0].path}")
    candidate = replace(
        document,
        resources={key: value for key, value in document.resources.items() if key != resource_id},
        metadata=deepcopy(document.metadata),
    )
    committed = False
    try:
        if replacement_id is not None:
            for link in links:
                _set_resource_reference(link, replacement_id)
            for font in fonts:
                font._set(replacement_id, resolved)
            _remap_integration(candidate, {}, {resource_id: replacement_id}, resolved)
        _require_document(candidate, resolved)
        committed = True
    finally:
        if not committed:
            for link in links:
                _set_resource_reference(link, resource_id)
            for style, raw in font_values:
                style.properties[FONT_REFERENCE_PROPERTY] = raw
    del document.resources[resource_id]
    if integration_links:
        document.metadata = candidate.metadata
    return old


def find_duplicate_resources(document: DocumentModel, *, limits: DocumentLimits | None = None) -> tuple[tuple[str, ...], ...]:
    """Group exact equal embedded bytes, including empty data, in ID order.

    Kind/media type/properties are not an equality condition. External-only
    sources are not opened or guessed equal. This never redirects links.
    """
    resolved = _resolve_limits(limits)
    _require_document(document, resolved)
    groups: dict[bytes, list[str]] = {}
    for identifier, resource in document.resources.items():
        if resource.data is not None:
            groups.setdefault(resource.data, []).append(identifier)
    return tuple(tuple(identifiers) for identifiers in groups.values() if len(identifiers) > 1)


def _selection(document: DocumentModel, resource_ids: Iterable[str] | None, limits: DocumentLimits) -> list[str]:
    if resource_ids is None:
        return list(document.resources)
    if isinstance(resource_ids, (str, bytes)):
        raise ValueError("resource_ids must be an iterable of IDs, not a string")
    try:
        iterator = iter(resource_ids)
    except TypeError as error:
        raise ValueError("resource_ids must be an iterable of IDs") from error
    selected: dict[str, None] = {}
    for index, identifier in enumerate(iterator):
        if index >= limits.max_nodes:
            _quota("resource_ids", "nodes", limits.max_nodes)
        _existing(document, identifier)
        selected[identifier] = None
    return list(selected)


def _local_path(source: str, base_dir: Path | None) -> Path:
    if not source or source.startswith(("\\\\", "//")):
        raise ValueError("source must be a local filesystem path, not UNC/device/URL")
    # Windows drive prefixes must not be mistaken for URI schemes. Drive-
    # relative C:foo is excluded because it depends on hidden process state.
    drive = re.match(r"^[A-Za-z]:", source)
    if drive:
        if os.name != "nt" or len(source) < 3 or source[2] not in "\\/":
            raise ValueError("source must use an absolute native drive path")
    elif urlsplit(source).scheme:
        raise ValueError("source URLs are not local filesystem paths")
    path = Path(source)
    if not path.is_absolute():
        if base_dir is None:
            raise ValueError("relative source requires an explicit absolute base_dir")
        path = base_dir / path
    return path


def _read_local(path: Path, maximum: int) -> bytes:
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError(f"{path}: source must be a regular file")
    with path.open("rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"{path}: source must be a regular file")
        chunks: list[bytes] = []
        size = 0
        while chunk := stream.read(min(1024 * 1024, maximum - size + 1)):
            size += len(chunk)
            if size > maximum:
                _quota(str(path), "embedded input bytes", maximum)
            chunks.append(chunk)
    return b"".join(chunks)


def embed_resources(
    document: DocumentModel,
    *,
    base_dir: str | Path | None = None,
    resource_ids: Iterable[str] | None = None,
    limits: DocumentLimits | None = None,
) -> DocumentModel:
    """Return an independent document with selected local sources embedded.

    By default all resource definitions are selected, including unused ones.
    Existing data wins without I/O; selected sources become None. Relative
    source needs explicit absolute base_dir, absolute native paths are allowed.
    URLs/UNC/device paths and nonregular files are rejected. Reads are bounded
    by per-file max_bytes and remaining total embedded bytes (including package).
    Filesystem errors propagate. No source file or original model is changed.
    """
    resolved = _resolve_limits(limits)
    embedded = _require_document(document, resolved)
    if base_dir is not None and not isinstance(base_dir, (str, Path)):
        raise ValueError("base_dir must be an absolute path or None")
    directory = Path(base_dir) if base_dir is not None else None
    if directory is not None and (not directory.is_absolute() or str(directory).startswith(("\\\\", "//"))):
        raise ValueError("base_dir must be an absolute local directory path")
    identifiers = _selection(document, resource_ids, resolved)
    # Resolve every selected source before starting I/O, so a later forbidden
    # URL or missing relative base does not cause earlier files to be opened.
    paths: dict[str, Path] = {}
    for identifier in identifiers:
        resource = document.resources[identifier]
        if resource.data is None:
            assert resource.source is not None  # The complete model was validated above.
            paths[identifier] = _local_path(resource.source, directory)
    result = deepcopy(document)
    for identifier in identifiers:
        resource = result.resources[identifier]
        if resource.data is None:
            maximum = min(resolved.max_bytes, resolved.max_embedded_bytes - embedded)
            resource.data = _read_local(paths[identifier], maximum)
            embedded += len(resource.data)
        resource.source = None
    _require_document(result, resolved)
    return result


__all__ = [
    "ResourceConflictPolicy",
    "add_resource",
    "embed_resources",
    "find_duplicate_resources",
    "find_resource_uses",
    "remove_resource",
    "replace_resource",
]
