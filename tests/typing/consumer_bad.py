"""Deliberate static errors; checked but never executed."""

from opendoc_model import (
    CapabilityProfile,
    CheckResult,
    ColorValue,
    ConversionReport,
    DocumentComparison,
    DocumentInspection,
    ListItem,
    MatchingLimits,
    PathCommand,
    SheetCell,
    TextPosition,
    TextRun,
)


def incorrect(
    inspection: DocumentInspection, comparison: DocumentComparison, result: CheckResult, report: ConversionReport
) -> None:
    TextRun(123)  # type-error: arg-type
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
