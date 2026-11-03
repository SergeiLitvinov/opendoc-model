"""Bounded evidence for bold/italic changes in the inspected text flow."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity
from opendoc_model.footnotes import _note_content_available

if TYPE_CHECKING:
    from opendoc_model.document_model import TextRun
    from opendoc_model.inspection import DocumentComparison

EMPHASIS_VERSION = "model-text-emphasis-v1"
MAX_EMPHASIS_RUNS = 10_000


class EmphasisInventory:
    """Ignore whitespace and run/paragraph boundaries, preserve character order."""

    def __init__(self) -> None:
        self.digest = hashlib.sha256()
        self.characters = 0
        self.runs: list[list[int | bool]] = []
        self.available = True

    def add(self, run: TextRun) -> None:
        text = "".join(character for character in run.text if not character.isspace())
        if not text:
            return
        self.digest.update(text.encode("utf-8"))
        self.characters += len(text)
        style = [bool(run.style.bold), bool(run.style.italic)]
        if self.available:
            if self.runs and self.runs[-1][1:] == style:
                self.runs[-1][0] += len(text)
            elif len(self.runs) < MAX_EMPHASIS_RUNS:
                self.runs.append([len(text), *style])
            else:
                self.available = False
                self.runs.clear()

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": EMPHASIS_VERSION,
            "sha256": self.digest.hexdigest(),
            "characters": self.characters,
            "runs": self.runs if self.available else None,
        }


def _valid(value: dict[str, Any]) -> bool:
    runs = value.get("runs")
    return (
        value.get("version") == EMPHASIS_VERSION
        and isinstance(value.get("sha256"), str)
        and type(value.get("characters")) is int
        and value["characters"] >= 0
        and (
            isinstance(runs, list)
            and len(runs) <= MAX_EMPHASIS_RUNS
            and all(
                isinstance(run, list)
                and len(run) == 3
                and type(run[0]) is int
                and run[0] > 0
                and all(type(flag) is bool for flag in run[1:])
                for run in runs
            )
            and sum(run[0] for run in runs) == value.get("characters")
        )
    )


def _changes(source: list[list[int | bool]], target: list[list[int | bool]]) -> int:
    left, right = iter(source), iter(target)
    a, b = next(left, None), next(right, None)
    changed = 0
    if a is None or b is None:
        return changed
    remaining_a, remaining_b = a[0], b[0]
    while a is not None and b is not None:
        size = min(remaining_a, remaining_b)
        changed += size if a[1:] != b[1:] else 0
        remaining_a -= size
        remaining_b -= size
        if remaining_a == 0:
            a = next(left, None)
            remaining_a = a[0] if a is not None else 0
        if remaining_b == 0:
            b = next(right, None)
            remaining_b = b[0] if b is not None else 0
    return changed


@dataclass(frozen=True)
class EmphasisLossPolicy:
    max_changed_emphasis: int = 0

    def __post_init__(self) -> None:
        if type(self.max_changed_emphasis) is not int or self.max_changed_emphasis < 0:
            raise ValueError("max_changed_emphasis must be a non-negative integer")

    def evaluate(self, report: ConversionReport | CheckResult, comparison: DocumentComparison | None) -> bool:
        source = comparison.source.metadata.get("text_emphasis", {}) if comparison is not None else {}
        target = comparison.target.metadata.get("text_emphasis", {}) if comparison is not None else {}
        available = (
            comparison is not None
            and comparison.valid
            and _note_content_available(comparison.source.metadata, comparison.target.metadata)
            and all(isinstance(value, dict) and _valid(value) for value in (source, target))
            and source["sha256"] == target["sha256"]
            and source["characters"] == target["characters"]
        )
        changed = _changes(source["runs"], target["runs"]) if available else None
        accepted = available and changed is not None and changed <= self.max_changed_emphasis
        report.metrics["emphasis_quality_gate"] = {
            "basis": EMPHASIS_VERSION,
            "verified": available,
            "accepted": accepted,
            "changed_characters": changed,
            "max_changed_emphasis": self.max_changed_emphasis,
            "reason": "accepted" if accepted else "budget-exceeded" if available else "unavailable",
        }
        if not accepted:
            report.add(
                IssueSeverity.ERROR,
                "emphasis-quality",
                f"Символов с изменённым жирным/курсивным выделением: {changed}; допустимо: {self.max_changed_emphasis}."
                if available
                else "Выделение не проверено: текст не сопоставим или представление недоступно. Результат не выдан.",
            )
        return accepted
