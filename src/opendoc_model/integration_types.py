"""Format-neutral, inert adapter data; coordinates are points, offsets are Unicode code points."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal

from opendoc_model.color import ColorValue
from opendoc_model.diagnostics import DiagnosticIssue
from opendoc_model.document_model import Box, Provenance


class PreservationState(str, Enum):
    SEMANTIC = "semantic"
    OPAQUE = "opaque"
    VISUAL = "visual"
    LOST = "lost"
    REJECTED = "rejected"


@dataclass(frozen=True, kw_only=True)
class IntegrationRecord:
    """Unknown JSON fields survive round trips without implying semantic support."""

    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FeatureCapability(IntegrationRecord):
    feature: str
    states: tuple[PreservationState, ...] = (PreservationState.SEMANTIC,)
    schema_version: int = 1


@dataclass(frozen=True)
class CapabilityProfile(IntegrationRecord):
    id: str
    version: int
    features: tuple[FeatureCapability, ...] = ()


@dataclass(frozen=True)
class PreservationRecord(IntegrationRecord):
    """The existing diagnostic is the explanation; state describes what survived."""

    issue: DiagnosticIssue
    state: PreservationState
    node_id: str | None = None
    provenance: Provenance | None = None


@dataclass(frozen=True)
class SourceSpan(IntegrationRecord):
    source_id: str
    start: int
    end: int
    line: int | None = None
    column: int | None = None
    object_id: str | None = None
    expansion_id: str | None = None


@dataclass(frozen=True)
class SourceFile(IntegrationRecord):
    id: str
    uri: str
    offset_unit: Literal["codepoint", "byte"] = "codepoint"
    part: str | None = None
    resource_id: str | None = None
    sha256: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class SourceMapping(IntegrationRecord):
    node_id: str
    spans: tuple[SourceSpan, ...]


@dataclass(frozen=True)
class SourceMap(IntegrationRecord):
    sources: tuple[SourceFile, ...] = ()
    mappings: tuple[SourceMapping, ...] = ()
    expansions: tuple[SourceSpan, ...] = ()


@dataclass(frozen=True)
class UnknownFragment(IntegrationRecord):
    id: str
    resource_id: str
    media_type: str
    max_bytes: int
    export_policy: Literal["preserve", "visual", "reject"] = "preserve"
    node_id: str | None = None
    source: SourceSpan | None = None
    visual_resource_id: str | None = None


@dataclass(frozen=True)
class TextPosition(IntegrationRecord):
    node_id: str
    offset: int
    affinity: Literal["before", "after"] = "after"


@dataclass(frozen=True)
class TextRange(IntegrationRecord):
    id: str
    start: TextPosition
    end: TextPosition


@dataclass(frozen=True)
class Field(IntegrationRecord):
    id: str
    kind: Literal["literal", "reference", "citation", "page", "date", "custom"]
    code: str = ""
    value: str = ""
    range_id: str | None = None
    target_id: str | None = None
    bibliography_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class BibliographyEntry(IntegrationRecord):
    id: str
    title: str
    authors: tuple[str, ...] = ()
    year: str | None = None
    identifiers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Comment(IntegrationRecord):
    id: str
    range_id: str
    text: str
    author: str = ""
    reply_to: str | None = None


@dataclass(frozen=True)
class Revision(IntegrationRecord):
    id: str
    range_id: str
    kind: Literal["insert", "delete", "format"]
    author: str = ""
    original_text: str = ""


@dataclass(frozen=True)
class ContentControl(IntegrationRecord):
    id: str
    range_id: str
    kind: Literal["text", "choice", "date", "checkbox"] = "text"
    choices: tuple[str, ...] = ()
    locked: bool = False


@dataclass(frozen=True)
class AffineTransform(IntegrationRecord):
    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0


@dataclass(frozen=True)
class PathCommand(IntegrationRecord):
    operation: Literal["move", "line", "quadratic", "cubic", "close"]
    values: tuple[float, ...] = ()


@dataclass(frozen=True)
class Paint(IntegrationRecord):
    color: ColorValue
    opacity: float = 1.0


@dataclass(frozen=True)
class VectorPath(IntegrationRecord):
    id: str
    commands: tuple[PathCommand, ...]
    fill: Paint | None = None
    stroke: Paint | None = None
    stroke_width: float = 1.0
    fill_rule: Literal["nonzero", "evenodd"] = "nonzero"
    transform: AffineTransform = field(default_factory=AffineTransform)
    clip_id: str | None = None
    mask_resource_id: str | None = None
    z_order: int = 0


@dataclass(frozen=True)
class VectorGroup(IntegrationRecord):
    id: str
    children: tuple[str, ...]
    transform: AffineTransform = field(default_factory=AffineTransform)
    clip_id: str | None = None
    mask_resource_id: str | None = None
    opacity: float = 1.0
    z_order: int = 0
    compositing: GroupCompositing | None = field(default=None, kw_only=True, metadata={"omit_default": True})


BlendMode = Literal[
    "normal",
    "multiply",
    "screen",
    "overlay",
    "darken",
    "lighten",
    "color-dodge",
    "color-burn",
    "hard-light",
    "soft-light",
    "difference",
    "exclusion",
    "hue",
    "saturation",
    "color",
    "luminosity",
]


@dataclass(frozen=True)
class GroupCompositing(IntegrationRecord):
    """Composition of the complete scope, not multiplication of child alphas.

    None is unknown; it never implies Normal, isolation, knockout or opacity 1.
    Rendering, backdrop construction and native mode translation are external.
    """

    opacity: float | None = None
    isolated: bool | None = None
    knockout: bool | None = None
    blend_mode: BlendMode | None = None
    color_space: GroupColorSpace | None = field(default=None, kw_only=True, metadata={"omit_default": True})


@dataclass(frozen=True)
class GroupColorSpace(IntegrationRecord):
    """Declared intermediate blending space; no conversion, ICC parsing or inferred defaults.

    rgb/gray/cmyk name component models, not calibrated colorimetry. ICC requires
    a profile resource; explicit sRGB has fixed colorimetry and forbids a profile
    override. Unknown space may retain a known opaque profile reference.
    """

    space: Literal["rgb", "gray", "cmyk", "srgb", "icc"] | None = None
    profile_resource_id: str | None = None


@dataclass(frozen=True)
class VectorClip(IntegrationRecord):
    """Clip-local points mapped into the clipped owner's local space by transform.

    Winding None is unknown. Known winding with empty commands means empty area.
    This stores geometry, without calculating intersections or hiding model text.
    """

    id: str
    commands: tuple[PathCommand, ...]
    fill_rule: Literal["nonzero", "evenodd"] | None = None
    transform: AffineTransform = field(default_factory=AffineTransform)


@dataclass(frozen=True)
class SceneOccurrence(IntegrationRecord):
    """One scene-local paint occurrence of an anchored structural object.

    Occurrence ID, anchor ID and resource ID have different scopes. Several
    occurrences may use one anchor without copying or trimming its content.
    """

    id: str
    node_id: str
    transform: AffineTransform = field(default_factory=AffineTransform)
    clip_id: str | None = None
    mask_resource_id: str | None = None
    compositing: GroupCompositing | None = None


@dataclass(frozen=True)
class VectorScene(IntegrationRecord):
    id: str
    width: float
    height: float
    paths: tuple[VectorPath, ...] = ()
    groups: tuple[VectorGroup, ...] = ()
    roots: tuple[str, ...] = ()
    node_id: str | None = None
    clips: tuple[VectorClip, ...] = field(default=(), kw_only=True, metadata={"omit_default": True})
    occurrences: tuple[SceneOccurrence, ...] = field(default=(), kw_only=True, metadata={"omit_default": True})
    scope_version: Literal[1] | None = field(default=None, kw_only=True, metadata={"omit_default": True})


@dataclass(frozen=True)
class ChartSeries(IntegrationRecord):
    name: str
    values: tuple[float | None, ...]
    categories: tuple[str, ...] = ()
    cached: bool = True
    x_values: tuple[float, ...] = ()


@dataclass(frozen=True)
class ChartAxis(IntegrationRecord):
    id: str
    kind: Literal["category", "value", "date"]
    title: str = ""
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class Chart(IntegrationRecord):
    id: str
    kind: Literal["bar", "line", "scatter", "pie"]
    series: tuple[ChartSeries, ...]
    axes: tuple[ChartAxis, ...] = ()
    node_id: str | None = None
    style_id: str | None = None
    visual_resource_id: str | None = None


@dataclass(frozen=True)
class SceneStyle(IntegrationRecord):
    id: str
    properties: dict[str, Any] = field(default_factory=dict)
    parent_id: str | None = None
    layer: Literal["theme", "master", "layout", "local"] = "local"


@dataclass(frozen=True)
class Diagram(IntegrationRecord):
    id: str
    scene_id: str
    edges: tuple[tuple[str, str], ...] = ()
    node_id: str | None = None
    style_id: str | None = None
    visual_resource_id: str | None = None


@dataclass(frozen=True)
class Accessibility(IntegrationRecord):
    node_id: str
    role: str
    alt_text: str = ""
    language: str | None = None


@dataclass(frozen=True)
class DocumentPage(IntegrationRecord):
    id: str
    width: float
    height: float
    reading_order: tuple[str, ...] = ()


@dataclass(frozen=True)
class Annotation(IntegrationRecord):
    id: str
    page_id: str
    kind: Literal["note", "link", "highlight"]
    text: str = ""
    range_id: str | None = None
    target: str | None = None
    action: dict[str, Any] = field(default_factory=dict)
    box: Box | None = None


@dataclass(frozen=True)
class FormControl(IntegrationRecord):
    id: str
    page_id: str
    kind: Literal["text", "checkbox", "choice", "button"]
    value: str = ""
    choices: tuple[str, ...] = ()
    action: dict[str, Any] = field(default_factory=dict)
    box: Box | None = None


@dataclass(frozen=True)
class MediaObject(IntegrationRecord):
    id: str
    resource_id: str
    kind: Literal["audio", "video"]
    node_id: str | None = None
    duration: float | None = None
    poster_resource_id: str | None = None


@dataclass(frozen=True)
class Timing(IntegrationRecord):
    id: str
    target_id: str
    start: float
    duration: float
    after_id: str | None = None


@dataclass(frozen=True)
class SheetCell(IntegrationRecord):
    row: int
    column: int
    value: str | int | float | bool | None = None
    formula: str | None = None
    row_span: int = 1
    column_span: int = 1
    style_id: str | None = None


@dataclass(frozen=True)
class Sheet(IntegrationRecord):
    id: str
    name: str
    cells: tuple[SheetCell, ...] = ()


@dataclass(frozen=True)
class Workbook(IntegrationRecord):
    id: str
    sheets: tuple[Sheet, ...]


@dataclass(frozen=True)
class MathNode(IntegrationRecord):
    kind: Literal["identifier", "number", "operator", "row", "fraction", "root", "script", "matrix", "text"]
    value: str = ""
    children: tuple[MathNode, ...] = ()


@dataclass(frozen=True)
class FormulaTree(IntegrationRecord):
    node_id: str
    root: MathNode
    original_resource_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class IntegrationModel(IntegrationRecord):
    """Optional schema v1 linked to existing anchor IDs, resources and diagnostics."""

    profiles: tuple[CapabilityProfile, ...] = ()
    preservation: tuple[PreservationRecord, ...] = ()
    assessed_features: tuple[str, ...] = ()
    assessment_complete: bool = False
    source_map: SourceMap = field(default_factory=SourceMap)
    unknown_fragments: tuple[UnknownFragment, ...] = ()
    ranges: tuple[TextRange, ...] = ()
    fields: tuple[Field, ...] = ()
    bibliography: tuple[BibliographyEntry, ...] = ()
    comments: tuple[Comment, ...] = ()
    revisions: tuple[Revision, ...] = ()
    content_controls: tuple[ContentControl, ...] = ()
    scenes: tuple[VectorScene, ...] = ()
    charts: tuple[Chart, ...] = ()
    diagrams: tuple[Diagram, ...] = ()
    scene_styles: tuple[SceneStyle, ...] = ()
    pages: tuple[DocumentPage, ...] = ()
    accessibility: tuple[Accessibility, ...] = ()
    annotations: tuple[Annotation, ...] = ()
    forms: tuple[FormControl, ...] = ()
    media: tuple[MediaObject, ...] = ()
    timing: tuple[Timing, ...] = ()
    workbooks: tuple[Workbook, ...] = ()
    formula_trees: tuple[FormulaTree, ...] = ()


__all__ = [
    "BlendMode",
    "GroupCompositing",
    "GroupColorSpace",
    "VectorClip",
    "SceneOccurrence",
    "Accessibility",
    "AffineTransform",
    "Annotation",
    "BibliographyEntry",
    "CapabilityProfile",
    "Chart",
    "ChartAxis",
    "ChartSeries",
    "Comment",
    "ContentControl",
    "Diagram",
    "DocumentPage",
    "FeatureCapability",
    "Field",
    "FormControl",
    "FormulaTree",
    "IntegrationModel",
    "IntegrationRecord",
    "MathNode",
    "MediaObject",
    "Paint",
    "PathCommand",
    "PreservationRecord",
    "PreservationState",
    "Revision",
    "SceneStyle",
    "Sheet",
    "SheetCell",
    "SourceFile",
    "SourceMap",
    "SourceMapping",
    "SourceSpan",
    "TextPosition",
    "TextRange",
    "Timing",
    "UnknownFragment",
    "VectorGroup",
    "VectorPath",
    "VectorScene",
    "Workbook",
]
