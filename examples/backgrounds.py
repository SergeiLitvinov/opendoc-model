"""Declared stops and geometry; no native projection or rendering."""

from opendoc_model import (
    BackgroundPaint,
    ColorValue,
    DocumentModel,
    GradientPaint,
    GradientStop,
    LinearGradient,
    Point2D,
    Section,
    document_from_json,
    document_to_json,
    get_section_background,
    set_section_background,
)

section = Section()
paint = BackgroundPaint(
    "gradient",
    gradient=GradientPaint(
        (GradientStop(0, ColorValue.from_hex("#FF0000", alpha=0.5)), GradientStop(1, ColorValue.from_hex("#0000FF"))),
        linear=LinearGradient("relative", Point2D(0, 0), Point2D(1, 1)),
        opacity=1,
        spread="pad",
        interpolation="srgb",
    ),
)
set_section_background(section, paint)
model = DocumentModel([section])
wire = document_to_json(model)
for _ in range(2):
    model = document_from_json(wire)
    assert document_to_json(model) == wire
assert get_section_background(model.sections[0]) == paint
set_section_background(model.sections[0], BackgroundPaint("none"))
assert get_section_background(model.sections[0]).kind == "none"
set_section_background(model.sections[0], None)
assert get_section_background(model.sections[0]) is None
