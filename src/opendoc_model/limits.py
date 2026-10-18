"""Per-operation document budgets, independent of application storage."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass

from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, PackagePart, Resource
from opendoc_model.storage import ArtifactLimitError


@dataclass(frozen=True)
class DocumentLimits:
    """UTF-8/byte input, container depth, value count and embedded-byte budgets.

    Depth is capped at 128 to keep the recursive codec below Python's normal
    recursion limit. Budgets apply separately to input and output trees.
    """

    max_bytes: int = 100 * 1024 * 1024
    max_depth: int = 64
    max_nodes: int = 100_000
    max_embedded_bytes: int = 75 * 1024 * 1024

    def __post_init__(self) -> None:
        for item in fields(self):
            value = getattr(self, item.name)
            if type(value) is not int or value < 0:
                raise ValueError(f"{item.name} must be a non-negative integer")
        if not 1 <= self.max_depth <= 128:
            raise ValueError("max_depth must be between 1 and 128")
        if self.max_nodes < 1:
            raise ValueError("max_nodes must be positive")


def _resolve_limits(limits: DocumentLimits | None) -> DocumentLimits:
    if limits is None:
        return DocumentLimits()
    if not isinstance(limits, DocumentLimits):
        raise ValueError("limits must be DocumentLimits or None")
    return limits


def _quota(path: str, name: str, maximum: int) -> None:
    raise ArtifactLimitError(f"{path}: {name} quota exceeded ({maximum})", path=path, quota=name, maximum=maximum)


def _utf8_size(value: str, maximum: int, path: str, *, used: int = 0) -> int:
    if len(value) > maximum - used:
        _quota(path, "bytes", maximum)
    size = 0
    for index in range(0, len(value), 8192):
        try:
            size += len(value[index : index + 8192].encode("utf-8"))
        except UnicodeEncodeError as error:
            raise _DiagnosticError(path, "string cannot be encoded as UTF-8", "json.utf8") from error
        if size + used > maximum:
            _quota(path, "bytes", maximum)
    return size


def _check_json_text(value: str | bytes | bytearray, limits: DocumentLimits) -> None:
    if isinstance(value, str):
        _utf8_size(value, limits.max_bytes, "$")
        tokens = (ord(character) for character in value)
    else:
        if len(value) > limits.max_bytes:
            _quota("$", "bytes", limits.max_bytes)
        # JSON bytes can be UTF-16/32. Normalize after a bounded input read so
        # depth scanning uses characters, not the bytes of another encoding.
        import json

        text = value.decode(json.detect_encoding(value))
        tokens = (ord(character) for character in text)
    depth, quoted, escaped = 0, False, False
    for token in tokens:
        if quoted:
            if escaped:
                escaped = False
            elif token == 92:
                escaped = True
            elif token == 34:
                quoted = False
        elif token == 34:
            quoted = True
        elif token in (91, 123):
            depth += 1
            if depth > limits.max_depth:
                _quota("$", "depth", limits.max_depth)
        elif token in (93, 125):
            depth -= 1


def _guard_model(value: object, limits: DocumentLimits) -> tuple[int, int]:
    """Bound traversal before recursive encoding or allocating base64 strings."""
    pending = [(value, "$", False)]
    active: set[int] = set()
    nodes, embedded = 0, 0
    while pending:
        item, path, leaving = pending.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > limits.max_nodes:
            _quota(path, "nodes", limits.max_nodes)
        if isinstance(item, (Resource, PackagePart)) and item.data is not None:
            if not isinstance(item.data, bytes):
                raise _DiagnosticError(f"{path}.data", "expected bytes", "model.type")
            embedded += len(item.data)
            if embedded > limits.max_embedded_bytes:
                _quota(f"{path}.data", "embedded bytes", limits.max_embedded_bytes)
        children = None
        if is_dataclass(item) and not isinstance(item, type):
            children = [
                (getattr(item, field.name), f"{path}.{field.name}")
                for field in fields(item)
                if not (field.metadata.get("omit_default") and getattr(item, field.name) == field.default)
            ]
            if isinstance(item, DocumentModel):
                # Absent extensions must not change accepted budgets for old
                # documents. Populated/malformed fields still consume quotas.
                children = [
                    (child, location)
                    for child, location in children
                    if not (
                        location == f"{path}.footnotes"
                        and type(child) is list
                        and not child
                        or location == f"{path}.footnote_properties"
                        and type(child) is dict
                        and not child
                        or location == f"{path}.footnote_extensions"
                        and type(child) is dict
                        and not child
                    )
                ]
        elif isinstance(item, Mapping):
            if len(item) > limits.max_nodes - nodes:
                _quota(path, "nodes", limits.max_nodes)
            if any(not isinstance(key, str) for key in item):
                raise _DiagnosticError(path, "mapping keys must be strings", "model.mapping-key")
            children = [(child, f"{path}[{key!r}]") for key, child in item.items()]
        elif isinstance(item, (list, tuple)):
            if len(item) > limits.max_nodes - nodes:
                _quota(path, "nodes", limits.max_nodes)
            children = [(child, f"{path}[{index}]") for index, child in enumerate(item)]
        if children is None:
            continue
        if id(item) in active:
            raise _DiagnosticError(path, "cyclic document model", "model.cycle")
        active.add(id(item))
        if len(active) > limits.max_depth:
            _quota(path, "depth", limits.max_depth)
        pending.append((item, path, True))
        pending.extend((child, location, False) for child, location in reversed(children))
    return nodes, embedded


__all__ = ["DocumentLimits"]
