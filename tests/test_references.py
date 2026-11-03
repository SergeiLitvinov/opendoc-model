"""Document-local targets, opaque preservation and composition of references."""

import json
from copy import deepcopy

import pytest

from opendoc_model import (
    ANCHOR_PROPERTY,
    INTERNAL_LINK_PROPERTY,
    SECTION_CONTENT_FIELDS,
    Anchor,
    ArtifactLimitError,
    DocumentIdMap,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    InternalLink,
    Paragraph,
    QualityPolicy,
    Resource,
    ResourceKind,
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
    get_anchor,
    get_internal_link,
    inspect_document_model,
    iter_anchors,
    iter_elements,
    iter_internal_links,
    merge_documents,
    resolve_anchor,
    set_anchor,
    set_internal_link,
    walk_model,
)


def _document(identifier="chapter"):
    target = Paragraph([TextRun("Chapter")])
    run = TextRun("Go to chapter")
    set_anchor(target, Anchor(identifier))
    set_internal_link(run, InternalLink(identifier))
    return DocumentModel(sections=[Section(blocks=[Paragraph([run]), target])])


@pytest.mark.parametrize("constructor", [Anchor, InternalLink])
@pytest.mark.parametrize("value", [None, "", 1, True, [], "\ud800"])
def test_identifiers_are_strict_utf8_nonempty_strings(constructor, value):
    with pytest.raises(ValueError):
        constructor(value)


def test_accessors_roundtrip_resolve_and_remove_without_mutating_text_or_style():
    document = _document("chapter / привет#1")
    before = document_to_json(document)
    restored = document_from_json(before)
    target = resolve_anchor(restored, "chapter / привет#1")
    assert target.node is restored.sections[0].blocks[1]
    assert target.path == "sections[0].blocks[1]"
    assert get_anchor(target.node) == Anchor("chapter / привет#1")
    assert resolve_anchor(restored, "absent") is None
    link = next(iter_internal_links(restored))
    assert link.node is restored.sections[0].blocks[0].content[0]
    assert get_internal_link(link.node) == InternalLink("chapter / привет#1")
    assert restored == document
    assert document_to_json(document) == before
    set_internal_link(link.node, None)
    set_anchor(target.node, None)
    assert list(iter_anchors(restored)) == list(iter_internal_links(restored)) == []
    assert target.node.plain_text == "Chapter" and link.node.text == "Go to chapter"
    assert restored.validate() == []


def test_all_carriers_and_seven_collections_nested_tables_are_supported():
    section = Section()
    for index, field in enumerate(SECTION_CONTENT_FIELDS):
        run = TextRun(f"target {index}")
        set_anchor(run, Anchor(f"run-{index}"))
        link = TextRun("go")
        set_internal_link(link, InternalLink(f"run-{index}"))
        paragraph = Paragraph([run, link])
        set_anchor(paragraph, Anchor(f"paragraph-{index}"))
        table = Table([TableRow([TableCell([paragraph])])])
        set_anchor(table, Anchor(f"table-{index}"))
        getattr(section, field).append(table)
    formula = Formula("x", FormulaFormat.LATEX)
    image = Image("asset")
    set_anchor(formula, Anchor("formula"))
    set_anchor(image, Anchor("image"))
    section.blocks.extend([formula, image])
    document = DocumentModel(
        sections=[section], resources={"asset": Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", b"png")}
    )
    assert document.validate() == []
    assert len(list(iter_anchors(document))) == 23
    assert len(list(iter_internal_links(document))) == 7
    assert document_from_json(document_to_json(document)) == document
    assert resolve_anchor(document, "run-0").path.endswith("headers[0].rows[0].cells[0].blocks[0].content[0]")
    assert get_anchor(formula) == Anchor("formula")
    assert get_anchor(image) == Anchor("image")


def test_self_and_cyclic_links_do_not_require_recursive_resolution():
    first, second = TextRun("first"), TextRun("second")
    for run, identifier, target in ((first, "first", "second"), (second, "second", "first")):
        set_anchor(run, Anchor(identifier))
        set_internal_link(run, InternalLink(target))
    document = DocumentModel(sections=[Section(blocks=[Paragraph([first, second])])])
    assert document.validate() == []
    assert resolve_anchor(document, "second").node is second
    set_internal_link(first, InternalLink("first"))
    assert document_from_json(document_to_json(document)) == document


def test_missing_target_duplicate_occurrences_and_external_conflict_have_precise_codes():
    document = _document()
    document.sections[0].blocks.pop()
    result = check_document(document)
    issue = next(item for item in result.issues if item.code == "semantic.anchor.missing")
    assert issue.location == "sections[0].blocks[0].content[0].properties['opendoc.internal-link'].target_id"
    assert issue.measurement == {"identifier": "chapter"}
    with pytest.raises(ValueError, match="unknown anchor"):
        document_to_json(document)
    with pytest.raises(ValueError, match="unknown anchor"):
        resolve_anchor(document, "chapter")
    document = _document()
    document.sections[0].blocks.append(document.sections[0].blocks[1])
    result = check_document(document)
    duplicate = next(item for item in result.issues if item.code == "semantic.anchor.duplicate")
    assert duplicate.location.endswith("blocks[2].properties['opendoc.anchor'].id")
    assert duplicate.measurement == {"first_location": "sections[0].blocks[1]"}
    document = _document()
    next(iter_internal_links(document)).node.link = "https://example.test"
    assert any(item.code == "semantic.link.conflict" for item in check_document(document).issues)
    with pytest.raises(ValueError, match="conflicts"):
        document_to_json(document)


@pytest.mark.parametrize("key", [ANCHOR_PROPERTY, INTERNAL_LINK_PROPERTY])
@pytest.mark.parametrize("opaque", [None, 7, "old", {}, {"format": "other", "version": 99}])
def test_opaque_extensions_are_preserved_and_not_overwritten(key, opaque):
    run = TextRun("run", properties={key: opaque})
    document = DocumentModel(sections=[Section(blocks=[Paragraph([run])])])
    getter, setter, item = (
        (get_anchor, set_anchor, Anchor("a"))
        if key == ANCHOR_PROPERTY
        else (get_internal_link, set_internal_link, InternalLink("a"))
    )
    assert getter(run) is None
    assert document_from_json(document_to_json(document)) == document
    for replacement in (item, None):
        with pytest.raises(ValueError, match="opaque"):
            setter(run, replacement)
    assert run.properties[key] == opaque


@pytest.mark.parametrize("key,field", [(ANCHOR_PROPERTY, "id"), (INTERNAL_LINK_PROPERTY, "target_id")])
@pytest.mark.parametrize("version", [True, 0, 2, "1", None])
def test_declared_unknown_versions_fail_at_read_write_and_memory_boundary(key, field, version):
    document = _document()
    payload = json.loads(document_to_json(document))
    run_data = payload["document"]["sections"][0]["blocks"][0]["content"][0]
    run_data["properties"][key] = {"format": key, "version": version, field: "chapter"}
    with pytest.raises(ValueError, match="unsupported reference version"):
        document_from_json(json.dumps(payload))
    run = document.sections[0].blocks[0].content[0]
    run.properties[key] = run_data["properties"][key]
    assert any(item.code == "semantic.version" for item in check_document(document).issues)
    with pytest.raises(ValueError, match="unsupported reference version"):
        document_to_json(document)


@pytest.mark.parametrize("version", [1, 2])
def test_independent_json_schema_and_unknown_tagged_fields_survive(version):
    payload = {
        "format": "opendoc.document",
        "version": version,
        "sections": [
            {
                "blocks": [
                    {
                        "type": "paragraph",
                        "properties": {ANCHOR_PROPERTY: {"format": ANCHOR_PROPERTY, "version": 1, "id": "a", "extra": [1]}},
                        "content": [
                            {
                                "type": "text",
                                "text": "self",
                                "properties": {
                                    INTERNAL_LINK_PROPERTY: {
                                        "format": INTERNAL_LINK_PROPERTY,
                                        "version": 1,
                                        "target_id": "a",
                                        "extra": {"x": [2]},
                                    }
                                },
                            }
                        ],
                    }
                ]
            }
        ],
    }
    document = document_from_json(
        json.dumps({"format": payload.pop("format"), "version": payload.pop("version"), "document": payload})
    )
    paragraph = document.sections[0].blocks[0]
    old = paragraph.properties[ANCHOR_PROPERTY]
    old_link = paragraph.content[0].properties[INTERNAL_LINK_PROPERTY]
    set_anchor(paragraph, Anchor("renamed"))
    set_internal_link(paragraph.content[0], InternalLink("renamed"))
    paragraph.properties[ANCHOR_PROPERTY]["extra"].append(3)
    paragraph.content[0].properties[INTERNAL_LINK_PROPERTY]["extra"]["x"].append(4)
    assert old["extra"] == [1] and old_link["extra"] == {"x": [2]}
    assert document_from_json(document_to_json(document)) == document


def test_setter_is_atomic_under_bad_arguments_quota_and_external_link_conflict():
    run = TextRun("go", link="#old")
    with pytest.raises(ValueError, match="cannot coexist"):
        set_internal_link(run, InternalLink("a"))
    assert run.properties == {} and run.link == "#old"
    for setter, item in ((set_anchor, Anchor("a")), (set_internal_link, InternalLink("a"))):
        with pytest.raises(ValueError):
            setter(Section(), item)
        with pytest.raises(ValueError):
            setter(TextRun("x"), {})
        clean = TextRun("clean")
        with pytest.raises(ArtifactLimitError):
            setter(clean, item, limits=DocumentLimits(max_nodes=1))
        assert clean.properties == {}
    set_anchor(run, Anchor("a"))
    assert run.link == "#old"
    assert list(iter_internal_links(Paragraph([run]))) == []


def test_merge_renames_anchor_and_link_ids_with_reserved_suffixes_and_shared_links():
    first, second, third = _document("a"), _document("a"), _document("a~2")
    run = second.sections[0].blocks[0].content[0]
    second.sections[0].blocks[0].content.append(run)
    before = [document_to_json(document) for document in (first, second, third)]
    with pytest.raises(ValueError, match="anchors.*identifier conflict"):
        merge_documents([first, second, third])
    merged = merge_documents([first, second, third], conflicts="rename")
    assert [mapping.anchors for mapping in merged.id_maps] == [{"a": "a"}, {"a": "a~3"}, {"a~2": "a~2"}]
    assert [get_internal_link(item.node).target_id for item in iter_internal_links(merged.document)] == ["a", "a~3", "a~3", "a~2"]
    runs = merged.document.sections[1].blocks[0].content
    assert runs[0] is runs[1]
    assert merged.document.validate() == []
    assert document_from_json(document_to_json(merged.document)) == merged.document
    assert [document_to_json(document) for document in (first, second, third)] == before
    assert DocumentIdMap({}, {}).anchors == {}


def test_extraction_expands_missing_target_sections_transitively_and_copies_dependencies():
    first_run, second_run = TextRun("to second"), TextRun("to third")
    set_internal_link(first_run, InternalLink("second"))
    set_internal_link(second_run, InternalLink("third"))
    second = Paragraph([second_run])
    set_anchor(second, Anchor("second"))
    third = Image("asset")
    set_anchor(third, Anchor("third"))
    document = DocumentModel(
        sections=[
            Section(blocks=[Paragraph([TextRun("unselected")]), Paragraph([first_run])]),
            Section(first_page_headers=[second]),
            Section(blocks=[third]),
            Section(blocks=[Paragraph([TextRun("unused section")])]),
        ],
        resources={"asset": Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", b"png")},
    )
    before = document_to_json(document)
    location = next(item for item in iter_elements(document, TextRun) if item.node is first_run)
    extracted = extract_document(document, location)
    assert len(extracted.sections) == 3
    assert len(extracted.sections[0].blocks) == 1
    assert extracted.sections[1].first_page_headers[0].plain_text == "to third"
    assert set(extracted.resources) == {"asset"}
    assert extracted.validate() == []
    assert document_from_json(document_to_json(extracted)) == extracted
    assert document_to_json(document) == before
    extracted.resources["asset"].data = b"new"
    assert document.resources["asset"].data == b"png"


def test_same_section_extraction_expands_without_duplicate_selected_anchor_and_cycles():
    document = _document()
    run = document.sections[0].blocks[0].content[0]
    set_anchor(run, Anchor("back"))
    back = TextRun("return")
    set_internal_link(back, InternalLink("back"))
    document.sections[0].blocks[1].content.append(back)
    location = next(iter_internal_links(document))
    extracted = extract_document(document, location)
    assert extracted.sections == document.sections
    assert extracted.validate() == []
    assert len(list(iter_anchors(extracted))) == 2
    assert extract_document(document, next(walk_model(document))).validate() == []


def test_reference_comparison_reports_loss_retargeting_moves_and_measurements():
    document = _document()
    inspection = inspect_document_model(document)
    assert inspection.metrics["anchors"] == inspection.metrics["internal_links"] == 1
    assert inspection.metadata["semantic_references"]["links"][0]["target_location"] == "sections[0].blocks[1]"
    identical = compare_documents(document, document)
    diff = identical.metrics["comparison"]["object_diff"]["references"]
    assert diff["available"] and diff["lost_links"] == diff["changed_links"] == diff["lost_anchors"] == 0
    changed = clone_model(document)
    new_target = Paragraph([TextRun("other")])
    set_anchor(new_target, Anchor("other"))
    changed.sections[0].blocks.append(new_target)
    set_internal_link(next(iter_internal_links(changed)).node, InternalLink("other"))
    comparison = compare_documents(document, changed)
    issue = next(item for item in comparison.issues if item.code == "internal-link-change")
    assert issue.measurement["source"]["target_id"] == "chapter"
    assert issue.measurement["target"]["target_id"] == "other"
    stripped = clone_model(document)
    set_internal_link(next(iter_internal_links(stripped)).node, None)
    set_anchor(next(iter_anchors(stripped)).node, None)
    losses = compare_documents(document, stripped, policies=[QualityPolicy()])
    assert not losses.success
    assert {"anchor-loss", "internal-link-loss"} <= {item.code for item in losses.issues}
    moved = clone_model(document)
    moved.sections[0].blocks.reverse()
    result = compare_documents(document, moved)
    assert {"anchor-change", "internal-link-change"} <= {item.code for item in result.issues}
    assert result.lossless


def test_repeated_link_text_is_not_collapsed_and_pairing_ambiguity_is_explicit():
    document = _document()
    paragraph = document.sections[0].blocks[0]
    paragraph.content.append(deepcopy(paragraph.content[0]))
    target = clone_model(document)
    target.sections[0].blocks[0].content.pop()
    result = compare_documents(document, target)
    diff = result.metrics["comparison"]["object_diff"]["references"]
    assert diff["lost_links"] == 1 and len(diff["link_matches"]) == 1
    assert diff["link_matches"][0]["ambiguous"] is True


@pytest.mark.parametrize("mutation", ["missing", "version", "target", "hash", "duplicate"])
def test_old_or_corrupt_reference_inventory_is_unknown_instead_of_loss_or_equality(mutation):
    source = inspect_document_model(_document())
    target = deepcopy(source)
    value = target.metadata["semantic_references"]
    if mutation == "missing":
        del target.metadata["semantic_references"]
    elif mutation == "version":
        value["version"] = True
    elif mutation == "target":
        value["links"][0]["target_id"] = "absent"
    elif mutation == "hash":
        value["links"][0]["content_hash"] = "unknown"
    else:
        value["anchors"].append(deepcopy(value["anchors"][0]))
    result = compare_inspections(source, target)
    diff = result.object_diff["references"]
    assert diff["available"] is False and diff["lost_anchors"] is diff["lost_links"] is diff["changed_links"] is None
    assert not any(issue.feature.startswith(("anchor-", "internal-link-")) for issue in result.issues)


def test_traversal_and_resolution_respect_limits_and_do_not_open_external_sources(monkeypatch):
    document = _document()
    for iterator in (iter_anchors, iter_internal_links):
        with pytest.raises(ArtifactLimitError):
            list(iterator(document, limits=DocumentLimits(max_nodes=1)))
    with pytest.raises(ArtifactLimitError):
        resolve_anchor(document, "chapter", limits=DocumentLimits(max_nodes=1))
    with pytest.raises(ValueError):
        resolve_anchor(document, "")
    document.resources["remote"] = Resource("remote", ResourceKind.ATTACHMENT, "type", source="https://invalid.test/data")

    def fail(*args, **kwargs):
        raise AssertionError("unexpected external IO")

    monkeypatch.setattr("pathlib.Path.stat", fail)
    monkeypatch.setattr("pathlib.Path.open", fail)
    assert resolve_anchor(document, "chapter").node is document.sections[0].blocks[1]
    assert check_document(document).success
