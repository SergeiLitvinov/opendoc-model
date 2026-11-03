"""Canonical physical units, rounding, and page coordinate transforms."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum

POINTS_PER_INCH = 72.0
CSS_PIXELS_PER_INCH = 96.0
EMU_PER_INCH = 914400
EMU_PER_POINT = EMU_PER_INCH / POINTS_PER_INCH
OOXML_ANGLE_PER_DEGREE = 60000


class CoordinateOrigin(str, Enum):
    TOP_LEFT = "top-left"
    BOTTOM_LEFT = "bottom-left"


@dataclass(frozen=True)
class Point2D:
    x: float
    y: float


@dataclass(frozen=True)
class Rect2D:
    x: float
    y: float
    width: float
    height: float


def canonical_coordinate_contract() -> dict[str, str]:
    return {
        "unit": "pt",
        "origin": CoordinateOrigin.TOP_LEFT.value,
        "x_axis": "right",
        "y_axis": "down",
        "rotation_unit": "degree",
        "rotation_direction": "clockwise",
    }


def round_half_away(value: float, digits: int = 0) -> int | float:
    """Round decimal halves away from zero, independent of binary float ties."""
    quantum = Decimal(1).scaleb(-digits)
    rounded = Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
    return int(rounded) if digits == 0 else float(rounded)


def emu_to_points(value: float | int) -> float:
    return float(value) / EMU_PER_POINT


def emu_to_inches(value: float | int) -> float:
    return float(value) / EMU_PER_INCH


def inches_to_emu(value: float) -> int:
    return int(round_half_away(value * EMU_PER_INCH))


def points_to_emu(value: float) -> int:
    return int(round_half_away(value * EMU_PER_POINT))


def points_to_css_px(value: float) -> float:
    return value * CSS_PIXELS_PER_INCH / POINTS_PER_INCH


def css_px_to_points(value: float) -> float:
    return value * POINTS_PER_INCH / CSS_PIXELS_PER_INCH


def ooxml_angle_to_degrees(value: float | int) -> float:
    return float(value) / OOXML_ANGLE_PER_DEGREE


def degrees_to_ooxml_angle(value: float) -> int:
    return int(round_half_away(value * OOXML_ANGLE_PER_DEGREE))


def transform_point_origin(
    point: Point2D,
    *,
    page_height: float,
    source: CoordinateOrigin,
    target: CoordinateOrigin,
) -> Point2D:
    if source is target:
        return point
    return Point2D(point.x, page_height - point.y)


def transform_rect_origin(
    rectangle: Rect2D,
    *,
    page_height: float,
    source: CoordinateOrigin,
    target: CoordinateOrigin,
) -> Rect2D:
    if source is target:
        return rectangle
    return Rect2D(rectangle.x, page_height - rectangle.y - rectangle.height, rectangle.width, rectangle.height)


__all__ = [
    "CSS_PIXELS_PER_INCH",
    "EMU_PER_INCH",
    "EMU_PER_POINT",
    "OOXML_ANGLE_PER_DEGREE",
    "POINTS_PER_INCH",
    "CoordinateOrigin",
    "Point2D",
    "Rect2D",
    "canonical_coordinate_contract",
    "css_px_to_points",
    "degrees_to_ooxml_angle",
    "emu_to_inches",
    "emu_to_points",
    "inches_to_emu",
    "ooxml_angle_to_degrees",
    "points_to_css_px",
    "points_to_emu",
    "round_half_away",
    "transform_point_origin",
    "transform_rect_origin",
]
