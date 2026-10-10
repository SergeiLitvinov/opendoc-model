"""Document structures, serialization and comparison without application backends."""

__version__ = "0.8.0"

from .checks import CheckPolicy as CheckPolicy
from .checks import check_document as check_document
from .checks import compare_documents as compare_documents
from .color import (
    ColorSpace as ColorSpace,
)
from .color import (
    ColorValue as ColorValue,
)
from .composition import (
    DocumentIdMap as DocumentIdMap,
)
from .composition import (
    DocumentMerge as DocumentMerge,
)
from .composition import (
    IdentifierConflictPolicy as IdentifierConflictPolicy,
)
from .composition import (
    MetadataConflictPolicy as MetadataConflictPolicy,
)
from .composition import (
    PackagePolicy as PackagePolicy,
)
from .composition import (
    extract_document as extract_document,
)
from .composition import (
    merge_documents as merge_documents,
)
from .diagnostics import CheckResult as CheckResult
from .diagnostics import (
    ConversionIssue as ConversionIssue,
)
from .diagnostics import (
    ConversionReport as ConversionReport,
)
from .diagnostics import DiagnosticIssue as DiagnosticIssue
from .diagnostics import (
    IssueSeverity as IssueSeverity,
)
from .document_codec import (
    FORMAT_NAME as FORMAT_NAME,
)
from .document_codec import (
    FORMAT_VERSION as FORMAT_VERSION,
)
from .document_codec import (
    document_from_dict as document_from_dict,
)
from .document_codec import (
    document_from_json as document_from_json,
)
from .document_codec import (
    document_to_dict as document_to_dict,
)
from .document_codec import (
    document_to_json as document_to_json,
)
from .document_codec import (
    load_document as load_document,
)
from .document_codec import (
    save_document as save_document,
)
from .document_model import (
    VECTOR_IMAGE_MEDIA_TYPES as VECTOR_IMAGE_MEDIA_TYPES,
)
from .document_model import (
    Block as Block,
)
from .document_model import (
    Box as Box,
)
from .document_model import (
    ConversionMode as ConversionMode,
)
from .document_model import (
    DocumentModel as DocumentModel,
)
from .document_model import Footnote as Footnote
from .document_model import (
    Formula as Formula,
)
from .document_model import (
    FormulaFormat as FormulaFormat,
)
from .document_model import (
    Image as Image,
)
from .document_model import (
    ImageCrop as ImageCrop,
)
from .document_model import (
    ImageProperties as ImageProperties,
)
from .document_model import (
    Inline as Inline,
)
from .document_model import (
    Length as Length,
)
from .document_model import (
    PackageGraph as PackageGraph,
)
from .document_model import (
    PackagePart as PackagePart,
)
from .document_model import (
    PackageRelationship as PackageRelationship,
)
from .document_model import (
    PageSettings as PageSettings,
)
from .document_model import (
    Paragraph as Paragraph,
)
from .document_model import (
    ParagraphProperties as ParagraphProperties,
)
from .document_model import (
    Provenance as Provenance,
)
from .document_model import (
    ProvenanceEvent as ProvenanceEvent,
)
from .document_model import (
    Resource as Resource,
)
from .document_model import (
    ResourceKind as ResourceKind,
)
from .document_model import (
    Section as Section,
)
from .document_model import (
    SectionProperties as SectionProperties,
)
from .document_model import (
    Table as Table,
)
from .document_model import (
    TableCell as TableCell,
)
from .document_model import (
    TableCellProperties as TableCellProperties,
)
from .document_model import (
    TableProperties as TableProperties,
)
from .document_model import (
    TableRow as TableRow,
)
from .document_model import (
    TableRowProperties as TableRowProperties,
)
from .document_model import (
    TextRun as TextRun,
)
from .document_model import (
    TextStyle as TextStyle,
)
from .document_model import (
    TextStyleProperties as TextStyleProperties,
)
from .document_model import (
    VisualSurrogate as VisualSurrogate,
)
from .document_model import (
    attach_visual_surrogate as attach_visual_surrogate,
)
from .emphasis_quality import (
    EmphasisLossPolicy as EmphasisLossPolicy,
)
from .extensions import ExtensionCallback as ExtensionCallback
from .extensions import ExtensionContext as ExtensionContext
from .extensions import (
    ExtensionMigration as ExtensionMigration,
)
from .extensions import (
    ExtensionMigrationCallback as ExtensionMigrationCallback,
)
from .extensions import ExtensionSchema as ExtensionSchema
from .extensions import ExtensionScope as ExtensionScope
from .extensions import ExtensionValue as ExtensionValue
from .extensions import UnknownExtensionPolicy as UnknownExtensionPolicy
from .extensions import check_extensions as check_extensions
from .extensions import get_extension as get_extension
from .extensions import (
    migrate_extension as migrate_extension,
)
from .extensions import remove_extension as remove_extension
from .extensions import set_extension as set_extension
from .footnotes import FOOTNOTE_REFERENCE_PROPERTY as FOOTNOTE_REFERENCE_PROPERTY
from .footnotes import FOOTNOTES_PROPERTY as FOOTNOTES_PROPERTY
from .footnotes import FootnoteNumber as FootnoteNumber
from .footnotes import FootnoteReference as FootnoteReference
from .footnotes import get_footnote as get_footnote
from .footnotes import get_footnote_reference as get_footnote_reference
from .footnotes import iter_footnote_numbers as iter_footnote_numbers
from .footnotes import iter_footnote_references as iter_footnote_references
from .footnotes import iter_footnotes as iter_footnotes
from .footnotes import remove_footnote as remove_footnote
from .footnotes import set_footnote as set_footnote
from .footnotes import set_footnote_reference as set_footnote_reference
from .formula_quality_policy import (
    FormulaLossPolicy as FormulaLossPolicy,
)
from .inspection import (
    DocumentComparison as DocumentComparison,
)
from .inspection import (
    DocumentInspection as DocumentInspection,
)
from .inspection import (
    compare_inspections as compare_inspections,
)
from .inspection import (
    inspect_document_model as inspect_document_model,
)
from .integration import (
    INTEGRATION_PROPERTY as INTEGRATION_PROPERTY,
)
from .integration import (
    INTEGRATION_VERSION as INTEGRATION_VERSION,
)
from .integration import (
    edit_anchored_text as edit_anchored_text,
)
from .integration import (
    get_integration as get_integration,
)
from .integration import (
    integration_resource_uses as integration_resource_uses,
)
from .integration import (
    negotiate_capabilities as negotiate_capabilities,
)
from .integration import (
    preservation_result as preservation_result,
)
from .integration import (
    resolve_scene_style as resolve_scene_style,
)
from .integration import (
    set_integration as set_integration,
)
from .integration_types import (
    Accessibility as Accessibility,
)
from .integration_types import (
    AffineTransform as AffineTransform,
)
from .integration_types import (
    Annotation as Annotation,
)
from .integration_types import (
    BibliographyEntry as BibliographyEntry,
)
from .integration_types import (
    CapabilityProfile as CapabilityProfile,
)
from .integration_types import (
    Chart as Chart,
)
from .integration_types import (
    ChartAxis as ChartAxis,
)
from .integration_types import (
    ChartSeries as ChartSeries,
)
from .integration_types import (
    Comment as Comment,
)
from .integration_types import (
    ContentControl as ContentControl,
)
from .integration_types import (
    Diagram as Diagram,
)
from .integration_types import (
    DocumentPage as DocumentPage,
)
from .integration_types import (
    FeatureCapability as FeatureCapability,
)
from .integration_types import (
    Field as Field,
)
from .integration_types import (
    FormControl as FormControl,
)
from .integration_types import (
    FormulaTree as FormulaTree,
)
from .integration_types import (
    IntegrationModel as IntegrationModel,
)
from .integration_types import (
    IntegrationRecord as IntegrationRecord,
)
from .integration_types import (
    MathNode as MathNode,
)
from .integration_types import (
    MediaObject as MediaObject,
)
from .integration_types import (
    Paint as Paint,
)
from .integration_types import (
    PathCommand as PathCommand,
)
from .integration_types import (
    PreservationRecord as PreservationRecord,
)
from .integration_types import (
    PreservationState as PreservationState,
)
from .integration_types import (
    Revision as Revision,
)
from .integration_types import (
    SceneStyle as SceneStyle,
)
from .integration_types import (
    Sheet as Sheet,
)
from .integration_types import (
    SheetCell as SheetCell,
)
from .integration_types import (
    SourceFile as SourceFile,
)
from .integration_types import (
    SourceMap as SourceMap,
)
from .integration_types import (
    SourceMapping as SourceMapping,
)
from .integration_types import (
    SourceSpan as SourceSpan,
)
from .integration_types import (
    TextPosition as TextPosition,
)
from .integration_types import (
    TextRange as TextRange,
)
from .integration_types import (
    Timing as Timing,
)
from .integration_types import (
    UnknownFragment as UnknownFragment,
)
from .integration_types import (
    VectorGroup as VectorGroup,
)
from .integration_types import (
    VectorPath as VectorPath,
)
from .integration_types import (
    VectorScene as VectorScene,
)
from .integration_types import (
    Workbook as Workbook,
)
from .limits import DocumentLimits as DocumentLimits
from .lists import LIST_PROPERTY as LIST_PROPERTY
from .lists import ListItem as ListItem
from .lists import ListKind as ListKind
from .lists import ListNumber as ListNumber
from .lists import get_list_item as get_list_item
from .lists import iter_list_items as iter_list_items
from .lists import iter_list_numbers as iter_list_numbers
from .lists import set_list_item as set_list_item
from .object_matching import MatchingLimits as MatchingLimits
from .object_quality_policy import (
    ObjectLossPolicy as ObjectLossPolicy,
)
from .operations import (
    clone_model as clone_model,
)
from .operations import (
    extract_text as extract_text,
)
from .operations import (
    insert_node as insert_node,
)
from .operations import (
    remove_node as remove_node,
)
from .operations import (
    replace_node as replace_node,
)
from .operations import (
    transform_elements as transform_elements,
)
from .outline import OUTLINE_PROPERTY as OUTLINE_PROPERTY
from .outline import Outline as Outline
from .outline import OutlineEntry as OutlineEntry
from .outline import OutlineTarget as OutlineTarget
from .outline import get_outline as get_outline
from .outline import remap_outline as remap_outline
from .outline import set_outline as set_outline
from .page_geometry import PAGE_GEOMETRY_PROPERTY as PAGE_GEOMETRY_PROPERTY
from .page_geometry import PageGeometry as PageGeometry
from .page_geometry import get_page_geometry as get_page_geometry
from .page_geometry import page_display_size as page_display_size
from .page_geometry import page_point_from_display as page_point_from_display
from .page_geometry import page_point_to_display as page_point_to_display
from .page_geometry import page_rect_from_display as page_rect_from_display
from .page_geometry import page_rect_to_display as page_rect_to_display
from .page_geometry import with_page_geometry as with_page_geometry
from .properties import (
    PROPERTY_SCHEMA_VERSION as PROPERTY_SCHEMA_VERSION,
)
from .quality_policy import (
    QualityPolicy as QualityPolicy,
)
from .references import ANCHOR_PROPERTY as ANCHOR_PROPERTY
from .references import INTERNAL_LINK_PROPERTY as INTERNAL_LINK_PROPERTY
from .references import Anchor as Anchor
from .references import InternalLink as InternalLink
from .references import get_anchor as get_anchor
from .references import get_internal_link as get_internal_link
from .references import iter_anchors as iter_anchors
from .references import iter_internal_links as iter_internal_links
from .references import resolve_anchor as resolve_anchor
from .references import set_anchor as set_anchor
from .references import set_internal_link as set_internal_link
from .resources import (
    ResourceConflictPolicy as ResourceConflictPolicy,
)
from .resources import (
    add_resource as add_resource,
)
from .resources import (
    embed_resources as embed_resources,
)
from .resources import (
    find_duplicate_resources as find_duplicate_resources,
)
from .resources import (
    find_resource_uses as find_resource_uses,
)
from .resources import (
    remove_resource as remove_resource,
)
from .resources import (
    replace_resource as replace_resource,
)
from .result_types import (
    CheckData as CheckData,
)
from .result_types import (
    ComparisonData as ComparisonData,
)
from .result_types import (
    ConversionIssueData as ConversionIssueData,
)
from .result_types import (
    ConversionReportData as ConversionReportData,
)
from .result_types import (
    DiagnosticData as DiagnosticData,
)
from .result_types import (
    InspectionData as InspectionData,
)
from .semantics import HEADING_PROPERTY as HEADING_PROPERTY
from .semantics import Heading as Heading
from .semantics import get_heading as get_heading
from .semantics import iter_headings as iter_headings
from .semantics import set_heading as set_heading
from .storage import ArtifactLimitError as ArtifactLimitError
from .styles import effective_text_style as effective_text_style
from .styles import resolve_style as resolve_style
from .table_borders import (
    CELL_BORDERS_PROPERTY as CELL_BORDERS_PROPERTY,
)
from .table_borders import (
    TABLE_BORDERS_PROPERTY as TABLE_BORDERS_PROPERTY,
)
from .table_borders import (
    Border as Border,
)
from .table_borders import (
    BorderSet as BorderSet,
)
from .table_borders import (
    BorderSide as BorderSide,
)
from .table_borders import (
    BorderStyle as BorderStyle,
)
from .table_borders import (
    get_borders as get_borders,
)
from .table_borders import (
    resolve_borders as resolve_borders,
)
from .table_borders import (
    set_border as set_border,
)
from .table_borders import (
    set_borders as set_borders,
)
from .table_semantics import (
    TABLE_CELL_SEMANTICS_PROPERTY as TABLE_CELL_SEMANTICS_PROPERTY,
)
from .table_semantics import (
    TABLE_ROW_SEMANTICS_PROPERTY as TABLE_ROW_SEMANTICS_PROPERTY,
)
from .table_semantics import (
    TABLE_SEMANTICS_PROPERTY as TABLE_SEMANTICS_PROPERTY,
)
from .table_semantics import (
    TableCellSemantics as TableCellSemantics,
)
from .table_semantics import (
    TableColumnGroup as TableColumnGroup,
)
from .table_semantics import (
    TableRowGroup as TableRowGroup,
)
from .table_semantics import (
    TableRowSemantics as TableRowSemantics,
)
from .table_semantics import (
    TableSemantics as TableSemantics,
)
from .table_semantics import (
    get_table_cell_semantics as get_table_cell_semantics,
)
from .table_semantics import (
    get_table_row_semantics as get_table_row_semantics,
)
from .table_semantics import (
    get_table_semantics as get_table_semantics,
)
from .table_semantics import (
    set_table_cell_semantics as set_table_cell_semantics,
)
from .table_semantics import (
    set_table_row_semantics as set_table_row_semantics,
)
from .table_semantics import (
    set_table_semantics as set_table_semantics,
)
from .text_quality_policy import (
    TextPreservationPolicy as TextPreservationPolicy,
)
from .traversal import (
    SECTION_CONTENT_FIELDS as SECTION_CONTENT_FIELDS,
)
from .traversal import (
    Element as Element,
)
from .traversal import (
    ModelNode as ModelNode,
)
from .traversal import (
    NodeKind as NodeKind,
)
from .traversal import (
    NodeLocation as NodeLocation,
)
from .traversal import (
    ResourceReference as ResourceReference,
)
from .traversal import (
    ResourceReferenceKind as ResourceReferenceKind,
)
from .traversal import (
    iter_blocks as iter_blocks,
)
from .traversal import (
    iter_elements as iter_elements,
)
from .traversal import (
    iter_inlines as iter_inlines,
)
from .traversal import (
    iter_resource_references as iter_resource_references,
)
from .traversal import (
    iter_sections as iter_sections,
)
from .traversal import (
    walk_model as walk_model,
)
from .units import Point2D as Point2D
from .units import Rect2D as Rect2D
from .widths import WidthMeasure as WidthMeasure
from .widths import get_preferred_width as get_preferred_width
from .widths import set_preferred_width as set_preferred_width

__all__ = [
    "CELL_BORDERS_PROPERTY",
    "TABLE_BORDERS_PROPERTY",
    "Border",
    "BorderSet",
    "BorderSide",
    "BorderStyle",
    "get_borders",
    "set_borders",
    "set_border",
    "resolve_borders",
    "OUTLINE_PROPERTY",
    "Outline",
    "OutlineEntry",
    "OutlineTarget",
    "get_outline",
    "set_outline",
    "remap_outline",
    "PAGE_GEOMETRY_PROPERTY",
    "PageGeometry",
    "Point2D",
    "Rect2D",
    "get_page_geometry",
    "with_page_geometry",
    "page_display_size",
    "page_point_to_display",
    "page_point_from_display",
    "page_rect_to_display",
    "page_rect_from_display",
    "TABLE_SEMANTICS_PROPERTY",
    "TABLE_ROW_SEMANTICS_PROPERTY",
    "TABLE_CELL_SEMANTICS_PROPERTY",
    "TableSemantics",
    "TableRowSemantics",
    "TableCellSemantics",
    "TableRowGroup",
    "TableColumnGroup",
    "get_table_semantics",
    "set_table_semantics",
    "get_table_row_semantics",
    "set_table_row_semantics",
    "get_table_cell_semantics",
    "set_table_cell_semantics",
    "WidthMeasure",
    "get_preferred_width",
    "set_preferred_width",
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
    "INTEGRATION_PROPERTY",
    "INTEGRATION_VERSION",
    "edit_anchored_text",
    "get_integration",
    "integration_resource_uses",
    "negotiate_capabilities",
    "preservation_result",
    "resolve_scene_style",
    "set_integration",
    "ExtensionMigration",
    "ExtensionMigrationCallback",
    "migrate_extension",
    "CheckData",
    "ComparisonData",
    "ConversionIssueData",
    "ConversionReportData",
    "DiagnosticData",
    "InspectionData",
    "MatchingLimits",
    "ExtensionCallback",
    "ExtensionContext",
    "ExtensionSchema",
    "ExtensionScope",
    "ExtensionValue",
    "UnknownExtensionPolicy",
    "check_extensions",
    "get_extension",
    "remove_extension",
    "set_extension",
    "FOOTNOTES_PROPERTY",
    "FOOTNOTE_REFERENCE_PROPERTY",
    "Footnote",
    "FootnoteNumber",
    "FootnoteReference",
    "get_footnote",
    "get_footnote_reference",
    "iter_footnote_numbers",
    "iter_footnote_references",
    "iter_footnotes",
    "remove_footnote",
    "set_footnote",
    "set_footnote_reference",
    "ANCHOR_PROPERTY",
    "INTERNAL_LINK_PROPERTY",
    "Anchor",
    "InternalLink",
    "get_anchor",
    "get_internal_link",
    "iter_anchors",
    "iter_internal_links",
    "resolve_anchor",
    "set_anchor",
    "set_internal_link",
    "LIST_PROPERTY",
    "ListItem",
    "ListKind",
    "ListNumber",
    "get_list_item",
    "iter_list_items",
    "iter_list_numbers",
    "set_list_item",
    "HEADING_PROPERTY",
    "Heading",
    "get_heading",
    "iter_headings",
    "set_heading",
    "CheckPolicy",
    "CheckResult",
    "DiagnosticIssue",
    "check_document",
    "compare_documents",
    "ResourceConflictPolicy",
    "add_resource",
    "embed_resources",
    "find_duplicate_resources",
    "find_resource_uses",
    "remove_resource",
    "replace_resource",
    "effective_text_style",
    "resolve_style",
    "DocumentIdMap",
    "DocumentMerge",
    "IdentifierConflictPolicy",
    "MetadataConflictPolicy",
    "PackagePolicy",
    "extract_document",
    "merge_documents",
    "clone_model",
    "extract_text",
    "insert_node",
    "remove_node",
    "replace_node",
    "transform_elements",
    "SECTION_CONTENT_FIELDS",
    "Element",
    "ModelNode",
    "NodeKind",
    "NodeLocation",
    "ResourceReference",
    "ResourceReferenceKind",
    "iter_blocks",
    "iter_elements",
    "iter_inlines",
    "iter_resource_references",
    "iter_sections",
    "walk_model",
    "ArtifactLimitError",
    "FORMAT_NAME",
    "FORMAT_VERSION",
    "PROPERTY_SCHEMA_VERSION",
    "VECTOR_IMAGE_MEDIA_TYPES",
    "Block",
    "Box",
    "ColorSpace",
    "ColorValue",
    "ConversionIssue",
    "ConversionMode",
    "ConversionReport",
    "DocumentComparison",
    "DocumentInspection",
    "DocumentModel",
    "DocumentLimits",
    "EmphasisLossPolicy",
    "Formula",
    "FormulaFormat",
    "FormulaLossPolicy",
    "Image",
    "ImageCrop",
    "ImageProperties",
    "Inline",
    "IssueSeverity",
    "Length",
    "ObjectLossPolicy",
    "PackageGraph",
    "PackagePart",
    "PackageRelationship",
    "PageSettings",
    "Paragraph",
    "ParagraphProperties",
    "Provenance",
    "ProvenanceEvent",
    "QualityPolicy",
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
    "TextPreservationPolicy",
    "TextRun",
    "TextStyle",
    "TextStyleProperties",
    "VisualSurrogate",
    "attach_visual_surrogate",
    "compare_inspections",
    "document_from_dict",
    "document_from_json",
    "document_to_dict",
    "document_to_json",
    "inspect_document_model",
    "load_document",
    "save_document",
]
