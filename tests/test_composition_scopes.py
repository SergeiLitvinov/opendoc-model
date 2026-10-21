"""Generated IDs, dependency closure and explicit split/merge remain reference-safe."""

from copy import deepcopy

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    Chart,
    Diagram,
    DocumentLimits,
    DocumentModel,
    Field,
    FontReference,
    IntegrationModel,
    InternalLink,
    ListItem,
    MediaObject,
    Paragraph,
    Resource,
    ResourceKind,
    SceneOccurrence,
    Section,
    TextRun,
    TextStyle,
    Timing,
    VectorScene,
    document_from_json,
    document_to_json,
    extract_document,
    get_font_reference,
    get_integration,
    get_internal_link,
    get_list_item,
    iter_elements,
    iter_sections,
    merge_documents,
    set_anchor,
    set_font_reference,
    set_integration,
    set_internal_link,
    set_list_item,
)


def _paragraph(identifier, text):
    result = Paragraph([TextRun(text)])
    set_anchor(result, Anchor(identifier))
    return result


def _model(kind):
    common = {
        "timing": (Timing("event", "a~2", 0, 1),),
        "fields": (Field("field", "reference", target_id="a"),),
        "extra": {"historical": {"target_id": "a"}},
    }
    if kind == "scenes":
        common["scenes"] = (
            VectorScene("a~2", 10, 10, roots=("paint",), occurrences=(SceneOccurrence("paint", "a"),), scope_version=1),
        )
    elif kind == "charts":
        common["charts"] = (Chart("a~2", "bar", (), node_id="a"),)
    elif kind == "diagrams":
        common["scenes"] = (VectorScene("support", 10, 10),)
        common["diagrams"] = (Diagram("a~2", "support", node_id="a"),)
    else:
        common["media"] = (MediaObject("a~2", "sound", "audio", node_id="a"),)
    return IntegrationModel(**common)


def _inputs(kind):
    first = DocumentModel(sections=[Section(blocks=[_paragraph("a", "First")])])
    head = _paragraph("a", "Second")
    continuation = Paragraph([TextRun("Continuation")])
    set_list_item(head, ListItem("items"))
    set_list_item(continuation, ListItem("items", continuation_of="a"))
    set_internal_link(continuation.content[0], InternalLink("a"))
    style = TextStyle()
    set_font_reference(style, FontReference("font"))
    head.style_id = "body"
    second = DocumentModel(
        sections=[Section(blocks=[head, continuation])],
        styles={"body": style},
        resources={
            "sound": Resource("sound", ResourceKind.ATTACHMENT, "audio/own", b"own audio bytes"),
            "font": Resource("font", ResourceKind.FONT, "font/own", b"own opaque font"),
        },
    )
    set_integration(second, _model(kind))
    return first, second


@pytest.mark.parametrize("kind", ["media", "scenes", "charts", "diagrams"])
def test_generated_anchor_id_does_not_collide_with_integration_targets(kind):
    first, second = _inputs(kind)
    before = deepcopy((first, second))
    merged = merge_documents([first, second], conflicts="rename")
    assert merged.id_maps[1].anchors == {"a": "a~3"}
    result = merged.document
    for _ in range(2):
        result = document_from_json(document_to_json(result))
        model = get_integration(result)
        assert model.timing[0].target_id == "a~2"
        assert model.fields[0].target_id == "a~3"
        record = getattr(model, kind)[0]
        if kind == "scenes":
            assert record.occurrences[0].node_id == "a~3"
        else:
            assert record.node_id == "a~3"
        assert model.extra["historical"] == {"target_id": "a"}
        continuation = result.sections[1].blocks[1]
        assert get_list_item(continuation).continuation_of == "a~3"
        assert get_internal_link(continuation.content[0]).target_id == "a~3"
        assert get_font_reference(result.styles["body"]).resource_id == "font"
        assert result.validate() == []
    assert (first, second) == before


@pytest.mark.parametrize("kind", ["media", "scenes", "charts", "diagrams"])
def test_split_extract_merge_preserves_targets_resources_and_json(kind):
    first, second = _inputs(kind)
    before = document_to_json(second)
    selected = extract_document(second, list(iter_elements(second, Paragraph))[1])
    assert selected.sections == second.sections  # Links close back to the containing section.
    expected_resources = {"sound", "font"} if kind == "media" else {"font"}
    assert set(selected.resources) == expected_resources
    parts = [extract_document(first, next(iter_sections(first))), selected]
    for index, part in enumerate(parts):
        for _ in range(2):
            part = document_from_json(document_to_json(part))
        parts[index] = part
    joined = merge_documents(parts, conflicts="rename")
    assert get_integration(joined.document).timing[0].target_id == "a~2"
    assert joined.id_maps[1].anchors["a"] == "a~3"
    assert set(joined.document.resources) == expected_resources
    assert document_to_json(second) == before


def test_suffixes_reserve_original_anchor_names_too_and_limits_leave_inputs_intact():
    first, second = _inputs("scenes")
    third = DocumentModel(sections=[Section(blocks=[_paragraph("a~3", "Third")])])
    before = deepcopy((first, second, third))
    merged = merge_documents([first, second, third], conflicts="rename")
    assert merged.id_maps[1].anchors == {"a": "a~4"}
    assert merged.id_maps[2].anchors == {"a~3": "a~3"}
    with pytest.raises(ArtifactLimitError):
        merge_documents([first, second, third], conflicts="rename", limits=DocumentLimits(max_nodes=10))
    with pytest.raises(ValueError, match="conflict"):
        merge_documents([first, second])
    assert (first, second, third) == before


def test_font_resource_and_style_conflicts_keep_exact_links_alongside_timing():
    first, second = _inputs("scenes")
    first.resources["font"] = deepcopy(second.resources["font"])
    first.styles["body"] = deepcopy(second.styles["body"])
    merged = merge_documents([first, second], conflicts="rename")
    mapping = merged.id_maps[1]
    paragraph = merged.document.sections[1].blocks[0]
    assert paragraph.style_id == mapping.styles["body"] == "body~2"
    assert get_font_reference(merged.document.styles[paragraph.style_id]).resource_id == mapping.resources["font"] == "font~2"
    assert get_integration(merged.document).timing[0].target_id == "a~2"
    assert document_from_json(document_to_json(merged.document)) == merged.document


def test_custom_budget_reaches_reserved_id_scan_without_default_reset():
    first, second = _inputs("scenes")
    second.metadata["opendoc.integration"]["data"]["custom"] = [None] * 100_001
    limits = DocumentLimits(max_nodes=300_000)
    with pytest.raises(ArtifactLimitError):
        merge_documents([first, second], conflicts="rename")
    result = merge_documents([first, second], conflicts="rename", limits=limits).document
    for _ in range(2):
        result = document_from_json(document_to_json(result, limits=limits), limits=limits)
    assert get_integration(result, limits=limits).timing[0].target_id == "a~2"


def test_existing_cross_domain_ambiguity_still_refuses_without_guessing_new_scene_ids():
    first, second = _inputs("scenes")
    set_anchor(first.sections[0].blocks[0], Anchor("a~2"))
    before = deepcopy((first, second))
    with pytest.raises(ValueError, match="ambiguous target"):
        merge_documents([first, second], conflicts="rename")
    assert (first, second) == before
