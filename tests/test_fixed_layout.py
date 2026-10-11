"""Own fixed-layout corpus: exact declarations, Unicode endpoints and independent history."""

from copy import deepcopy
from dataclasses import replace

import pytest

from examples.fixed_layout import fixture
from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
    PageGeometry,
    Paragraph,
    Point2D,
    Provenance,
    ProvenanceEvent,
    Rect2D,
    check_document,
    clone_model,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    edit_anchored_text,
    extract_document,
    get_integration,
    get_page_geometry,
    iter_elements,
    page_point_from_display,
    page_point_to_display,
    page_rect_from_display,
    page_rect_to_display,
    set_integration,
    with_page_geometry,
)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_exact_two_json_cycles_coordinates_provenance_and_unicode(rotation):
    document = fixture()
    model = get_integration(document)
    page = model.pages[1]
    geometry = replace(get_page_geometry(page), rotation=rotation)
    set_integration(document, replace(model, pages=(model.pages[0], with_page_geometry(page, geometry))))
    expected = deepcopy(document)
    expected_json = document_to_dict(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and document_to_dict(document) == expected_json
    model = get_integration(document)
    assert len(document.sections) == len(model.pages) == 2
    assert all(len(section.blocks) == 1 for section in document.sections)
    assert model.pages[1].reading_order == ("paragraph-1",)
    assert model.source_map.mappings[0].spans[0].extra == {"page": 0}
    run = document.sections[0].blocks[0].content[0]
    assert run.text[model.ranges[0].start.offset : model.ranges[0].end.offset] == "😀 e\u0301"
    assert run.provenance.page == 0 and run.provenance.object_id == "text-0"
    assert run.provenance.events == [ProvenanceEvent("import", "explicit positions")]
    for rect in (Rect2D(30.125, 50.25, 240.5, 18.75), Rect2D(-40.125, -50.25, 0, 0)):
        assert page_rect_from_display(geometry, page_rect_to_display(geometry, rect)) == rect
    point = Point2D(-40.125, -50.25)
    assert page_point_from_display(geometry, page_point_to_display(geometry, point)) == point


def test_transformed_history_owns_existing_events_in_both_directions():
    source = Provenance("own-fixed", page=0, object_id="origin", events=[ProvenanceEvent("import", "original")])
    transformed = source.transformed("edit", detail="updated", fallback_reason="declared-only")
    assert transformed.events == [ProvenanceEvent("import", "original"), ProvenanceEvent("edit", "updated", "declared-only")]
    transformed.events[0].detail = "changed-copy"
    assert source.events[0].detail == "original"
    source.events[0].operation = "changed-source"
    assert transformed.events[0].operation == "import"
    assert transformed.page == source.page and transformed.object_id == source.object_id


def test_clone_extract_and_text_edit_preserve_geometry_without_relayout():
    document = fixture()
    before = deepcopy(document)
    copied = clone_model(document)
    copied.sections[0].blocks[0].content[0].provenance.events[0].detail = "changed-copy"
    assert document == before
    extracted = extract_document(document, next(iter_elements(document, Paragraph)))
    assert extracted.sections[0].blocks[0].box == document.sections[0].blocks[0].box
    assert get_integration(extracted) == get_integration(document)
    edited = edit_anchored_text(document, "run-0", 4, 5, "XY")
    assert document == before
    assert edited.sections[0].blocks[0].box == document.sections[0].blocks[0].box
    model = get_integration(edited)
    assert model.ranges[0].start.offset == 4 and model.ranges[0].end.offset == 9
    assert model.pages == get_integration(document).pages and model.source_map == get_integration(document).source_map


@pytest.mark.parametrize(
    "mutation",
    [
        lambda model: replace(model, ranges=(replace(model.ranges[0], end=replace(model.ranges[0].end, offset=99)),)),
        lambda model: replace(model, pages=(replace(model.pages[0], reading_order=("missing",)),)),
        lambda model: replace(model, annotations=(replace(model.annotations[0], page_id="missing"),)),
    ],
)
def test_invalid_reference_and_endpoint_refusal_is_atomic(mutation):
    document = fixture()
    before = deepcopy(document)
    with pytest.raises(ValueError):
        set_integration(document, mutation(get_integration(document)))
    assert document == before


def test_json_v1_compatibility_and_explicit_limits():
    document = fixture()
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    with pytest.raises(ArtifactLimitError):
        document_to_json(document, limits=DocumentLimits(max_nodes=20))
    limits = DocumentLimits(max_nodes=10_000)
    assert check_document(document, limits=limits).success
    assert document_from_json(document_to_json(document, limits=limits), limits=limits) == document


def test_unknown_geometry_and_explicit_zero_remain_distinct():
    document = fixture()
    page = get_integration(document).pages[0]
    assert get_page_geometry(replace(page, extra={})) is None
    geometry = PageGeometry(Rect2D(0, 0, 600, 800), rotation=0)
    assert get_page_geometry(with_page_geometry(page, geometry)).rotation == 0
