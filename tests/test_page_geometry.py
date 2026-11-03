"""Page geometry contracts: independent coordinates, compatibility and bounded failures."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    PAGE_GEOMETRY_PROPERTY,
    Annotation,
    ArtifactLimitError,
    Box,
    DocumentLimits,
    DocumentModel,
    DocumentPage,
    IntegrationModel,
    PageGeometry,
    Paragraph,
    Point2D,
    Rect2D,
    Section,
    document_from_json,
    document_to_json,
    extract_document,
    get_integration,
    get_page_geometry,
    merge_documents,
    page_display_size,
    page_point_from_display,
    page_point_to_display,
    page_rect_from_display,
    page_rect_to_display,
    set_integration,
    walk_model,
    with_page_geometry,
)


@pytest.mark.parametrize(
    "rotation,size,point,rect",
    [
        (0, (500, 700), Point2D(10, 20), Rect2D(10, 20, 40, 60)),
        (90, (700, 500), Point2D(680, 10), Rect2D(620, 10, 60, 40)),
        (180, (500, 700), Point2D(490, 680), Rect2D(450, 620, 40, 60)),
        (270, (700, 500), Point2D(20, 490), Rect2D(20, 450, 60, 40)),
    ],
)
def test_quarter_turns_with_shifted_crop(rotation, size, point, rect):
    geometry = PageGeometry(Rect2D(-10, -20, 600, 800), Rect2D(20, 30, 500, 700), rotation)
    assert page_display_size(geometry) == size
    assert page_point_to_display(geometry, Point2D(30, 50)) == point
    assert page_point_from_display(geometry, point) == Point2D(30, 50)
    assert page_rect_to_display(geometry, Rect2D(30, 50, 40, 60)) == rect
    assert page_rect_from_display(geometry, rect) == Rect2D(30, 50, 40, 60)
    for outside in (Point2D(-100, -200), Point2D(900, 1000), Point2D(21.25, 31.75)):
        assert page_point_from_display(geometry, page_point_to_display(geometry, outside)) == outside
    degenerate = Rect2D(30, 50, 0, 0)
    assert page_rect_from_display(geometry, page_rect_to_display(geometry, degenerate)) == degenerate


def fixture_document():
    geometry = PageGeometry(Rect2D(-10, -20, 600, 800), Rect2D(20, 30, 500, 700), 90, extra={"future": [1]})
    page = with_page_geometry(DocumentPage("page", 600, 800, extra={"origin": "synthetic"}), geometry)
    document = DocumentModel(sections=[Section([Paragraph()])])
    set_integration(
        document,
        IntegrationModel(pages=(page,), annotations=(Annotation("note", "page", "note", box=Box(30, 50, 40, 60, 15)),)),
    )
    return document, geometry


def test_json_composition_preserves_geometry_and_does_not_rotate_element_boxes():
    document, geometry = fixture_document()
    restored = document
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
        page = get_integration(restored).pages[0]
        assert get_page_geometry(page) == geometry
        assert page.extra["origin"] == "synthetic"
        assert get_integration(restored).annotations[0].box == Box(30, 50, 40, 60, 15)
        assert restored.validate() == []
    merged = merge_documents([document, restored], metadata_conflicts="keep_first")
    assert get_page_geometry(get_integration(merged.document).pages[0]) == geometry
    location = next(location for location in walk_model(document) if isinstance(location.node, Paragraph))
    extracted = extract_document(document, location)
    assert get_page_geometry(get_integration(extracted).pages[0]) == geometry
    changed = get_page_geometry(get_integration(extracted).pages[0])
    changed.extra["future"].append(2)
    assert get_page_geometry(get_integration(document).pages[0]).extra == {"future": [1]}


def test_legacy_pages_remain_unknown_and_unknown_geometry_fields_survive():
    page = DocumentPage("page", 600, 800)
    assert get_page_geometry(page) is None
    geometry = PageGeometry(Rect2D(0, 0, 600, 800), extra={"future": {"x": 1}})
    enriched = with_page_geometry(page, geometry)
    updated = with_page_geometry(enriched, PageGeometry(geometry.media_box, rotation=270))
    assert get_page_geometry(updated).extra == geometry.extra
    assert page.extra == {}
    assert with_page_geometry(updated, None) == page
    doc = DocumentModel(version=1)
    set_integration(doc, IntegrationModel(pages=(enriched,)))
    assert get_page_geometry(get_integration(document_from_json(document_to_json(doc))).pages[0]) == geometry


@pytest.mark.parametrize(
    "media,crop,rotation",
    [
        (Rect2D(0, 0, 0, 10), None, 0),
        (Rect2D(0, 0, 10, -1), None, 0),
        (Rect2D(0, 0, float("nan"), 10), None, 0),
        (Rect2D(False, 0, 10, 10), None, 0),
        (Rect2D(1e308, 0, 1e308, 10), None, 0),
        (Rect2D(0, 0, 10, 10), Rect2D(-1, 0, 10, 10), 0),
        (Rect2D(0, 0, 10, 10), Rect2D(1, 1, 10, 10), 0),
        (Rect2D(0, 0, 10, 10), Rect2D(0, 0, 0, 10), 0),
        (Rect2D(0, 0, 10, 10), None, 45),
        (Rect2D(0, 0, 10, 10), None, 90.0),
        (Rect2D(0, 0, 10, 10), None, True),
    ],
)
def test_invalid_regions_and_rotations(media, crop, rotation):
    with pytest.raises(ValueError):
        PageGeometry(media, crop, rotation)


def test_bad_tagged_data_and_atomic_set_integration():
    document, geometry = fixture_document()
    previous = deepcopy(document.metadata)
    page = get_integration(document).pages[0]
    for version in (True, 2, "1"):
        extra = deepcopy(page.extra)
        extra[PAGE_GEOMETRY_PROPERTY]["version"] = version
        bad = replace(page, extra=extra)
        with pytest.raises(ValueError, match="schema version"):
            set_integration(document, IntegrationModel(pages=(bad,)))
        assert document.metadata == previous
    with pytest.raises(ValueError, match="unrotated media"):
        with_page_geometry(DocumentPage("other", 800, 600), geometry)
    raw = deepcopy(page.extra)
    raw[PAGE_GEOMETRY_PROPERTY]["rotation"] = 15
    corrupted = replace(page, extra=raw)
    with pytest.raises(ValueError):
        get_page_geometry(corrupted)
    # Direct metadata edits are diagnosed during ordinary document validation.
    key = "opendoc.integration"
    document.metadata[key]["data"]["pages"][0][PAGE_GEOMETRY_PROPERTY]["rotation"] = 15
    assert document.validate()


def test_opaque_collision_extra_and_limits_do_not_modify_page():
    geometry = PageGeometry(Rect2D(0, 0, 600, 800))
    page = DocumentPage("page", 600, 800, extra={PAGE_GEOMETRY_PROPERTY: {"private": [1]}})
    original = deepcopy(page.extra)
    assert get_page_geometry(page) is None
    for value in (geometry, None):
        with pytest.raises(ValueError, match="opaque"):
            with_page_geometry(page, value)
        assert page.extra == original
    clean = DocumentPage("page", 600, 800)
    for extra in ({"version": 2}, {"media_box": {}}, {"extra": {}}):
        with pytest.raises(ValueError):
            with_page_geometry(clean, replace(geometry, extra=extra))
    cycle = {}
    cycle["cycle"] = cycle
    with pytest.raises(ValueError):
        with_page_geometry(clean, replace(geometry, extra=cycle))
    with pytest.raises(ArtifactLimitError):
        with_page_geometry(clean, geometry, limits=DocumentLimits(max_nodes=2))
    assert clean.extra == {}


def test_transform_invalid_and_overflow_inputs_are_explicit():
    geometry = PageGeometry(Rect2D(0, 0, 10, 10))
    with pytest.raises(ValueError):
        page_point_to_display(geometry, Point2D(float("inf"), 0))
    with pytest.raises(ValueError):
        page_rect_from_display(geometry, Rect2D(0, 0, -1, 1))
    huge = PageGeometry(Rect2D(-1e308, 0, 1e308, 10))
    with pytest.raises(ValueError):
        page_point_to_display(huge, Point2D(1e308, 0))


@pytest.mark.parametrize("opaque", [None, False, 0, "private", []])
def test_unmarked_geometry_key_is_never_replaced_or_removed(opaque):
    page = DocumentPage("page", 600, 800, extra={PAGE_GEOMETRY_PROPERTY: opaque})
    before = deepcopy(page.extra)
    assert get_page_geometry(page) is None
    for value in (PageGeometry(Rect2D(0, 0, 600, 800)), None):
        with pytest.raises(ValueError, match="opaque"):
            with_page_geometry(page, value)
        assert page.extra == before
