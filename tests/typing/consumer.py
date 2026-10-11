"""Typed consumer of the installed library; also executed in its empty environment."""

from pathlib import Path
from typing import Any, assert_type

from opendoc_model import (
    Anchor,
    CapabilityProfile,
    CheckData,
    CheckResult,
    ColorValue,
    ComparisonData,
    ConversionIssueData,
    ConversionReport,
    ConversionReportData,
    DiagnosticData,
    DiagnosticIssue,
    DocumentComparison,
    DocumentInspection,
    DocumentModel,
    DocumentPage,
    Footnote,
    InspectionData,
    IntegrationModel,
    IssueSeverity,
    NodeLocation,
    Outline,
    OutlineEntry,
    OutlineTarget,
    PageGeometry,
    Paragraph,
    ParagraphProperties,
    Point2D,
    PreservationState,
    Rect2D,
    Section,
    Table,
    TableCell,
    TableCellSemantics,
    TableRow,
    TableRowSemantics,
    TableSemantics,
    TextPosition,
    TextRange,
    TextRun,
    WidthMeasure,
    check_document,
    clone_model,
    compare_inspections,
    document_from_json,
    document_to_json,
    edit_anchored_text,
    get_integration,
    get_outline,
    get_page_geometry,
    get_preferred_width,
    get_table_cell_semantics,
    get_table_row_semantics,
    get_table_semantics,
    inspect_document_model,
    iter_elements,
    iter_footnotes,
    negotiate_capabilities,
    page_point_to_display,
    preservation_result,
    set_anchor,
    set_integration,
    set_outline,
    set_preferred_width,
    set_table_semantics,
    with_page_geometry,
)
from opendoc_model.object_matching import ObjectMatch, match_objects
from opendoc_model.text_flow import TextFlowData, TextFlowFingerprint


def main() -> None:
    navigation_document = DocumentModel()
    set_outline(navigation_document, Outline((OutlineEntry("root", "", 0, target=OutlineTarget("external", uri="urn:test")),)))
    assert_type(get_outline(navigation_document), Outline | None)
    geometry = PageGeometry(Rect2D(0, 0, 600, 800), rotation=90)
    page = with_page_geometry(DocumentPage("typed-page", 600, 800), geometry)
    assert_type(page, DocumentPage)
    assert_type(get_page_geometry(page), PageGeometry | None)
    assert_type(page_point_to_display(geometry, Point2D(0, 0)), Point2D)
    table, cell = Table(), TableCell()
    set_table_semantics(table, TableSemantics())
    assert_type(get_table_semantics(table), TableSemantics | None)
    assert_type(get_table_cell_semantics(cell), TableCellSemantics | None)
    assert_type(get_table_row_semantics(TableRow()), TableRowSemantics | None)
    assert get_table_cell_semantics(cell) is None
    set_preferred_width(table, WidthMeasure("absolute", 480, "pt"))
    set_preferred_width(cell, WidthMeasure("relative", 0.1, "ratio", "table"))
    assert_type(get_preferred_width(cell), WidthMeasure | None)
    assert_type(table.properties.preferred_width, WidthMeasure | None)
    assert_type(cell.properties.preferred_width, WidthMeasure | None)
    assert get_preferred_width(cell) == WidthMeasure("relative", 0.1, "ratio", "table")
    paragraph = Paragraph([TextRun("Typed consumer")], properties=ParagraphProperties({"custom": {"revision": 3}}))
    document = DocumentModel(sections=[Section(blocks=[paragraph])], footnotes=[Footnote("note")])
    assert_type(clone_model(document), DocumentModel)
    assert_type(document_from_json(document_to_json(document)), DocumentModel)
    location = next(iter_elements(document, Paragraph))
    assert_type(location, NodeLocation[Paragraph])
    assert_type(location.node, Paragraph)
    assert_type(next(iter_footnotes(document)), NodeLocation[Footnote])
    color = ColorValue.from_hex("#123456", alpha=0.5, blend_mode="normal")
    assert_type(color, ColorValue)
    inspection = inspect_document_model(document)
    assert_type(inspection, DocumentInspection)
    snapshot = inspection.to_dict()
    assert_type(snapshot, InspectionData)
    assert_type(snapshot["valid"], bool)
    assert_type(snapshot["source_path"], str | None)
    assert_type(snapshot["metrics"]["paragraphs"], int)
    assert_type(snapshot["issues"], list[ConversionIssueData])
    # Open consumer schemas remain dynamic; the checker does not infer their fields.
    assert_type(paragraph.properties["custom"], Any)
    comparison = compare_inspections(inspection, inspection)
    assert_type(comparison, DocumentComparison)
    measured = comparison.to_dict()
    assert_type(measured, ComparisonData)
    assert_type(measured["has_losses"], bool)
    assert_type(measured["retention"]["characters"]["ratio"], float | int | None)
    assert_type(measured["matching_resource_hashes"], int)
    result = check_document(document)
    assert_type(result, CheckResult)
    checked = result.to_dict()
    assert_type(checked, CheckData)
    assert_type(checked["version"], int)
    assert_type(checked["success"], bool)
    issue = DiagnosticIssue("consumer.info", IssueSeverity.INFO, "Typed diagnostic")
    result.issues.append(issue)
    assert_type(result.to_dict()["issues"][0], DiagnosticData)
    assert_type(result.to_dict()["issues"][0]["reason"], str | None)
    report = ConversionReport(Path("consumer-output"))
    report.add(IssueSeverity.INFO, "consumer", "Typed conversion report")
    assert_type(report.to_dict(), ConversionReportData)
    assert_type(report.to_dict()["output_path"], str)
    assert_type(report.to_dict()["issues"][0], ConversionIssueData)
    objects = [{"type": "paragraph", "content_hash": "same", "location": "one"}]
    matches, _, _ = match_objects(objects, objects)
    assert_type(matches, list[ObjectMatch])
    assert_type(matches[0]["source_index"], int)
    flow = TextFlowFingerprint()
    flow.add("typed text")
    assert_type(flow.to_dict(), TextFlowData)
    assert_type(flow.to_dict()["tokens"], list[str] | None)
    assert result.success and snapshot["valid"] and measured["valid"]
    run = paragraph.content[0]
    assert isinstance(run, TextRun)
    set_anchor(run, Anchor("typed-run"))
    model = IntegrationModel(
        ranges=(TextRange("typed-range", TextPosition("typed-run", 0), TextPosition("typed-run", len(run.text))),)
    )
    set_integration(document, model)
    assert_type(get_integration(document), IntegrationModel | None)
    assert_type(edit_anchored_text(document, "typed-run", 0, 1, "x"), DocumentModel)
    assert_type(preservation_result(model), CheckResult)
    profile = CapabilityProfile("typed-profile", 1)
    assert_type(negotiate_capabilities(profile, profile), dict[str, tuple[PreservationState, ...]])
    from opendoc_model import Border, BorderSet, get_borders, resolve_borders, set_border, set_borders

    bordered = Table([])
    set_borders(bordered, BorderSet({"inside-horizontal": Border(width_pt=0.75)}))
    set_border(bordered, "top", Border("none"))
    assert_type(get_borders(bordered), BorderSet | None)
    assert_type(resolve_borders(bordered), BorderSet)
    assert resolve_borders(bordered).sides["top"].kind == "none"
    from opendoc_model import (
        ObjectMapping,
        object_mapping_from_dict,
        object_mapping_to_dict,
        remap_object_mapping,
        validate_object_mapping,
        with_mapping_publication,
    )

    mapping = ObjectMapping()
    assert_type(object_mapping_from_dict(object_mapping_to_dict(mapping)), ObjectMapping)
    assert_type(remap_object_mapping(mapping), ObjectMapping)
    validate_object_mapping(mapping)
    assert_type(with_mapping_publication(mapping, "attempted"), ObjectMapping)
    from opendoc_model import TextFlowProfile, text_flow_profile_from_dict, text_flow_profile_to_dict

    measured_profile = TextFlowProfile("typed-v1", "selected-text-v1", measured=True, complete=True)
    assert_type(text_flow_profile_from_dict(text_flow_profile_to_dict(measured_profile)), TextFlowProfile)
    from opendoc_model import (
        TableIndent,
        TabStop,
        TabStops,
        get_tab_stops,
        get_table_indent,
        resolve_tab_stops,
        resolve_table_indent,
        set_tab_stop,
        set_tab_stops,
        set_table_indent,
    )

    spacing_table = Table([])
    spacing_paragraph = Paragraph([])
    set_table_indent(spacing_table, TableIndent(30))
    assert_type(get_table_indent(spacing_table), TableIndent | None)
    assert_type(resolve_table_indent(spacing_table), TableIndent | None)
    set_tab_stops(spacing_paragraph, TabStops((TabStop(396, alignment="right", leader="line"),)))
    set_tab_stop(spacing_paragraph, 396, TabStop(396, "clear"))
    assert_type(get_tab_stops(spacing_paragraph), TabStops | None)
    assert_type(resolve_tab_stops(spacing_paragraph), TabStops)
    from opendoc_model import LineSpacing, get_line_spacing, resolve_line_spacing, set_line_spacing

    set_line_spacing(spacing_paragraph, LineSpacing("relative", 1.5))
    assert_type(get_line_spacing(spacing_paragraph), LineSpacing | None)
    assert_type(resolve_line_spacing(spacing_paragraph), LineSpacing | None)
    from opendoc_model import ArtifactLimitError

    quota_error = ArtifactLimitError("own", path="$", quota="bytes", maximum=1)
    assert_type(quota_error.path, str | None)
    assert_type(quota_error.quota, str | None)
    assert_type(quota_error.maximum, int | None)
    print("Installed typed consumer: runtime and named result fields OK")


if __name__ == "__main__":
    main()
