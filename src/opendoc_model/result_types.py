"""Fixed report envelopes with explicit open JSON records at extension boundaries.

These are annotations for existing dictionaries, not new wire schemas or runtime
validators. Metadata, measurements and format-dependent inventory records retain
their open JSON contract; consumers must validate their own additional keys.
"""

from typing import Any, TypedDict


class ConversionIssueData(TypedDict):
    severity: str
    feature: str
    message: str
    location: str


class DiagnosticData(TypedDict):
    code: str
    severity: str
    message: str
    location: str
    measurement: dict[str, Any] | None
    reason: str | None


class ConversionReportData(TypedDict):
    success: bool
    lossless: bool
    output_path: str
    metrics: dict[str, Any]
    issues: list[ConversionIssueData]


class CheckData(TypedDict):
    format: str
    version: int
    success: bool
    lossless: bool
    metrics: dict[str, Any]
    issues: list[DiagnosticData]


class InspectionData(TypedDict):
    valid: bool
    source_path: str | None
    source_format: str
    metadata: dict[str, Any]
    metrics: dict[str, int]
    pages: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    package_parts: list[dict[str, Any]]
    fonts: dict[str, int]
    formula_formats: dict[str, int]
    objects: list[dict[str, Any]]
    issues: list[ConversionIssueData]


class ComparisonData(TypedDict):
    valid: bool
    has_losses: bool
    retention: dict[str, dict[str, float | int | None]]
    page_geometry: list[dict[str, Any]]
    geometry_summary: dict[str, float | int | None]
    resource_comparison: dict[str, Any]
    package_comparison: dict[str, Any]
    font_comparison: dict[str, Any]
    matching_resource_hashes: int
    matching_package_part_hashes: int
    object_diff: dict[str, Any]
    issues: list[ConversionIssueData]


__all__ = ["CheckData", "ComparisonData", "ConversionIssueData", "ConversionReportData", "DiagnosticData", "InspectionData"]
