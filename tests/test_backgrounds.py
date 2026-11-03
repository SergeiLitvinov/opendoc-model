"""Neutral gradient roles, no inferred native geometry, independent bounded transport."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    BACKGROUND_PROPERTY,
    ArtifactLimitError,
    BackgroundPaint,
    ColorValue,
    DocumentLimits,
    DocumentModel,
    DocumentPage,
    GradientPaint,
    GradientStop,
    IntegrationModel,
    LinearGradient,
    Paint,
    Point2D,
    RadialGradient,
    Section,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_integration,
    get_page_background,
    get_section_background,
    iter_backgrounds,
    merge_documents,
    set_integration,
    set_section_background,
    walk_model,
    with_page_background,
)


def background(radial=False):
    red = ColorValue.from_hex("#FF0000", alpha=0.3)
    blue = ColorValue.from_hex("#0000FF", alpha=0.8)
    stops = (GradientStop(0, red, extra={"future": [1]}), GradientStop(0.5, red), GradientStop(0.5, blue), GradientStop(1, blue))
    geometry = (
        {"radial": RadialGradient("points", Point2D(20, 30), 10)}
        if radial
        else {"linear": LinearGradient("relative", Point2D(0, 0), Point2D(1, 1))}
    )
    return BackgroundPaint(
        "gradient",
        gradient=GradientPaint(stops, opacity=0.7, spread="pad", interpolation="srgb", **geometry),
        extra={"custom": [2]},
    )


def fixture():
    section = Section()
    set_section_background(section, background())
    page = with_page_background(DocumentPage("page", 600, 800), background(True))
    document = DocumentModel([section])
    set_integration(document, IntegrationModel(pages=(page,)))
    return document


def test_two_cycles_stops_ties_alpha_geometry_and_independence():
    document = fixture()
    expected = document_to_dict(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert document_to_dict(document) == expected
    section_paint = get_section_background(document.sections[0])
    page_paint = get_page_background(get_integration(document).pages[0])
    assert [stop.position for stop in section_paint.gradient.stops] == [0, 0.5, 0.5, 1]
    assert section_paint.gradient.stops[0].color.alpha == 0.3
    assert section_paint.gradient.opacity == 0.7
    assert page_paint.gradient.radial.radius == 10
    section_paint.gradient.stops[0].extra["future"].append(9)
    assert get_section_background(document.sections[0]).gradient.stops[0].extra["future"] == [1]
    assert BackgroundPaint.from_dict(background().to_dict()) == background()
    raw = background().to_dict()
    decoded = BackgroundPaint.from_dict(raw)
    raw["custom"].append(9)
    assert decoded.extra["custom"] == [2]


@pytest.mark.parametrize(
    "value",
    [
        None,
        BackgroundPaint("none"),
        BackgroundPaint("unknown"),
        BackgroundPaint("solid", solid=Paint(ColorValue.from_hex("#123456"), 0.4)),
        BackgroundPaint("gradient", gradient=GradientPaint()),
    ],
)
def test_absent_none_unknown_solid_and_unknown_gradient_are_distinct(value):
    section = Section()
    set_section_background(section, value)
    document = document_from_json(document_to_json(DocumentModel([section])))
    assert get_section_background(document.sections[0]) == value
    if value is None:
        assert BACKGROUND_PROPERTY not in section.properties
    if value is not None and value.kind == "gradient":
        assert value.gradient.stops is None and value.gradient.linear is None and value.gradient.radial is None


def test_edit_remove_authoritative_and_no_hints_resurrection():
    document = fixture()
    section = document.sections[0]
    section.properties["native-hint"] = {"stops": ["old"]}
    envelope = section.properties[BACKGROUND_PROPERTY]
    envelope["future-envelope"] = [5]
    current = get_section_background(section)
    changed = replace(current, gradient=replace(current.gradient, stops=(current.gradient.stops[0], current.gradient.stops[-1])))
    set_section_background(section, changed)
    assert len(get_section_background(section).gradient.stops) == 2
    assert section.properties[BACKGROUND_PROPERTY]["future-envelope"] == [5]
    set_section_background(section, BackgroundPaint("none"))
    assert get_section_background(section).gradient is None
    set_section_background(section, None)
    assert get_section_background(section) is None and section.properties["native-hint"]["stops"] == ["old"]
    page = get_integration(document).pages[0]
    assert get_page_background(with_page_background(page, None)) is None
    assert get_page_background(page) is not None


@pytest.mark.parametrize(
    "factory",
    [
        lambda: GradientStop(-0.1),
        lambda: GradientStop(1.1),
        lambda: GradientStop(True),
        lambda: GradientStop(float("nan")),
        lambda: GradientPaint((GradientStop(1), GradientStop(0))),
        lambda: GradientPaint(()),
        lambda: GradientPaint(opacity=1.1),
        lambda: GradientPaint(spread="native"),
        lambda: LinearGradient("relative", Point2D(0, 0), Point2D(0, 0)),
        lambda: LinearGradient("native", Point2D(0, 0), Point2D(1, 0)),
        lambda: RadialGradient("points", Point2D(0, 0), 0),
        lambda: BackgroundPaint("none", gradient=GradientPaint()),
        lambda: BackgroundPaint("solid"),
        lambda: GradientPaint(
            linear=LinearGradient("points", Point2D(0, 0), Point2D(1, 1)), radial=RadialGradient("points", Point2D(0, 0), 1)
        ),
    ],
)
def test_invalid_profiles_refuse(factory):
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "raw",
    [
        {"format": BACKGROUND_PROPERTY, "version": 2, "data": {}},
        {"format": BACKGROUND_PROPERTY, "version": True, "data": {}},
        {"format": BACKGROUND_PROPERTY, "version": 1},
        {"format": BACKGROUND_PROPERTY, "version": 1, "data": {"kind": "solid"}},
    ],
)
def test_located_document_failures(raw):
    document = fixture()
    document.sections[0].properties[BACKGROUND_PROPERTY] = raw
    with pytest.raises(ValueError, match=r"sections\[0\].properties"):
        document_to_dict(document)


def test_opaque_collision_atomic_quotas_and_cycle():
    section = Section(properties={BACKGROUND_PROPERTY: {"opaque": True}})
    previous = section.properties
    assert get_section_background(section) is None
    with pytest.raises(ValueError, match="opaque"):
        set_section_background(section, background())
    assert section.properties is previous
    section = Section()
    set_section_background(section, background())
    previous = section.properties
    for limit in (DocumentLimits(max_nodes=1), DocumentLimits(max_depth=1), DocumentLimits(max_bytes=1)):
        with pytest.raises(ArtifactLimitError):
            set_section_background(section, BackgroundPaint("none"), limits=limit)
        assert section.properties is previous
    value = background()
    value.extra["cycle"] = value.extra
    with pytest.raises(ValueError, match="cyclic"):
        set_section_background(section, value)
    assert section.properties is previous


def test_composition_separate_walk_and_no_resource_guessing():
    document = fixture()
    entries = list(iter_backgrounds(document))
    assert [entry.kind for entry in entries] == ["section", "page"]
    assert entries[1].page_id == "page"
    assert len(list(walk_model(document))) == 2
    merged = merge_documents([document, document], metadata_conflicts="keep_last").document
    assert len(list(iter_backgrounds(merged))) == 3
    location = next(loc for loc in walk_model(document) if isinstance(loc.node, Section))
    selected = extract_document(document, location)
    assert get_section_background(selected.sections[0]) == get_section_background(document.sections[0])
    assert not document_from_json(document_to_json(merged)).validate()


@pytest.mark.parametrize("quota", ["max_nodes", "max_depth", "max_bytes"])
def test_exact_transport_boundary(quota):
    document = fixture()
    wire = document_to_json(document)

    def accepted(value):
        limits = replace(DocumentLimits(), **{quota: value})
        try:
            document_to_json(document, limits=limits)
            document_from_json(wire, limits=limits)
        except ArtifactLimitError:
            return False
        return True

    low, high = 0, 128 if quota == "max_depth" else max(10000, len(wire.encode()))
    while low + 1 < high:
        midpoint = (low + high) // 2
        if accepted(midpoint):
            high = midpoint
        else:
            low = midpoint
    assert accepted(high) and not accepted(high - 1)
    assert document_to_json(document) == wire


def test_invalid_page_background_and_input_json_independence():
    document = fixture()
    raw = document_to_dict(document)
    expected = deepcopy(raw)
    decoded = document_from_dict(raw)
    raw["document"]["sections"][0]["properties"][BACKGROUND_PROPERTY]["data"]["custom"].append(7)
    assert document_to_dict(decoded) == expected
    integration = get_integration(document)
    page = integration.pages[0]
    page.extra[BACKGROUND_PROPERTY]["data"]["kind"] = "solid"
    previous = document.metadata
    with pytest.raises(ValueError, match="pages"):
        set_integration(document, replace(integration, pages=(page,)))
    assert document.metadata is previous
