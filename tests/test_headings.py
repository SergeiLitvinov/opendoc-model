"""Explicit heading semantics survive editing/JSON and distinguish role changes."""

import json

import pytest

from opendoc_model import (
    HEADING_PROPERTY,
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Heading,
    Paragraph,
    QualityPolicy,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    check_document,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_json,
    document_to_json,
    extract_document,
    get_heading,
    inspect_document_model,
    iter_elements,
    iter_headings,
    merge_documents,
    set_heading,
)


def _paragraph(level=2):
    paragraph = Paragraph([TextRun("Title")], properties={"custom": {"tags": [1]}})
    set_heading(paragraph, Heading(level))
    return paragraph


def test_assign_change_remove_preserves_unknown_fields_and_visual_style():
    paragraph = _paragraph()
    bag = paragraph.properties
    assert get_heading(paragraph) == Heading(2)
    paragraph.properties[HEADING_PROPERTY]["custom"] = {"values": [1]}
    old_value = paragraph.properties[HEADING_PROPERTY]
    set_heading(paragraph, Heading(3))
    assert paragraph.properties is bag
    assert get_heading(paragraph) == Heading(3)
    assert old_value["level"] == 2
    assert paragraph.properties[HEADING_PROPERTY]["custom"] == {"values": [1]}
    paragraph.properties[HEADING_PROPERTY]["custom"]["values"].append(2)
    assert old_value["custom"] == {"values": [1]}
    assert paragraph.content[0].style.bold is None and paragraph.style_id is None
    set_heading(paragraph, None)
    assert get_heading(paragraph) is None
    assert paragraph.properties.to_dict() == {"custom": {"tags": [1]}}
    set_heading(paragraph, None)


@pytest.mark.parametrize("level", [0, 10, -1, True, 1.0, "2", None])
def test_levels_are_strict(level):
    with pytest.raises(ValueError):
        Heading(level)


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_heading_search_covers_nested_tables_and_all_collections(field):
    heading = _paragraph()
    document = DocumentModel(sections=[Section(**{field: [Table([TableRow([TableCell([heading])])]), heading]})])
    locations = list(iter_headings(document))
    assert [location.path for location in locations] == [
        f"sections[0].{field}[0].rows[0].cells[0].blocks[0]",
        f"sections[0].{field}[1]",
    ]
    assert all(location.node is heading for location in locations)
    assert list(iter_headings(heading))[0].path == ""


@pytest.mark.parametrize("version", [1, 2])
def test_independent_json_representation_preserves_tag_and_unknown_fields(version):
    payload = {
        "format": "opendoc.document",
        "version": version,
        "document": {
            "sections": [
                {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "Title"}],
                            "properties": {
                                HEADING_PROPERTY: {"format": "opendoc.heading", "version": 1, "level": 2, "custom": [1]}
                            },
                        }
                    ]
                }
            ]
        },
    }
    document = document_from_json(json.dumps(payload))
    assert get_heading(document.sections[0].blocks[0]) == Heading(2)
    assert document.version == 2
    restored = document_from_json(document_to_json(document))
    assert restored == document
    assert restored.sections[0].blocks[0].properties[HEADING_PROPERTY]["custom"] == [1]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"version": 2}, "semantic.version"),
        ({"version": True}, "semantic.version"),
        ({"level": 0}, "semantic.heading.level"),
        ({"level": True}, "semantic.heading.level"),
    ],
)
def test_declared_tag_invalid_versions_and_levels_fail_model_read_write_and_check(change, code):
    document = DocumentModel(sections=[Section(blocks=[_paragraph()])])
    payload = json.loads(document_to_json(document))
    paragraph = document.sections[0].blocks[0]
    paragraph.properties[HEADING_PROPERTY].update(change)
    payload["document"]["sections"][0]["blocks"][0]["properties"][HEADING_PROPERTY].update(change)
    assert document.validate()
    assert any(issue.code == code for issue in check_document(document).issues)
    with pytest.raises(ValueError):
        document_to_json(document)
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))
    with pytest.raises(ValueError):
        get_heading(paragraph)


@pytest.mark.parametrize("opaque", [None, 2, "title", {}, {"format": "custom", "level": 3}])
def test_old_opaque_extensions_are_preserved_and_never_overwritten_or_inferred(opaque):
    paragraph = Paragraph(properties={HEADING_PROPERTY: opaque, "heading_level": 5})
    assert get_heading(paragraph) is None
    document = DocumentModel(sections=[Section(blocks=[paragraph])])
    assert document_from_json(document_to_json(document)) == document
    assert list(iter_headings(document)) == []
    for heading in (None, Heading(1)):
        with pytest.raises(ValueError, match="opaque"):
            set_heading(paragraph, heading)
    assert paragraph.properties[HEADING_PROPERTY] == opaque


def test_cloning_merge_extract_and_generic_traversal_preserve_semantics():
    document = DocumentModel(sections=[Section(blocks=[_paragraph()])])
    copied = clone_model(document)
    set_heading(next(iter_headings(copied)).node, Heading(1))
    assert get_heading(document.sections[0].blocks[0]) == Heading(2)
    merged = merge_documents([document, copied]).document
    assert [get_heading(location.node).level for location in iter_headings(merged)] == [2, 1]
    selected = list(iter_elements(merged, Paragraph))[1]
    extracted = extract_document(merged, selected)
    assert get_heading(extracted.sections[0].blocks[0]) == Heading(1)


def test_level_change_and_heading_role_loss_are_compared_without_text_changes():
    source = DocumentModel(sections=[Section(blocks=[_paragraph()])])
    target = clone_model(source)
    set_heading(target.sections[0].blocks[0], Heading(3))
    result = compare_documents(source, target)
    diff = result.metrics["comparison"]["object_diff"]
    assert diff["headings_available"] is True and diff["changed_headings"] == 1
    assert diff["changed"][0]["changes"] == ["heading"]
    assert any(issue.code == "heading-change" for issue in result.issues)
    set_heading(target.sections[0].blocks[0], None)
    loss = compare_documents(source, target, policies=[QualityPolicy()])
    assert not loss.success
    assert any(issue.code == "heading-loss" for issue in loss.issues)


def test_old_inventory_cannot_claim_heading_equality():
    document = DocumentModel(sections=[Section(blocks=[_paragraph()])])
    before, after = inspect_document_model(document), inspect_document_model(document)
    for item in before.objects:
        item.pop("heading", None)
    diff = compare_inspections(before, after).object_diff
    assert diff["headings_available"] is False and diff["changed_headings"] is None


def test_errors_and_limits_leave_heading_intact():
    paragraph = _paragraph()
    old = paragraph.properties[HEADING_PROPERTY]
    with pytest.raises(ArtifactLimitError):
        set_heading(paragraph, Heading(3), limits=DocumentLimits(max_nodes=1))
    assert paragraph.properties[HEADING_PROPERTY] is old
    with pytest.raises(ValueError):
        set_heading(paragraph, 3)
    with pytest.raises(ValueError):
        get_heading(TextRun("bad"))
    with pytest.raises(ValueError):
        get_heading(paragraph, limits=3)
    paragraph.properties = None
    assert check_document(DocumentModel(sections=[Section(blocks=[paragraph])])).success is False
