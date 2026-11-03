"""Flow scope, compound list identity and bounded, independent transport."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    BlockGroup,
    BlockGroupListOwner,
    DocumentLimits,
    DocumentModel,
    Footnote,
    InternalLink,
    ListItem,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    extract_text,
    get_anchor,
    inspect_document_model,
    iter_list_numbers,
    merge_documents,
    remove_node,
    resolve_anchor,
    set_anchor,
    set_internal_link,
    set_list_item,
    walk_model,
)
from opendoc_model.limits import _guard_model


def paragraph(text, anchor=None, item=None):
    value = Paragraph([TextRun(text)])
    if anchor:
        set_anchor(value, Anchor(anchor))
    if item:
        set_list_item(value, item)
    return value


def compound():
    primary = paragraph("Before", "owner", ListItem("list", start=3))
    tail = paragraph("After", "tail", ListItem("list", start=3, continuation_of="owner"))
    table = Table([TableRow([TableCell([paragraph("Cell", "cell")])])])
    group = BlockGroup([primary, table, tail], list_owner=BlockGroupListOwner("owner"))
    set_anchor(group, Anchor("group"))
    following = paragraph("Next", "next", ListItem("list", start=3))
    return DocumentModel([Section([group, following])])


def cycles(document):
    first = document_to_dict(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert document_to_dict(document) == first
    return document


def test_compound_roundtrip_walk_refs_and_numbering():
    model = compound()
    group = model.sections[0].blocks[0]
    group.role = "quotation"
    group.provenance = Provenance("test", object_id="scope")
    group.extensions["future"] = {"items": [1]}
    group.properties["custom"] = {"values": [2]}
    group.list_owner.extensions["future"] = [3]
    set_internal_link(group.children[2].content[0], InternalLink("group"))
    result = cycles(model)
    restored = result.sections[0].blocks[0]
    assert [type(child) for child in restored.children] == [Paragraph, Table, Paragraph]
    assert [entry.number for entry in iter_list_numbers(result)] == [3, None, 4]
    assert resolve_anchor(result, "group").node is restored
    assert resolve_anchor(result, "owner").path == "sections[0].blocks[0].children[0]"
    assert get_anchor(restored.children[1]) is None
    restored.extensions["future"]["items"].append(9)
    restored.properties["custom"]["values"].append(9)
    restored.list_owner.extensions["future"].append(9)
    assert group.extensions["future"]["items"] == [1]
    assert group.properties["custom"]["values"] == [2]
    assert group.list_owner.extensions["future"] == [3]
    assert extract_text(result) == "Before\nCell\nAfter\nNext"


def test_nested_cell_notes_headers_empty_and_occurrences():
    shared = BlockGroup([paragraph("reused")], role="quotation")
    outer = BlockGroup([shared, shared, BlockGroup()])
    doc = DocumentModel(
        [Section([Table([TableRow([TableCell([outer])])])], headers=[BlockGroup()])],
        footnotes=[Footnote("note", [BlockGroup([paragraph("note")])])],
    )
    result = cycles(doc)
    paths = [loc.path for loc in walk_model(doc) if loc.node is shared]
    assert len(paths) == 2 and paths[0] != paths[1]
    assert isinstance(result.sections[0].headers[0], BlockGroup)
    assert isinstance(result.footnotes[0].blocks[0], BlockGroup)


def test_nested_list_start_restart_empty_primary():
    doc = compound()
    group = doc.sections[0].blocks[0]
    nested_owner = paragraph("", "nested-owner", ListItem("nested", parent_id="owner", restart=7))
    group.children.insert(1, BlockGroup([nested_owner], list_owner=BlockGroupListOwner("nested-owner")))
    doc.sections[0].blocks.append(paragraph("Restart", item=ListItem("list", start=3, restart=9)))
    assert [entry.number for entry in iter_list_numbers(cycles(doc))] == [3, 7, None, 4, 9]


@pytest.mark.parametrize("reference", ["missing", "group", "tail", "next", "cell"])
def test_invalid_list_owner_is_located_and_atomic_transport(reference):
    doc = compound()
    doc.sections[0].blocks[0].list_owner = BlockGroupListOwner(reference)
    before = deepcopy(doc)
    with pytest.raises(ValueError, match=r"sections\[0\].blocks\[0\].list_owner.paragraph_id"):
        document_to_dict(doc)
    assert doc == before


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda g: setattr(g, "role", "html"), "role"),
        (lambda g: setattr(g, "list_owner", "owner"), "list_owner"),
        (lambda g: g.children.append(TextRun("inline")), "children"),
        (lambda g: g.extensions.update(type="paragraph"), "extensions"),
        (lambda g: g.list_owner.extensions.update(paragraph_id="wrong"), "extensions"),
    ],
)
def test_bad_model_state(change, match):
    doc = compound()
    change(doc.sections[0].blocks[0])
    with pytest.raises(ValueError, match=match):
        document_to_json(doc)


@pytest.mark.parametrize("field,value", [("children", [None]), ("role", "unknown"), ("list_owner", {"paragraph_id": 1})])
def test_bad_json_state(field, value):
    payload = document_to_dict(compound())
    payload["document"]["sections"][0]["blocks"][0][field] = value
    with pytest.raises(ValueError, match=field):
        document_from_dict(payload)


def test_cycles_duplicate_claims_and_nested_owner_refused():
    doc = compound()
    group = doc.sections[0].blocks[0]
    group.children.append(group)
    with pytest.raises(ValueError, match="cyclic"):
        document_to_json(doc)
    doc = compound()
    group = doc.sections[0].blocks[0]
    group.children = [BlockGroup(group.children, list_owner=group.list_owner)]
    with pytest.raises(ValueError, match="nested compound group"):
        document_to_json(doc)


def test_edit_removal_rolls_back_dangling_owner_then_explicit_unbind():
    doc = compound()
    group = doc.sections[0].blocks[0]
    owner_location = next(loc for loc in walk_model(doc) if loc.node is group.children[0])
    before = document_to_dict(doc)
    with pytest.raises(ValueError, match="list_owner"):
        remove_node(doc, owner_location)
    assert document_to_dict(doc) == before
    # Removing the whole group removes the binding and does not add a list number.
    location = next(loc for loc in walk_model(doc) if loc.node is group)
    remove_node(doc, location)
    assert [entry.number for entry in iter_list_numbers(doc)] == [3]


def test_merge_remap_extract_and_independence():
    doc = compound()
    merged = merge_documents([doc, doc], conflicts="rename").document
    second = merged.sections[1].blocks[0]
    assert second.list_owner.paragraph_id == "owner~2"
    assert get_anchor(second).id == "group~2"
    assert not cycles(merged).validate()
    assert doc.sections[0].blocks[0].list_owner.paragraph_id == "owner"
    group_loc = resolve_anchor(doc, "group")
    extracted = extract_document(doc, group_loc)
    assert isinstance(extracted.sections[0].blocks[0], BlockGroup)
    extracted.sections[0].blocks[0].children[0].content[0].text = "Edit"
    assert doc.sections[0].blocks[0].children[0].plain_text == "Before"
    # Extracting a table retains its compound scope; the owner dependency closes safely.
    location = next(loc for loc in walk_model(doc) if isinstance(loc.node, Table))
    assert not cycles(extract_document(doc, location)).validate()


@pytest.mark.parametrize("quota", ["max_nodes", "max_depth", "max_bytes"])
def test_json_limit_exact_boundary_and_refusal(quota):
    doc = compound()
    baseline = document_to_json(doc)

    def accepted(maximum):
        try:
            limit = replace(DocumentLimits(), **{quota: maximum})
            document_to_json(doc, limits=limit)
            document_from_json(baseline, limits=limit)
        except ArtifactLimitError:
            return False
        return True

    low, high = 0, 128 if quota == "max_depth" else max(len(baseline.encode()), 10000)
    while low + 1 < high:
        middle = (low + high) // 2
        if accepted(middle):
            high = middle
        else:
            low = middle
    assert accepted(high)
    assert not accepted(high - 1)
    assert document_to_json(doc) == baseline


def test_traversal_selected_budget_group_and_children_count():
    group = BlockGroup([BlockGroup([paragraph("Text")])])
    nodes, _ = _guard_model(group, DocumentLimits())
    assert len(list(walk_model(group, limits=DocumentLimits(max_nodes=nodes)))) == 4
    with pytest.raises(ArtifactLimitError):
        list(walk_model(group, limits=DocumentLimits(max_nodes=nodes - 1)))


def test_inspection_records_group_scope_and_parent():
    report = inspect_document_model(compound())
    groups = [entry for entry in report.objects if entry["type"] == "blockgroup"]
    assert len(groups) == 1
    assert groups[0]["block_group"]["list_owner"]["paragraph_id"] == "owner"
    child = next(entry for entry in report.objects if entry["location"].endswith("children[0]"))
    assert child["parent_location"] == groups[0]["location"]
