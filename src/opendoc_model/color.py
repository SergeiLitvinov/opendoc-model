"""Canonical color values shared by document importers and exporters."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Any, TypeAlias, TypedDict, Unpack


class _ColorAppearance(TypedDict, total=False):
    icc_profile: str | None
    blend_mode: str


class _ColorMetadata(_ColorAppearance, total=False):
    alpha: float


class ColorSpace(str, Enum):
    SRGB = "srgb"
    CMYK = "cmyk"


@dataclass(frozen=True)
class ColorValue:
    space: ColorSpace
    components: tuple[float, ...]
    alpha: float = 1.0
    icc_profile: str | None = None
    blend_mode: str = "normal"

    def __post_init__(self) -> None:
        if not isinstance(self.space, ColorSpace):
            object.__setattr__(self, "space", ColorSpace(self.space))
        expected = 3 if self.space is ColorSpace.SRGB else 4
        if len(self.components) != expected:
            raise ValueError(f"{self.space.value} requires {expected} components")
        components = tuple(float(component) for component in self.components)
        object.__setattr__(self, "components", components)
        if any(not isfinite(component) or component < 0.0 or component > 1.0 for component in components):
            raise ValueError("color components must be between 0 and 1")
        alpha = float(self.alpha)
        object.__setattr__(self, "alpha", alpha)
        if not isfinite(alpha) or not 0.0 <= alpha <= 1.0:
            raise ValueError("alpha must be between 0 and 1")
        if not self.blend_mode or not self.blend_mode.strip():
            raise ValueError("blend mode must not be empty")

    @classmethod
    def from_hex(cls, value: str, **metadata: Unpack[_ColorMetadata]) -> ColorValue:
        token = value.strip().removeprefix("#")
        if len(token) in (3, 4):
            token = "".join(character * 2 for character in token)
        if len(token) not in (6, 8):
            raise ValueError(f"invalid hexadecimal color {value!r}")
        try:
            channels = tuple(int(token[index : index + 2], 16) / 255 for index in range(0, len(token), 2))
        except ValueError as error:
            raise ValueError(f"invalid hexadecimal color {value!r}") from error
        alpha = channels[3] if len(channels) == 4 else float(metadata.pop("alpha", 1.0))
        appearance: _ColorAppearance = metadata
        return cls(ColorSpace.SRGB, channels[:3], alpha=alpha, **appearance)

    @classmethod
    def from_pdf_srgb(cls, value: int, **metadata: Unpack[_ColorMetadata]) -> ColorValue:
        if value < 0 or value > 0xFFFFFF:
            raise ValueError("PDF sRGB integer must be between 0x000000 and 0xFFFFFF")
        return cls.from_hex(f"#{value:06X}", **metadata)

    @classmethod
    def from_srgb_components(cls, red: float, green: float, blue: float, **metadata: Unpack[_ColorMetadata]) -> ColorValue:
        return cls(ColorSpace.SRGB, (red, green, blue), **metadata)

    @classmethod
    def from_cmyk(
        cls, cyan: float, magenta: float, yellow: float, black: float, **metadata: Unpack[_ColorMetadata]
    ) -> ColorValue:
        return cls(ColorSpace.CMYK, (cyan, magenta, yellow, black), **metadata)

    def to_srgb(self) -> ColorValue:
        if self.space is ColorSpace.SRGB:
            return self
        cyan, magenta, yellow, black = self.components
        components = (
            (1.0 - cyan) * (1.0 - black),
            (1.0 - magenta) * (1.0 - black),
            (1.0 - yellow) * (1.0 - black),
        )
        return ColorValue(ColorSpace.SRGB, components, self.alpha, self.icc_profile, self.blend_mode)

    def transformed(
        self,
        *,
        tint: float | None = None,
        shade: float | None = None,
        luminance_mod: float | None = None,
        luminance_offset: float | None = None,
        alpha: float | None = None,
    ) -> ColorValue:
        """Apply normalized OOXML-style channel transforms deterministically."""
        color = self.to_srgb()
        components = color.components
        if tint is not None:
            _validate_fraction(tint, "tint")
            components = tuple(channel + (1.0 - channel) * tint for channel in components)
        if shade is not None:
            _validate_fraction(shade, "shade")
            components = tuple(channel * shade for channel in components)
        if luminance_mod is not None:
            _validate_fraction(luminance_mod, "luminance modifier")
            components = tuple(channel * luminance_mod for channel in components)
        if luminance_offset is not None:
            _validate_fraction(luminance_offset, "luminance offset")
            components = tuple(min(1.0, channel + luminance_offset) for channel in components)
        result_alpha = color.alpha if alpha is None else alpha
        return ColorValue(ColorSpace.SRGB, components, result_alpha, color.icc_profile, color.blend_mode)

    def to_hex(self, *, include_alpha: bool = False) -> str:
        color = self.to_srgb()
        channels = color.components + ((color.alpha,) if include_alpha else ())
        return "#" + "".join(f"{round(channel * 255):02X}" for channel in channels)

    def to_css(self) -> str:
        if self.alpha >= 1.0:
            return self.to_hex()
        red, green, blue = (round(channel * 255) for channel in self.to_srgb().components)
        alpha = f"{self.alpha:.4f}".rstrip("0").rstrip(".")
        return f"rgba({red}, {green}, {blue}, {alpha})"

    def to_dict(self) -> dict[str, object]:
        return {
            "space": self.space.value,
            "components": list(self.components),
            "alpha": self.alpha,
            "icc_profile": self.icc_profile,
            "blend_mode": self.blend_mode,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> ColorValue:
        """Restore a color from the stable document-codec representation."""
        return cls(
            space=ColorSpace(str(value["space"])),
            components=tuple(float(component) for component in value["components"]),
            alpha=float(value.get("alpha", 1.0)),
            icc_profile=value.get("icc_profile"),
            blend_mode=str(value.get("blend_mode", "normal")),
        )


ColorLike: TypeAlias = ColorValue | str


def _validate_fraction(value: float, name: str) -> None:
    if not isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1")


def color_to_css(value: ColorLike | None) -> str | None:
    """Return CSS for a color/legacy token; unresolved 'auto' returns None."""
    if value is None or value == "auto":
        return None
    if isinstance(value, ColorValue):
        return value.to_css()
    if re.fullmatch(r"[a-zA-Z]{1,24}", value):
        return value
    try:
        return ColorValue.from_hex(value).to_css()
    except (TypeError, ValueError):
        return None


__all__ = ["ColorLike", "ColorSpace", "ColorValue", "color_to_css"]
