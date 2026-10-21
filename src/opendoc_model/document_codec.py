"""Версионированная JSON-сериализация :class:`DocumentModel`."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from copy import deepcopy
from pathlib import Path
from typing import Any

from opendoc_model._json_validation import _validate_document_payload
from opendoc_model._validation import _validate_model
from opendoc_model.color import ColorLike, ColorValue
from opendoc_model.document_model import (
    Block,
    Box,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    Length,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    PageSettings,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    VisualSurrogate,
)
from opendoc_model.footnotes import FOOTNOTES_PROPERTY, _decode_notes, _encode_notes
from opendoc_model.limits import DocumentLimits, _check_json_text, _quota, _resolve_limits, _utf8_size
from opendoc_model.properties import (
    PROPERTY_SCHEMA_VERSION,
    ImageProperties,
    ParagraphProperties,
    SectionProperties,
    TableCellProperties,
    TableProperties,
    TableRowProperties,
    TextStyleProperties,
    VersionedProperties,
)

FORMAT_NAME = "opendoc.document"
FORMAT_VERSION = 2
SUPPORTED_FORMAT_VERSIONS = frozenset({1, FORMAT_VERSION})


def document_to_dict(document: DocumentModel, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Создать независимый JSON-совместимый снимок без потери ресурсов."""

    budget = _resolve_limits(limits)
    errors = _validate_model(document, budget)
    if errors:
        raise ValueError("invalid document model: " + "; ".join(errors))
    metadata = _properties_to_dict(document.metadata)
    if document.footnotes or document.footnote_properties or document.footnote_extensions:
        metadata[FOOTNOTES_PROPERTY] = _encode_notes(document)
    payload = {
        "format": FORMAT_NAME,
        "version": FORMAT_VERSION,
        "document": {
            "property_schema_version": PROPERTY_SCHEMA_VERSION,
            "mode": document.mode.value,
            "source_format": document.source_format,
            "metadata": metadata,
            "package": _package_to_dict(document.package),
            "styles": {key: _style_to_dict(value) for key, value in document.styles.items()},
            "resources": {key: _resource_to_dict(value) for key, value in document.resources.items()},
            "sections": [_section_to_dict(section) for section in document.sections],
        },
    }
    _validate_payload(payload, budget)
    return deepcopy(payload)


def document_from_dict(payload: dict[str, Any], *, limits: DocumentLimits | None = None) -> DocumentModel:
    """Восстановить независимую модель; проверить формат, версию и ссылки."""

    budget = _resolve_limits(limits)
    _validate_payload(payload, budget)
    raw = deepcopy(payload["document"])
    metadata = dict(raw.get("metadata", {}))
    notes = _decode_notes(metadata.get(FOOTNOTES_PROPERTY), f"$.document.metadata[{FOOTNOTES_PROPERTY!r}]")
    if notes is not None:
        del metadata[FOOTNOTES_PROPERTY]

    document = DocumentModel(
        sections=[_section_from_dict(value) for value in raw.get("sections", [])],
        resources={key: _resource_from_dict(value) for key, value in raw.get("resources", {}).items()},
        styles={key: _style_from_dict(value) for key, value in raw.get("styles", {}).items()},
        metadata=metadata,
        package=_package_from_dict(raw.get("package")),
        mode=ConversionMode(raw.get("mode", ConversionMode.BALANCED.value)),
        source_format=raw.get("source_format"),
        version=FORMAT_VERSION,
        footnotes=notes[0] if notes is not None else [],
        footnote_properties=notes[1] if notes is not None else {},
        footnote_extensions=notes[2] if notes is not None else {},
    )
    # Input quotas have already been checked. Constructor defaults must not
    # charge extra nodes against the accepted serialized representation.
    errors = _validate_model(document, budget, preflight=False)
    if errors:
        raise ValueError("invalid document model: " + "; ".join(errors))
    return document


def document_to_json(document: DocumentModel, *, indent: int | None = None, limits: DocumentLimits | None = None) -> str:
    return "".join(_json_chunks(document, indent, _resolve_limits(limits)))


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"$: duplicate JSON object key {key!r}")
        result[key] = value
    return result


def document_from_json(value: str | bytes, *, limits: DocumentLimits | None = None) -> DocumentModel:
    if not isinstance(value, (str, bytes, bytearray)):
        raise ValueError("$: JSON input must be a string or bytes")
    budget = _resolve_limits(limits)
    _check_json_text(value, budget)
    return document_from_dict(json.loads(value, object_pairs_hook=_unique_json_object), limits=budget)


def _validate_payload(payload: Any, limits: DocumentLimits) -> None:
    _validate_document_payload(
        payload,
        format_name=FORMAT_NAME,
        format_versions=SUPPORTED_FORMAT_VERSIONS,
        property_schema_version=PROPERTY_SCHEMA_VERSION,
        limits=limits,
    )


def _json_chunks(document: DocumentModel, indent: int | None, limits: DocumentLimits) -> Iterator[str]:
    payload = document_to_dict(document, limits=limits)
    encoder = json.JSONEncoder(ensure_ascii=False, indent=indent, allow_nan=False)
    size = 0
    for chunk in encoder.iterencode(payload):
        size += _utf8_size(chunk, limits.max_bytes, "$", used=size)
        if size > limits.max_bytes:
            _quota("$", "bytes", limits.max_bytes)
        yield chunk


def save_document(
    document: DocumentModel, path: str | Path, *, indent: int | None = 2, limits: DocumentLimits | None = None
) -> Path:
    from opendoc_model.storage import _atomic_write_chunks

    budget = _resolve_limits(limits)
    output = Path(path)
    _atomic_write_chunks(output, _json_chunks(document, indent, budget), encoding="utf-8", max_bytes=budget.max_bytes)
    return output


def load_document(path: str | Path, *, limits: DocumentLimits | None = None) -> DocumentModel:
    budget = _resolve_limits(limits)
    with Path(path).open("rb") as source:
        value = source.read(budget.max_bytes + 1)
    if len(value) > budget.max_bytes:
        _quota("$", "bytes", budget.max_bytes)
    return document_from_json(value, limits=budget)


def _length_to_value(value: Length | None) -> float | None:
    return value.pt if value is not None else None


def _length_from_value(value: float | None) -> Length | None:
    return Length(float(value)) if value is not None else None


def _box_to_dict(value: Box | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"x": value.x, "y": value.y, "width": value.width, "height": value.height, "rotation": value.rotation}


def _box_from_dict(value: dict[str, Any] | None) -> Box | None:
    return Box(**value) if value is not None else None


def _crop_to_dict(value: ImageCrop | None) -> dict[str, float] | None:
    if value is None:
        return None
    return {"left": value.left, "top": value.top, "right": value.right, "bottom": value.bottom}


def _crop_from_dict(value: dict[str, Any] | None) -> ImageCrop | None:
    return ImageCrop(**value) if value is not None else None


def _properties_to_dict(value: dict[str, Any] | VersionedProperties) -> dict[str, Any]:
    return value.to_dict() if isinstance(value, VersionedProperties) else dict(value)


def _package_to_dict(value: PackageGraph | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "format": value.format,
        "root": value.root,
        "parts": {
            name: {
                "name": part.name,
                "media_type": part.media_type,
                "data_base64": base64.b64encode(part.data).decode("ascii"),
            }
            for name, part in value.parts.items()
        },
        "relationships": [
            {
                "id": relationship.id,
                "relationship_type": relationship.relationship_type,
                "source": relationship.source,
                "target": relationship.target,
                "external": relationship.external,
            }
            for relationship in value.relationships
        ],
    }


def _package_from_dict(value: dict[str, Any] | None) -> PackageGraph | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("package payload must be an object")
    parts: dict[str, PackagePart] = {}
    for name, raw_part in value.get("parts", {}).items():
        try:
            data = base64.b64decode(raw_part["data_base64"], validate=True)
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"invalid package part {name!r}") from error
        part = PackagePart(
            name=raw_part.get("name", name),
            media_type=raw_part["media_type"],
            data=data,
        )
        parts[name] = part
    return PackageGraph(
        format=str(value.get("format", "")),
        root=str(value.get("root", "/word/document.xml")),
        parts=parts,
        relationships=[
            PackageRelationship(
                id=item["id"],
                relationship_type=item["relationship_type"],
                source=item["source"],
                target=item["target"],
                external=bool(item.get("external", False)),
            )
            for item in value.get("relationships", [])
        ],
    )


def _style_to_dict(value: TextStyle) -> dict[str, Any]:
    return {
        "font_family": value.font_family,
        "font_size_pt": _length_to_value(value.font_size),
        "bold": value.bold,
        "italic": value.italic,
        "underline": value.underline,
        "superscript": value.superscript,
        "subscript": value.subscript,
        "color": _color_to_value(value.color),
        "background": _color_to_value(value.background),
        "language": value.language,
        "properties": _properties_to_dict(value.properties),
    }


def _style_from_dict(value: dict[str, Any]) -> TextStyle:
    return TextStyle(
        font_family=value.get("font_family"),
        font_size=_length_from_value(value.get("font_size_pt")),
        bold=value.get("bold"),
        italic=value.get("italic"),
        underline=value.get("underline"),
        superscript=value.get("superscript"),
        subscript=value.get("subscript"),
        color=_color_from_value(value.get("color")),
        background=_color_from_value(value.get("background")),
        language=value.get("language"),
        properties=TextStyleProperties(dict(value.get("properties", {}))),
    )


def _resource_to_dict(value: Resource) -> dict[str, Any]:
    return {
        "id": value.id,
        "kind": value.kind.value,
        "media_type": value.media_type,
        "data_base64": base64.b64encode(value.data).decode("ascii") if value.data is not None else None,
        "source": value.source,
        "filename": value.filename,
        "properties": _properties_to_dict(value.properties),
        "provenance": _provenance_to_dict(value.provenance),
    }


def _resource_from_dict(value: dict[str, Any]) -> Resource:
    encoded = value.get("data_base64")
    try:
        data = base64.b64decode(encoded, validate=True) if encoded is not None else None
    except (ValueError, TypeError) as error:
        raise ValueError(f"invalid base64 resource {value.get('id')!r}") from error
    return Resource(
        id=value["id"],
        kind=ResourceKind(value["kind"]),
        media_type=value["media_type"],
        data=data,
        source=value.get("source"),
        filename=value.get("filename"),
        properties=dict(value.get("properties", {})),
        provenance=_provenance_from_dict(value.get("provenance")),
    )


def _color_to_value(value: ColorLike | None) -> str | dict[str, object] | None:
    return value.to_dict() if isinstance(value, ColorValue) else value


def _color_from_value(value: Any) -> ColorLike | None:
    if isinstance(value, dict) and "space" in value and "components" in value:
        return ColorValue.from_dict(value)
    return value if isinstance(value, str) else None


def _provenance_to_dict(value: Provenance | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "source_format": value.source_format,
        "source_path": value.source_path,
        "page": value.page,
        "object_id": value.object_id,
        "package_part": value.package_part,
        "events": [
            {"operation": event.operation, "detail": event.detail, "fallback_reason": event.fallback_reason}
            for event in value.events
        ],
    }


def _provenance_from_dict(value: dict[str, Any] | None) -> Provenance | None:
    if not value:
        return None
    return Provenance(
        source_format=value["source_format"],
        source_path=value.get("source_path"),
        page=value.get("page"),
        object_id=value.get("object_id"),
        package_part=value.get("package_part"),
        events=[
            ProvenanceEvent(
                operation=event["operation"],
                detail=event.get("detail", ""),
                fallback_reason=event.get("fallback_reason"),
            )
            for event in value.get("events", [])
        ],
    )


def _surrogate_to_dict(value: VisualSurrogate | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "resource_id": value.resource_id,
        "reason": value.reason,
        "media_type": value.media_type,
        "fidelity": value.fidelity,
    }


def _surrogate_from_dict(value: dict[str, Any] | None) -> VisualSurrogate | None:
    if not value:
        return None
    return VisualSurrogate(
        resource_id=value["resource_id"],
        reason=value["reason"],
        media_type=value.get("media_type"),
        fidelity=value.get("fidelity"),
    )


def _inline_to_dict(value: TextRun | Formula | Image) -> dict[str, Any]:
    if isinstance(value, TextRun):
        return {
            "type": "text",
            "text": value.text,
            "style": _style_to_dict(value.style),
            "link": value.link,
            "properties": _properties_to_dict(value.properties),
            "provenance": _provenance_to_dict(value.provenance),
            "visual_surrogate": _surrogate_to_dict(value.visual_surrogate),
        }
    return _block_to_dict(value)


def _inline_from_dict(value: dict[str, Any]) -> TextRun | Formula | Image:
    if value.get("type") == "text":
        return TextRun(
            text=value.get("text", ""),
            style=_style_from_dict(value.get("style", {})),
            link=value.get("link"),
            properties=dict(value.get("properties", {})),
            provenance=_provenance_from_dict(value.get("provenance")),
            visual_surrogate=_surrogate_from_dict(value.get("visual_surrogate")),
        )
    block = _block_from_dict(value)
    if not isinstance(block, (Formula, Image)):
        raise ValueError(f"invalid inline element: {value.get('type')!r}")
    return block


def _block_to_dict(value: Block) -> dict[str, Any]:
    if isinstance(value, Paragraph):
        return {
            "type": "paragraph",
            "content": [_inline_to_dict(item) for item in value.content],
            "style_id": value.style_id,
            "alignment": value.alignment,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
            "provenance": _provenance_to_dict(value.provenance),
            "visual_surrogate": _surrogate_to_dict(value.visual_surrogate),
        }
    if isinstance(value, Table):
        return {
            "type": "table",
            "rows": [
                {
                    "cells": [
                        {
                            "blocks": [_block_to_dict(block) for block in cell.blocks],
                            "row_span": cell.row_span,
                            "column_span": cell.column_span,
                            "properties": _properties_to_dict(cell.properties),
                        }
                        for cell in row.cells
                    ],
                    "properties": _properties_to_dict(row.properties),
                }
                for row in value.rows
            ],
            "style_id": value.style_id,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
            "provenance": _provenance_to_dict(value.provenance),
            "visual_surrogate": _surrogate_to_dict(value.visual_surrogate),
        }
    if isinstance(value, Formula):
        return {
            "type": "formula",
            "value": value.value,
            "format": value.format.value,
            "display": value.display,
            "fallback_text": value.fallback_text,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
            "provenance": _provenance_to_dict(value.provenance),
            "visual_surrogate": _surrogate_to_dict(value.visual_surrogate),
        }
    if isinstance(value, Image):
        return {
            "type": "image",
            "resource_id": value.resource_id,
            "alt_text": value.alt_text,
            "box": _box_to_dict(value.box),
            "properties": _properties_to_dict(value.properties),
            "crop": _crop_to_dict(value.crop),
            "provenance": _provenance_to_dict(value.provenance),
            "visual_surrogate": _surrogate_to_dict(value.visual_surrogate),
        }
    raise TypeError(f"unsupported block: {type(value).__name__}")


def _block_from_dict(value: dict[str, Any]) -> Block:
    element_type = value.get("type")
    if element_type == "paragraph":
        return Paragraph(
            content=[_inline_from_dict(item) for item in value.get("content", [])],
            style_id=value.get("style_id"),
            alignment=value.get("alignment"),
            box=_box_from_dict(value.get("box")),
            properties=ParagraphProperties(dict(value.get("properties", {}))),
            provenance=_provenance_from_dict(value.get("provenance")),
            visual_surrogate=_surrogate_from_dict(value.get("visual_surrogate")),
        )
    if element_type == "table":
        rows = []
        for raw_row in value.get("rows", []):
            cells = [
                TableCell(
                    blocks=[_block_from_dict(block) for block in raw_cell.get("blocks", [])],
                    row_span=raw_cell.get("row_span", 1),
                    column_span=raw_cell.get("column_span", 1),
                    properties=TableCellProperties(dict(raw_cell.get("properties", {}))),
                )
                for raw_cell in raw_row.get("cells", [])
            ]
            rows.append(TableRow(cells=cells, properties=TableRowProperties(dict(raw_row.get("properties", {})))))
        return Table(
            rows=rows,
            style_id=value.get("style_id"),
            box=_box_from_dict(value.get("box")),
            properties=TableProperties(dict(value.get("properties", {}))),
            provenance=_provenance_from_dict(value.get("provenance")),
            visual_surrogate=_surrogate_from_dict(value.get("visual_surrogate")),
        )
    if element_type == "formula":
        return Formula(
            value=value.get("value", ""),
            format=FormulaFormat(value["format"]),
            display=value.get("display", False),
            fallback_text=value.get("fallback_text", ""),
            box=_box_from_dict(value.get("box")),
            properties=dict(value.get("properties", {})),
            provenance=_provenance_from_dict(value.get("provenance")),
            visual_surrogate=_surrogate_from_dict(value.get("visual_surrogate")),
        )
    if element_type == "image":
        return Image(
            resource_id=value["resource_id"],
            alt_text=value.get("alt_text", ""),
            box=_box_from_dict(value.get("box")),
            properties=ImageProperties(dict(value.get("properties", {}))),
            crop=_crop_from_dict(value.get("crop")),
            provenance=_provenance_from_dict(value.get("provenance")),
            visual_surrogate=_surrogate_from_dict(value.get("visual_surrogate")),
        )
    raise ValueError(f"unsupported element type: {element_type!r}")


def _page_to_dict(value: PageSettings) -> dict[str, float]:
    return {
        "width_pt": value.width.pt,
        "height_pt": value.height.pt,
        "margin_top_pt": value.margin_top.pt,
        "margin_right_pt": value.margin_right.pt,
        "margin_bottom_pt": value.margin_bottom.pt,
        "margin_left_pt": value.margin_left.pt,
    }


def _page_from_dict(value: dict[str, Any]) -> PageSettings:
    defaults = PageSettings()
    return PageSettings(
        width=Length(value.get("width_pt", defaults.width.pt)),
        height=Length(value.get("height_pt", defaults.height.pt)),
        margin_top=Length(value.get("margin_top_pt", defaults.margin_top.pt)),
        margin_right=Length(value.get("margin_right_pt", defaults.margin_right.pt)),
        margin_bottom=Length(value.get("margin_bottom_pt", defaults.margin_bottom.pt)),
        margin_left=Length(value.get("margin_left_pt", defaults.margin_left.pt)),
    )


def _section_to_dict(value: Section) -> dict[str, Any]:
    return {
        "blocks": [_block_to_dict(block) for block in value.blocks],
        "page": _page_to_dict(value.page),
        "headers": [_block_to_dict(block) for block in value.headers],
        "footers": [_block_to_dict(block) for block in value.footers],
        "first_page_headers": [_block_to_dict(block) for block in value.first_page_headers],
        "first_page_footers": [_block_to_dict(block) for block in value.first_page_footers],
        "even_page_headers": [_block_to_dict(block) for block in value.even_page_headers],
        "even_page_footers": [_block_to_dict(block) for block in value.even_page_footers],
        "properties": _properties_to_dict(value.properties),
        "provenance": _provenance_to_dict(value.provenance),
    }


def _section_from_dict(value: dict[str, Any]) -> Section:
    return Section(
        blocks=[_block_from_dict(block) for block in value.get("blocks", [])],
        page=_page_from_dict(value.get("page", {})),
        headers=[_block_from_dict(block) for block in value.get("headers", [])],
        footers=[_block_from_dict(block) for block in value.get("footers", [])],
        first_page_headers=[_block_from_dict(block) for block in value.get("first_page_headers", [])],
        first_page_footers=[_block_from_dict(block) for block in value.get("first_page_footers", [])],
        even_page_headers=[_block_from_dict(block) for block in value.get("even_page_headers", [])],
        even_page_footers=[_block_from_dict(block) for block in value.get("even_page_footers", [])],
        properties=SectionProperties(dict(value.get("properties", {}))),
        provenance=_provenance_from_dict(value.get("provenance")),
    )


__all__ = [
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "document_from_dict",
    "document_from_json",
    "document_to_dict",
    "document_to_json",
    "load_document",
    "save_document",
]
