"""Deliberate static errors; checked but never executed."""

from opendoc_model import (
    CapabilityProfile,
    CheckResult,
    ColorValue,
    ConversionReport,
    DocumentComparison,
    DocumentInspection,
    DocumentModel,
    ImageSourceRect,
    ListItem,
    MatchingLimits,
    PageSettingValue,
    PathCommand,
    SheetCell,
    TextCluster,
    TextLayout,
    TextPosition,
    TextRun,
    integration_from_dict,
    integration_to_dict,
    invalidate_text_layouts,
)


def incorrect(
    inspection: DocumentInspection, comparison: DocumentComparison, result: CheckResult, report: ConversionReport
) -> None:
    TextRun(123)  # type-error: arg-type
    ImageSourceRect("outside", 0.0, 1.0, 1.0)  # type-error: arg-type
    PageSettingValue("assumed")  # type-error: arg-type
    invalidate_text_layouts(DocumentModel(), detach="yes")  # type-error: arg-type
    TextLayout(1)  # type-error: arg-type
    TextCluster((0,), range_ids=(1,))  # type-error: arg-type
    integration_to_dict({})  # type-error: arg-type
    integration_from_dict([])  # type-error: arg-type
    ListItem("items", parent_id=42)  # type-error: arg-type
    MatchingLimits(max_work="many")  # type-error: arg-type
    ColorValue.from_hex("#123456", alpha="opaque")  # type-error: arg-type
    inspection.to_dict()["valid"] = "yes"  # type-error: typeddict-item
    comparison.to_dict()["retention"]["characters"]["ratio"] = "complete"  # type-error: assignment
    result.to_dict()["issues"][0]["reason"] = 42  # type-error: typeddict-item
    result.to_dict()["issues"][0]["measurement"] = "text"  # type-error: typeddict-item
    report.to_dict()["lossless"] = "yes"  # type-error: typeddict-item
    TextPosition("anchor", "one")  # type-error: arg-type
    PathCommand("execute")  # type-error: arg-type
    SheetCell(0, 0, value=[])  # type-error: arg-type
    CapabilityProfile("profile", 1, features=["text"])  # type-error: arg-type


def bad_block_group() -> None:
    from opendoc_model import BlockGroup, BlockGroupListOwner, TextRun

    BlockGroup([TextRun("inline")])  # type-error: list-item
    BlockGroup(role="html")  # type-error: arg-type
    BlockGroupListOwner(1)  # type-error: arg-type


def bad_outline_label() -> None:
    from opendoc_model import OutlineLabel, Paragraph

    OutlineLabel("Caption", (Paragraph(),))  # type-error: arg-type
    OutlineLabel("Caption", [TextRun("Caption")])  # type-error: arg-type


def bad_background() -> None:
    from opendoc_model import BackgroundPaint, GradientStop

    GradientStop("half")  # type-error: arg-type
    BackgroundPaint("native")  # type-error: arg-type
