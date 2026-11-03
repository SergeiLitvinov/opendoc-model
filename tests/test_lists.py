"""List membership, numbering, composition and comparisons remain independent."""

import json

import pytest

from opendoc_model import (
    LIST_PROPERTY,
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    ListItem,
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
    get_list_item,
    inspect_document_model,
    iter_elements,
    iter_list_items,
    iter_list_numbers,
    merge_documents,
    set_list_item,
)


def _paragraph(item, text="item"):
    paragraph = Paragraph([TextRun(text)], properties={"custom": {"values": [1]}})
    set_list_item(paragraph, item)
    return paragraph


def _document(*items):
    return DocumentModel(sections=[Section(blocks=[_paragraph(item, f"item {index}") for index, item in enumerate(items)])])


def test_numbering_levels_restart_interleaving_and_plain_paragraphs():
    document = _document(
        ListItem("a", start=3),
        ListItem("a", level=1),
        ListItem("a", level=1),
        ListItem("b"),
        ListItem("a", start=3),
        ListItem("a", level=1),
        ListItem("a", level=1, restart=7),
        ListItem("a", level=1),
        ListItem("a", start=3, restart=10),
        ListItem("a", level=1),
    )
    document.sections[0].blocks.insert(5, Paragraph([TextRun("plain")]))
    before = document_to_json(document)
    assert [entry.number for entry in iter_list_numbers(document)] == [3, 1, 2, 1, 4, 1, 7, 8, 10, 1]
    assert document_to_json(document) == before
    assert document.validate() == []


def test_unordered_parent_resets_nested_ordered_counters_without_inventing_labels():
    document = _document(
        ListItem("a", kind="unordered"),
        ListItem("a", level=1),
        ListItem("a", level=1),
        ListItem("a", kind="unordered"),
        ListItem("a", level=1),
        ListItem("orphan", level=8),
    )
    assert [entry.number for entry in iter_list_numbers(document)] == [None, 1, 2, None, 1, 1]
    assert list(iter_list_numbers(document))[-1].item.level == 8


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_all_collections_nested_tables_and_repeated_occurrences(field):
    paragraph = _paragraph(ListItem("a"))
    document = DocumentModel(sections=[Section(**{field: [Table([TableRow([TableCell([paragraph])])]), paragraph]})])
    locations = list(iter_list_items(document))
    assert [location.path for location in locations] == [
        f"sections[0].{field}[0].rows[0].cells[0].blocks[0]",
        f"sections[0].{field}[1]",
    ]
    numbered = list(iter_list_numbers(document))
    assert [entry.number for entry in numbered] == [1, 2]
    assert all(entry.location.node is paragraph for entry in numbered)
    assert list(iter_list_numbers(paragraph))[0].number == 1


@pytest.mark.parametrize(
    "values",
    [
        {"list_id": ""},
        {"list_id": "\ud800"},
        {"list_id": None},
        {"level": True},
        {"level": -1},
        {"level": 9},
        {"level": "1"},
        {"kind": "roman"},
        {"start": 0},
        {"start": True},
        {"restart": 0},
        {"restart": 1.0},
        {"kind": "unordered", "start": 2},
        {"kind": "unordered", "restart": 1},
    ],
)
def test_invalid_constructor_fields(values):
    with pytest.raises(ValueError):
        ListItem(**{"list_id": "a", **values})


def test_edit_removal_extensions_and_atomic_budget():
    paragraph = _paragraph(ListItem("a"))
    bag = paragraph.properties
    value = paragraph.properties[LIST_PROPERTY]
    value["custom"] = {"values": [1]}
    set_list_item(paragraph, ListItem("b", level=1, restart=5))
    assert paragraph.properties is bag and value["list_id"] == "a"
    assert get_list_item(paragraph) == ListItem("b", level=1, restart=5)
    paragraph.properties[LIST_PROPERTY]["custom"]["values"].append(2)
    assert value["custom"] == {"values": [1]}
    current = paragraph.properties[LIST_PROPERTY]
    with pytest.raises(ArtifactLimitError):
        set_list_item(paragraph, ListItem("c"), limits=DocumentLimits(max_nodes=1))
    assert paragraph.properties[LIST_PROPERTY] is current
    set_list_item(paragraph, None)
    assert get_list_item(paragraph) is None
    assert paragraph.properties.to_dict() == {"custom": {"values": [1]}}


@pytest.mark.parametrize("value", [None, 7, "a", {}, {"format": "custom", "version": 9}])
def test_old_properties_stay_opaque_and_are_not_overwritten(value):
    paragraph = Paragraph(properties={LIST_PROPERTY: value, "numbering_id": 4, "numbering_level": 2})
    assert get_list_item(paragraph) is None
    assert list(iter_list_items(paragraph)) == []
    for item in (ListItem("a"), None):
        with pytest.raises(ValueError, match="opaque"):
            set_list_item(paragraph, item)
    document = DocumentModel(sections=[Section(blocks=[paragraph])])
    assert document_from_json(document_to_json(document)) == document


@pytest.mark.parametrize("version", [1, 2])
def test_independent_json_schema_defaults_and_extensions(version):
    payload = {
        "format": "opendoc.document",
        "version": version,
        "document": {
            "sections": [
                {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "item"}],
                            "properties": {
                                LIST_PROPERTY: {"format": "opendoc.list-item", "version": 1, "list_id": "a", "custom": [1]}
                            },
                        }
                    ]
                }
            ]
        },
    }
    document = document_from_json(json.dumps(payload))
    assert get_list_item(document.sections[0].blocks[0]) == ListItem("a")
    assert list(iter_list_numbers(document))[0].number == 1
    assert document_from_json(document_to_json(document)) == document
    assert document.sections[0].blocks[0].properties[LIST_PROPERTY]["custom"] == [1]


@pytest.mark.parametrize(
    "change,code",
    [
        ({"version": 3}, "semantic.version"),
        ({"version": True}, "semantic.version"),
        ({"list_id": ""}, "semantic.list.id"),
        ({"level": 10}, "semantic.list.level"),
        ({"kind": "other"}, "semantic.list.kind"),
        ({"restart": True}, "semantic.list.number"),
    ],
)
def test_declared_schema_failures_have_codes_and_reject_read_write(change, code):
    document = _document(ListItem("a"))
    payload = json.loads(document_to_json(document))
    document.sections[0].blocks[0].properties[LIST_PROPERTY].update(change)
    payload["document"]["sections"][0]["blocks"][0]["properties"][LIST_PROPERTY].update(change)
    assert any(issue.code == code for issue in check_document(document).issues)
    with pytest.raises(ValueError):
        document_to_json(document)
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))


def test_group_configuration_conflict_is_rejected_before_numbering_yields():
    document = _document(ListItem("a"), ListItem("a", start=2))
    assert any(issue.code == "semantic.list.config" for issue in check_document(document).issues)
    iterator = iter_list_numbers(document)
    with pytest.raises(ValueError, match="conflicting"):
        next(iterator)
    with pytest.raises(ValueError):
        document_to_json(document)


def test_merge_list_ids_are_independent_reserved_and_shared_bags_are_remapped_once():
    first = _document(ListItem("a"), ListItem("a"))
    second = _document(ListItem("a"))
    paragraph = second.sections[0].blocks[0]
    second.sections[0].blocks.append(paragraph)
    third = _document(ListItem("a~2"))
    original = document_to_json(second)
    with pytest.raises(ValueError, match="lists"):
        merge_documents([first, second, third])
    merged = merge_documents([first, second, third], conflicts="rename")
    assert [mapping.lists for mapping in merged.id_maps] == [{"a": "a"}, {"a": "a~3"}, {"a~2": "a~2"}]
    assert [entry.number for entry in iter_list_numbers(merged.document)] == [1, 2, 1, 2, 1]
    assert merged.document.sections[1].blocks[0] is merged.document.sections[1].blocks[1]
    assert document_to_json(second) == original


def test_extract_reflows_numbers_in_new_document_but_preserves_membership():
    document = _document(ListItem("a", start=3), ListItem("a", start=3))
    selected = list(iter_elements(document, Paragraph))[1]
    extracted = extract_document(document, selected)
    assert list(iter_list_numbers(document))[1].number == 4
    assert list(iter_list_numbers(extracted))[0].number == 3
    assert get_list_item(extracted.sections[0].blocks[0]) == ListItem("a", start=3)


def test_membership_loss_and_derived_number_changes_are_distinct():
    source = _document(ListItem("a"), ListItem("a"), ListItem("a"))
    target = clone_model(source)
    target.sections[0].blocks.pop(1)
    result = compare_documents(source, target)
    diff = result.metrics["comparison"]["object_diff"]
    assert diff["lists_available"] and diff["list_numbers_available"]
    assert diff["changed_list_items"] == 0 and diff["changed_list_numbers"] == 1
    assert any("list_number" in entry["changes"] for entry in diff["changed"])
    target = clone_model(source)
    set_list_item(target.sections[0].blocks[0], None)
    strict = compare_documents(source, target, policies=[QualityPolicy()])
    assert not strict.success and any(issue.code == "list-loss" for issue in strict.issues)


def test_older_inventories_do_not_claim_semantic_or_number_equality():
    document = _document(ListItem("a"))
    before, after = inspect_document_model(document), inspect_document_model(document)
    for item in before.objects:
        item.pop("list_item", None)
        item.pop("list_number", None)
    diff = compare_inspections(before, after).object_diff
    assert diff["lists_available"] is False and diff["changed_list_items"] is None
    assert diff["list_numbers_available"] is False and diff["changed_list_numbers"] is None


def test_bad_arguments_and_budget_are_explicit():
    paragraph = _paragraph(ListItem("a"))
    with pytest.raises(ValueError):
        get_list_item(TextRun("bad"))
    with pytest.raises(ValueError):
        set_list_item(paragraph, 1)
    with pytest.raises(ValueError):
        get_list_item(paragraph, limits=3)
    with pytest.raises(ArtifactLimitError):
        list(iter_list_numbers(_document(ListItem("a")), limits=DocumentLimits(max_nodes=1)))
    paragraph.properties = None
    assert check_document(DocumentModel(sections=[Section(blocks=[paragraph])])).success is False
