"""Проверка бюджета диагностированных потерь результата конвертации."""

from __future__ import annotations

from dataclasses import dataclass

from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity


@dataclass(frozen=True)
class QualityPolicy:
    """Лимит событий LOSS; не подменяет измерение сохранности объектов."""

    max_loss_issues: int = 0

    def __post_init__(self) -> None:
        if type(self.max_loss_issues) is not int or self.max_loss_issues < 0:
            raise ValueError("max_loss_issues must be a non-negative integer")

    def evaluate(self, report: ConversionReport | CheckResult) -> bool:
        losses = [issue for issue in report.issues if issue.severity is IssueSeverity.LOSS]
        accepted = len(losses) <= self.max_loss_issues
        report.metrics["quality_gate"] = {
            "basis": "reported_loss_issues",
            "max_loss_issues": self.max_loss_issues,
            "loss_issues": len(losses),
            "accepted": accepted,
            "visual_score": None,
            "editability_score": None,
        }
        if not accepted and not any(issue.feature == "quality-budget" for issue in report.issues):
            report.add(
                IssueSeverity.ERROR,
                "quality-budget",
                f"Бюджет потерь превышен: {len(losses)} при допустимых {self.max_loss_issues}",
            )
        return accepted
