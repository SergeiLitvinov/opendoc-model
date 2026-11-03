"""Budget changed or removed source formulas using reproducible fingerprints."""

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from opendoc_model._xml import _parse_xml, _xml_bytes
from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity
from opendoc_model.document_model import Formula, FormulaFormat
from opendoc_model.footnotes import _note_content_available
from opendoc_model.object_inventory import OBJECT_INVENTORY_SCOPE

if TYPE_CHECKING:
    from opendoc_model.inspection import DocumentComparison

FORMULA_FINGERPRINT_VERSION = "formula-native-tree-v1"


def formula_fingerprint(formula: Formula) -> str | None:
    """Compare supported MathML through OMML; preserve exact LaTeX source."""
    if not isinstance(formula.value, str) or not formula.value or not isinstance(formula.format, FormulaFormat):
        return None
    try:
        _xml_bytes(formula.value)
    except ValueError:
        return None
    if formula.format is FormulaFormat.LATEX:
        content: list[Any] = ["latex", formula.value]
    else:
        try:
            if formula.format is FormulaFormat.MATHML:
                from opendoc_model.mathml import _mathml_to_omml_tree

                root = _mathml_to_omml_tree(formula.value)
            else:
                root = _parse_xml(formula.value)
            namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
            if root.tag == namespace + "oMathPara" and len(root) == 1:
                if root.attrib or (root.text or "").strip() or (root.tail or "").strip():
                    return None
                root = root[0]
            if root.tag != namespace + "oMath":
                return None
            content = ["omml", _tree(root)]
        except (ImportError, ValueError, TypeError, RecursionError, SyntaxError):
            return None
    return hashlib.sha256(json.dumps(content, ensure_ascii=False).encode("utf-8")).hexdigest()


def _tree(node: Any) -> list[Any]:
    """Namespace prefixes and XML indentation are not formula content."""
    namespace = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
    if not isinstance(node.tag, str) or not node.tag.startswith(namespace):
        raise ValueError("Unsupported namespace in OMML")
    if any(not name.startswith(namespace) and name != "{http://www.w3.org/XML/1998/namespace}space" for name in node.attrib):
        raise ValueError("Unsupported attribute namespace in OMML")
    if (node.tail or "").strip():
        raise ValueError("Text outside OMML elements")
    text = node.text or ""
    if node.tag != namespace + "t":
        if text.strip():
            raise ValueError("Text outside OMML tokens")
        text = ""
    return [node.tag, sorted(node.attrib.items()), text, [_tree(child) for child in node if isinstance(child.tag, str)]]


@dataclass(frozen=True)
class FormulaLossPolicy:
    max_changed_formulas: int = 0

    def __post_init__(self) -> None:
        if type(self.max_changed_formulas) is not int or self.max_changed_formulas < 0:
            raise ValueError("max_changed_formulas must be a non-negative integer")

    def evaluate(self, report: ConversionReport | CheckResult, comparison: "DocumentComparison | None") -> bool:
        available = comparison is not None and comparison.valid
        if available and comparison is not None:
            available = _note_content_available(comparison.source.metadata, comparison.target.metadata)
        counts = []
        for side in (comparison.source, comparison.target) if available and comparison is not None else ():
            formulas = [item for item in side.objects if item.get("type") == "formula"]
            available = (
                available
                and side.metadata.get("object_inventory_scope") == OBJECT_INVENTORY_SCOPE
                and all(
                    item.get("formula_fingerprint_version") == FORMULA_FINGERPRINT_VERSION
                    and isinstance(item.get("formula_hash"), str)
                    for item in formulas
                )
            )
            counts.append(Counter(item.get("formula_hash") for item in formulas))
        changed = sum((counts[0] - counts[1]).values()) if available else None
        accepted = available and changed is not None and changed <= self.max_changed_formulas
        report.metrics["formula_quality_gate"] = {
            "basis": FORMULA_FINGERPRINT_VERSION,
            "verified": available,
            "accepted": accepted,
            "max_changed_formulas": self.max_changed_formulas,
            "changed_formulas": changed,
            "source_formulas": sum(counts[0].values()) if counts else None,
            "reason": "accepted" if accepted else "budget-exceeded" if available else "unavailable",
        }
        if not accepted:
            report.add(
                IssueSeverity.ERROR,
                "formula-quality",
                f"Несовпавших или удалённых формул: {changed}; допустимо: {self.max_changed_formulas}."
                if available
                else "Сохранность формул не удалось проверить: нет полного сопоставимого представления. Результат не выдан.",
            )
        return accepted
