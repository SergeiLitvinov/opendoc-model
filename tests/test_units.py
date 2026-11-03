"""Contract tests for canonical units and coordinate systems."""

import pytest

from opendoc_model.units import (
    CoordinateOrigin,
    Point2D,
    Rect2D,
    canonical_coordinate_contract,
    css_px_to_points,
    degrees_to_ooxml_angle,
    emu_to_inches,
    emu_to_points,
    inches_to_emu,
    ooxml_angle_to_degrees,
    points_to_css_px,
    points_to_emu,
    round_half_away,
    transform_point_origin,
    transform_rect_origin,
)


def test_rounding_contract_is_half_away_from_zero():
    assert round_half_away(2.5) == 3
    assert round_half_away(-2.5) == -3
    assert round_half_away(1.2345, 3) == 1.235


@pytest.mark.parametrize("points", [0.0, 0.5, 1.0, 72.0, -12.25, 841.89])
def test_emu_point_roundtrip_is_within_half_an_emu(points):
    assert emu_to_points(points_to_emu(points)) == pytest.approx(points, abs=0.5 / 12700)


def test_emu_inch_roundtrip():
    assert emu_to_inches(914400) == 1.0
    assert inches_to_emu(1.0) == 914400


def test_css_pixel_contract_uses_96_dpi():
    assert points_to_css_px(72) == 96
    assert css_px_to_points(96) == 72


def test_ooxml_angle_roundtrip():
    assert degrees_to_ooxml_angle(12.5) == 750000
    assert ooxml_angle_to_degrees(750000) == 12.5


def test_coordinate_origin_transform_is_involutive():
    point = Point2D(10, 20)
    rectangle = Rect2D(10, 20, 30, 40)
    flipped_point = transform_point_origin(
        point, page_height=200, source=CoordinateOrigin.TOP_LEFT, target=CoordinateOrigin.BOTTOM_LEFT
    )
    flipped_rectangle = transform_rect_origin(
        rectangle, page_height=200, source=CoordinateOrigin.TOP_LEFT, target=CoordinateOrigin.BOTTOM_LEFT
    )

    assert flipped_point == Point2D(10, 180)
    assert flipped_rectangle == Rect2D(10, 140, 30, 40)
    assert (
        transform_rect_origin(
            flipped_rectangle, page_height=200, source=CoordinateOrigin.BOTTOM_LEFT, target=CoordinateOrigin.TOP_LEFT
        )
        == rectangle
    )


def test_canonical_document_coordinates_are_explicit():
    assert canonical_coordinate_contract() == {
        "unit": "pt",
        "origin": "top-left",
        "x_axis": "right",
        "y_axis": "down",
        "rotation_unit": "degree",
        "rotation_direction": "clockwise",
    }
