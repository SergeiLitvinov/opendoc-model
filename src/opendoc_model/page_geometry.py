"""Explicit page regions and quarter-turn transforms, without rendering or clipping."""

from __future__ import annotations

import math
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, Literal

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.integration_types import DocumentPage, IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.units import Point2D, Rect2D

PAGE_GEOMETRY_PROPERTY = "opendoc.page-geometry"


def _error(message: str) -> Any:
    raise _DiagnosticError("page.geometry", message, "page.geometry.invalid")


def _number(value: float) -> None:
    if type(value) not in (int, float):
        _error("expected finite point coordinates")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        _error("coordinate exceeds the floating point range")
    if not finite:
        _error("expected finite point coordinates")


def _rect(value: Rect2D, *, positive: bool) -> None:
    if type(value) is not Rect2D:
        _error("expected Rect2D")
    for number in (value.x, value.y, value.width, value.height):
        _number(number)
    if value.width < 0 or value.height < 0 or positive and (value.width == 0 or value.height == 0):
        _error("invalid region dimensions")
    _number(value.x + value.width)
    _number(value.y + value.height)


@dataclass(frozen=True)
class PageGeometry(IntegrationRecord):
    """Unrotated source regions in points; clockwise rotation after crop translation.

    Source coordinates use the canonical top-left origin with x right and y down.
    Crop defaults to media; display coordinates start at the rotated crop's top left.
    """

    media_box: Rect2D
    crop_box: Rect2D | None = None
    rotation: Literal[0, 90, 180, 270] = 0

    def __post_init__(self) -> None:
        _rect(self.media_box, positive=True)
        if type(self.rotation) is not int or self.rotation not in (0, 90, 180, 270):
            _error("rotation must be 0, 90, 180 or 270 degrees")
        if self.crop_box is not None:
            _rect(self.crop_box, positive=True)
            media, crop = self.media_box, self.crop_box
            if (
                crop.x < media.x
                or crop.y < media.y
                or crop.x + crop.width > media.x + media.width
                or crop.y + crop.height > media.y + media.height
            ):
                _error("crop region must be contained in media region")


def _check(geometry: PageGeometry) -> Rect2D:
    if type(geometry) is not PageGeometry:
        _error("expected PageGeometry")
    geometry.__post_init__()
    return geometry.crop_box or geometry.media_box


def page_display_size(geometry: PageGeometry) -> tuple[float, float]:
    """Return rotated crop width/height; no content measurement is performed."""
    area = _check(geometry)
    return (area.height, area.width) if geometry.rotation in (90, 270) else (area.width, area.height)


def _point(point: Point2D) -> None:
    if type(point) is not Point2D:
        _error("expected Point2D")
    _number(point.x)
    _number(point.y)


def page_point_to_display(geometry: PageGeometry, point: Point2D) -> Point2D:
    """Translate then rotate a source point; outside points are not clipped."""
    area = _check(geometry)
    _point(point)
    x, y = point.x - area.x, point.y - area.y
    if geometry.rotation == 90:
        x, y = area.height - y, x
    elif geometry.rotation == 180:
        x, y = area.width - x, area.height - y
    elif geometry.rotation == 270:
        x, y = y, area.width - x
    result = Point2D(x, y)
    _point(result)
    return result


def page_point_from_display(geometry: PageGeometry, point: Point2D) -> Point2D:
    """Invert the crop translation and clockwise quarter-turn rotation."""
    area = _check(geometry)
    _point(point)
    x, y = point.x, point.y
    if geometry.rotation == 90:
        x, y = y, area.height - x
    elif geometry.rotation == 180:
        x, y = area.width - x, area.height - y
    elif geometry.rotation == 270:
        x, y = area.width - y, x
    result = Point2D(x + area.x, y + area.y)
    _point(result)
    return result


def _transform_rect(geometry: PageGeometry, rect: Rect2D, *, inverse: bool) -> Rect2D:
    _rect(rect, positive=False)
    transform = page_point_from_display if inverse else page_point_to_display
    corners = tuple(
        transform(geometry, Point2D(x, y)) for x in (rect.x, rect.x + rect.width) for y in (rect.y, rect.y + rect.height)
    )
    left, top = min(point.x for point in corners), min(point.y for point in corners)
    result = Rect2D(left, top, max(point.x for point in corners) - left, max(point.y for point in corners) - top)
    _rect(result, positive=False)
    return result


def page_rect_to_display(geometry: PageGeometry, rect: Rect2D) -> Rect2D:
    """Transform an axis-aligned source rectangle, without clipping or element rotation."""
    return _transform_rect(geometry, rect, inverse=False)


def page_rect_from_display(geometry: PageGeometry, rect: Rect2D) -> Rect2D:
    """Invert an axis-aligned display rectangle; quarter turns preserve its shape."""
    return _transform_rect(geometry, rect, inverse=True)


def get_page_geometry(page: DocumentPage, *, limits: DocumentLimits | None = None) -> PageGeometry | None:
    """Read independent tagged geometry; missing or unmarked data stays unknown."""
    budget = _resolve_limits(limits)
    if type(page) is not DocumentPage or not isinstance(page.extra, dict):
        _error("expected DocumentPage with extra dictionary")
    raw = page.extra.get(PAGE_GEOMETRY_PROPERTY)
    if raw is None:
        return None
    _json_tree(raw, "page.geometry", budget)
    if not isinstance(raw, dict) or raw.get("format") != PAGE_GEOMETRY_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error("unsupported geometry schema version")
    try:
        geometry: PageGeometry = _convert(
            {key: value for key, value in raw.items() if key not in {"format", "version"}},
            PageGeometry,
            "page.geometry",
            encode=False,
        )
    except _DiagnosticError as error:
        raise _DiagnosticError(error.location, error.message, "page.geometry.invalid") from error
    if page.width != geometry.media_box.width or page.height != geometry.media_box.height:
        _error("page width/height must equal unrotated media dimensions")
    return geometry


def with_page_geometry(
    page: DocumentPage, geometry: PageGeometry | None, *, limits: DocumentLimits | None = None
) -> DocumentPage:
    """Return an independent page; refuse opaque collisions, keep unknown fields and dimensions."""
    budget = _resolve_limits(limits)
    _guard_model(page, budget)
    previous = get_page_geometry(page, limits=budget)
    if PAGE_GEOMETRY_PROPERTY in page.extra and previous is None:
        _error("occupied geometry key contains opaque data")
    extra = deepcopy(page.extra)
    if geometry is None:
        extra.pop(PAGE_GEOMETRY_PROPERTY, None)
    else:
        _guard_model(geometry, budget)
        _check(geometry)
        if not isinstance(geometry.extra, dict) or {"format", "version"}.intersection(geometry.extra):
            _error("geometry extra cannot shadow envelope fields")
        if previous is not None:
            geometry = replace(geometry, extra={**previous.extra, **geometry.extra})
        encoded = _convert(geometry, PageGeometry, "page.geometry", encode=True)
        extra[PAGE_GEOMETRY_PROPERTY] = {**encoded, "format": PAGE_GEOMETRY_PROPERTY, "version": 1}
    result = replace(page, extra=extra)
    _guard_model(result, budget)
    get_page_geometry(result, limits=budget)
    return result


__all__ = [
    "PAGE_GEOMETRY_PROPERTY",
    "PageGeometry",
    "get_page_geometry",
    "with_page_geometry",
    "page_display_size",
    "page_point_to_display",
    "page_point_from_display",
    "page_rect_to_display",
    "page_rect_from_display",
]
