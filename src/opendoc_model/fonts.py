"""Explicit opaque font-program bindings, independent of family names and parsers."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from dataclasses import dataclass, replace
from typing import NoReturn, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, ResourceKind, TextRun, TextStyle
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.traversal import ModelNode, _walk_locations

FONT_REFERENCE_PROPERTY = "opendoc.font-reference"


def _error(path: str, message: str, code: str = "font.reference.invalid") -> NoReturn:
    raise _DiagnosticError(path, message, code)


@dataclass(frozen=True)
class FontReference(IntegrationRecord):
    """A document-local FONT resource and optional collection face, without parsing bytes.

    None is an unknown face index, distinct from explicit zero. No family-name
    matching, default face, embedding permission or system-font lookup is implied.
    """

    resource_id: str
    face_index: int | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.resource_id, str)
            or not self.resource_id
            or any(0xD800 <= ord(char) <= 0xDFFF for char in self.resource_id)
        ):
            _error("resource_id", "expected nonempty UTF-8 resource identifier")
        if self.face_index is not None and (type(self.face_index) is not int or self.face_index < 0):
            _error("face_index", "expected nonnegative integer or unknown")


def get_font_reference(style: TextStyle, *, limits: DocumentLimits | None = None) -> FontReference | None:
    """Read an independent tagged binding; absent or opaque values return None."""
    if not isinstance(style, TextStyle) or not isinstance(style.properties, Mapping):
        _error("style", "expected TextStyle")
    budget = _resolve_limits(limits)
    raw = style.properties.get(FONT_REFERENCE_PROPERTY)
    _json_tree(raw, FONT_REFERENCE_PROPERTY, budget)
    if not isinstance(raw, dict) or raw.get("format") != FONT_REFERENCE_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error("version", "unsupported font reference version")
    FontReference(cast(str, raw.get("resource_id")), raw.get("face_index"))
    return cast(
        FontReference,
        _convert(
            {key: value for key, value in raw.items() if key not in {"format", "version"}},
            FontReference,
            FONT_REFERENCE_PROPERTY,
            encode=False,
        ),
    )


def set_font_reference(style: TextStyle, reference: FontReference | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically set/remove a direct binding; document validation resolves its ID/kind.

    Removing a binding permits normal model inheritance, without selecting by name.
    Unknown envelope fields survive replacement; occupied opaque data is untouched.
    """
    budget = _resolve_limits(limits)
    previous = get_font_reference(style, limits=budget)
    if not isinstance(style.properties, MutableMapping):
        _error("properties", "expected mutable property mapping")
    if FONT_REFERENCE_PROPERTY in style.properties and previous is None:
        _error(FONT_REFERENCE_PROPERTY, "property occupied by opaque data")
    if reference is None:
        style.properties.pop(FONT_REFERENCE_PROPERTY, None)
        return
    if type(reference) is not FontReference or type(reference.extra) is not dict:
        _error(FONT_REFERENCE_PROPERTY, "expected FontReference with dictionary extra")
    if previous is not None:
        reference = replace(reference, extra={**previous.extra, **reference.extra})
    _guard_model(reference, budget)
    raw = _convert(reference, FontReference, FONT_REFERENCE_PROPERTY, encode=True)
    _convert(raw, FontReference, FONT_REFERENCE_PROPERTY, encode=False)
    if {"format", "version"}.intersection(raw):
        _error("extra", "cannot shadow format/version")
    raw.update(format=FONT_REFERENCE_PROPERTY, version=1)
    _json_tree(raw, FONT_REFERENCE_PROPERTY, budget)
    style.properties[FONT_REFERENCE_PROPERTY] = raw


@dataclass(frozen=True)
class FontReferenceLocation:
    """A live style owner, detached binding and current path, including named styles.

    Paths describe this traversal and must be refreshed after structural edits.
    """

    style: TextStyle
    reference: FontReference
    path: str

    def _set(self, identifier: str, limits: DocumentLimits) -> None:
        set_font_reference(self.style, replace(self.reference, resource_id=identifier), limits=limits)


def _font_links(root: ModelNode, limits: DocumentLimits) -> Iterator[FontReferenceLocation]:
    def link(style: TextStyle, path: str) -> Iterator[FontReferenceLocation]:
        try:
            reference = get_font_reference(style, limits=limits)
        except _DiagnosticError as error:
            suffix = error.location.removeprefix(FONT_REFERENCE_PROPERTY).lstrip(".")
            _error(path + ("." + suffix if suffix else ""), error.message)
        if reference is not None:
            yield FontReferenceLocation(style, reference, path)

    if isinstance(root, DocumentModel):
        for identifier, style in root.styles.items():
            yield from link(style, f"styles[{identifier!r}].properties[{FONT_REFERENCE_PROPERTY!r}]")
    for location in _walk_locations(root, limits):
        node = location.node
        if isinstance(node, TextRun):
            yield from link(node.style, f"{location.path}.style.properties[{FONT_REFERENCE_PROPERTY!r}]")


def iter_font_references(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[FontReferenceLocation]:
    """Yield direct font bindings in named styles and structural run styles.

    Inherited uses are resolved through model styles, without inventing direct
    bindings or choosing resources by family name. This performs no font I/O.
    """
    budget = _resolve_limits(limits)
    _guard_model(root, budget)
    yield from _font_links(root, budget)


def _validate_fonts(document: DocumentModel, limits: DocumentLimits) -> None:
    for link in _font_links(document, limits):
        resource = document.resources.get(link.reference.resource_id)
        path = link.path + ".resource_id"
        if resource is None:
            _error(path, "unknown font resource", "font.reference.missing")
        if resource.kind != ResourceKind.FONT:
            _error(path, "expected FONT resource", "font.reference.kind")
    for location in _walk_locations(document, limits):
        node = location.node
        for name, bag in (("properties", getattr(node, "properties", {})), ("metadata", getattr(node, "metadata", {}))):
            raw = bag.get(FONT_REFERENCE_PROPERTY)
            if isinstance(raw, dict) and raw.get("format") == FONT_REFERENCE_PROPERTY:
                _error(f"{location.path}.{name}[{FONT_REFERENCE_PROPERTY!r}]", "binding owner must be TextStyle")


__all__ = [
    "FONT_REFERENCE_PROPERTY",
    "FontReference",
    "FontReferenceLocation",
    "get_font_reference",
    "set_font_reference",
    "iter_font_references",
]
