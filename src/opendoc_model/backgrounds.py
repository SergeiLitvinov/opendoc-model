"""Inert background/gradient declarations, without native parsing or rendering."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, replace
from typing import Any, Literal, NoReturn, Self

from opendoc_model._integration_codec import _convert, _copy_json
from opendoc_model._json_validation import _json_tree
from opendoc_model.color import ColorValue
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import DocumentModel, Section
from opendoc_model.integration_types import DocumentPage, IntegrationRecord, Paint
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.properties import SectionProperties
from opendoc_model.traversal import _walk_locations
from opendoc_model.units import Point2D

BACKGROUND_PROPERTY = "opendoc.background"


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "background.invalid")


def _number(value: float, path: str, *, unit: bool = False) -> None:
    if type(value) not in (int, float):
        _error(path, "expected finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or unit and not 0 <= value <= 1:
        _error(path, "expected finite number" + (" between 0 and 1" if unit else ""))


def _point(value: Point2D, path: str) -> None:
    if type(value) is not Point2D:
        _error(path, "expected Point2D")
    _number(value.x, path + ".x")
    _number(value.y, path + ".y")


class _PaintRecord(IntegrationRecord):
    def to_dict(self, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
        """Independent typed JSON snapshot, with bounded values and unknown fields."""
        budget = _resolve_limits(limits)
        _guard_model(self, budget)
        encoded: dict[str, Any] = _convert(self, type(self), "background", encode=True)
        _json_tree(encoded, "background", budget)
        _convert(encoded, type(self), "background", encode=False)
        return encoded

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, limits: DocumentLimits | None = None) -> Self:
        budget = _resolve_limits(limits)
        _json_tree(data, "background", budget)
        result: Self = _convert(data, cls, "background", encode=False)
        _guard_model(result, budget)
        return result


@dataclass(frozen=True)
class GradientStop(_PaintRecord):
    """Position in [0,1]; None color is unknown, distinct from transparent color."""

    position: float
    color: ColorValue | None = None

    def __post_init__(self) -> None:
        _number(self.position, "gradient.stop.position", unit=True)
        if self.color is not None and type(self.color) is not ColorValue:
            _error("gradient.stop.color", "expected ColorValue or explicit unknown")


@dataclass(frozen=True)
class LinearGradient(_PaintRecord):
    """Endpoints in explicit paint-local points or relative paint-area coordinates."""

    coordinate_space: Literal["relative", "points"]
    start: Point2D
    end: Point2D

    def __post_init__(self) -> None:
        if self.coordinate_space not in ("relative", "points"):
            _error("gradient.coordinate_space", "expected relative or points")
        _point(self.start, "gradient.start")
        _point(self.end, "gradient.end")
        if self.start == self.end:
            _error("gradient.end", "linear endpoints must differ")


@dataclass(frozen=True)
class RadialGradient(_PaintRecord):
    """Concentric circular radial profile, not an approximation of arbitrary native paths."""

    coordinate_space: Literal["relative", "points"]
    center: Point2D
    radius: float

    def __post_init__(self) -> None:
        if self.coordinate_space not in ("relative", "points"):
            _error("gradient.coordinate_space", "expected relative or points")
        _point(self.center, "gradient.center")
        _number(self.radius, "gradient.radius")
        if self.radius <= 0:
            _error("gradient.radius", "expected positive radius")


@dataclass(frozen=True)
class GradientPaint(_PaintRecord):
    """None means unknown, never a guessed first color, stops or gradient geometry."""

    stops: tuple[GradientStop, ...] | None = None
    linear: LinearGradient | None = None
    radial: RadialGradient | None = None
    opacity: float | None = None
    spread: Literal["pad", "repeat", "reflect"] | None = None
    interpolation: Literal["srgb", "linear-srgb"] | None = None

    def __post_init__(self) -> None:
        if self.stops is not None:
            if type(self.stops) is not tuple or len(self.stops) < 2:
                _error("gradient.stops", "expected at least two ordered stops or unknown")
            previous = -1.0
            for index, stop in enumerate(self.stops):
                if type(stop) is not GradientStop:
                    _error(f"gradient.stops[{index}]", "expected GradientStop")
                stop.__post_init__()
                if stop.position < previous:
                    _error(f"gradient.stops[{index}].position", "positions must be nondecreasing; ties retain order")
                previous = stop.position
        if self.linear is not None and self.radial is not None:
            _error("gradient", "choose at most one geometry; both absent means unknown")
        for name, geometry, expected in (("linear", self.linear, LinearGradient), ("radial", self.radial, RadialGradient)):
            if geometry is not None:
                if type(geometry) is not expected:
                    _error("gradient." + name, "unexpected geometry type")
                geometry.__post_init__()
        if self.opacity is not None:
            _number(self.opacity, "gradient.opacity", unit=True)
        if self.spread not in (None, "pad", "repeat", "reflect"):
            _error("gradient.spread", "unsupported spread")
        if self.interpolation not in (None, "srgb", "linear-srgb"):
            _error("gradient.interpolation", "unsupported interpolation")


@dataclass(frozen=True)
class BackgroundPaint(_PaintRecord):
    """Explicit role: no paint, unknown, existing solid Paint or neutral gradient."""

    kind: Literal["none", "unknown", "solid", "gradient"]
    solid: Paint | None = None
    gradient: GradientPaint | None = None

    def __post_init__(self) -> None:
        if self.kind not in ("none", "unknown", "solid", "gradient"):
            _error("background.kind", "unsupported background role")
        if self.kind == "solid":
            if type(self.solid) is not Paint or self.gradient is not None:
                _error("background.solid", "solid requires only existing Paint")
            _number(self.solid.opacity, "background.solid.opacity", unit=True)
        elif self.kind == "gradient":
            if type(self.gradient) is not GradientPaint or self.solid is not None:
                _error("background.gradient", "gradient requires only GradientPaint")
            self.gradient.__post_init__()
        elif self.solid is not None or self.gradient is not None:
            _error("background", "none/unknown cannot retain paint payloads")


def _read(bag: Mapping[str, Any], limits: DocumentLimits, path: str) -> BackgroundPaint | None:
    raw = bag.get(BACKGROUND_PROPERTY)
    if BACKGROUND_PROPERTY not in bag:
        return None
    _json_tree(raw, path, limits)
    if not isinstance(raw, dict) or raw.get("format") != BACKGROUND_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(path + ".version", "unsupported background version")
    if "data" not in raw:
        _error(path + ".data", "missing background data")
    try:
        return BackgroundPaint.from_dict(raw["data"], limits=limits)
    except _DiagnosticError as error:
        raise _DiagnosticError(path + ".data." + error.location, error.message, "background.invalid") from error


def _updated(bag: Mapping[str, Any], value: BackgroundPaint | None, limits: DocumentLimits, path: str) -> dict[str, Any]:
    previous = _read(bag, limits, path)
    if BACKGROUND_PROPERTY in bag and previous is None:
        _error(path, "background key contains opaque data")
    result: dict[str, Any] = _copy_json(dict(bag), path)
    if value is None:
        result.pop(BACKGROUND_PROPERTY, None)
    else:
        if type(value) is not BackgroundPaint:
            _error(path, "expected BackgroundPaint or None")
        envelope = result.get(BACKGROUND_PROPERTY, {})
        envelope.update(format=BACKGROUND_PROPERTY, version=1, data=value.to_dict(limits=limits))
        result[BACKGROUND_PROPERTY] = envelope
    _json_tree(result, path, limits)
    return result


def get_section_background(section: Section, *, limits: DocumentLimits | None = None) -> BackgroundPaint | None:
    """Read an independent declaration; absence and opaque data imply no inferred role."""
    if type(section) is not Section or not isinstance(section.properties, Mapping):
        _error("section.background", "expected Section with properties")
    return _read(section.properties, _resolve_limits(limits), "section.background")


def set_section_background(section: Section, value: BackgroundPaint | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically replace/remove the declaration; never consult native hints."""
    get_section_background(section, limits=limits)
    budget = _resolve_limits(limits)
    _guard_model(section, budget)
    properties = SectionProperties(_updated(section.properties, value, budget, "section.background"))
    candidate = replace(section, properties=properties)
    _guard_model(candidate, budget)
    section.properties = properties


def get_page_background(page: DocumentPage, *, limits: DocumentLimits | None = None) -> BackgroundPaint | None:
    """Read the page's own declaration, without inheriting from a Section or theme."""
    if type(page) is not DocumentPage or type(page.extra) is not dict:
        _error("page.background", "expected DocumentPage with extra")
    return _read(page.extra, _resolve_limits(limits), "page.background")


def with_page_background(
    page: DocumentPage, value: BackgroundPaint | None, *, limits: DocumentLimits | None = None
) -> DocumentPage:
    """Return an independent page declaration, retaining unrelated page extensions."""
    get_page_background(page, limits=limits)
    budget = _resolve_limits(limits)
    _guard_model(page, budget)
    result = replace(page, extra=_updated(page.extra, value, budget, "page.background"))
    _guard_model(result, budget)
    return result


@dataclass(frozen=True)
class BackgroundLocation:
    """One separately scoped declaration; values are independent getter snapshots."""

    kind: Literal["section", "page"]
    path: str
    background: BackgroundPaint
    page_id: str | None = None


def iter_backgrounds(document: DocumentModel, *, limits: DocumentLimits | None = None) -> Iterator[BackgroundLocation]:
    from opendoc_model.integration import get_integration

    budget = _resolve_limits(limits)
    _guard_model(document, budget)
    for location in _walk_locations(document, budget):
        if isinstance(location.node, Section):
            background = get_section_background(location.node, limits=budget)
            if background is not None:
                yield BackgroundLocation("section", location.path + ".properties[" + repr(BACKGROUND_PROPERTY) + "]", background)
    integration = get_integration(document, limits=budget)
    if integration is not None:
        for index, page in enumerate(integration.pages):
            background = get_page_background(page, limits=budget)
            if background is not None:
                yield BackgroundLocation(
                    "page", f"integration.pages[{index}].extra[{BACKGROUND_PROPERTY!r}]", background, page.id
                )


__all__ = [
    "BACKGROUND_PROPERTY",
    "GradientStop",
    "LinearGradient",
    "RadialGradient",
    "GradientPaint",
    "BackgroundPaint",
    "BackgroundLocation",
    "get_section_background",
    "set_section_background",
    "get_page_background",
    "with_page_background",
    "iter_backgrounds",
]
