"""Explicit list boundaries use the existing anchor and composition contracts."""

import json
from dataclasses import replace

import pytest

from opendoc_model import (
    LIST_PROPERTY,
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    ListItem,
    Paragraph,
    Section,
    TextRun,
    check_document,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    extract_document,
    get_anchor,
    get_list_item,
    iter_elements,
    iter_list_numbers,
    merge_documents,
    remove_node,
    set_anchor,
    set_list_item,
)


def _paragraph(text, item=None, anchor=None):
    paragraph = Paragraph([TextRun(text)] if text else [])
    if item is not None:
        set_list_item(paragraph, item)
    if anchor is not None:
        set_anchor(paragraph, Anchor(anchor))
    return paragraph


def _document():
    return DocumentModel(
        sections=[
            Section(
                blocks=[
                    _paragraph("First.", ListItem("a"), "first"),
                    _paragraph("Continuation.", ListItem("a", continuation_of="first")),
                    _paragraph("Outside."),
                    _paragraph("", ListItem("a"), "empty"),
                    _paragraph("Child.", ListItem("children", parent_id="empty"), "child"),
                    _paragraph("Child continuation.", ListItem("children", continuation_of="child", parent_id="empty")),
                    _paragraph("Next.", ListItem("a")),
                ]
            )
        ]
    )


@pytest.mark.parametrize("version", [1, 2])
def test_two_json_cycles_numbering_outside_empty_parent_and_clone(version):
    original = _document()
    document = clone_model(original)
    payload = json.loads(document_to_json(document))
    payload["version"] = version
    document = document_from_json(json.dumps(payload))
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert document == original
        assert document.validate() == []
        assert [entry.number for entry in iter_list_numbers(document)] == [1, None, 2, 1, None, 3]
        assert get_list_item(document.sections[0].blocks[2]) is None
        comparison = compare_documents(original, document)
        diff = comparison.metrics["comparison"]["object_diff"]
        assert diff["lists_available"] and diff["list_numbers_available"]
        assert diff["changed_list_items"] == diff["changed_list_numbers"] == 0
    document.sections[0].blocks[1].content[0].text = "Independent"
    assert original.sections[0].blocks[1].content[0].text == "Continuation."


def test_continuation_does_not_reset_deeper_numbering():
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    _paragraph("head", ListItem("a"), "head"),
                    _paragraph("nested", ListItem("a", level=1, parent_id="head")),
                    _paragraph("continued", ListItem("a", continuation_of="head")),
                    _paragraph("nested again", ListItem("a", level=1, parent_id="head")),
                ]
            )
        ]
    )
    assert [entry.number for entry in iter_list_numbers(document)] == [1, 1, None, 2]


def test_merge_remaps_references_and_keeps_unknown_properties_opaque():
    source = _document()
    source.sections[0].blocks[1].properties[LIST_PROPERTY]["custom"] = {"continuation_of": "first"}
    before = document_to_json(source)
    merged = merge_documents([source, source], conflicts="rename")
    second = merged.document.sections[1].blocks
    ids = merged.id_maps[1]
    assert get_list_item(second[1]).continuation_of == ids.anchors["first"]
    assert get_list_item(second[4]).parent_id == ids.anchors["empty"]
    assert get_list_item(second[5]).continuation_of == ids.anchors["child"]
    assert get_list_item(second[5]).list_id == ids.lists["children"]
    assert second[1].properties[LIST_PROPERTY]["custom"] == {"continuation_of": "first"}
    assert [entry.number for entry in iter_list_numbers(merged.document)] == [1, None, 2, 1, None, 3] * 2
    assert document_to_json(source) == before


@pytest.mark.parametrize("index", [1, 4, 5])
def test_extract_closes_primary_and_parent_dependencies(index):
    source = _document()
    location = list(iter_elements(source, Paragraph))[index]
    extracted = extract_document(source, location)
    assert extracted.validate() == []
    # Existing extraction expands the containing section to close anchor links.
    assert extracted == source
    assert extracted is not source


@pytest.mark.parametrize("index", [0, 3])
def test_removing_primary_or_empty_parent_is_atomic_and_never_promotes(index):
    document = _document()
    before = document_to_json(document)
    location = list(iter_elements(document, Paragraph))[index]
    with pytest.raises(ValueError, match="anchored list paragraph"):
        remove_node(document, location)
    assert document_to_json(document) == before
    # Direct list mutation is possible, but validation and serialization refuse dangling links.
    document.sections[0].blocks.pop(index)
    assert any(issue.code == "semantic.list.reference" for issue in check_document(document).issues)
    with pytest.raises(ValueError):
        document_to_json(document)


def test_explicit_promotion_retargeting_and_removal():
    document = _document()
    blocks = document.sections[0].blocks
    set_list_item(blocks[1], ListItem("a"))
    remove_node(document, list(iter_elements(document, Paragraph))[0])
    assert [entry.number for entry in iter_list_numbers(document)] == [1, 2, 1, None, 3]
    child, continuation = blocks[3], blocks[4]
    set_list_item(child, replace(get_list_item(child), parent_id=None))
    set_list_item(continuation, replace(get_list_item(continuation), parent_id=None))
    remove_node(document, list(iter_elements(document, Paragraph))[2])
    assert document.validate() == []
    assert get_anchor(child).id == "child"


def test_edits_preserve_extensions_delete_owned_links_and_do_not_revive_legacy():
    document = _document()
    paragraph = document.sections[0].blocks[1]
    paragraph.properties[LIST_PROPERTY]["custom"] = [1]
    paragraph.properties["native_list"] = {"continuation_of": "first"}
    set_list_item(paragraph, ListItem("a"))
    bag = paragraph.properties[LIST_PROPERTY]
    assert bag["version"] == 1 and "continuation_of" not in bag
    assert bag["custom"] == [1]
    assert [entry.number for entry in iter_list_numbers(document)][:3] == [1, 2, 3]
    set_list_item(paragraph, None)
    assert get_list_item(paragraph) is None and paragraph.properties["native_list"]
    assert document.validate() == []


@pytest.mark.parametrize(
    "change",
    [
        {"continuation_of": "absent"},
        {"parent_id": "absent"},
        {"continuation_of": "empty"},
        {"parent_id": "child"},
        {"list_id": "different"},
        {"parent_id": "first"},
    ],
)
def test_dangling_forward_and_conflicting_continuations_rejected_before_yield(change):
    document = _document()
    paragraph = document.sections[0].blocks[1]
    set_list_item(paragraph, replace(get_list_item(paragraph), **change))
    with pytest.raises(ValueError):
        next(iter_list_numbers(document))
    assert not check_document(document).success
    with pytest.raises(ValueError):
        document_to_json(document)


def test_wrong_kind_target_chained_continuation_and_parent_cycle():
    document = _document()
    blocks = document.sections[0].blocks
    set_anchor(blocks[2], Anchor("outside"))
    set_list_item(blocks[1], ListItem("a", continuation_of="outside"))
    assert not check_document(document).success
    set_anchor(blocks[1], Anchor("continued"))
    set_list_item(blocks[1], ListItem("a", continuation_of="first"))
    set_list_item(blocks[6], ListItem("a", continuation_of="continued"))
    assert not check_document(document).success
    set_list_item(blocks[6], ListItem("a"))
    set_list_item(blocks[3], ListItem("a", parent_id="child"))
    assert any(issue.code == "semantic.list.cycle" for issue in check_document(document).issues)


@pytest.mark.parametrize(
    "change",
    [
        {"continuation_of": ""},
        {"parent_id": False},
        {"continuation_of": "\ud800"},
        {"continuation_of": "first", "restart": 3},
    ],
)
def test_bad_fields_are_rejected_in_constructor_and_codec(change):
    with pytest.raises(ValueError):
        ListItem("a", **change)
    payload = json.loads(document_to_json(_document()))
    payload["document"]["sections"][0]["blocks"][1]["properties"][LIST_PROPERTY].update(change)
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))


def test_old_json_positional_constructor_and_opaque_v1_fields_stay_compatible():
    paragraph = _paragraph("Old", ListItem("a", 1, "ordered", 3, 5))
    expected = {"format": LIST_PROPERTY, "version": 1, "list_id": "a", "level": 1, "kind": "ordered", "start": 3, "restart": 5}
    assert paragraph.properties[LIST_PROPERTY] == expected
    paragraph.properties[LIST_PROPERTY]["continuation_of"] = "opaque-old-field"
    assert get_list_item(paragraph).continuation_of is None
    set_list_item(paragraph, ListItem("a", parent_id="head"))
    assert get_list_item(paragraph).continuation_of is None
    assert "continuation_of" not in paragraph.properties[LIST_PROPERTY]


def test_graph_depth_and_setter_limits_are_structured_and_atomic():
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    _paragraph(str(index), ListItem("a", parent_id=str(index - 1) if index else None), str(index))
                    for index in range(15)
                ]
            )
        ]
    )
    assert document.validate() == []
    with pytest.raises(ArtifactLimitError) as caught:
        list(iter_list_numbers(document, limits=DocumentLimits(max_depth=10)))
    assert (caught.value.path, caught.value.quota, caught.value.maximum) == ("list_items", "graph depth", 10)
    paragraph = document.sections[0].blocks[1]
    before = paragraph.properties.to_dict()
    with pytest.raises(ArtifactLimitError):
        set_list_item(paragraph, ListItem("a", continuation_of="0"), limits=DocumentLimits(max_nodes=2))
    assert paragraph.properties.to_dict() == before


def test_custom_budget_is_forwarded_through_two_json_cycles_and_composition():
    document = _document()
    document.sections[0].blocks[1].properties[LIST_PROPERTY]["custom"] = [None] * 100_001
    limits = DocumentLimits(max_nodes=300_000)
    with pytest.raises(ArtifactLimitError):
        document_to_json(document)
    encoded = document_to_json(document, limits=limits)
    for _ in range(2):
        document = document_from_json(encoded, limits=limits)
        encoded = document_to_json(document, limits=limits)
    assert list(iter_list_numbers(document, limits=limits))[1].number is None
    merged = merge_documents([document], limits=limits).document
    assert document_to_json(merged, limits=limits) == encoded


def test_extract_cross_section_and_structural_replacement_roll_back():
    from opendoc_model import replace_node

    document = _document()
    blocks = document.sections[0].blocks
    document.sections.append(Section(blocks=[blocks.pop(1)]))
    selected = list(iter_elements(document, Paragraph))[-1]
    extracted = extract_document(document, selected)
    assert len(extracted.sections) == 2 and extracted.validate() == []
    before = document_to_json(document)
    with pytest.raises(ValueError):
        replace_node(document, list(iter_elements(document, Paragraph))[0], Paragraph())
    assert document_to_json(document) == before


def test_link_changes_remain_visible_in_comparison():
    before = _document()
    after = clone_model(before)
    set_list_item(after.sections[0].blocks[1], ListItem("a"))
    diff = compare_documents(before, after).metrics["comparison"]["object_diff"]
    assert diff["lists_available"] and diff["list_numbers_available"]
    assert diff["changed_list_items"] == 1 and diff["changed_list_numbers"] > 0
