"""Independent effective text styles with explicit inheritance semantics."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import fields

from opendoc_model.document_model import DocumentModel, Paragraph, Section, TextRun, TextStyle
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits


def _require_document(document: DocumentModel, limits: DocumentLimits) -> None:
    if not isinstance(document, DocumentModel):
        raise ValueError("document must be DocumentModel")
    errors = document.validate(limits=limits)
    if errors:
        raise ValueError("invalid document: " + "; ".join(errors))


def _overlay(target: TextStyle, source: TextStyle) -> None:
    for item in fields(TextStyle):
        if item.name == "properties":
            for key, value in source.properties.items():
                if key != "base_style_id" and value is not None:
                    target.properties[key] = value
        elif (value := getattr(source, item.name)) is not None:
            setattr(target, item.name, value)


def _resolved(document: DocumentModel, style: str | TextStyle | None, limits: DocumentLimits) -> TextStyle:
    chain: list[TextStyle] = []
    visited: set[str] = set()
    if isinstance(style, TextStyle):
        # Validate an independent override through the same model rules used
        # by persistence, including inline base references and JSON properties.
        context = DocumentModel(
            styles=document.styles, resources=document.resources, sections=[Section(blocks=[Paragraph([TextRun("", style)])])]
        )
        _require_document(context, limits)
        chain.append(style)
        current = style.properties.get("base_style_id")
    elif style is None or isinstance(style, str):
        current = style
    else:
        raise ValueError("style must be a style ID, TextStyle or None")
    while current is not None:
        if not isinstance(current, str) or not current:
            raise ValueError("base_style_id must be a nonempty string or None")
        if current in visited:
            raise ValueError(f"cyclic style inheritance: {current!r}")
        visited.add(current)
        if current not in document.styles:
            raise ValueError(f"unknown style {current!r}")
        inherited = document.styles[current]
        chain.append(inherited)
        current = inherited.properties.get("base_style_id")
    result = TextStyle()
    for item in reversed(chain):
        _overlay(result, item)
    _guard_model(result, limits)
    return result


def resolve_style(
    document: DocumentModel,
    style: str | TextStyle | None = None,
    *,
    overrides: TextStyle | None = None,
    limits: DocumentLimits | None = None,
) -> TextStyle:
    """Flatten a named/inline style, then overlay an optional inline chain.

    None inherits; false, zero and empty values override. Properties merge by
    key, including extensions; nested values replace whole values. The base
    pointer is consumed. No renderer defaults are guessed. Inputs are intact
    and the returned style owns its mutable values.
    """
    resolved_limits = _resolve_limits(limits)
    _require_document(document, resolved_limits)
    result = _resolved(document, style, resolved_limits)
    if overrides is not None:
        if not isinstance(overrides, TextStyle):
            raise ValueError("overrides must be TextStyle or None")
        _overlay(result, _resolved(document, overrides, resolved_limits))
    _guard_model(result, resolved_limits)
    return deepcopy(result)


def effective_text_style(
    document: DocumentModel,
    paragraph: Paragraph,
    run: TextRun | None = None,
    *,
    limits: DocumentLimits | None = None,
) -> TextStyle:
    """Resolve paragraph style/properties and then a contained run's style.

    A paragraph may be detached; references resolve against document styles
    and resources. A supplied run must occur in paragraph.content by identity.
    Paragraph alignment/geometry remain paragraph fields, not text styles.
    """
    resolved_limits = _resolve_limits(limits)
    _require_document(document, resolved_limits)
    if not isinstance(paragraph, Paragraph):
        raise ValueError("paragraph must be Paragraph")
    context = DocumentModel(sections=[Section(blocks=[paragraph])], styles=document.styles, resources=document.resources)
    _require_document(context, resolved_limits)
    if run is not None and (not isinstance(run, TextRun) or not any(item is run for item in paragraph.content)):
        raise ValueError("run must be a TextRun contained in paragraph.content")
    result = _resolved(document, paragraph.style_id, resolved_limits)
    for key, value in paragraph.properties.items():
        if value is not None and key != "base_style_id":
            result.properties[key] = value
    if run is not None:
        _overlay(result, _resolved(document, run.style, resolved_limits))
    _guard_model(result, resolved_limits)
    return deepcopy(result)


__all__ = ["effective_text_style", "resolve_style"]
