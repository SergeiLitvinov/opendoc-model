"""Placed glyph contracts remain independent of parsers, shaping and renderers."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    AffineTransform,
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    DocumentPage,
    FontReference,
    IntegrationModel,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    TextCluster,
    TextLayout,
    TextPosition,
    TextRange,
    TextRun,
    VectorScene,
    check_document,
    clone_model,
    document_from_json,
    document_to_json,
    edit_anchored_text,
    extract_document,
    get_integration,
    get_text_layout,
    integration_from_dict,
    integration_resource_uses,
    integration_to_dict,
    invalidate_text_layout,
    invalidate_text_layouts,
    iter_elements,
    merge_documents,
    remove_node,
    remove_resource,
    remove_text_layout,
    set_anchor,
    set_integration,
    set_text_layout,
    set_text_layouts,
)


def _document():
    first, second = TextRun("fi a\u0301 😀אב"), TextRun("tail")
    set_anchor(first, Anchor("first"))
    set_anchor(second, Anchor("second"))
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([first, second])])],
        resources={"font": Resource("font", ResourceKind.FONT, "font/own", b"own opaque program")},
    )
    set_integration(
        document,
        IntegrationModel(
            ranges=(
                TextRange("ligature", TextPosition("first", 0), TextPosition("first", 2)),
                TextRange("combining", TextPosition("first", 3), TextPosition("first", 5)),
                TextRange("one", TextPosition("first", 3), TextPosition("first", 4)),
                TextRange("cross", TextPosition("first", 7), TextPosition("second", 2)),
            ),
            pages=(DocumentPage("page", 200, 300),),
            scenes=(VectorScene("scene", 200, 300),),
        ),
    )
    return document


def _glyph(x=10, y=20, font=0, gid=42):
    return font, gid, 1, 0, 0, 1, x, y


def _layout(identifier="fill"):
    return TextLayout(
        identifier,
        glyphs=(_glyph(), _glyph(30), _glyph(28, 22)),
        fonts=(FontReference("font", 0),),
        clusters=(
            TextCluster((0,), ("ligature",)),
            TextCluster((1, 2), ("one", "combining")),
        ),
        page_id="page",
        scene_id="scene",
        provenance=Provenance("own", object_id="placed", events=[ProvenanceEvent("observe", detail="own")]),
        extra={"future": {"values": [1]}},
        transform=AffineTransform(0, 1, -1, 0, 12, 34, extra={"own": [1]}),
    )


def test_many_to_many_two_occurrences_and_two_json_cycles_preserve_exact_data():
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    set_text_layout(document, replace(_layout("stroke"), glyphs=(_glyph(70), _glyph(50), _glyph(48, 22))), verify=True)
    before = document_to_json(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert document_to_json(document) == before
        fill, stroke = get_text_layout(document, "fill"), get_text_layout(document, "stroke")
        assert fill.state == stroke.state == "verified"
        assert fill.glyphs != stroke.glyphs
        assert fill.clusters[0].glyph_indices == (0,) and fill.clusters[0].range_ids == ("ligature",)
        assert fill.clusters[1].glyph_indices == (1, 2)
        assert document.validate() == []
    restored = clone_model(document)
    assert restored == document
    get_text_layout(restored, "fill").extra["future"]["values"].append(2)
    get_text_layout(restored, "fill").provenance.events[0].detail = "independent"
    assert document_to_json(document) == before


def test_cross_run_ranges_unknown_glyph_font_and_mapping_do_not_infer_defaults():
    document = _document()
    unknown = TextLayout("unknown", glyphs=(_glyph(font=None, gid=None),), clusters=(TextCluster((0,)),))
    set_text_layout(document, unknown)
    value = get_text_layout(document, "unknown")
    assert value.state == "unknown" and value.fonts == () and value.clusters[0].range_ids == ()
    assert value.page_id is value.scene_id is None
    cross = replace(_layout("cross"), glyphs=(_glyph(),), clusters=(TextCluster((0,), ("cross",)),))
    set_text_layout(document, cross, verify=True)
    assert get_text_layout(document, "cross").state == "verified"
    document.sections[0].blocks[0].content[1].text = "changed"
    assert get_text_layout(document, "cross").state == "stale"
    assert get_text_layout(document, "unknown").state == "unknown"


@pytest.mark.parametrize(
    "change", ["text", "run_style", "named_style", "font_program", "font_kind", "geometry", "page", "alignment"]
)
def test_direct_edits_are_stale_and_cannot_be_serialized_as_verified(change):
    from opendoc_model import TextStyle

    document = _document()
    set_text_layout(document, _layout(), verify=True)
    if change == "text":
        document.sections[0].blocks[0].content[0].text = "FI á 😀אב"
    elif change == "run_style":
        document.sections[0].blocks[0].content[0].style.bold = True
    elif change == "named_style":
        document.styles["new"] = TextStyle(italic=True)
    elif change == "font_program":
        document.resources["font"].data = b"changed program"
    elif change == "font_kind":
        document.resources["font"].kind = ResourceKind.ATTACHMENT
    elif change == "page":
        document.metadata["opendoc.integration"]["data"]["pages"][0]["width"] = 999
    elif change == "alignment":
        document.sections[0].blocks[0].alignment = "right"
    else:
        get = document.metadata["opendoc.integration"]["data"]["text_layouts"][0]
        get["glyphs"][0][6] = 111
    assert get_text_layout(document, "fill").state == "stale"
    assert any(issue.code == "text-layout.invalid" for issue in check_document(document).issues)
    with pytest.raises(ValueError):
        document_to_json(document)
    if change == "font_kind":
        document.resources["font"].kind = ResourceKind.FONT
    invalidate_text_layout(document, "fill")
    assert get_text_layout(document, "fill").state == "stale"
    assert document.validate() == []


def test_range_aware_edit_invalidates_without_changing_source_or_guessing_new_glyphs():
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    before = document_to_json(document)
    result = edit_anchored_text(document, "first", 0, 2, "ffi")
    assert get_text_layout(result, "fill").state == "stale"
    assert get_text_layout(result, "fill").glyphs == get_text_layout(document, "fill").glyphs
    assert document_to_json(document) == before
    assert document_from_json(document_to_json(result)) == result


def test_merge_extract_resource_remap_and_font_removal_follow_existing_maps():
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    before = document_to_json(document)
    merged = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_last")
    layout = get_text_layout(merged.document, "fill")
    assert layout.state == "stale"
    assert layout.fonts[0].resource_id == merged.id_maps[1].resources["font"]
    assert get_integration(merged.document).ranges[0].start.node_id == merged.id_maps[1].anchors["first"]
    selected = extract_document(document, next(iter_elements(document, TextRun)))
    assert get_text_layout(selected, "fill").state == "stale"
    assert set(selected.resources) == {"font"}
    assert selected.validate() == [] and document_to_json(document) == before
    assert integration_resource_uses(document, "font")
    with pytest.raises(ValueError):
        remove_resource(document, "font")
    document.resources["replacement"] = Resource("replacement", ResourceKind.FONT, "font/own", b"replacement")
    remove_resource(document, "font", replacement_id="replacement")
    assert get_text_layout(document, "fill").fonts[0].resource_id == "replacement"
    assert get_text_layout(document, "fill").state == "stale"


def test_delete_is_atomic_and_detachment_is_explicit():
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    before = document_to_json(document)
    with pytest.raises(ValueError):
        remove_node(document, next(iter_elements(document, TextRun)))
    assert document_to_json(document) == before
    invalidate_text_layout(document, "fill", detach=True)
    assert all(not value.range_ids for value in get_text_layout(document, "fill").clusters)
    model = get_integration(document)
    set_integration(document, replace(model, ranges=()))
    remove_node(document, next(iter_elements(document, TextRun)))
    assert document.validate() == []
    remove_text_layout(document, "fill")
    assert get_text_layout(document, "fill") is None and "font" in document.resources


@pytest.mark.parametrize(
    "change",
    [
        {"glyphs": ((0, -1, 1, 0, 0, 1, 0, 0),)},
        {"glyphs": ((-1, 4, 1, 0, 0, 1, 0, 0),)},
        {"glyphs": ((_glyph(font=None, gid=4)),)},
        {"glyphs": ((_glyph(font=9)),)},
        {"glyphs": ((0, 4, float("nan"), 0, 0, 1, 0, 0),)},
        {"glyphs": ((0, 4, float("inf"), 0, 0, 1, 0, 0),)},
        {"glyphs": ((0, 4, "x", 0, 0, 1, 0, 0),)},
        {"glyphs": ((0, 4, 1, 0),)},
        {"glyphs": ((True, 4, 1, 0, 0, 1, 0, 0),)},
        {"glyphs": ((0, True, 1, 0, 0, 1, 0, 0),)},
        {"transform": AffineTransform(a=float("inf"))},
        {"fonts": (FontReference("font"),)},
        {"clusters": (TextCluster((-1,), ("one",)),)},
        {"clusters": (TextCluster((4,), ("one",)),)},
        {"clusters": (TextCluster((0, 0), ("one",)),)},
        {"clusters": (TextCluster((0,), ("one", "one")),)},
        {"page_id": "absent"},
        {"scene_id": "absent"},
        {"fonts": (FontReference("absent", 0),)},
        {"clusters": (TextCluster((0,), ("absent",)),)},
        {"state": "current"},
        {"binding_sha256": "bad"},
        {"extra": {"glyphs": []}},
    ],
)
def test_bad_declarations_fail_atomically_with_paths(change):
    document = _document()
    before = document_to_json(document)
    with pytest.raises(ValueError) as caught:
        set_text_layout(document, replace(_layout(), **change))
    assert "layout" in str(caught.value) or "integration" in str(caught.value)
    assert document_to_json(document) == before


def test_wrong_font_kind_face_and_unowned_verification_are_rejected():
    document = _document()
    document.resources["font"].kind = ResourceKind.ATTACHMENT
    before = document_to_json(document)
    with pytest.raises(ValueError, match="FONT"):
        set_text_layout(document, _layout())
    assert document_to_json(document) == before
    with pytest.raises(ValueError):
        FontReference("font", -1)
    model = IntegrationModel(text_layouts=(_layout(),))
    # Standalone transport has no owner to resolve references, like the rest of the integration codec.
    assert integration_from_dict(integration_to_dict(model)) == model
    with pytest.raises(ValueError):
        set_text_layout(document, TextLayout("empty"), verify=True)


def test_layout_absence_preserves_old_wire_and_exact_minimal_budget():
    raw = {"format": "opendoc.integration", "version": 1, "data": {}}
    model = integration_from_dict(raw, limits=DocumentLimits(max_nodes=4))
    encoded = integration_to_dict(model)
    assert "text_layouts" not in encoded["data"]
    document = DocumentModel()
    assert "text_layouts" not in document_to_json(document)
    assert get_text_layout(document, "absent") is None


def test_limits_large_glyph_arrays_and_large_unknown_fields_remain_bounded():
    document = _document()
    glyphs = tuple(_glyph(index) for index in range(12_000))
    layout = replace(_layout(), glyphs=glyphs, clusters=(), extra={"future": [None] * 100_001})
    before = document_to_json(document)
    with pytest.raises(ArtifactLimitError):
        set_text_layout(document, layout)
    assert document_to_json(document) == before
    limits = DocumentLimits(max_nodes=500_000)
    set_text_layout(document, layout, limits=limits)
    for _ in range(2):
        document = document_from_json(document_to_json(document, limits=limits), limits=limits)
    assert len(get_text_layout(document, "fill", limits=limits).glyphs) == 12_000
    current = document.metadata
    with pytest.raises(ArtifactLimitError) as caught:
        get_text_layout(document, "fill", limits=replace(limits, max_embedded_bytes=0))
    assert caught.value.quota == "embedded bytes" and caught.value.maximum == 0
    assert document.metadata is current


def test_unicode_offsets_and_explicit_unknown_face_are_preserved():
    document = _document()
    model = get_integration(document)
    set_integration(
        document, replace(model, ranges=model.ranges + (TextRange("emoji", TextPosition("first", 6), TextPosition("first", 7)),))
    )
    layout = replace(_layout("emoji"), glyphs=(_glyph(),), clusters=(TextCluster((0,), ("emoji",)),))
    set_text_layout(document, layout, verify=True)
    changed = edit_anchored_text(document, "first", 6, 7, "X")
    assert changed.sections[0].blocks[0].content[0].text == "fi á Xאב"
    assert get_text_layout(changed, "emoji").state == "stale"
    unknown = TextLayout("face", glyphs=(_glyph(gid=None),), fonts=(FontReference("font"),))
    set_text_layout(document, unknown)
    assert get_text_layout(document_from_json(document_to_json(document)), "face").fonts[0].face_index is None


def test_raw_dangling_range_offset_and_duplicate_occurrences_are_refused():
    document = _document()
    set_text_layout(document, _layout())
    for mutate in (
        lambda data: data["ranges"][0]["end"].update(offset=999),
        lambda data: data["text_layouts"].append(deepcopy(data["text_layouts"][0])),
        lambda data: data["text_layouts"][0]["clusters"][0].update(range_ids=["missing"]),
    ):
        payload = json.loads(document_to_json(document))
        mutate(payload["document"]["metadata"]["opendoc.integration"]["data"])
        with pytest.raises(ValueError):
            document_from_json(json.dumps(payload))


def test_verified_layout_uses_compact_rows_and_old_glyph_budget_is_not_bypassed():
    document = _document()
    before = document_to_json(document)
    layout = replace(_layout(), glyphs=tuple(_glyph(index) for index in range(12_000)), clusters=())
    with pytest.raises(ArtifactLimitError):
        set_text_layout(document, layout)
    assert document_to_json(document) == before
    set_text_layout(document, _layout(), verify=True)
    wire = json.loads(document_to_json(document))["document"]["metadata"]["opendoc.integration"]["data"]["text_layouts"][0]
    assert len(wire["fonts"]) == 1
    assert all(type(row) is list and len(row) == 8 for row in wire["glyphs"])
    assert all(type(value) is not dict for row in wire["glyphs"] for value in row)


def test_integer_lengths_do_not_spuriously_stale_after_json_normalization():
    from opendoc_model import Length, TextStyle

    document = _document()
    document.sections[0].blocks[0].content[0].style.font_size = Length(12)
    document.styles["own"] = TextStyle(font_size=Length(13))
    set_text_layout(document, _layout(), verify=True)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_text_layout(document, "fill").state == "verified"


def test_runtime_type_introspection_resolves_optional_layouts():
    from typing import get_type_hints

    assert get_type_hints(IntegrationModel)["text_layouts"] == tuple[TextLayout, ...]


def test_total_binding_work_is_bounded_without_changing_the_document():
    document = _document()
    for index in range(30):
        set_text_layout(document, _layout(f"paint-{index}"), verify=True)
    before = document_to_json(document)
    with pytest.raises(ArtifactLimitError) as caught:
        check_document(document, limits=DocumentLimits(max_nodes=4000))
    assert caught.value.quota == "layout binding work" and caught.value.maximum == 4000
    assert document_to_json(document) == before


def _directly_edited_occurrences():
    document = _document()
    set_text_layout(document, _layout("fill"), verify=True)
    set_text_layout(document, _layout("stroke"), verify=True)
    set_text_layout(document, _layout("unknown"))
    document.sections[0].blocks[0].content[0].text = "FI á 😀אב"
    assert get_text_layout(document, "fill").state == get_text_layout(document, "stroke").state == "stale"
    return document


@pytest.mark.parametrize("selected", [("fill", "stroke"), None])
def test_batch_invalidation_of_fill_stroke_after_direct_edit_preserves_all_data(selected):
    document = _directly_edited_occurrences()
    before = get_integration(document)
    with pytest.raises(ValueError, match="stale"):
        document_to_json(document)
    invalidate_text_layouts(document, selected)
    after = get_integration(document)
    assert after.text_layouts == tuple(
        replace(value, state="stale") if value.state == "verified" else value for value in before.text_layouts
    )
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_text_layout(document, "fill").state == get_text_layout(document, "stroke").state == "stale"
        assert get_text_layout(document, "unknown").state == "unknown"


def test_partial_invalidation_is_rejected_atomically_including_single_helper():
    document = _directly_edited_occurrences()
    before = deepcopy(document)
    metadata = document.metadata
    with pytest.raises(ValueError, match="stale"):
        invalidate_text_layout(document, "fill")
    assert document == before and document.metadata is metadata
    with pytest.raises(ValueError, match="stale"):
        invalidate_text_layouts(document, ("stroke",))
    assert document == before and document.metadata is metadata


def test_batch_does_not_waive_dangling_font_or_range_references():
    for kind in ("font", "range"):
        document = _directly_edited_occurrences()
        if kind == "font":
            del document.resources["font"]
        else:
            document.metadata["opendoc.integration"]["data"]["ranges"] = []
        before = deepcopy(document)
        metadata = document.metadata
        with pytest.raises(ValueError):
            invalidate_text_layouts(document)
        assert document == before and document.metadata is metadata


@pytest.mark.parametrize("selected", ["fill", ["missing"], [1], ["fill", "missing"], 3])
def test_invalid_batch_selection_is_atomic(selected):
    document = _directly_edited_occurrences()
    before = deepcopy(document)
    with pytest.raises(ValueError):
        invalidate_text_layouts(document, selected)
    assert document == before


def test_batch_detach_and_identifier_budget_preserve_unknown_and_are_bounded():
    document = _directly_edited_occurrences()
    before = deepcopy(document)
    with pytest.raises(ArtifactLimitError) as caught:
        invalidate_text_layouts(document, ("fill" for _ in range(2000)), limits=DocumentLimits(max_nodes=1000))
    assert caught.value.quota == "nodes" and caught.value.maximum == 1000
    assert caught.value.path == "text_layout.ids"
    assert document == before
    invalidate_text_layouts(document, detach=True)
    for value in get_integration(document).text_layouts:
        assert value.state == ("unknown" if value.id == "unknown" else "stale")
        assert value.binding_sha256 is None and all(not cluster.range_ids for cluster in value.clusters)
    assert document.validate() == []


@pytest.mark.parametrize("kind", ["anchors", "paragraph_anchor", "ranges", "pages", "scenes", "font_id"])
def test_ambiguous_owner_context_cannot_remain_verified_or_bypass_validation(kind):
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    if kind == "anchors":
        document.sections[0].blocks.append(deepcopy(document.sections[0].blocks[0]))
    elif kind == "paragraph_anchor":
        set_anchor(document.sections[0].blocks[0], Anchor("first"))
    elif kind == "font_id":
        document.resources["font"].id = "changed"
    else:
        raw = document.metadata["opendoc.integration"]["data"]
        raw[kind].append(deepcopy(raw[kind][0]))
    before = deepcopy(document)
    metadata = document.metadata
    assert get_text_layout(document, "fill").state == "stale"
    assert not check_document(document).success
    with pytest.raises(ValueError):
        document_to_json(document)
    with pytest.raises(ValueError):
        invalidate_text_layouts(document)
    assert document == before and document.metadata is metadata


def test_plain_and_versioned_property_bags_have_the_same_stable_snapshot():
    from opendoc_model import ParagraphProperties

    document = _document()
    document.sections[0].blocks[0].properties = {"own": {"values": [1]}}
    document.resources["font"].properties = ParagraphProperties({"own": [2]})
    assert document.validate() == []
    set_text_layout(document, _layout(), verify=True)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_text_layout(document, "fill").state == "verified"


@pytest.mark.parametrize(
    "kind",
    [
        "run_style",
        "font_size",
        "paragraph_properties",
        "resource_properties",
        "resource_record",
        "paragraph_box",
        "styles",
        "resources",
        "named_style",
    ],
)
def test_malformed_owner_context_has_no_attribute_error_and_no_partial_invalidation(kind):
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    paragraph = document.sections[0].blocks[0]
    if kind == "run_style":
        paragraph.content[0].style = None
    elif kind == "font_size":
        paragraph.content[0].style.font_size = 12
    elif kind == "paragraph_properties":
        paragraph.properties = None
    elif kind == "resource_properties":
        document.resources["font"].properties = None
    elif kind == "resource_record":
        document.resources["font"] = {}
    elif kind == "paragraph_box":
        paragraph.box = {}
    elif kind == "styles":
        document.styles = []
    elif kind == "resources":
        document.resources = []
    else:
        document.styles["broken"] = None
    before = deepcopy(document)
    metadata = document.metadata
    assert get_text_layout(document, "fill").state == "stale"
    assert not check_document(document).success
    with pytest.raises(ValueError):
        invalidate_text_layouts(document)
    assert document == before and document.metadata is metadata


def test_reverification_is_explicit_for_each_occurrence_and_does_not_promote_unknown():
    document = _directly_edited_occurrences()
    invalidate_text_layouts(document)
    before = get_integration(document)
    for identifier in ("fill", "stroke"):
        layout = get_text_layout(document, identifier)
        # A producer must explicitly assert a newly checked mapping; Model does not reshape it.
        set_text_layout(document, layout, verify=True)
        assert get_text_layout(document, identifier).state == "verified"
    assert get_text_layout(document, "unknown").state == "unknown"
    after = get_integration(document)
    assert [value.glyphs for value in before.text_layouts] == [value.glyphs for value in after.text_layouts]
    assert before.text_layouts[0].binding_sha256 != after.text_layouts[0].binding_sha256
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_text_layout(document, "fill").state == get_text_layout(document, "stroke").state == "verified"


@pytest.mark.parametrize(
    "bad,initial",
    [
        (True, 1),
        ("12", 12),
        pytest.param(10**400, 12, id="positive-overflow"),
        pytest.param(-(10**400), 12, id="negative-overflow"),
    ],
)
@pytest.mark.parametrize("context", ["run", "named"])
def test_invalid_length_cannot_compare_equal_after_numeric_coercion(bad, initial, context):
    from opendoc_model import Length, TextStyle

    document = _document()
    style = TextStyle(font_size=Length(initial))
    if context == "run":
        document.sections[0].blocks[0].content[0].style = style
    else:
        document.styles["named"] = style
    set_text_layout(document, _layout(), verify=True)
    style.font_size = Length(bad)
    before = deepcopy(document)
    metadata = document.metadata
    assert get_text_layout(document, "fill").state == "stale"
    assert not check_document(document).success
    for operation in (
        lambda: set_text_layouts(document, (_layout(),), verify=True),
        lambda: invalidate_text_layouts(document),
        lambda: document_to_json(document),
    ):
        with pytest.raises(ValueError):
            operation()
        assert document == before and document.metadata is metadata


@pytest.mark.parametrize(
    "limits,quota,maximum",
    [
        (DocumentLimits(max_bytes=1), "bytes", 1),
        (DocumentLimits(max_depth=1), "depth", 1),
        (DocumentLimits(max_nodes=1), "nodes", 1),
        (DocumentLimits(max_embedded_bytes=0), "embedded bytes", 0),
    ],
)
def test_getter_and_batch_propagate_budget_errors_without_downgrading_or_mutation(limits, quota, maximum):
    document = _document()
    set_text_layout(document, _layout(), verify=True)
    before = deepcopy(document)
    metadata = document.metadata
    for operation in (
        lambda: get_text_layout(document, "fill", limits=limits),
        lambda: invalidate_text_layouts(document, limits=limits),
    ):
        with pytest.raises(ArtifactLimitError) as caught:
            operation()
        assert caught.value.path
        assert caught.value.quota == quota
        assert caught.value.maximum == maximum
        assert document == before and document.metadata is metadata
    assert get_text_layout(document, "fill").state == "verified"


def test_batch_set_merges_extra_keeps_other_registries_and_detaches_inputs_through_two_cycles():
    document = _document()
    set_text_layouts(document, (_layout("fill"), _layout("untouched")), verify=True)
    before = get_integration(document)
    supplied = [_layout("fill"), _layout("stroke")]
    supplied[0].extra.clear()
    supplied[0].extra["new"] = {"values": [2]}
    set_text_layouts(document, iter(supplied))
    after = get_integration(document)
    assert after.ranges == before.ranges and after.pages == before.pages and after.scenes == before.scenes
    assert [value.id for value in after.text_layouts] == ["fill", "untouched", "stroke"]
    assert after.text_layouts[1] == before.text_layouts[1]
    assert after.text_layouts[0].state == after.text_layouts[2].state == "unknown"
    assert after.text_layouts[0].extra == {"future": {"values": [1]}, "new": {"values": [2]}}
    supplied[0].extra["new"]["values"].append(99)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_integration(document) == after


@pytest.mark.parametrize("kind", ["duplicate", "font", "range", "type", "iterable", "budget", "snapshot_budget"])
def test_batch_set_failure_never_commits_a_prefix(kind):
    document = _document()
    set_text_layout(document, _layout("retained"), verify=True)
    supplied = [_layout("first"), _layout("second")]
    limits = None
    if kind == "duplicate":
        supplied[1] = supplied[0]
    elif kind == "font":
        supplied[1] = replace(supplied[1], fonts=(FontReference("missing", 0),))
    elif kind == "range":
        supplied[1] = replace(supplied[1], clusters=(TextCluster((0, 1, 2), ("missing",)),))
    elif kind == "type":
        supplied[1] = {}
    elif kind == "iterable":
        supplied = None
    elif kind == "budget":
        supplied = (_layout(str(index)) for index in range(5000))
        limits = DocumentLimits(max_nodes=1000)
    else:
        supplied = [_layout(str(index)) for index in range(30)]
        limits = DocumentLimits(max_nodes=5000)
    before = deepcopy(document)
    metadata = document.metadata
    with pytest.raises((ValueError, ArtifactLimitError)):
        set_text_layouts(document, supplied, verify=True, limits=limits)
    assert document == before and document.metadata is metadata


def test_batch_reverification_can_replace_all_stale_occurrences_atomically():
    document = _directly_edited_occurrences()
    pending = [get_text_layout(document, identifier) for identifier in ("fill", "stroke")]
    set_text_layouts(document, pending, verify=True)
    assert get_text_layout(document, "fill").state == get_text_layout(document, "stroke").state == "verified"
    assert get_text_layout(document, "unknown").state == "unknown"
    assert document.validate() == []


def test_batch_set_snapshot_work_is_linear_and_owner_validation_runs_once(monkeypatch):
    import opendoc_model._validation as validation
    import opendoc_model.text_layout as layout_module

    fingerprint = layout_module._fingerprint
    validate = validation._validate_model
    walks = layout_module._walk_locations
    counts = dict(snapshots=0, validations=0, walks=0)

    def counted_snapshot(*args, **kwargs):
        counts["snapshots"] += 1
        return fingerprint(*args, **kwargs)

    def counted_validation(*args, **kwargs):
        counts["validations"] += 1
        return validate(*args, **kwargs)

    def counted_walk(*args, **kwargs):
        counts["walks"] += 1
        return walks(*args, **kwargs)

    monkeypatch.setattr(layout_module, "_fingerprint", counted_snapshot)
    monkeypatch.setattr(validation, "_validate_model", counted_validation)
    monkeypatch.setattr(layout_module, "_walk_locations", counted_walk)
    for size in (8, 16):
        document = _document()
        counts.update(snapshots=0, validations=0, walks=0)
        set_text_layouts(document, [_layout(str(index)) for index in range(size)], verify=True)
        assert counts == dict(snapshots=2 * size, validations=1, walks=2)
    document = _document()
    counts.update(snapshots=0, validations=0, walks=0)
    for index in range(16):
        set_text_layout(document, _layout(str(index)), verify=True)
    assert counts["validations"] == 16
    assert counts["snapshots"] > 4 * 16


def test_legacy_snapshot_from_consumer4_remains_verified_without_wire_changes():
    run = TextRun("fi")
    set_anchor(run, Anchor("first"))
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([run])])],
        resources={"font": Resource("font", ResourceKind.FONT, "font/own", b"font")},
    )
    # This SHA was produced by the preserved consumer4 wheel, not the current codec.
    legacy_sha = "cb264f6725f394aa3f85ed1abcfe08c2e30d5cb15fac2e1b70ef9faec2b1f09e"
    layout = TextLayout(
        "legacy",
        fonts=(FontReference("font", 0),),
        glyphs=(_glyph(),),
        clusters=(TextCluster((0,), ("fi",)),),
        state="verified",
        binding_sha256=legacy_sha,
    )
    set_integration(
        document,
        IntegrationModel(ranges=(TextRange("fi", TextPosition("first", 0), TextPosition("first", 2)),), text_layouts=(layout,)),
    )
    for _ in range(2):
        wire = document_to_json(document)
        assert '"binding_version"' not in wire
        document = document_from_json(wire)
        current = get_text_layout(document, "legacy")
        assert current == layout and current.binding_version == 1
    set_text_layout(document, current, verify=True)
    upgraded = get_text_layout(document, "legacy")
    assert upgraded.binding_version == 2 and upgraded.binding_sha256 != legacy_sha
    assert upgraded.glyphs == layout.glyphs and upgraded.state == "verified"
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_text_layout(document, "legacy") == upgraded


def test_cluster_snapshots_store_unique_owners_with_linear_bytes_and_style_visits(monkeypatch):
    import opendoc_model.document_codec as codec
    import opendoc_model.text_layout as layout_module

    dumps = layout_module.json.dumps
    style = codec._style_to_dict
    payloads = []
    styles = []

    def capture(value, *args, **kwargs):
        if isinstance(value, dict) and "selections" in value:
            payloads.append(value)
        return dumps(value, *args, **kwargs)

    def counted_style(value):
        styles.append(value)
        return style(value)

    monkeypatch.setattr(layout_module.json, "dumps", capture)
    monkeypatch.setattr(codec, "_style_to_dict", counted_style)
    sizes = []
    limits = DocumentLimits(max_bytes=1_000_000, max_nodes=200_000)
    for size in (1000, 2000):
        run = TextRun("x" * size)
        set_anchor(run, Anchor("text"))
        document = DocumentModel(sections=[Section(blocks=[Paragraph([run])])])
        ranges = tuple(TextRange(str(i), TextPosition("text", i), TextPosition("text", i + 1)) for i in range(size))
        set_integration(document, IntegrationModel(ranges=ranges), limits=limits)
        layout = TextLayout(
            "clusters",
            glyphs=tuple(_glyph(index, font=None, gid=None) for index in range(size)),
            clusters=tuple(TextCluster((i,), (str(i),)) for i in range(size)),
        )
        payloads.clear()
        styles.clear()
        set_text_layouts(document, (layout,), verify=True, limits=limits)
        assert len(payloads) == 2 and len(styles) == 2
        payload = payloads[0]
        assert len(payload["owners"]) == 1 and payload["owners"][0]["text"] == run.text
        assert len(payload["selections"]) == size
        assert all(value["owners"] == [0] for value in payload["selections"])
        sizes.append(len(dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
        for _ in range(2):
            document = document_from_json(document_to_json(document, limits=limits), limits=limits)
            assert get_text_layout(document, "clusters", limits=limits).state == "verified"
        document.sections[0].blocks[0].content[0].text = "y" + run.text[1:]
        assert get_text_layout(document, "clusters", limits=limits).state == "stale"
    assert sizes[1] < 2.2 * sizes[0] < limits.max_bytes


@pytest.mark.parametrize("version", [True, 0, 3, "2"])
def test_unknown_binding_versions_are_rejected_without_mutation(version):
    document = _document()
    before = deepcopy(document)
    with pytest.raises(ValueError):
        set_text_layout(document, replace(_layout(), binding_version=version), verify=True)
    assert document == before
