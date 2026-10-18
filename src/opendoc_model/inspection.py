"""Структурная инспекция документов и промежуточной модели."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from opendoc_model._validation import _model_issues
from opendoc_model.diagnostics import ConversionIssue, IssueSeverity
from opendoc_model.document_model import (
    Box,
    DocumentModel,
    Footnote,
    Formula,
    Image,
    PageSettings,
    Paragraph,
    Resource,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
)
from opendoc_model.emphasis_quality import EmphasisInventory
from opendoc_model.footnotes import _compare_notes, _note_content_available, _note_inventory
from opendoc_model.limits import DocumentLimits, _resolve_limits
from opendoc_model.lists import _list_inventory_valid, iter_list_numbers
from opendoc_model.object_inventory import OBJECT_INVENTORY_SCOPE, _inventory_parent, _object_entry
from opendoc_model.object_matching import MatchingLimits, _match_objects, _MatchingBudget, _MatchingLimitError
from opendoc_model.references import _compare_references, _reference_inventory
from opendoc_model.result_types import ComparisonData, InspectionData
from opendoc_model.text_flow import TextFlowFingerprint
from opendoc_model.traversal import SECTION_CONTENT_FIELDS, Element, NodeLocation, _references_at, _walk_locations

_MODEL_METRICS_SCOPE = "model-structural-metrics-v1"


@dataclass
class DocumentInspection:
    source_path: Path | None
    source_format: str
    metadata: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)
    pages: list[dict[str, Any]] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    package_parts: list[dict[str, Any]] = field(default_factory=list)
    fonts: dict[str, int] = field(default_factory=dict)
    formula_formats: dict[str, int] = field(default_factory=dict)
    objects: list[dict[str, Any]] = field(default_factory=list)
    issues: list[ConversionIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity in {IssueSeverity.WARNING, IssueSeverity.LOSS} for issue in self.issues)

    def add(self, severity: IssueSeverity, feature: str, message: str, location: str = "") -> None:
        self.issues.append(ConversionIssue(severity, feature, message, location))

    def to_dict(self) -> InspectionData:
        return {
            "valid": self.valid,
            "source_path": str(self.source_path) if self.source_path is not None else None,
            "source_format": self.source_format,
            "metadata": _json_safe(self.metadata),
            "metrics": self.metrics,
            "pages": self.pages,
            "resources": self.resources,
            "package_parts": self.package_parts,
            "fonts": self.fonts,
            "formula_formats": self.formula_formats,
            "objects": self.objects,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "feature": issue.feature,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


@dataclass
class DocumentComparison:
    source: DocumentInspection
    target: DocumentInspection
    retention: dict[str, dict[str, float | int | None]]
    page_geometry: list[dict[str, Any]]
    geometry_summary: dict[str, float | int | None]
    resource_comparison: dict[str, Any]
    package_comparison: dict[str, Any]
    font_comparison: dict[str, Any]
    matching_resource_hashes: int
    matching_package_part_hashes: int
    object_diff: dict[str, Any] = field(default_factory=dict)
    issues: list[ConversionIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return self.source.valid and self.target.valid

    @property
    def has_losses(self) -> bool:
        return any(issue.severity is IssueSeverity.LOSS for issue in self.issues)

    def to_dict(self) -> ComparisonData:
        return {
            "valid": self.valid,
            "has_losses": self.has_losses,
            "retention": self.retention,
            "page_geometry": self.page_geometry,
            "geometry_summary": self.geometry_summary,
            "resource_comparison": self.resource_comparison,
            "package_comparison": self.package_comparison,
            "font_comparison": self.font_comparison,
            "matching_resource_hashes": self.matching_resource_hashes,
            "matching_package_part_hashes": self.matching_package_part_hashes,
            "object_diff": self.object_diff,
            "issues": [
                {
                    "severity": issue.severity.value,
                    "feature": issue.feature,
                    "message": issue.message,
                    "location": issue.location,
                }
                for issue in self.issues
            ],
        }


def compare_inspections(
    source: DocumentInspection, target: DocumentInspection, *, matching_limits: MatchingLimits | None = None
) -> DocumentComparison:
    """Сравнить структурную сохранность двух проинспектированных документов."""

    matching_budget = _MatchingBudget(matching_limits)
    source_metrics = _quality_metrics(source)
    target_metrics = _quality_metrics(target)
    note_content_available = _note_content_available(source.metadata, target.metadata)
    retention: dict[str, dict[str, float | int | None]] = {}
    issues: list[ConversionIssue] = []
    for name in source_metrics:
        before = source_metrics[name]
        after = target_metrics[name]
        if before is None or after is None or not note_content_available:
            retention[name] = {"source": before, "target": after, "delta": None, "ratio": None}
            continue
        ratio = 1.0 if before == 0 else min(after / before, 1.0)
        retention[name] = {
            "source": before,
            "target": after,
            "delta": after - before,
            "ratio": round(ratio, 4),
        }
        if after < before:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    f"retention-{name}",
                    f"{name}: retained {after} of {before}",
                )
            )

    inventories_available = all(
        side.valid and side.metadata.get("model_metrics_scope") == _MODEL_METRICS_SCOPE for side in (source, target)
    )
    page_geometry, geometry_summary, geometry_issues = _compare_page_geometry(
        source.pages, target.pages, available=inventories_available
    )
    issues.extend(geometry_issues)
    resource_comparison, resource_issues = _compare_resources(source.resources, target.resources, available=inventories_available)
    issues.extend(resource_issues)
    package_comparison, package_issues = _compare_resources(
        source.package_parts, target.package_parts, available=inventories_available
    )
    issues.extend(
        ConversionIssue(issue.severity, "package-part-loss", issue.message.replace("resource", "package part"))
        for issue in package_issues
    )
    font_comparison, font_issues = _compare_fonts(
        source.fonts, target.fonts, available=inventories_available and note_content_available
    )
    issues.extend(font_issues)
    scope = source.metadata.get("object_inventory_scope")
    object_diff, object_issues = _compare_objects(
        source.objects,
        target.objects,
        available=source.valid
        and target.valid
        and bool(scope)
        and scope == target.metadata.get("object_inventory_scope")
        and note_content_available,
        matching_budget=matching_budget,
    )
    issues.extend(object_issues)
    references, reference_issues = _compare_references(
        source.metadata.get("semantic_references"),
        target.metadata.get("semantic_references"),
        source.valid and target.valid,
        matching_budget=matching_budget,
    )
    object_diff["references"] = references
    issues.extend(reference_issues)
    notes, note_issues = _compare_notes(
        source.metadata.get("semantic_footnotes"),
        target.metadata.get("semantic_footnotes"),
        source.valid and target.valid,
        matching_budget=matching_budget,
    )
    object_diff["footnotes"] = notes
    issues.extend(note_issues)
    return DocumentComparison(
        source=source,
        target=target,
        retention=retention,
        page_geometry=page_geometry,
        geometry_summary=geometry_summary,
        resource_comparison=resource_comparison,
        package_comparison=package_comparison,
        font_comparison=font_comparison,
        matching_resource_hashes=resource_comparison["exact_hash_matches"],
        matching_package_part_hashes=package_comparison["exact_hash_matches"],
        object_diff=object_diff,
        issues=issues,
    )


def _compare_objects(
    source_objects: list[dict[str, Any]],
    target_objects: list[dict[str, Any]],
    *,
    available: bool = True,
    matching_budget: _MatchingBudget | None = None,
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    """Compare matched occurrences; location-only matches are explicitly heuristic."""
    if not available:
        return {
            "source_count": len(source_objects),
            "target_count": len(target_objects),
            "available": False,
            "retained": [],
            "changed": [],
            "lost": [],
            "added": [],
            "retention_ratio": None,
            "headings_available": False,
            "changed_headings": None,
            "lists_available": False,
            "changed_list_items": None,
            "list_numbers_available": False,
            "changed_list_numbers": None,
            "recommendations": [],
        }, []
    try:
        matches, lost, added = _match_objects(source_objects, target_objects, matching_budget or _MatchingBudget())
    except _MatchingLimitError as error:
        result, _ = _compare_objects(source_objects, target_objects, available=False)
        result.update(reason="matching-budget-exceeded", matching_budget=error.measurement)
        return result, [ConversionIssue(IssueSeverity.INFO, "object-matching-unavailable", str(error), "objects")]
    lists_available = all(
        "list_item" in item and _list_inventory_valid(item["list_item"])
        for item in (*source_objects, *target_objects)
        if item.get("type") == "paragraph"
    )
    list_numbers_available = lists_available and all(
        "list_number" in item
        and (
            type(item["list_number"]) is int and item["list_number"] > 0
            if item["list_item"] is not None and item["list_item"]["kind"] == "ordered"
            else item["list_number"] is None
        )
        for item in (*source_objects, *target_objects)
        if item.get("type") == "paragraph"
    )
    headings_available = all(
        "heading" in item and (item["heading"] is None or type(item["heading"]) is int and 1 <= item["heading"] <= 9)
        for item in (*source_objects, *target_objects)
        if item.get("type") == "paragraph"
    )
    from opendoc_model.text_colors import _text_colors_valid

    colors_available = all(
        "text_colors" in item and _text_colors_valid(item["text_colors"])
        for item in (*source_objects, *target_objects)
        if item.get("type") == "paragraph"
    )
    from opendoc_model.spacing import _line_spacing_valid

    line_spacing_available = all(
        "line_spacing" in item and _line_spacing_valid(item["line_spacing"])
        for item in (*source_objects, *target_objects)
        if item.get("type") == "paragraph"
    )
    retained: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for match in matches:
        before, after = match["source"], match["target"]
        color_changed = (
            colors_available
            and before.get("type") == "paragraph"
            and isinstance(before.get("text_hash"), str)
            and before.get("text_hash") == after.get("text_hash")
            and "text_colors" in before
            and "text_colors" in after
            and before["text_colors"] != after["text_colors"]
        )
        changes = [name for name in ("content_hash", "geometry", "style_id", "location") if before.get(name) != after.get(name)]
        if color_changed:
            changes.append("text_colors")
        if (
            before.get("type") == "paragraph"
            and _line_spacing_valid(before.get("line_spacing"))
            and _line_spacing_valid(after.get("line_spacing"))
            and before["line_spacing"] != after["line_spacing"]
        ):
            changes.append("line_spacing")
        for owner, spacing_field in (("table", "table_indent"), ("paragraph", "tab_stops")):
            if (
                before.get("type") == owner
                and spacing_field in before
                and spacing_field in after
                and before[spacing_field] != after[spacing_field]
            ):
                changes.append(spacing_field)
        if before.get("type") == "table" and "table_borders" in before and "table_borders" in after:
            if before["table_borders"] != after["table_borders"]:
                changes.append("table_borders")
        if before.get("type") == "table" and "preferred_widths" in before and "preferred_widths" in after:
            if before["preferred_widths"] != after["preferred_widths"]:
                changes.append("preferred_widths")
        if before.get("type") == "table" and "table_semantics" in before and "table_semantics" in after:
            if before["table_semantics"] != after["table_semantics"]:
                changes.append("table_semantics")
        if headings_available and before.get("type") == "paragraph" and before["heading"] != after["heading"]:
            changes.append("heading")
        if lists_available and before.get("type") == "paragraph":
            if before["list_item"] != after["list_item"]:
                changes.append("list_item")
            if list_numbers_available and before["list_number"] != after["list_number"]:
                changes.append("list_number")
        entry = {**match, "identity": f"occurrence:{match['source_index']}", "type": before.get("type")}
        if before.get("text_hash") is not None and after.get("text_hash") is not None:
            if before["text_hash"] != after["text_hash"]:
                entry["text_change"] = {
                    "source_characters": before["text_characters"],
                    "target_characters": after["text_characters"],
                    "net_character_reduction": max(0, before["text_characters"] - after["text_characters"]),
                }
                if not changes:
                    changes.append("text")
        if changes:
            entry["changes"] = changes
            changed.append(entry)
        else:
            retained.append(entry)
    recommendations = []
    if lost:
        recommendations.append(
            {
                "code": "restore-lost-objects",
                "message": "Проверьте объекты без совпадения: при необходимости восстановите их или добавьте визуальную копию.",
                "locations": [item.get("location") for item in lost],
            }
        )
    geometry_changed = [item for item in changed if "geometry" in item["changes"]]
    if geometry_changed:
        recommendations.append(
            {
                "code": "review-object-geometry",
                "message": "Сверьте расположение и размеры объектов с исходным документом.",
                "locations": [item["source"].get("location") for item in geometry_changed],
            }
        )
    issues = [
        ConversionIssue(
            IssueSeverity.LOSS,
            "object-loss",
            "Structural object has no match in the target inventory",
            str(item.get("location") or ""),
        )
        for item in lost
    ]
    for item in changed:
        if "line_spacing" in item["changes"]:
            from opendoc_model.spacing import _line_spacing_removed

            removed = _line_spacing_removed(item["source"]["line_spacing"], item["target"]["line_spacing"])
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                    "line-spacing-loss" if removed else "line-spacing-change",
                    "Line spacing declaration lost" if removed else "Line spacing declaration changed",
                    item["source"]["location"],
                )
            )
        if "text_colors" in item["changes"]:
            from opendoc_model.text_colors import _text_colors_removed

            removed = _text_colors_removed(item["source"]["text_colors"], item["target"]["text_colors"])
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                    "text-color-loss" if removed else "text-color-change",
                    "Text color declaration lost" if removed else "Text color declaration changed",
                    item["source"]["location"],
                )
            )
        for spacing_field, feature in (("table_indent", "table-indent"), ("tab_stops", "tab-stops")):
            if spacing_field in item["changes"]:
                from opendoc_model.spacing import _spacing_removed

                removed = _spacing_removed(item["source"][spacing_field], item["target"][spacing_field], spacing_field)
                issues.append(
                    ConversionIssue(
                        IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                        feature + ("-loss" if removed else "-change"),
                        "Spacing declaration removed or suppressed" if removed else "Spacing declaration changed",
                        item["source"]["location"],
                    )
                )
        if "table_borders" in item["changes"]:
            from opendoc_model.table_borders import _borders_removed

            removed = _borders_removed(item["source"]["table_borders"], item["target"]["table_borders"])
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                    "table-border-loss" if removed else "table-border-change",
                    "Table/cell border declaration removed" if removed else "Table/cell border declaration changed",
                    item["source"]["location"],
                )
            )
        if "table_semantics" in item["changes"]:
            source_semantics, target_semantics = item["source"]["table_semantics"], item["target"]["table_semantics"]
            removed = _table_semantics_removed(source_semantics, target_semantics)
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                    "table-semantics-loss" if removed else "table-semantics-change",
                    "Table semantic declaration removed" if removed else "Table semantic declaration changed",
                    item["source"]["location"],
                )
            )
        if "preferred_widths" in item["changes"]:
            before_widths, after_widths = item["source"]["preferred_widths"], item["target"]["preferred_widths"]
            removed = before_widths["table"] is not None and after_widths["table"] is None
            for row_index, row in enumerate(before_widths["cells"]):
                for column_index, width in enumerate(row):
                    target_rows = after_widths["cells"]
                    if width is not None and (
                        row_index >= len(target_rows)
                        or column_index >= len(target_rows[row_index])
                        or target_rows[row_index][column_index] is None
                    ):
                        removed = True
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                    "table-width-loss" if removed else "table-width-change",
                    "Preferred table/cell width removed" if removed else "Preferred table/cell width changed",
                    item["source"]["location"],
                )
            )
    if headings_available:
        for item in changed:
            if "heading" in item["changes"] and item["source"].get("heading") is not None:
                removed = item["target"].get("heading") is None
                issues.append(
                    ConversionIssue(
                        IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                        "heading-loss" if removed else "heading-change",
                        "Heading role removed" if removed else "Heading level changed",
                        item["source"]["location"],
                    )
                )
    if lists_available:
        for item in changed:
            if "list_number" in item["changes"] and "list_item" not in item["changes"]:
                issues.append(
                    ConversionIssue(
                        IssueSeverity.WARNING, "list-number-change", "Derived list number changed", item["source"]["location"]
                    )
                )
            if "list_item" in item["changes"] and item["source"].get("list_item") is not None:
                removed = item["target"].get("list_item") is None
                issues.append(
                    ConversionIssue(
                        IssueSeverity.LOSS if removed else IssueSeverity.WARNING,
                        "list-loss" if removed else "list-change",
                        "List membership removed" if removed else "List membership changed",
                        item["source"]["location"],
                    )
                )
    return {
        "lists_available": lists_available,
        "changed_list_items": sum("list_item" in item["changes"] for item in changed) if lists_available else None,
        "list_numbers_available": list_numbers_available,
        "changed_list_numbers": sum("list_number" in item["changes"] for item in changed) if list_numbers_available else None,
        "headings_available": headings_available,
        "changed_headings": sum("heading" in item["changes"] for item in changed) if headings_available else None,
        "text_colors_available": colors_available,
        "line_spacing_available": line_spacing_available,
        "source_count": len(source_objects),
        "target_count": len(target_objects),
        "available": True,
        "retained": retained,
        "changed": changed,
        "lost": lost,
        "added": added,
        "retention_ratio": round(_ratio(len(retained) + len(changed), len(source_objects)), 4),
        "recommendations": recommendations,
        "content_changes": {
            "changed_text_objects": sum("text_change" in item for item in changed),
            "net_character_reduction": sum(item.get("text_change", {}).get("net_character_reduction", 0) for item in changed),
            "basis": "matched_object_text_lengths_not_deleted_characters",
        },
        "matching": {
            "heuristic": sum(item["match_basis"] == "location" for item in matches),
            "ambiguous": sum(item["ambiguous"] for item in matches),
        },
    }, issues


def _table_semantics_removed(source: dict[str, Any], target: dict[str, Any]) -> bool:
    before, after = source["table"], target["table"]
    if before is not None:
        if after is None or not set(before["caption_ids"]) <= set(after["caption_ids"]):
            return True
        for name in ("row_groups", "column_groups"):
            if not {value["id"] for value in before[name]} <= {value["id"] for value in after[name]}:
                return True
    target_rows = {row["record"]["id"]: row["record"] for row in target["rows"] if row["record"] is not None}
    target_cells = {cell["id"]: cell for row in target["rows"] for cell in row["cells"] if cell is not None}
    for row in source["rows"]:
        record = row["record"]
        if record is not None:
            next_row = target_rows.get(record["id"])
            if next_row is None or record["group_id"] is not None and next_row["group_id"] is None:
                return True
        for cell in row["cells"]:
            if cell is None:
                continue
            next_cell = target_cells.get(cell["id"])
            if next_cell is None:
                return True
            if cell["role"] == "header" and next_cell["role"] != "header":
                return True
            if cell["scope"] is not None and next_cell["scope"] is None:
                return True
            if not set(cell["headers"]) <= set(next_cell["headers"]):
                return True
    return False


def _compare_page_geometry(
    source_pages: list[dict[str, Any]],
    target_pages: list[dict[str, Any]],
    *,
    tolerance_pt: float = 0.5,
    available: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, float | int | None], list[ConversionIssue]]:
    issues: list[ConversionIssue] = []
    summary: dict[str, float | int | None]
    if not available or not source_pages or not target_pages:
        if available and source_pages and not target_pages:
            issues.append(
                ConversionIssue(
                    IssueSeverity.WARNING,
                    "page-geometry-n-a",
                    "target has no page geometry (pagination-less format, e.g. HTML/LaTeX)",
                    "pages",
                )
            )
        elif available and target_pages and not source_pages:
            issues.append(
                ConversionIssue(
                    IssueSeverity.WARNING,
                    "page-geometry-n-a",
                    "source has no page geometry",
                    "pages",
                )
            )
        summary = {
            "available": False,
            "source_pages": len(source_pages),
            "target_pages": len(target_pages),
            "compared_pages": 0,
            "missing_pages": abs(len(source_pages) - len(target_pages)) if available else None,
            "tolerance_pt": tolerance_pt,
            "max_dimension_error_pt": None,
            "mean_dimension_error_pt": None,
            "rms_dimension_error_pt": None,
            "max_margin_error_pt": None,
            "mean_margin_error_pt": None,
            "rms_margin_error_pt": None,
        }
        return [], summary, issues
    page_geometry: list[dict[str, Any]] = []
    dimension_errors: list[float] = []
    margin_errors: list[float] = []
    missing_pages = 0
    margin_names = ("margin_top_pt", "margin_right_pt", "margin_bottom_pt", "margin_left_pt")
    for index in range(max(len(source_pages), len(target_pages))):
        source_page = source_pages[index] if index < len(source_pages) else None
        target_page = target_pages[index] if index < len(target_pages) else None
        if source_page is None or target_page is None:
            missing_pages += 1
            page_geometry.append(
                {
                    "index": index,
                    "source": source_page,
                    "target": target_page,
                    "same_size": False,
                    "same_margins": False,
                    "same_geometry": False,
                }
            )
            issues.append(
                ConversionIssue(
                    IssueSeverity.WARNING if source_page is None else IssueSeverity.LOSS,
                    "page-geometry",
                    f"page {index + 1} exists only in {'target' if source_page is None else 'source'}",
                    f"pages[{index}]",
                )
            )
            continue
        width_delta = float(target_page["width_pt"]) - float(source_page["width_pt"])
        height_delta = float(target_page["height_pt"]) - float(source_page["height_pt"])
        dimension_error = math.hypot(width_delta, height_delta)
        max_dimension_error = max(abs(width_delta), abs(height_delta))
        dimension_errors.append(dimension_error)
        same_size = max_dimension_error <= tolerance_pt
        margin_deltas = {
            name.removesuffix("_pt") + "_delta_pt": float(target_page[name]) - float(source_page[name])
            for name in margin_names
            if name in source_page and name in target_page
        }
        current_margin_errors = [abs(float(value)) for value in margin_deltas.values()]
        margin_errors.extend(current_margin_errors)
        max_margin_error = max(current_margin_errors, default=0.0)
        same_margins = not margin_deltas or max_margin_error <= tolerance_pt
        geometry = {
            "index": index,
            "source_width_pt": source_page["width_pt"],
            "source_height_pt": source_page["height_pt"],
            "target_width_pt": target_page["width_pt"],
            "target_height_pt": target_page["height_pt"],
            "width_delta_pt": round(width_delta, 3),
            "height_delta_pt": round(height_delta, 3),
            "dimension_error_pt": round(dimension_error, 3),
            "max_dimension_error_pt": round(max_dimension_error, 3),
            "same_size": same_size,
            "margin_deltas": {name: round(delta, 3) for name, delta in margin_deltas.items()},
            "max_margin_error_pt": round(max_margin_error, 3),
            "same_margins": same_margins,
            "same_geometry": same_size and same_margins,
        }
        page_geometry.append(geometry)
        if not same_size:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    "page-geometry",
                    f"page {index + 1} size changed by {width_delta:.2f} x {height_delta:.2f} pt",
                    f"pages[{index}]",
                )
            )
        if not same_margins:
            issues.append(
                ConversionIssue(
                    IssueSeverity.LOSS,
                    "page-margins",
                    f"page {index + 1} margins changed by up to {max_margin_error:.2f} pt",
                    f"pages[{index}]",
                )
            )
    summary = {
        "available": True,
        "source_pages": len(source_pages),
        "target_pages": len(target_pages),
        "compared_pages": min(len(source_pages), len(target_pages)),
        "missing_pages": missing_pages,
        "tolerance_pt": tolerance_pt,
        "max_dimension_error_pt": round(max(dimension_errors, default=0.0), 3),
        "mean_dimension_error_pt": round(_mean(dimension_errors), 3),
        "rms_dimension_error_pt": round(_rms(dimension_errors), 3),
        "max_margin_error_pt": round(max(margin_errors, default=0.0), 3),
        "mean_margin_error_pt": round(_mean(margin_errors), 3),
        "rms_margin_error_pt": round(_rms(margin_errors), 3),
    }
    return page_geometry, summary, issues


def _compare_resources(
    source_resources: list[dict[str, Any]],
    target_resources: list[dict[str, Any]],
    *,
    available: bool = True,
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    inventories_available = available
    available = available and all(item.get("sha256") for item in (*source_resources, *target_resources))
    source_hashes = Counter(item["sha256"] for item in source_resources if item.get("sha256"))
    target_hashes = Counter(item["sha256"] for item in target_resources if item.get("sha256"))
    matched_hashes = source_hashes & target_hashes
    exact_matches = sum(matched_hashes.values())
    remaining_targets = target_hashes.copy()
    lost_resources = []
    for item in source_resources:
        digest = item.get("sha256")
        if digest and remaining_targets[digest] > 0:
            remaining_targets[digest] -= 1
        else:
            if available:
                lost_resources.append(_resource_identity(item))
    remaining_sources = source_hashes.copy()
    added_resources = []
    for item in target_resources:
        digest = item.get("sha256")
        if digest and remaining_sources[digest] > 0:
            remaining_sources[digest] -= 1
        else:
            if available:
                added_resources.append(_resource_identity(item))
    source_by_id = {identifier: item for item in source_resources if (identifier := item.get("id"))}
    target_by_id = {identifier: item for item in target_resources if (identifier := item.get("id"))}
    changed_ids = [
        {
            "id": resource_id,
            "source_sha256": source_by_id[resource_id].get("sha256"),
            "target_sha256": target_by_id[resource_id].get("sha256"),
        }
        for resource_id in sorted(source_by_id.keys() & target_by_id.keys())
        if source_by_id[resource_id].get("sha256")
        and target_by_id[resource_id].get("sha256")
        and source_by_id[resource_id]["sha256"] != target_by_id[resource_id]["sha256"]
    ]
    source_bytes = _resource_bytes(source_resources) if inventories_available else None
    target_bytes = _resource_bytes(target_resources) if inventories_available else None
    matched_bytes: int | None = sum(
        int(next(item.get("size_bytes") or 0 for item in source_resources if item.get("sha256") == digest)) * count
        for digest, count in matched_hashes.items()
    )
    if not inventories_available:
        matched_bytes = None
    source_types = Counter(str(item.get("media_type") or "") for item in source_resources)
    target_types = Counter(str(item.get("media_type") or "") for item in target_resources)
    matched_types = sum((source_types & target_types).values())
    comparison = {
        "available": available,
        "source_count": len(source_resources),
        "target_count": len(target_resources),
        "exact_hash_matches": exact_matches,
        "exact_hash_retention_ratio": round(_ratio(exact_matches, len(source_resources)), 4) if available else None,
        "source_bytes": source_bytes,
        "target_bytes": target_bytes,
        "exact_bytes_retained": matched_bytes,
        "exact_byte_retention_ratio": round(_ratio(matched_bytes, source_bytes), 4)
        if available and source_bytes is not None and matched_bytes is not None
        else None,
        "media_type_retention_ratio": round(_ratio(matched_types, len(source_resources)), 4) if available else None,
        "lost_resources": lost_resources,
        "added_resources": added_resources,
        "changed_ids": changed_ids,
        "unmeasured_source_resources": [_resource_identity(item) for item in source_resources if not item.get("sha256")],
        "unmeasured_target_resources": [_resource_identity(item) for item in target_resources if not item.get("sha256")],
    }
    issues = (
        [
            ConversionIssue(
                IssueSeverity.LOSS,
                "resource-loss",
                f"{len(lost_resources)} resource(s) lost or changed; {exact_matches} of {len(source_resources)} hashes retained",
            )
        ]
        if lost_resources
        else []
    )
    return comparison, issues


def _compare_fonts(
    source_fonts: dict[str, int],
    target_fonts: dict[str, int],
    *,
    available: bool = True,
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    source = _normalised_fonts(source_fonts)
    target = _normalised_fonts(target_fonts)
    preserved = source & target
    missing = source - target
    added = target - source
    source_runs = sum(source.values())
    preserved_runs = sum(preserved.values())
    candidates = _font_substitution_candidates(missing, added)
    comparison = {
        "available": available,
        "source_families": dict(sorted(source.items())),
        "target_families": dict(sorted(target.items())),
        "preserved_families": sorted(preserved) if available else None,
        "missing_families": dict(sorted(missing.items())) if available else None,
        "added_families": dict(sorted(added.items())) if available else None,
        "source_runs": source_runs,
        "target_runs": sum(target.values()),
        "preserved_runs": preserved_runs if available else None,
        "exact_run_retention_ratio": round(_ratio(preserved_runs, source_runs), 4) if available else None,
        "possible_substitutions": candidates if available else [],
    }
    issues: list[ConversionIssue] = []
    if not available:
        return comparison, issues
    for family, count in sorted(missing.items()):
        replacements = [item["target"] for item in candidates if item["source"] == family]
        suffix = f"; possible replacement: {', '.join(replacements)}" if replacements else ""
        issues.append(
            ConversionIssue(
                IssueSeverity.LOSS,
                "font-substitution",
                f"font {family!r} missing for {count} run(s){suffix}",
            )
        )
    return comparison, issues


def _resource_bytes(resources: list[dict[str, Any]]) -> int | None:
    if any(type(item.get("size_bytes")) is not int or item["size_bytes"] < 0 for item in resources):
        return None
    return sum(int(item["size_bytes"]) for item in resources)


def _resource_identity(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item.get("id"),
        "kind": item.get("kind"),
        "media_type": item.get("media_type"),
        "size_bytes": item.get("size_bytes"),
        "sha256": item.get("sha256"),
    }


def _normalised_fonts(fonts: dict[str, int]) -> Counter[str]:
    result: Counter[str] = Counter()
    for name, count in fonts.items():
        result[_normalise_font_name(name)] += count
    return result


def _normalise_font_name(name: str) -> str:
    family = re.sub(r"^[A-Z]{6}\+", "", name.strip())
    compact = re.sub(r"[\s_-]+", "", family).casefold()
    aliases = {
        "arial": "Arial",
        "arialmt": "Arial",
        "calibri": "Calibri",
        "calibrilight": "Calibri Light",
        "couriernew": "Courier New",
        "couriernewpsmt": "Courier New",
        "timesnewroman": "Times New Roman",
        "timesnewromanpsmt": "Times New Roman",
    }
    return aliases.get(compact, family.casefold())


def _font_substitution_candidates(missing: Counter[str], added: Counter[str]) -> list[dict[str, Any]]:
    available = added.copy()
    candidates: list[dict[str, Any]] = []
    for source_name, missing_count in missing.most_common():
        remaining = missing_count
        ranked_targets = sorted(available, key=lambda name: (abs(available[name] - missing_count), name))
        for target_name in ranked_targets:
            if remaining <= 0:
                break
            count = min(remaining, available[target_name])
            if count <= 0:
                continue
            candidates.append({"source": source_name, "target": target_name, "runs": count})
            available[target_name] -= count
            remaining -= count
    return candidates


def _ratio(numerator: int, denominator: int) -> float:
    return 1.0 if denominator == 0 else min(numerator / denominator, 1.0)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _rms(values: list[float]) -> float:
    return math.sqrt(sum(value * value for value in values) / len(values)) if values else 0.0


def inspect_document_model(
    document: DocumentModel,
    *,
    source_path: str | Path | None = None,
    source_format: str | None = None,
    limits: DocumentLimits | None = None,
    check_external_sources: bool = True,
) -> DocumentInspection:
    """Собрать структурные метрики и диагностировать модель."""

    path = Path(source_path) if source_path is not None else None
    if type(check_external_sources) is not bool:
        raise ValueError("check_external_sources must be a boolean")
    model_format = document.source_format if isinstance(document.source_format, str) else None
    report = DocumentInspection(path, source_format or model_format or "document-model")
    errors = _model_issues(document, limits)
    if errors:
        for error in errors:
            report.add(IssueSeverity.ERROR, "model-validation", error.message, error.location)
        return report
    report.metadata = dict(document.metadata)
    report.metadata["object_inventory_scope"] = OBJECT_INVENTORY_SCOPE
    report.metadata["model_metrics_scope"] = _MODEL_METRICS_SCOPE
    report.metadata["footnote_content_included"] = bool(document.footnotes)
    text_flow = TextFlowFingerprint()
    emphasis = EmphasisInventory()
    counters: Counter[str] = Counter(
        sections=len(document.sections),
        pages=len(document.sections),
        resources=len(document.resources),
        package_parts=len(document.package.parts) if document.package is not None else 0,
        package_relationships=len(document.package.relationships) if document.package is not None else 0,
        style_definitions=len(document.styles),
    )
    fonts: Counter[str] = Counter()
    formula_formats: Counter[str] = Counter()
    referenced_resources: set[str] = set()
    content_cache: dict[int, str | None] = {}

    from opendoc_model.text_colors import _TextColors

    colors = _TextColors(document, _resolve_limits(limits))
    from opendoc_model.spacing import _LineSpacings

    line_spacings = _LineSpacings(document, _resolve_limits(limits))

    for reference in _walk_locations(document, _resolve_limits(limits)):
        node, location = reference.node, reference.path
        if isinstance(node, Section):
            assert reference.index is not None
            _inspect_page(node.page, reference.index, report)
            for name in SECTION_CONTENT_FIELDS:
                counters[f"{name}_top_level"] += len(getattr(node, name))
            continue
        if isinstance(node, (DocumentModel, Footnote)):
            continue
        section, section_index = reference.section, reference.section_index
        if isinstance(node, TableRow):
            counters["table_rows"] += 1
            continue
        if isinstance(node, TableCell):
            counters["table_cells"] += 1
            counters["merged_cells"] += int(node.row_span > 1 or node.column_span > 1)
            continue
        for resource_reference in _references_at(cast(NodeLocation[Element], reference)):
            referenced_resources.add(resource_reference.resource_id)
        if reference.kind == "block":
            counters["blocks"] += 1
        if not isinstance(node, TextRun):
            report.objects.append(
                _object_entry(
                    node,
                    location,
                    section_index,
                    document.resources,
                    parent=_inventory_parent(reference),
                    text_flow=text_flow,
                    emphasis=emphasis,
                    content_cache=content_cache,
                    limits=limits,
                    colors=colors,
                    line_spacings=line_spacings,
                )
            )
        if isinstance(node, Paragraph):
            counters["paragraphs"] += 1
            counters["styled_paragraphs"] += int(bool(node.style_id))
            counters["numbered_paragraphs"] += int(node.properties.get("numbering_id") is not None)
            _inspect_box(node.box, section.page if section is not None else None, report, location)
        elif isinstance(node, Table):
            counters["tables"] += 1
            _inspect_box(node.box, section.page if section is not None else None, report, location)
        elif isinstance(node, TextRun):
            _inspect_run(node, counters, fonts)
        elif isinstance(node, Formula):
            _inspect_formula(node, location, section.page if section is not None else None, report, counters, formula_formats)
        elif isinstance(node, Image):
            _inspect_image(node, location, section.page if section is not None else None, report, counters)
    numbers = {number.location.path: number.number for number in iter_list_numbers(document, limits=limits)}
    counters["semantic_list_items"] = len(numbers)
    counters["ordered_list_items"] = sum(number is not None for number in numbers.values())
    references = _reference_inventory(document, _resolve_limits(limits))
    report.metadata["semantic_references"] = references
    counters["anchors"] = len(references["anchors"])
    counters["internal_links"] = len(references["links"])
    notes = _note_inventory(document, _resolve_limits(limits))
    report.metadata["semantic_footnotes"] = notes
    counters["footnotes"] = len(notes["notes"])
    counters["semantic_footnote_references"] = len(notes["references"])
    counters["referenced_footnotes"] = len({reference["note_id"] for reference in notes["references"]})
    for entry in report.objects:
        if entry["type"] == "paragraph":
            entry["list_number"] = numbers.get(entry["location"])
    for resource in document.resources.values():
        report.resources.append(_inspect_resource(resource, report, check_external_sources=check_external_sources))
    if document.package is not None:
        report.package_parts = [
            {
                "id": part.name,
                "media_type": part.media_type,
                "size_bytes": len(part.data),
                "sha256": hashlib.sha256(part.data).hexdigest(),
            }
            for part in document.package.parts.values()
        ]
    from opendoc_model.fonts import _font_links

    referenced_resources.update(link.reference.resource_id for link in _font_links(document, _resolve_limits(limits)))
    from opendoc_model.integration import _integration_links

    referenced_resources.update(
        key for domain, key, _ in _integration_links(document, _resolve_limits(limits)) if domain == "resource"
    )
    for resource_id in sorted(set(document.resources) - referenced_resources):
        report.add(IssueSeverity.WARNING, "unused-resource", f"resource {resource_id!r} is not referenced")

    report.metrics = dict(sorted(counters.items()))
    report.metadata["text_flow"] = text_flow.to_dict()
    report.metadata["text_emphasis"] = emphasis.to_dict()
    from opendoc_model.graphics import _scene_unknowns
    from opendoc_model.integration import get_integration

    integration = get_integration(document, limits=limits)
    if integration is not None:
        for index, scene in enumerate(integration.scenes):
            for location, message in _scene_unknowns(scene, f"metadata['opendoc.integration'].data.scenes[{index}]"):
                report.add(IssueSeverity.INFO, "graphics-scope-unknown", message, location)
    report.fonts = dict(fonts.most_common())
    report.formula_formats = dict(sorted(formula_formats.items()))
    return report


def _inspect_page(page: PageSettings, section_index: int, report: DocumentInspection) -> None:
    report.pages.append(
        {
            "index": section_index,
            "width_pt": page.width.pt,
            "height_pt": page.height.pt,
            "margin_top_pt": page.margin_top.pt,
            "margin_right_pt": page.margin_right.pt,
            "margin_bottom_pt": page.margin_bottom.pt,
            "margin_left_pt": page.margin_left.pt,
        }
    )


def _inspect_run(run: TextRun, counters: Counter[str], fonts: Counter[str]) -> None:
    counters["text_runs"] += 1
    counters["characters"] += len(run.text)
    counters["hyperlinks"] += int(bool(run.link or run.properties.get("hyperlink_anchor")))
    counters["internal_hyperlinks"] += int(bool(run.properties.get("hyperlink_anchor")))
    counters["bookmark_starts"] += int(run.properties.get("bookmark_start") is not None)
    counters["bookmark_ends"] += int(run.properties.get("bookmark_end_id") is not None)
    for name, metric in (
        ("footnote_reference_id", "footnote_references"),
        ("endnote_reference_id", "endnote_references"),
        ("field_instruction", "fields"),
    ):
        if run.properties.get(name) is not None:
            counters[metric] += 1
    if run.properties.get("field_complex"):
        counters["complex_fields"] += 1
    if run.style.font_family:
        fonts[run.style.font_family] += 1


def _inspect_formula(
    formula: Formula,
    location: str,
    page: PageSettings | None,
    report: DocumentInspection,
    counters: Counter[str],
    formula_formats: Counter[str],
) -> None:
    counters["formulas"] += 1
    formula_formats[formula.format.value] += 1
    _inspect_box(formula.box, page, report, location)
    if not formula.fallback_text:
        report.add(IssueSeverity.WARNING, "formula-fallback", "formula has no portable fallback text", location)


def _inspect_image(
    image: Image,
    location: str,
    page: PageSettings | None,
    report: DocumentInspection,
    counters: Counter[str],
) -> None:
    counters["images"] += 1
    counters["cropped_images"] += int(image.crop is not None)
    counters["rotated_images"] += int(bool(image.box and image.box.rotation))
    counters["floating_images"] += int(image.properties.get("placement") == "anchor")
    counters["wrap_polygon_images"] += int(bool(image.properties.get("wrap_polygon")))
    _inspect_box(image.box, page, report, location)
    if not image.alt_text:
        report.add(IssueSeverity.WARNING, "image-alt-text", "image has no alternative text", location)


def _inspect_box(box: Box | None, page: PageSettings | None, report: DocumentInspection, location: str) -> None:
    if box is None or page is None:
        return
    if box.x < 0 or box.y < 0:
        report.add(IssueSeverity.WARNING, "element-geometry", "element starts outside the page", location)
    if box.x + box.width > page.width.pt or box.y + box.height > page.height.pt:
        report.add(IssueSeverity.WARNING, "element-geometry", "element extends beyond the page", location)


def _inspect_resource(resource: Resource, report: DocumentInspection, *, check_external_sources: bool = True) -> dict[str, Any]:
    raw = resource.data
    source_exists = None
    if raw is None and resource.source is not None:
        size = None
        digest = None
        if check_external_sources:
            source = Path(resource.source)
            source_exists = source.is_file()
            size = source.stat().st_size if source_exists else 0
            if not source_exists:
                report.add(IssueSeverity.ERROR, "resource", f"resource source does not exist: {source}", resource.id)
    else:
        size = len(raw or b"")
        digest = hashlib.sha256(raw).hexdigest() if raw is not None else None
    return {
        "id": resource.id,
        "kind": resource.kind.value,
        "media_type": resource.media_type,
        "filename": resource.filename,
        "size_bytes": size,
        "sha256": digest,
        "embedded": raw is not None,
        "source_exists": source_exists,
    }


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def _quality_metrics(report: DocumentInspection) -> dict[str, int | None]:
    metrics = report.metrics
    values = {
        "pages": metrics.get("pages", metrics.get("sections", 0)),
        "characters": metrics.get("characters", 0),
        "text_runs": metrics.get("text_runs", 0),
        "images": metrics.get("images", metrics.get("image_occurrences", 0)),
        "cropped_images": metrics.get("cropped_images", 0),
        "rotated_images": metrics.get("rotated_images", 0),
        "floating_images": metrics.get("floating_images", 0),
        "wrap_polygon_images": metrics.get("wrap_polygon_images", 0),
        "tables": metrics.get("tables", 0),
        "formulas": metrics.get("formulas", 0),
        "hyperlinks": metrics.get("hyperlinks", 0),
        "internal_hyperlinks": metrics.get("internal_hyperlinks", 0),
        "bookmark_starts": metrics.get("bookmark_starts", 0),
        "bookmark_ends": metrics.get("bookmark_ends", 0),
        "numbered_paragraphs": metrics.get("numbered_paragraphs", 0),
        "footnote_references": metrics.get("footnote_references", 0),
        "endnote_references": metrics.get("endnote_references", 0),
        "fields": metrics.get("fields", 0),
        "complex_fields": metrics.get("complex_fields", 0),
        "resources": metrics.get("resources", 0),
        "package_parts": metrics.get("package_parts", 0),
    }
    complete = report.metadata.get("model_metrics_scope") == _MODEL_METRICS_SCOPE
    aliases = {"pages": "sections", "images": "image_occurrences"}
    return {
        name: value
        if report.valid and (complete or name in metrics or aliases.get(name) in metrics) and type(value) is int and value >= 0
        else None
        for name, value in values.items()
    }


__all__ = ["DocumentComparison", "DocumentInspection", "compare_inspections", "inspect_document_model"]
