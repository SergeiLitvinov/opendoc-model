"""Outline hierarchy, links, independent copies, compatibility and bounded failures."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    INTEGRATION_PROPERTY,
    OUTLINE_PROPERTY,
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    DocumentPage,
    IntegrationModel,
    Outline,
    OutlineEntry,
    OutlineTarget,
    PageGeometry,
    Paragraph,
    Point2D,
    Provenance,
    Rect2D,
    Section,
    TextRun,
    check_document,
    document_from_json,
    document_to_json,
    extract_document,
    get_integration,
    get_outline,
    iter_elements,
    merge_documents,
    page_point_to_display,
    remap_outline,
    remove_node,
    set_anchor,
    set_integration,
    set_outline,
    with_page_geometry,
)


def fixture_document():
    first, second = Paragraph([TextRun("Introduction")]), Paragraph([TextRun("Details 😀")])
    set_anchor(first, Anchor("intro"))
    set_anchor(second, Anchor("details"))
    geometry = PageGeometry(Rect2D(0, 0, 600, 800), Rect2D(10, 20, 500, 700), 90)
    page = with_page_geometry(DocumentPage("page-1", 600, 800), geometry)
    document = DocumentModel(sections=[Section([first]), Section([second])])
    set_integration(document, IntegrationModel(pages=(page,), extra={"unknown": [1]}))
    outline = Outline(
        (
            OutlineEntry("child", "Details 😀", 20, "root", OutlineTarget("anchor", "details", extra={"future": True})),
            OutlineEntry("root", "Introduction", 5, target=OutlineTarget("anchor", "intro"), provenance=Provenance("synthetic")),
            OutlineEntry("page", "Page", 40, "root", OutlineTarget("page", "page-1", point=Point2D(30, 50), zoom=1.25)),
            OutlineEntry("external", "External", 10, target=OutlineTarget("external", uri="https://example.invalid/read")),
            OutlineEntry("unknown", "", 80),
        ),
        extra={"future": {"value": 1}},
    )
    set_outline(document, outline)
    return document, outline, geometry


def test_json_round_trips_and_page_coordinates():
    document, outline, geometry = fixture_document()
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_outline(document) == outline
        assert get_integration(document).extra["unknown"] == [1]
        assert document.validate() == []
        assert check_document(document).success
    target = get_outline(document).entries[2].target
    assert page_point_to_display(geometry, target.point) == Point2D(670, 20)
    doc_v1 = deepcopy(document)
    doc_v1.version = 1
    assert get_outline(document_from_json(document_to_json(doc_v1))) == outline


def test_merge_selects_whole_envelope_and_rewrites_anchor_targets():
    document, outline, _ = fixture_document()
    first = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_first")
    last = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_last")
    assert get_outline(first.document) == outline
    expected = remap_outline(outline, anchor_ids=last.id_maps[1].anchors)
    assert get_outline(last.document) == expected
    assert expected.entries[0].target.target_id == "details~2"
    assert expected.entries[2].target.target_id == "page-1"
    assert expected.entries[0].id == "child"
    assert len(expected.entries) == 5
    assert get_outline(document) == outline
    with pytest.raises(ValueError, match="metadata"):
        merge_documents([document, document], conflicts="rename")


def test_extract_closes_destinations_and_copies_unknown_fields():
    document, outline, _ = fixture_document()
    selected = extract_document(document, next(iter_elements(document, Paragraph)))
    assert len(selected.sections) == 2
    assert get_outline(selected) == outline
    independent = get_outline(selected)
    independent.extra["future"]["value"] = 2
    assert get_outline(document) == outline
    assert get_outline(selected) == outline


def test_remap_entry_parent_anchor_and_page_domains():
    _, outline, _ = fixture_document()
    mapped = remap_outline(
        outline,
        entry_ids={"root": "root-new", "child": "child-new"},
        anchor_ids={"details": "details-new"},
        page_ids={"page-1": "page-new"},
    )
    assert mapped.entries[0].id == "child-new"
    assert mapped.entries[0].parent_id == "root-new"
    assert mapped.entries[0].target.target_id == "details-new"
    assert mapped.entries[2].target.target_id == "page-new"
    assert mapped.entries[3].target == outline.entries[3].target
    assert mapped.entries[0].provenance == outline.entries[0].provenance
    with pytest.raises(ValueError, match="duplicate entry"):
        remap_outline(outline, entry_ids={"child": "root"})
    with pytest.raises(ValueError):
        remap_outline(outline, page_ids={"page-1": ""})
    assert outline.entries[0].id == "child"


@pytest.mark.parametrize("mutation", ["duplicate-id", "duplicate-order", "parent", "cycle", "anchor", "page"])
def test_invalid_hierarchy_and_targets_are_atomic(mutation):
    document, outline, _ = fixture_document()
    entries = list(outline.entries)
    if mutation == "duplicate-id":
        entries[0] = replace(entries[0], id="root")
    elif mutation == "duplicate-order":
        entries[0] = replace(entries[0], order=40)
    elif mutation == "parent":
        entries[0] = replace(entries[0], parent_id="absent")
    elif mutation == "cycle":
        entries[1] = replace(entries[1], parent_id="child")
    elif mutation == "anchor":
        entries[0] = replace(entries[0], target=OutlineTarget("anchor", "absent"))
    else:
        entries[0] = replace(entries[0], target=OutlineTarget("page", "absent"))
    before = deepcopy(document.metadata)
    with pytest.raises(ValueError):
        set_outline(document, replace(outline, entries=tuple(entries)))
    assert document.metadata == before


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "other"},
        {"kind": "anchor"},
        {"kind": "anchor", "target_id": "id", "uri": "uri"},
        {"kind": "anchor", "target_id": "id", "zoom": 1.0},
        {"kind": "external", "uri": "uri", "target_id": "id"},
        {"kind": "external", "uri": ""},
        {"kind": "page", "target_id": "page", "zoom": 0},
        {"kind": "page", "target_id": "page", "zoom": True},
        {"kind": "page", "target_id": "page", "zoom": float("inf")},
        {"kind": "page", "target_id": "page", "point": Point2D(float("nan"), 0)},
    ],
)
def test_invalid_destination_values(kwargs):
    with pytest.raises(ValueError):
        OutlineTarget(**kwargs)


def test_structural_edit_cannot_leave_dangling_destination():
    document, outline, _ = fixture_document()
    original = document_to_json(document)
    with pytest.raises(ValueError, match="outline|integration"):
        remove_node(document, list(iter_elements(document, Paragraph))[1])
    assert document_to_json(document) == original
    assert get_outline(document) == outline


def test_unknown_data_collisions_versions_and_atomic_removal():
    document, outline, _ = fixture_document()
    raw = document.metadata[INTEGRATION_PROPERTY]["data"][OUTLINE_PROPERTY]
    for version in (True, 2, "1"):
        raw["version"] = version
        with pytest.raises(ValueError, match="version"):
            get_outline(document)
        assert not check_document(document).success
    raw["version"] = 1
    set_outline(document, Outline(outline.entries))
    assert get_outline(document).extra == outline.extra
    set_outline(document, None)
    assert get_outline(document) is None
    assert get_integration(document).pages
    assert get_integration(document).extra["unknown"] == [1]
    model = replace(get_integration(document), extra={OUTLINE_PROPERTY: {"private": "opaque"}})
    set_integration(document, model)
    assert get_outline(document) is None
    before = deepcopy(document.metadata)
    for value in (outline, None):
        with pytest.raises(ValueError, match="opaque"):
            set_outline(document, value)
        assert document.metadata == before


def test_limits_extra_cycles_and_shadowed_fields():
    document, outline, _ = fixture_document()
    before = document_to_json(document)
    for extras in ({"entries": []}, {"version": 1}, {"extra": {}}):
        with pytest.raises(ValueError):
            set_outline(document, replace(outline, extra=extras))
    cycle = {}
    cycle["cycle"] = cycle
    with pytest.raises(ValueError):
        set_outline(document, replace(outline, extra=cycle))
    with pytest.raises(ArtifactLimitError):
        set_outline(document, outline, limits=DocumentLimits(max_nodes=2))
    assert document_to_json(document) == before
    # The flat JSON fits depth 12; a parent chain of 13 must still fail.
    chain = Outline(tuple(OutlineEntry(str(i), "", 0, str(i - 1) if i else None) for i in range(13)))
    with pytest.raises(ArtifactLimitError, match="hierarchy depth"):
        set_outline(DocumentModel(), chain, limits=DocumentLimits(max_depth=12))


def test_new_outline_and_none_do_not_require_existing_integration():
    document = DocumentModel()
    set_outline(document, None)
    assert document.metadata == {}
    set_outline(document, Outline((OutlineEntry("external", "", 0, target=OutlineTarget("external", uri="urn:test")),)))
    assert len(get_outline(document).entries) == 1
    assert document.validate() == []


@pytest.mark.parametrize("opaque", [None, False, 0, "private", []])
def test_unmarked_outline_key_is_never_replaced_or_removed(opaque):
    document = DocumentModel()
    set_integration(document, IntegrationModel(extra={OUTLINE_PROPERTY: opaque}))
    before = document_to_json(document)
    assert get_outline(document) is None
    for value in (Outline(), None):
        with pytest.raises(ValueError, match="opaque"):
            set_outline(document, value)
        assert document_to_json(document) == before
