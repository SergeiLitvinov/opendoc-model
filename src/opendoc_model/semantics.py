"""Explicit format-neutral paragraph semantics stored in preserved properties."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import Paragraph
from opendoc_model.limits import DocumentLimits, _resolve_limits
from opendoc_model.traversal import ModelNode, NodeLocation, iter_elements

HEADING_PROPERTY = "opendoc.heading"


@dataclass(frozen=True)
class Heading:
    """A semantic heading level (1–9), independent of visual text styling."""

    level: int

    def __post_init__(self) -> None:
        if type(self.level) is not int or not 1 <= self.level <= 9:
            raise ValueError("heading level must be an integer between 1 and 9")


def _heading_payload(value: Any, path: str) -> Heading | None:
    # Unmarked values remain opaque extensions, including older documents
    # that used this property key before semantic support was introduced.
    if not isinstance(value, dict) or value.get("format") != "opendoc.heading":
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        raise _DiagnosticError(f"{path}.version", "unsupported heading version", "semantic.version")
    level = value.get("level")
    if type(level) is not int or not 1 <= level <= 9:
        raise _DiagnosticError(f"{path}.level", "heading level must be an integer between 1 and 9", "semantic.heading.level")
    return Heading(level)


def get_heading(paragraph: Paragraph, *, limits: DocumentLimits | None = None) -> Heading | None:
    """Read only explicitly tagged heading data; never infer from styles/text."""
    from opendoc_model._json_validation import _json_tree

    if not isinstance(paragraph, Paragraph) or not isinstance(paragraph.properties, Mapping):
        raise ValueError("paragraph must be Paragraph with property mapping")
    resolved = _resolve_limits(limits)
    if HEADING_PROPERTY not in paragraph.properties:
        return None
    value = paragraph.properties[HEADING_PROPERTY]
    _json_tree(value, f"properties[{HEADING_PROPERTY!r}]", resolved)
    return _heading_payload(value, f"properties[{HEADING_PROPERTY!r}]")


def set_heading(paragraph: Paragraph, heading: Heading | None, *, limits: DocumentLimits | None = None) -> None:
    """Assign/remove a heading in place, preserving unknown tagged fields.

    Failure leaves properties intact; an opaque value occupying the key is
    never overwritten. Removal drops only the explicitly tagged heading bag.
    """
    from opendoc_model._json_validation import _json_tree

    if not isinstance(paragraph, Paragraph) or not isinstance(paragraph.properties, MutableMapping):
        raise ValueError("paragraph must be Paragraph with property mapping")
    if heading is not None and not isinstance(heading, Heading):
        raise ValueError("heading must be Heading or None")
    resolved = _resolve_limits(limits)
    existing = get_heading(paragraph, limits=resolved)
    if HEADING_PROPERTY in paragraph.properties and existing is None:
        raise ValueError("heading property is occupied by an opaque extension")
    if heading is None:
        if existing is not None:
            del paragraph.properties[HEADING_PROPERTY]
        return
    value = deepcopy(paragraph.properties[HEADING_PROPERTY]) if existing is not None else {}
    value.update(format="opendoc.heading", version=1, level=heading.level)
    _json_tree(value, f"properties[{HEADING_PROPERTY!r}]", resolved)
    _heading_payload(value, f"properties[{HEADING_PROPERTY!r}]")
    paragraph.properties[HEADING_PROPERTY] = value


def iter_headings(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Paragraph]]:
    """Yield explicitly marked headings in common traversal order, including tables/headers."""
    for location in iter_elements(root, Paragraph, limits=limits):
        if get_heading(location.node, limits=limits) is not None:
            yield location


__all__ = ["HEADING_PROPERTY", "Heading", "get_heading", "iter_headings", "set_heading"]
