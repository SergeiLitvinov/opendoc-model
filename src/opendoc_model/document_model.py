"""Богатая промежуточная модель для конвертации и генерации документов.

Модель не привязана к DOCX, PDF или PPTX. Импортёры должны сохранять в ней
семантику и геометрию исходного документа, а экспортёры — явно сообщать о
неподдержанных элементах вместо неявной потери данных.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, TypeAlias

from opendoc_model.color import ColorLike
from opendoc_model.properties import (
    ImageProperties,
    ParagraphProperties,
    SectionProperties,
    TableCellProperties,
    TableProperties,
    TableRowProperties,
    TextStyleProperties,
)

if TYPE_CHECKING:
    from opendoc_model.limits import DocumentLimits


class ConversionMode(str, Enum):
    EDITABLE = "editable"
    FAITHFUL = "faithful"
    BALANCED = "balanced"


class ResourceKind(str, Enum):
    RASTER_IMAGE = "raster_image"
    VECTOR_IMAGE = "vector_image"
    FONT = "font"
    ATTACHMENT = "attachment"


VECTOR_IMAGE_MEDIA_TYPES = frozenset({"image/svg+xml", "image/x-emf", "image/x-wmf", "image/emf", "image/wmf"})


class FormulaFormat(str, Enum):
    LATEX = "latex"
    MATHML = "mathml"
    OMML = "omml"


@dataclass
class ProvenanceEvent:
    """One traceable transformation applied to a model element or resource."""

    operation: str
    detail: str = ""
    fallback_reason: str | None = None


@dataclass
class Provenance:
    """Stable origin pointer plus an append-only transformation history."""

    source_format: str
    source_path: str | None = None
    page: int | None = None
    object_id: str | None = None
    package_part: str | None = None
    events: list[ProvenanceEvent] = field(default_factory=list)

    def transformed(self, operation: str, *, detail: str = "", fallback_reason: str | None = None) -> Provenance:
        return Provenance(
            source_format=self.source_format,
            source_path=self.source_path,
            page=self.page,
            object_id=self.object_id,
            package_part=self.package_part,
            events=[*self.events, ProvenanceEvent(operation, detail, fallback_reason)],
        )


@dataclass
class VisualSurrogate:
    """Visual companion retained beside a native editable representation."""

    resource_id: str
    reason: str
    media_type: str | None = None
    fidelity: float | None = None

    def __post_init__(self) -> None:
        if not self.resource_id:
            raise ValueError("visual surrogate resource id must not be empty")
        if not self.reason:
            raise ValueError("visual surrogate reason must not be empty")
        if self.fidelity is not None and not 0.0 <= self.fidelity <= 1.0:
            raise ValueError("visual surrogate fidelity must be between 0 and 1")


@dataclass
class Length:
    """Физическая длина в пунктах (1/72 дюйма)."""

    pt: float


@dataclass
class Box:
    """Неповёрнутая рамка элемента в исходных координатах страницы, в пунктах.

    x/y задают верхний левый угол рамки, width/height — её размеры до поворота.
    Положительный rotation поворачивает рамку по часовой стрелке вокруг её центра.
    Рамка не заменяется автоматически осевым bounding box повёрнутой фигуры.
    """

    x: float
    y: float
    width: float
    height: float
    rotation: float = 0.0


@dataclass
class ImageCrop:
    """Обрезка изображения как доля от исходного размера для каждой стороны."""

    left: float = 0.0
    top: float = 0.0
    right: float = 0.0
    bottom: float = 0.0


@dataclass
class TextStyle:
    """Declared text attributes; color/background='auto' is explicit, None inherits.

    Automatic tokens remain unresolved; the model never guesses their RGB value.
    """

    font_family: str | None = None
    font_size: Length | None = None
    bold: bool | None = None
    italic: bool | None = None
    underline: bool | None = None
    superscript: bool | None = None
    subscript: bool | None = None
    color: ColorLike | None = None
    background: ColorLike | None = None
    language: str | None = None
    properties: TextStyleProperties = field(default_factory=TextStyleProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TextStyleProperties):
            self.properties = TextStyleProperties(self.properties)


@dataclass
class Resource:
    id: str
    kind: ResourceKind
    media_type: str
    data: bytes | None = None
    source: str | None = None
    filename: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("resource id must not be empty")
        if self.data is None and self.source is None:
            raise ValueError("resource requires either data or source")


@dataclass
class PackagePart:
    """Opaque package part preserved for a format-aware round-trip."""

    name: str
    media_type: str
    data: bytes

    def __post_init__(self) -> None:
        if not self.name.startswith("/"):
            raise ValueError("package part name must be absolute")


@dataclass
class PackageRelationship:
    """Directed relationship between package parts or to an external target."""

    id: str
    relationship_type: str
    source: str
    target: str
    external: bool = False


@dataclass
class PackageGraph:
    """Format-specific package topology kept outside semantic resources."""

    format: str
    root: str = "/word/document.xml"
    parts: dict[str, PackagePart] = field(default_factory=dict)
    relationships: list[PackageRelationship] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        format: str,
        *,
        root: str = "/",
        parts: Iterable[PackagePart] = (),
        relationships: Iterable[PackageRelationship] = (),
        limits: DocumentLimits | None = None,
    ) -> PackageGraph:
        """Create an independent format-neutral graph; legacy constructor defaults remain unchanged.

        The logical root need not be a physical part. Inputs share node/embedded
        budgets, duplicate definitions fail, external targets are never opened.
        """
        from copy import deepcopy
        from dataclasses import replace

        from opendoc_model._validation import _validate_package
        from opendoc_model.limits import _guard_model, _resolve_limits

        if not isinstance(format, str) or not format:
            raise ValueError("format must be a nonempty string")
        budget = _resolve_limits(limits)
        graph = cls(format, root=root)
        errors = _validate_package(graph, budget)
        if errors:
            raise ValueError("; ".join(errors))
        nodes, embedded = _guard_model(graph, budget)
        for label, values, expected in (("parts", parts, PackagePart), ("relationships", relationships, PackageRelationship)):
            try:
                iterator = iter(values)
            except TypeError as error:
                raise ValueError(f"{label}: expected an iterable") from error
            for index, value in enumerate(iterator):
                if not isinstance(value, expected):
                    raise ValueError(f"{label}[{index}]: expected {expected.__name__}")
                remaining = replace(
                    budget, max_nodes=max(1, budget.max_nodes - nodes), max_embedded_bytes=budget.max_embedded_bytes - embedded
                )
                if nodes == budget.max_nodes:
                    from opendoc_model.limits import _quota

                    _quota(label, "nodes", budget.max_nodes)
                count, byte_count = _guard_model(value, remaining)
                nodes += count
                embedded += byte_count
                copied = deepcopy(value)
                if isinstance(copied, PackagePart):
                    if copied.name in graph.parts:
                        raise ValueError(f"parts[{index}]: duplicate part {copied.name!r}")
                    graph.add_part(copied)
                else:
                    graph.add_relationship(copied)
        errors = _validate_package(graph, budget)
        if errors:
            raise ValueError("; ".join(errors))
        return graph

    def add_part(self, part: PackagePart) -> None:
        if part.name in self.parts and self.parts[part.name] != part:
            raise ValueError(f"duplicate package part: {part.name}")
        self.parts[part.name] = part

    def add_relationship(self, relationship: PackageRelationship) -> None:
        key = (relationship.source, relationship.id)
        if any((item.source, item.id) == key for item in self.relationships):
            raise ValueError(f"duplicate package relationship: {relationship.source}:{relationship.id}")
        self.relationships.append(relationship)

    def related_part(self, source: str, relationship_type: str) -> PackagePart | None:
        relationship = next(
            (
                item
                for item in self.relationships
                if item.source == source and item.relationship_type == relationship_type and not item.external
            ),
            None,
        )
        return self.parts.get(relationship.target) if relationship is not None else None

    def validate(self, *, limits: DocumentLimits | None = None) -> list[str]:
        """Return package topology errors; quota exhaustion remains explicit."""
        from opendoc_model._validation import _validate_package

        return _validate_package(self, limits)


@dataclass
class TextRun:
    text: str
    style: TextStyle = field(default_factory=TextStyle)
    link: str | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None


@dataclass
class Formula:
    value: str
    format: FormulaFormat
    display: bool = False
    fallback_text: str = ""
    box: Box | None = None
    properties: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None


@dataclass
class Image:
    resource_id: str
    alt_text: str = ""
    box: Box | None = None
    properties: ImageProperties = field(default_factory=ImageProperties)
    crop: ImageCrop | None = None
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, ImageProperties):
            self.properties = ImageProperties(self.properties)


Inline: TypeAlias = TextRun | Formula | Image


@dataclass
class Paragraph:
    content: list[Inline] = field(default_factory=list)
    style_id: str | None = None
    alignment: str | None = None
    box: Box | None = None
    properties: ParagraphProperties = field(default_factory=ParagraphProperties)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, ParagraphProperties):
            self.properties = ParagraphProperties(self.properties)

    @property
    def plain_text(self) -> str:
        parts: list[str] = []
        for item in self.content:
            if isinstance(item, TextRun):
                parts.append(item.text)
            elif isinstance(item, Formula):
                parts.append(item.fallback_text or item.value)
            elif isinstance(item, Image) and item.alt_text:
                parts.append(item.alt_text)
        return "".join(parts)


@dataclass
class TableCell:
    blocks: list[Block] = field(default_factory=list)
    row_span: int = 1
    column_span: int = 1
    properties: TableCellProperties = field(default_factory=TableCellProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableCellProperties):
            self.properties = TableCellProperties(self.properties)


@dataclass
class TableRow:
    cells: list[TableCell] = field(default_factory=list)
    properties: TableRowProperties = field(default_factory=TableRowProperties)

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableRowProperties):
            self.properties = TableRowProperties(self.properties)


@dataclass
class Table:
    rows: list[TableRow] = field(default_factory=list)
    style_id: str | None = None
    box: Box | None = None
    properties: TableProperties = field(default_factory=TableProperties)
    provenance: Provenance | None = None
    visual_surrogate: VisualSurrogate | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, TableProperties):
            self.properties = TableProperties(self.properties)


Block: TypeAlias = Paragraph | Table | Formula | Image


@dataclass
class Footnote:
    """Document-local note definition with rich blocks, independent of pagination."""

    id: str
    blocks: list[Block] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)


def attach_visual_surrogate(
    element: Paragraph | Table | Formula | Image,
    resource: Resource,
    *,
    reason: str,
    fidelity: float | None = None,
    operation: str = "fallback.visual-surrogate",
) -> None:
    """Attach a visual companion and record why the native representation is insufficient."""
    element.visual_surrogate = VisualSurrogate(
        resource_id=resource.id,
        reason=reason,
        media_type=resource.media_type,
        fidelity=fidelity,
    )
    if element.provenance is not None:
        element.provenance = element.provenance.transformed(
            operation,
            detail=f"linked visual surrogate {resource.id}",
            fallback_reason=reason,
        )


@dataclass
class PageSettings:
    width: Length = field(default_factory=lambda: Length(595.28))
    height: Length = field(default_factory=lambda: Length(841.89))
    margin_top: Length = field(default_factory=lambda: Length(72.0))
    margin_right: Length = field(default_factory=lambda: Length(72.0))
    margin_bottom: Length = field(default_factory=lambda: Length(72.0))
    margin_left: Length = field(default_factory=lambda: Length(72.0))


@dataclass
class Section:
    blocks: list[Block] = field(default_factory=list)
    page: PageSettings = field(default_factory=PageSettings)
    headers: list[Block] = field(default_factory=list)
    footers: list[Block] = field(default_factory=list)
    first_page_headers: list[Block] = field(default_factory=list)
    first_page_footers: list[Block] = field(default_factory=list)
    even_page_headers: list[Block] = field(default_factory=list)
    even_page_footers: list[Block] = field(default_factory=list)
    properties: SectionProperties = field(default_factory=SectionProperties)
    provenance: Provenance | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.properties, SectionProperties):
            self.properties = SectionProperties(self.properties)


@dataclass
class DocumentModel:
    """Каноническое представление редактируемой и визуальной структуры."""

    sections: list[Section] = field(default_factory=list)
    resources: dict[str, Resource] = field(default_factory=dict)
    styles: dict[str, TextStyle] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    package: PackageGraph | None = None
    mode: ConversionMode = ConversionMode.BALANCED
    source_format: str | None = None
    version: int = 2
    footnotes: list[Footnote] = field(default_factory=list)
    footnote_properties: dict[str, Any] = field(default_factory=dict)
    footnote_extensions: dict[str, Any] = field(default_factory=dict)

    def add_resource(self, resource: Resource) -> None:
        if resource.id in self.resources:
            raise ValueError(f"duplicate resource id: {resource.id}")
        self.resources[resource.id] = resource

    def validate(self, *, limits: DocumentLimits | None = None) -> list[str]:
        """Return structural errors with locations; raise ArtifactLimitError for quotas."""
        from opendoc_model._validation import _validate_model

        return _validate_model(self, limits)


__all__ = [
    "Footnote",
    "VECTOR_IMAGE_MEDIA_TYPES",
    "Block",
    "Box",
    "ConversionMode",
    "DocumentModel",
    "Formula",
    "FormulaFormat",
    "Image",
    "ImageCrop",
    "ImageProperties",
    "Inline",
    "Length",
    "PackageGraph",
    "PackagePart",
    "PackageRelationship",
    "PageSettings",
    "Paragraph",
    "ParagraphProperties",
    "Provenance",
    "ProvenanceEvent",
    "Resource",
    "ResourceKind",
    "Section",
    "SectionProperties",
    "Table",
    "TableCell",
    "TableCellProperties",
    "TableProperties",
    "TableRow",
    "TableRowProperties",
    "TextRun",
    "TextStyle",
    "TextStyleProperties",
    "VisualSurrogate",
    "attach_visual_surrogate",
]
