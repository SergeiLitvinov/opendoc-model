"""Tests for the canonical color contract."""

import pytest

from opendoc_model.color import ColorSpace, ColorValue, color_to_css


def test_hex_color_roundtrip_preserves_alpha():
    color = ColorValue.from_hex("#33669980", icc_profile="display-p3.icc", blend_mode="multiply")

    assert color.space is ColorSpace.SRGB
    assert color.to_hex(include_alpha=True) == "#33669980"
    assert color.to_css() == "rgba(51, 102, 153, 0.502)"
    assert color.to_dict()["icc_profile"] == "display-p3.icc"
    assert color.to_dict()["blend_mode"] == "multiply"


def test_cmyk_conversion_is_deterministic():
    color = ColorValue.from_cmyk(0.0, 1.0, 1.0, 0.0)

    assert color.to_hex() == "#FF0000"


def test_pdf_integer_uses_canonical_srgb_channel_order():
    assert ColorValue.from_pdf_srgb(0x1234AB).to_hex() == "#1234AB"


def test_color_dict_roundtrip_and_legacy_css_validation():
    original = ColorValue.from_cmyk(0.1, 0.2, 0.3, 0.4, alpha=0.75, icc_profile="press.icc")

    assert ColorValue.from_dict(original.to_dict()) == original
    assert color_to_css("#abc") == "#AABBCC"
    assert color_to_css("transparent") == "transparent"
    assert color_to_css("red;position:fixed") is None


def test_ooxml_channel_transforms_are_deterministic():
    base = ColorValue.from_hex("#204060")

    assert base.transformed(tint=0.5).to_hex() == "#90A0B0"
    assert base.transformed(shade=0.5).to_hex() == "#102030"
    assert base.transformed(luminance_mod=0.5, luminance_offset=0.25, alpha=0.4).to_hex() == "#506070"
    assert base.transformed(alpha=0.4).to_hex(include_alpha=True) == "#20406066"


@pytest.mark.parametrize(
    "factory",
    [
        lambda: ColorValue(ColorSpace.SRGB, (1.1, 0.0, 0.0)),
        lambda: ColorValue(ColorSpace.CMYK, (0.0, 0.0, 0.0)),
        lambda: ColorValue.from_hex("#xyz"),
    ],
)
def test_invalid_colors_are_rejected(factory):
    with pytest.raises(ValueError):
        factory()
