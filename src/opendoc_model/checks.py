"""In-memory structural checks and comparison through the existing policies."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from dataclasses import replace
from typing import TypeAlias

from opendoc_model._validation import _model_issues
from opendoc_model.diagnostics import CheckResult, ConversionIssue, DiagnosticIssue, IssueSeverity
from opendoc_model.document_model import DocumentModel
from opendoc_model.emphasis_quality import EmphasisLossPolicy
from opendoc_model.extensions import ExtensionSchema, UnknownExtensionPolicy, _check_extensions, _schemas
from opendoc_model.formula_quality_policy import FormulaLossPolicy
from opendoc_model.inspection import DocumentComparison, DocumentInspection, compare_inspections, inspect_document_model
from opendoc_model.limits import DocumentLimits, _quota, _resolve_limits
from opendoc_model.object_matching import MatchingLimits, _MatchingBudget
from opendoc_model.object_quality_policy import ObjectLossPolicy
from opendoc_model.quality_policy import QualityPolicy
from opendoc_model.text_quality_policy import TextPreservationPolicy

CheckPolicy: TypeAlias = QualityPolicy | TextPreservationPolicy | ObjectLossPolicy | FormulaLossPolicy | EmphasisLossPolicy


def _inspect(document: DocumentModel, limits: DocumentLimits) -> tuple[DocumentInspection, list[DiagnosticIssue]]:
    issues = _model_issues(document, limits)
    if issues:
        inspection = DocumentInspection(
            None,
            "document-model",
            issues=[ConversionIssue(issue.severity, "model-validation", issue.message, issue.location) for issue in issues],
        )
        return inspection, issues
    inspection = inspect_document_model(document, limits=limits, check_external_sources=False)
    issues.extend(DiagnosticIssue(issue.feature, issue.severity, issue.message, issue.location) for issue in inspection.issues)
    return inspection, issues


def check_document(
    document: DocumentModel,
    *,
    limits: DocumentLimits | None = None,
    extensions: Iterable[ExtensionSchema] | None = None,
    unknown_extensions: UnknownExtensionPolicy = "error",
) -> CheckResult:
    """Validate and inspect without any filesystem lookup or output path.

    Structural errors have machine codes/paths; invalid models have no metrics.
    Valid external-only resources remain structurally valid with unknown sizes
    and hashes. DocumentLimits exhaustion continues to raise ArtifactLimitError.
    """
    resolved = _resolve_limits(limits)
    if unknown_extensions not in ("error", "preserve"):
        raise ValueError("unknown_extensions must be error or preserve")
    selected = _schemas(extensions, resolved) if extensions is not None else None
    inspection, issues = _inspect(document, resolved)
    metrics = {"inspection": deepcopy(inspection.to_dict())}
    if selected is not None and inspection.valid:
        checked = _check_extensions(document, selected, unknown_extensions, resolved)
        issues.extend(checked.issues)
        metrics.update(deepcopy(checked.metrics))
    return CheckResult(issues, metrics)


def _policies(policies: Iterable[CheckPolicy] | None, limits: DocumentLimits) -> list[CheckPolicy]:
    if policies is None:
        return []
    try:
        iterator = iter(policies)
    except TypeError as error:
        raise ValueError("policies must be an iterable of supported policies") from error
    selected: list[CheckPolicy] = []
    for index, policy in enumerate(iterator):
        if index >= limits.max_nodes:
            _quota("policies", "nodes", limits.max_nodes)
        if not isinstance(
            policy, (QualityPolicy, TextPreservationPolicy, ObjectLossPolicy, FormulaLossPolicy, EmphasisLossPolicy)
        ):
            raise ValueError("unsupported check policy")
        selected.append(policy)
    return selected


def _comparison_issue(issue: ConversionIssue, comparison: DocumentComparison) -> DiagnosticIssue:
    measurement = None
    reason = None
    if issue.feature.endswith("-matching-unavailable"):
        measurement = {
            "object": comparison.object_diff,
            "reference": comparison.object_diff.get("references", {}),
            "footnote": comparison.object_diff.get("footnotes", {}),
        }[issue.feature.removesuffix("-matching-unavailable")]
        reason = measurement.get("reason")
        measurement = measurement.get("matching_budget")
    elif issue.feature.startswith("retention-"):
        measurement = comparison.retention.get(issue.feature.removeprefix("retention-"))
    elif issue.feature.startswith("page-geometry"):
        measurement = comparison.geometry_summary
    elif issue.feature == "resource-loss":
        measurement = comparison.resource_comparison
    elif issue.feature == "package-part-loss":
        measurement = comparison.package_comparison
    elif issue.feature == "font-substitution":
        measurement = comparison.font_comparison
    elif issue.feature == "object-loss":
        measurement = {"available": comparison.object_diff.get("available"), "location": issue.location}
    elif issue.feature.startswith("footnote-"):
        change = next(
            (
                item
                for item in comparison.object_diff.get("footnotes", {}).get("changes", [])
                if item["code"] == issue.feature and item["source"]["location"] == issue.location
            ),
            None,
        )
        if change is not None:
            measurement = {"source": change["source"], "target": change["target"]}
    elif issue.feature.startswith(("anchor-", "internal-link-")):
        change = next(
            (
                item
                for item in comparison.object_diff.get("references", {}).get("changes", [])
                if item["code"] == issue.feature and item["source"]["location"] == issue.location
            ),
            None,
        )
        if change is not None:
            measurement = {"source": change["source"], "target": change["target"]}
    elif issue.feature.startswith(("list-", "heading-")):
        change = next(
            (item for item in comparison.object_diff.get("changed", []) if item["source"].get("location") == issue.location), None
        )
        if change is not None:
            field = "heading" if issue.feature.startswith("heading-") else "list_item"
            measurement = {"source": change["source"].get(field), "target": change["target"].get(field)}
            if field == "list_item":
                measurement.update(
                    source_number=change["source"].get("list_number"), target_number=change["target"].get("list_number")
                )
    elif issue.feature.startswith("table-border-"):
        change = next(
            (item for item in comparison.object_diff.get("changed", []) if item["source"].get("location") == issue.location), None
        )
        if change is not None:
            measurement = {"source": change["source"].get("table_borders"), "target": change["target"].get("table_borders")}
    elif issue.feature.startswith("table-width-"):
        change = next(
            (item for item in comparison.object_diff.get("changed", []) if item["source"].get("location") == issue.location), None
        )
        if change is not None:
            measurement = {"source": change["source"].get("preferred_widths"), "target": change["target"].get("preferred_widths")}
    elif issue.feature.startswith("table-semantics-"):
        change = next(
            (item for item in comparison.object_diff.get("changed", []) if item["source"].get("location") == issue.location), None
        )
        if change is not None:
            measurement = {"source": change["source"].get("table_semantics"), "target": change["target"].get("table_semantics")}
    return DiagnosticIssue(issue.feature, issue.severity, issue.message, issue.location, deepcopy(measurement), reason)


def compare_documents(
    source: DocumentModel,
    target: DocumentModel,
    *,
    policies: Iterable[CheckPolicy] | None = None,
    limits: DocumentLimits | None = None,
    extensions: Iterable[ExtensionSchema] | None = None,
    unknown_extensions: UnknownExtensionPolicy = "error",
    matching_limits: MatchingLimits | None = None,
) -> CheckResult:
    """Compare entire models in memory and apply explicit policies in order.

    No policy is implicit. LOSS differs from ERROR; a selected policy may turn
    loss or unavailable evidence into rejection. Both model issues and complete
    comparison snapshots are retained; reasons are obtained from measurements.
    Existing ConversionReport usage and policy return values remain supported.
    """
    _MatchingBudget(matching_limits)
    resolved = _resolve_limits(limits)
    if unknown_extensions not in ("error", "preserve"):
        raise ValueError("unknown_extensions must be error or preserve")
    schemas = _schemas(extensions, resolved) if extensions is not None else None
    selected = _policies(policies, resolved)
    before, source_issues = _inspect(source, resolved)
    after, target_issues = _inspect(target, resolved)
    extension_metrics = {}
    if schemas is not None:
        for side, model, inspection, model_issues in (
            ("source", source, before, source_issues),
            ("target", target, after, target_issues),
        ):
            if inspection.valid:
                checked = _check_extensions(model, schemas, unknown_extensions, resolved)
                model_issues.extend(checked.issues)
                extension_metrics[side] = checked.metrics["extensions"]
    comparison = compare_inspections(before, after, matching_limits=matching_limits)
    issues = [
        replace(issue, location=f"{side}.{issue.location}" if issue.location else side)
        for side, side_issues in (("source", source_issues), ("target", target_issues))
        for issue in side_issues
    ]
    issues.extend(_comparison_issue(issue, comparison) for issue in comparison.issues)
    for name, measurement in (
        ("resources", comparison.resource_comparison),
        ("package", comparison.package_comparison),
        ("fonts", comparison.font_comparison),
        ("objects", comparison.object_diff),
        ("references", comparison.object_diff.get("references", {})),
        ("footnotes", comparison.object_diff.get("footnotes", {})),
        ("geometry", comparison.geometry_summary),
    ):
        if measurement.get("available") is False:
            reason = "invalid-model" if not comparison.valid else "no-pages" if name == "geometry" else "external-data-not-loaded"
            supplied_reason = measurement.get("reason")
            if isinstance(supplied_reason, str) and supplied_reason:
                reason = supplied_reason
            issues.append(
                DiagnosticIssue(
                    "measurement.unavailable",
                    IssueSeverity.INFO,
                    f"{name} measurement is unavailable",
                    f"comparison.{name}",
                    {
                        "name": name,
                        "available": False,
                        **({"matching_budget": measurement["matching_budget"]} if "matching_budget" in measurement else {}),
                    },
                    reason,
                )
            )
    result = CheckResult(
        issues, deepcopy({"source": before.to_dict(), "target": after.to_dict(), "comparison": comparison.to_dict()})
    )
    if schemas is not None:
        result.metrics["extensions"] = deepcopy(extension_metrics)
    for policy in selected:
        if isinstance(policy, QualityPolicy):
            policy.evaluate(result)
        else:
            policy.evaluate(result, comparison)
    return result


__all__ = ["CheckPolicy", "check_document", "compare_documents"]
