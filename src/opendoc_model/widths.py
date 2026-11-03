"""Inert, format-neutral preferred table widths; no layout is computed."""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from opendoc_model.document_model import Table, TableCell
    from opendoc_model.limits import DocumentLimits


@dataclass(frozen=True)
class WidthMeasure:
    """Preferred width in points or a ratio of an explicitly named containing area.

    Ratios above one are allowed (overflow is a layout decision). Auto and
    unspecified carry no number. Unknown JSON fields are retained in extra.
    """

    kind: Literal["absolute", "relative", "auto", "unspecified"]
    value: float | None = None
    unit: Literal["pt", "ratio"] | None = None
    reference: Literal["content", "table"] | None = None
    extra: dict[str, Any] = field(default_factory=dict, kw_only=True)

    def __post_init__(self) -> None:
        if self.kind not in ("absolute", "relative", "auto", "unspecified"):
            raise ValueError("width.kind: unsupported kind")
        if self.kind in ("absolute", "relative"):
            if not isinstance(self.value, (int, float)) or type(self.value) is bool:
                raise ValueError("width.value: expected nonnegative finite number")
            try:
                finite = math.isfinite(self.value)
            except OverflowError as error:
                raise ValueError("width.value: number is too large") from error
            if not finite or self.value < 0:
                raise ValueError("width.value: expected nonnegative finite number")
            expected = "pt" if self.kind == "absolute" else "ratio"
            if self.unit != expected:
                raise ValueError(f"width.unit: expected {expected}")
            if self.kind == "relative" and self.reference not in ("content", "table"):
                raise ValueError("width.reference: expected content or table")
            if self.kind == "absolute" and self.reference is not None:
                raise ValueError("width.reference: absolute width has no reference")
        elif any(item is not None for item in (self.value, self.unit, self.reference)):
            raise ValueError("width: auto/unspecified cannot carry value, unit or reference")
        if not isinstance(self.extra, dict) or {"kind", "value", "unit", "reference"}.intersection(self.extra):
            raise ValueError("width.extra: expected dictionary without reserved fields")
        self.to_dict()

    def to_dict(self, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
        """Return a bounded independent JSON value, retaining unknown fields."""
        from opendoc_model._json_validation import _json_tree
        from opendoc_model.limits import _resolve_limits

        if not isinstance(self.extra, dict) or {"kind", "value", "unit", "reference"}.intersection(self.extra):
            raise ValueError("width.extra: expected dictionary without reserved fields")
        result = {**self.extra, "kind": self.kind}
        if self.value is not None:
            result["value"] = self.value
        if self.unit is not None:
            result["unit"] = self.unit
        if self.reference is not None:
            result["reference"] = self.reference
        _json_tree(result, "width", _resolve_limits(limits))
        return deepcopy(result)


def _read_width(value: Any, reference: str, limits: DocumentLimits | None = None) -> WidthMeasure | None:
    from opendoc_model._json_validation import _json_tree
    from opendoc_model.limits import _resolve_limits

    resolved = _resolve_limits(limits)
    if value is None:
        return None
    if isinstance(value, WidthMeasure):
        value = value.to_dict(limits=limits)
    _json_tree(value, "preferred_width", resolved)
    if not isinstance(value, dict):
        raise ValueError("preferred_width: expected WidthMeasure or JSON dictionary")
    if "kind" not in value:
        raise ValueError("preferred_width.kind: missing kind")
    known = {"kind", "value", "unit", "reference"}
    measure = WidthMeasure(
        value["kind"],
        value.get("value"),
        value.get("unit"),
        value.get("reference"),
    )
    # The complete JSON was checked against the caller's budget above. Populate
    # its independent unknown fields after primitive constructor validation so
    # the constructor's default budget does not override explicit limits.
    measure.extra.update({key: deepcopy(item) for key, item in value.items() if key not in known})
    if measure.kind == "relative" and measure.reference != reference:
        raise ValueError(f"preferred_width.reference: expected {reference}")
    return measure


def get_preferred_width(node: Table | TableCell, *, limits: DocumentLimits | None = None) -> WidthMeasure | None:
    """Read an independent preference, falling back to legacy cell width_twips.

    Inconsistent duplicate legacy values fail. Missing means unknown preference,
    distinct from an explicit unspecified or zero; actual width is not measured.
    """
    from opendoc_model.document_model import Table, TableCell
    from opendoc_model.properties import TableCellProperties

    if not isinstance(node, (Table, TableCell)):
        raise ValueError("preferred width requires Table or TableCell")
    if not isinstance(node.properties, Mapping):
        raise ValueError("preferred width requires a property mapping")
    measure = _read_width(node.properties.get("preferred_width"), "table" if isinstance(node, TableCell) else "content", limits)
    if isinstance(node, TableCell) and node.properties.get("width_twips") is not None:
        legacy = TableCellProperties(node.properties).get_typed("width_twips", limits=limits)
        try:
            points = legacy / 20
        except OverflowError as error:
            raise ValueError("width_twips: number is too large") from error
        if measure is not None:
            if measure.kind != "absolute" or measure.value != points:
                raise ValueError("preferred_width: conflicts with width_twips")
        else:
            measure = WidthMeasure("absolute", points, "pt")
    return measure


def set_preferred_width(node: Table | TableCell, width: WidthMeasure | None, *, limits: DocumentLimits | None = None) -> None:
    """Set a validated preference atomically; cell legacy duplicate is removed.

    None removes both cell width declarations; unrelated native extensions and
    grid widths are preserved without interpretation.
    """
    from opendoc_model.document_model import Table, TableCell
    from opendoc_model.properties import VersionedProperties

    if not isinstance(node, (Table, TableCell)) or width is not None and not isinstance(width, WidthMeasure):
        raise ValueError("expected Table/TableCell and WidthMeasure or None")
    if not isinstance(node.properties, VersionedProperties):
        raise ValueError("preferred width setter requires a versioned property bag")
    node.properties.set_typed("preferred_width", width, limits=limits)
    if width is None:
        del node.properties["preferred_width"]


__all__ = ["WidthMeasure", "get_preferred_width", "set_preferred_width"]
