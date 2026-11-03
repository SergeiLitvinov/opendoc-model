"""Структурированная диагностика потерь и упрощений при конвертации."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from opendoc_model.result_types import CheckData, ConversionReportData

if TYPE_CHECKING:
    from opendoc_model.limits import DocumentLimits


class IssueSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    LOSS = "loss"
    ERROR = "error"


@dataclass(frozen=True)
class ConversionIssue:
    severity: IssueSeverity
    feature: str
    message: str
    location: str = ""


@dataclass
class ConversionReport:
    output_path: Path
    issues: list[ConversionIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def lossless(self) -> bool:
        return self.success and not any(issue.severity is IssueSeverity.LOSS for issue in self.issues)

    def add(self, severity: IssueSeverity, feature: str, message: str, location: str = "") -> None:
        self.issues.append(ConversionIssue(severity, feature, message, location))

    def to_dict(self) -> ConversionReportData:
        return {
            "success": self.success,
            "lossless": self.lossless,
            "output_path": str(self.output_path),
            "metrics": self.metrics,
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


@dataclass(frozen=True)
class DiagnosticIssue:
    """Machine-readable issue; the message is explanatory, never a parser input."""

    code: str
    severity: IssueSeverity
    message: str
    location: str = ""
    measurement: dict[str, Any] | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not self.code:
            raise ValueError("diagnostic code must be a nonempty string")
        if not isinstance(self.severity, IssueSeverity):
            raise ValueError("diagnostic severity must be IssueSeverity")
        if not isinstance(self.message, str) or not isinstance(self.location, str):
            raise ValueError("diagnostic message and location must be strings")
        if self.measurement is not None and not isinstance(self.measurement, dict):
            raise ValueError("diagnostic measurement must be a dictionary or None")
        if self.reason is not None and (not isinstance(self.reason, str) or not self.reason):
            raise ValueError("diagnostic reason must be a nonempty string or None")

    @property
    def feature(self) -> str:
        """Compatibility view used by existing quality policies."""
        return self.code


@dataclass
class CheckResult:
    """A model check result without a filesystem destination.

    Success means no ERROR; lossless additionally means no LOSS. Neither flag
    proves unrequested or unavailable measurements. Existing policies can use
    add/metrics/issues, and structured policy measurements are snapshotted.
    """

    issues: list[DiagnosticIssue] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return not any(issue.severity is IssueSeverity.ERROR for issue in self.issues)

    @property
    def lossless(self) -> bool:
        return self.success and not any(issue.severity is IssueSeverity.LOSS for issue in self.issues)

    def add(self, severity: IssueSeverity, feature: str, message: str, location: str = "") -> None:
        """Accept the legacy policy sink interface, preserving machine reasons."""
        key = {
            "quality-budget": "quality_gate",
            "text-quality": "text_quality_gate",
            "text-edits": "text_quality_gate",
            "object-quality-budget": "object_quality_gate",
            "formula-quality": "formula_quality_gate",
            "emphasis-quality": "emphasis_quality_gate",
        }.get(feature)
        measurement = self.metrics.get(key) if key is not None else None
        reason = measurement.get("reason") if isinstance(measurement, dict) else None
        if feature == "quality-budget":
            reason = "budget-exceeded"
        self.issues.append(DiagnosticIssue(feature, severity, message, location, deepcopy(measurement), reason))

    def to_dict(self, *, limits: DocumentLimits | None = None) -> CheckData:
        """Return an independent, bounded JSON payload (opendoc_model.check v1)."""
        from opendoc_model._json_validation import _json_tree
        from opendoc_model.limits import _resolve_limits

        if not isinstance(self.issues, list) or any(not isinstance(issue, DiagnosticIssue) for issue in self.issues):
            raise ValueError("issues must be a list of DiagnosticIssue")
        if not isinstance(self.metrics, dict):
            raise ValueError("metrics must be a dictionary")
        payload: CheckData = {
            "format": "opendoc.check",
            "version": 1,
            "success": self.success,
            "lossless": self.lossless,
            "metrics": self.metrics,
            "issues": [
                {
                    "code": issue.code,
                    "severity": issue.severity.value,
                    "message": issue.message,
                    "location": issue.location,
                    "measurement": issue.measurement,
                    "reason": issue.reason,
                }
                for issue in self.issues
            ],
        }
        _json_tree(payload, "$", _resolve_limits(limits))
        return deepcopy(payload)


class _DiagnosticError(ValueError):
    """Internal boundary error carrying the original location without parsing."""

    def __init__(self, location: str, message: str, code: str = "json.invalid") -> None:
        super().__init__(f"{location}: {message}" if location else message)
        self.location = location
        self.message = message
        self.code = code


__all__ = ["CheckResult", "DiagnosticIssue", "ConversionIssue", "ConversionReport", "IssueSeverity"]
