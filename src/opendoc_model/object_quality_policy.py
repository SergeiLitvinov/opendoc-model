"""Budget for unmatched recursive model objects with conservative verification."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity
from opendoc_model.object_inventory import OBJECT_INVENTORY_SCOPE

if TYPE_CHECKING:
    from opendoc_model.inspection import DocumentComparison


@dataclass(frozen=True)
class ObjectLossPolicy:
    """Do not treat unknown coverage or ambiguous matches as a passed budget."""

    max_lost_objects: int = 0

    def __post_init__(self) -> None:
        if type(self.max_lost_objects) is not int or self.max_lost_objects < 0:
            raise ValueError("max_lost_objects must be a non-negative integer")

    def evaluate(self, report: ConversionReport | CheckResult, comparison: "DocumentComparison | None") -> bool:
        diff = comparison.object_diff if comparison is not None else {}
        matching = diff.get("matching") or {}
        available = comparison is not None and comparison.valid and diff.get("available") is True
        available = (
            available
            and comparison is not None
            and comparison.source.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
        )
        uncertain = bool(matching.get("heuristic") or matching.get("ambiguous"))
        verified = available and not uncertain
        lost = len(diff["lost"]) if verified else None
        accepted = verified and lost is not None and lost <= self.max_lost_objects
        if verified:
            reason = "accepted" if accepted else "budget-exceeded"
        else:
            reason = "uncertain-matching" if available else "unavailable"
        report.metrics["object_quality_gate"] = {
            "basis": "unmatched_recursive_objects",
            "scope": OBJECT_INVENTORY_SCOPE,
            "max_lost_objects": self.max_lost_objects,
            "lost_objects": lost,
            "verified": verified,
            "accepted": accepted,
            "reason": reason,
            "heuristic_matches": matching.get("heuristic", 0),
            "ambiguous_matches": matching.get("ambiguous", 0),
            "content_changes": diff.get("content_changes"),
        }
        if not accepted:
            message = (
                f"Бюджет объектов превышен: без совпадения {lost}, допустимо {self.max_lost_objects}."
                if verified
                else "Бюджет объектов не удалось проверить: недостаточно данных или сопоставление неоднозначно."
            )
            report.add(IssueSeverity.ERROR, "object-quality-budget", message)
        return accepted
