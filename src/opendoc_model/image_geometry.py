"""Normalized image source viewports; no pixel processing or native units."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, NoReturn, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import Image, ImageCrop
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.properties import ImageProperties

IMAGE_SOURCE_RECT_PROPERTY = "opendoc.image-source-rect"
_COORDINATES = ("left", "top", "right", "bottom")


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "image.source-rect.invalid")


def _finite(value: Any, path: str) -> None:
    if type(value) not in (int, float):
        _error(path, "expected a finite number")
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite:
        _error(path, "expected a finite number")


@dataclass(frozen=True)
class ImageSourceRect(IntegrationRecord):
    """Source coordinates relative to the original image, independent of Image.box.

    The original bounds are (0,0,1,1). Signed/outside coordinates declare empty
    source area, never extrapolated pixels. The rectangle must have positive area.
    """

    left: float
    top: float
    right: float
    bottom: float

    def __post_init__(self) -> None:
        for name in _COORDINATES:
            _finite(getattr(self, name), f"image_source_rect.{name}")
        if self.right <= self.left or self.bottom <= self.top:
            _error("image_source_rect", "expected right > left and bottom > top")

    def to_dict(self, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
        """Return bounded independent coordinates and unknown JSON fields."""
        budget = _resolve_limits(limits)
        _guard_model(self, budget)
        raw: dict[str, Any] = _convert(self, ImageSourceRect, "image_source_rect", encode=True)
        _json_tree(raw, "image_source_rect", budget)
        return raw

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, limits: DocumentLimits | None = None) -> ImageSourceRect:
        """Decode the complete declaration without native units or guessed defaults."""
        budget = _resolve_limits(limits)
        _json_tree(value, "image_source_rect", budget)
        return cast(ImageSourceRect, _convert(value, cls, "image_source_rect", encode=False))


def _declared(image: Image, budget: DocumentLimits, path: str) -> ImageSourceRect | None:
    if not isinstance(image.properties, Mapping):
        _error(path + ".properties", "expected a property mapping")
    raw = image.properties.get(IMAGE_SOURCE_RECT_PROPERTY)
    here = f"{path}.properties[{IMAGE_SOURCE_RECT_PROPERTY!r}]"
    _json_tree(raw, here, budget)
    if not isinstance(raw, dict) or raw.get("format") != IMAGE_SOURCE_RECT_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(here + ".version", "unsupported source rectangle version")
    try:
        return ImageSourceRect.from_dict(
            {key: value for key, value in raw.items() if key not in {"format", "version"}}, limits=budget
        )
    except _DiagnosticError as error:
        suffix = error.location.removeprefix("image_source_rect")
        _error(here + suffix, error.message)


def _legacy(crop: ImageCrop, path: str) -> ImageSourceRect:
    if not isinstance(crop, ImageCrop):
        _error(path, "expected ImageCrop")
    for name in _COORDINATES:
        value = getattr(crop, name)
        _finite(value, f"{path}.{name}")
        if not 0 <= value <= 1:
            _error(f"{path}.{name}", "crop fraction must be between zero and one")
    if crop.left + crop.right >= 1 or crop.top + crop.bottom >= 1:
        _error(path, "crop removes the entire image")
    return ImageSourceRect(crop.left, crop.top, 1 - crop.right, 1 - crop.bottom)


def _source_rect(image: Image, budget: DocumentLimits, path: str) -> ImageSourceRect | None:
    declared = _declared(image, budget, path)
    if declared is not None and image.crop is not None:
        _error(path + ".crop", "ImageCrop and ImageSourceRect are mutually exclusive; use the source rectangle setter to migrate")
    return declared if declared is not None else _legacy(image.crop, path + ".crop") if image.crop is not None else None


def get_image_source_rect(image: Image, *, limits: DocumentLimits | None = None) -> ImageSourceRect | None:
    """Read a detached viewport, falling back to a valid legacy crop without mutation.

    Absent values remain unknown. Both declarations together are a conflict,
    even when numerically equivalent. Opaque property values are not interpreted.
    """
    if not isinstance(image, Image):
        _error("image", "expected Image")
    budget = _resolve_limits(limits)
    _guard_model(image, budget)
    return _source_rect(image, budget, "image")


def set_image_source_rect(image: Image, rectangle: ImageSourceRect | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically replace/remove the source viewport and clear the legacy crop.

    Setting a value explicitly migrates the declaration; None removes both.
    Preserve old unknown fields on replacement, never overwrite an opaque carrier.
    No native placement, rendering or text binding is recomputed or certified.
    """
    if not isinstance(image, Image) or rectangle is not None and type(rectangle) is not ImageSourceRect:
        _error("image_source_rect", "expected Image and ImageSourceRect or None")
    budget = _resolve_limits(limits)
    _guard_model(image, budget)
    previous = _declared(image, budget, "image")
    if IMAGE_SOURCE_RECT_PROPERTY in image.properties and previous is None:
        _error("image.properties", "source rectangle property is occupied by opaque data")
    properties = dict(image.properties)
    if rectangle is None:
        properties.pop(IMAGE_SOURCE_RECT_PROPERTY, None)
    else:
        rectangle = ImageSourceRect.from_dict(rectangle.to_dict(limits=budget), limits=budget)
        if previous is not None:
            rectangle = replace(rectangle, extra={**previous.extra, **rectangle.extra})
        raw = rectangle.to_dict(limits=budget)
        if {"format", "version"}.intersection(raw):
            _error("image_source_rect.extra", "cannot shadow format/version")
        raw.update(format=IMAGE_SOURCE_RECT_PROPERTY, version=1)
        properties[IMAGE_SOURCE_RECT_PROPERTY] = raw
    _json_tree(properties, "image.properties", budget)
    independent = _convert(properties, dict[str, Any], "image.properties", encode=True)
    candidate = replace(image, properties=ImageProperties(independent), crop=None)
    _guard_model(candidate, budget)
    _source_rect(candidate, budget, "image")
    image.properties, image.crop = candidate.properties, None


__all__ = ["IMAGE_SOURCE_RECT_PROPERTY", "ImageSourceRect", "get_image_source_rect", "set_image_source_rect"]
