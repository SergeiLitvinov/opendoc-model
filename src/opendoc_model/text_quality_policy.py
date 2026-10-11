"""Exact preservation of source paragraph text, independent of object identity."""

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity
from opendoc_model.footnotes import _note_content_available
from opendoc_model.object_inventory import OBJECT_INVENTORY_SCOPE
from opendoc_model.text_edit_budget import evaluate_text_edit_budget
from opendoc_model.text_flow import TEXT_FLOW_VERSION
from opendoc_model.text_flow_profile import TEXT_FLOW_PROFILE_KEY, _profiles_compatible

if TYPE_CHECKING:
    from opendoc_model.inspection import DocumentComparison


def _record_profile_scope(report: ConversionReport | CheckResult, metadata: dict[str, Any], available: bool) -> None:
    profile = metadata[TEXT_FLOW_PROFILE_KEY] if available else {}
    report.metrics["text_quality_gate"].update(
        coverage="declared-text-scope", profile=profile.get("profile"), scope=profile.get("scope")
    )


@dataclass(frozen=True)
class TextPreservationPolicy:
    """Check source paragraphs exactly, or the complete whitespace-normalized flow.

    Paragraph order and run segmentation do not affect this test. Splitting or
    joining paragraphs does: this is an exact fingerprint test, not semantic
    similarity or a count of deleted characters. Flow mode permits paragraph
    resegmentation but requires the same word order and disallows additions.
    Formula markup is excluded in both modes.
    """

    mode: str = "paragraphs"
    max_text_edits: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in {"paragraphs", "flow"}:
            raise ValueError("Неизвестный режим проверки текста")
        if self.max_text_edits is not None:
            if type(self.max_text_edits) is not int or self.max_text_edits < 0 or self.mode != "flow":
                raise ValueError("Допуск правок — целое неотрицательное число, применимое только к последовательности текста")

    def evaluate(self, report: ConversionReport | CheckResult, comparison: "DocumentComparison | None") -> bool:
        if self.mode == "flow":
            return self._evaluate_flow(report, comparison)
        available = comparison is not None and comparison.valid
        if available and comparison is not None:
            available = _note_content_available(comparison.source.metadata, comparison.target.metadata)
        if available and comparison is not None:
            available = all(
                side.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
                and all(
                    isinstance(item.get("text_hash"), str)
                    and type(item.get("text_characters")) is int
                    and item["text_characters"] >= 0
                    for item in side.objects
                    if item.get("type") == "paragraph"
                )
                for side in (comparison.source, comparison.target)
            )
        source: Counter[str] = Counter()
        target: Counter[str] = Counter()
        if available and comparison is not None:
            for side, counts in ((comparison.source, source), (comparison.target, target)):
                counts.update(
                    item["text_hash"] for item in side.objects if item.get("type") == "paragraph" and item["text_characters"] > 0
                )
        unmatched = sum((source - target).values()) if available else None
        accepted = available and unmatched == 0
        report.metrics["text_quality_gate"] = {
            "basis": "nonempty_paragraph_text_fingerprints_v1",
            "verified": available,
            "accepted": accepted,
            "source_paragraphs": sum(source.values()) if available else None,
            "unmatched_source_paragraphs": unmatched,
            "reason": "accepted" if accepted else "text-changed-or-removed" if available else "unavailable",
        }
        if not accepted:
            message = (
                f"Текст исходных абзацев изменён или удалён: {unmatched}. "
                "Разделение и объединение абзацев тоже считаются изменением."
                if available
                else "Сохранность текста не удалось проверить: нет сопоставимых данных об абзацах."
            )
            report.add(IssueSeverity.ERROR, "text-quality", message)
        return accepted

    def _evaluate_flow(self, report: ConversionReport | CheckResult, comparison: "DocumentComparison | None") -> bool:
        source = comparison.source.metadata.get("text_flow", {}) if comparison is not None else {}
        target = comparison.target.metadata.get("text_flow", {}) if comparison is not None else {}
        explicit = comparison is not None and any(
            TEXT_FLOW_PROFILE_KEY in side.metadata for side in (comparison.source, comparison.target)
        )
        available = (
            comparison is not None
            and comparison.valid
            and _note_content_available(comparison.source.metadata, comparison.target.metadata)
            and (
                _profiles_compatible(comparison.source.metadata, comparison.target.metadata)
                if explicit
                else all(
                    side.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
                    and isinstance(flow, dict)
                    and flow.get("version") == TEXT_FLOW_VERSION
                    and isinstance(flow.get("sha256"), str)
                    for side, flow in ((comparison.source, source), (comparison.target, target))
                )
            )
        )
        if self.max_text_edits is not None:
            accepted = evaluate_text_edit_budget(report, source, target, available, self.max_text_edits)
            if explicit and comparison is not None:
                _record_profile_scope(report, comparison.source.metadata, available)
            return accepted
        accepted = available and source["sha256"] == target["sha256"]
        report.metrics["text_quality_gate"] = {
            "basis": TEXT_FLOW_VERSION,
            "mode": "flow",
            "verified": available,
            "accepted": accepted,
            "source_characters": source.get("characters") if available else None,
            "target_characters": target.get("characters") if available else None,
            "reason": "accepted" if accepted else "text-flow-changed" if available else "unavailable",
        }
        if explicit and comparison is not None:
            _record_profile_scope(report, comparison.source.metadata, available)
        if not accepted:
            message = (
                "Последовательность текста изменилась после нормализации пробелов и границ абзацев."
                if available
                else ("Сохранность последовательности текста не удалось проверить: нет сопоставимых данных.")
            )
            report.add(IssueSeverity.ERROR, "text-quality", message)
        return accepted


def resolve_text_policy(
    required: bool = False,
    mode: str | None = None,
    max_text_edits: int | None = None,
) -> TextPreservationPolicy | None:
    if max_text_edits is not None and mode is None and not required:
        mode = "flow"
    if required and mode not in {None, "paragraphs"}:
        raise ValueError("Выберите один режим проверки текста: дословные абзацы или последовательность")
    if not required and mode is None:
        return None
    return TextPreservationPolicy(mode if mode is not None else "paragraphs", max_text_edits)
