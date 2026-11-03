"""Rich note definitions, first-use numbering and dependency-complete composition."""

import json
from copy import deepcopy

import pytest

from opendoc_model import (
    FOOTNOTE_REFERENCE_PROPERTY,
    FOOTNOTES_PROPERTY,
    SECTION_CONTENT_FIELDS,
    Anchor,
    ArtifactLimitError,
    Box,
    ConversionReport,
    DocumentIdMap,
    DocumentLimits,
    DocumentModel,
    EmphasisLossPolicy,
    Footnote,
    FootnoteReference,
    Formula,
    FormulaFormat,
    FormulaLossPolicy,
    Heading,
    Image,
    InternalLink,
    ListItem,
    ObjectLossPolicy,
    Paragraph,
    QualityPolicy,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextPreservationPolicy,
    TextRun,
    TextStyle,
    check_document,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_json,
    document_to_json,
    extract_document,
    extract_text,
    find_resource_uses,
    get_footnote,
    get_footnote_reference,
    insert_node,
    inspect_document_model,
    iter_elements,
    iter_footnote_numbers,
    iter_footnote_references,
    iter_footnotes,
    iter_headings,
    iter_list_items,
    merge_documents,
    remove_footnote,
    resolve_anchor,
    set_anchor,
    set_footnote,
    set_footnote_reference,
    set_heading,
    set_internal_link,
    set_list_item,
    transform_elements,
    walk_model,
)


def _run(identifier, text="*"):
    run = TextRun(text)
    set_footnote_reference(run, FootnoteReference(identifier))
    return run


def _document(identifier="note"):
    return DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("Main"), _run(identifier)])])],
        footnotes=[Footnote(identifier, [Paragraph([TextRun("Note body")])], {"custom": {"values": [1]}})],
        footnote_properties={"custom": [2]},
    )


def test_rich_note_roundtrip_common_walk_operations_resources_and_inspection():
    document = _document()
    document.resources["asset"] = Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", b"png")
    document.styles["note-style"] = TextStyle(bold=True)
    paragraph = Paragraph([TextRun("Rich"), Formula("x", FormulaFormat.LATEX), Image("asset", "image")], style_id="note-style")
    set_heading(paragraph, Heading(2))
    set_list_item(paragraph, ListItem("note-list"))
    document.footnotes[0].blocks.append(Table([TableRow([TableCell([paragraph])])]))
    restored = document_from_json(document_to_json(document))
    assert restored == document and restored.validate() == []
    note = next(iter_footnotes(restored))
    assert note.path == "footnotes[0]" and note.kind == "footnote" and note.section is None
    assert note.node is restored.footnotes[0]
    assert any(item.path == "footnotes[0].blocks[1].rows[0].cells[0].blocks[0].content[2]" for item in walk_model(restored))
    assert next(iter_headings(restored)).path.startswith("footnotes[0]")
    assert next(iter_list_items(restored)).path.startswith("footnotes[0]")
    assert find_resource_uses(restored, "asset")[0].path.startswith("footnotes[0]")
    inserted = insert_node(restored, note, "blocks", 0, Paragraph([TextRun("Inserted")]))
    assert inserted.path == "footnotes[0].blocks[0]"
    transformed = transform_elements(
        restored, TextRun, lambda item: TextRun(item.node.text.upper(), properties=item.node.properties)
    )
    assert get_footnote(transformed, "note").blocks[0].plain_text == "INSERTED"
    assert get_footnote(restored, "note").blocks[0].plain_text == "Inserted"
    assert extract_text(Footnote("n", [Paragraph([TextRun("one")]), Paragraph([TextRun("two")])])) == "one\ntwo"
    report = inspect_document_model(restored)
    assert report.valid and report.metrics["footnotes"] == report.metrics["referenced_footnotes"] == 1
    assert report.metrics["semantic_footnote_references"] == 1
    assert len(report.pages) == 1
    assert all(item["page"] is None for item in report.objects if item["location"].startswith("footnotes"))
    assert document_to_json(document) != document_to_json(restored)


@pytest.mark.parametrize("value", [None, "", True, 2, [], "\ud800"])
def test_reference_ids_are_nonempty_utf8(value):
    with pytest.raises(ValueError):
        FootnoteReference(value)


def test_numbering_first_use_aliases_unreferenced_notes_cycles_and_no_text_mutation():
    repeated = _run("b")
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([repeated, _run("a"), repeated])])],
        footnotes=[Footnote("a", [Paragraph([_run("b")])]), Footnote("b", [Paragraph([_run("a")])]), Footnote("unused")],
    )
    before = document_to_json(document)
    numbers = list(iter_footnote_numbers(document))
    assert [(item.note_id, item.number) for item in numbers] == [("b", 1), ("a", 2), ("b", 1), ("b", 1), ("a", 2)]
    assert numbers[0].location.node is numbers[2].location.node
    assert document_to_json(document) == before
    assert inspect_document_model(document).metrics["referenced_footnotes"] == 2


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_references_in_all_collections_are_validated_and_found(field):
    section = Section()
    getattr(section, field).append(Table([TableRow([TableCell([Paragraph([_run("n")])])])]))
    document = DocumentModel(sections=[section], footnotes=[Footnote("n")])
    location = next(iter_footnote_references(document))
    assert location.path == f"sections[0].{field}[0].rows[0].cells[0].blocks[0].content[0]"
    assert next(iter_footnote_numbers(document)).number == 1
    assert document_from_json(document_to_json(document)) == document


def test_missing_duplicate_bad_definition_and_conflicting_roles_are_structured_errors():
    document = _document()
    document.footnotes.clear()
    issue = next(item for item in check_document(document).issues if item.code == "semantic.footnote.missing")
    assert issue.location.endswith("content[1].properties['opendoc.footnote-reference'].note_id")
    assert issue.measurement == {"identifier": "note"}
    with pytest.raises(ValueError, match="unknown footnote"):
        next(iter_footnote_numbers(document))
    document = _document()
    document.footnotes.append(document.footnotes[0])
    assert any(item.code == "semantic.footnote.duplicate" for item in check_document(document).issues)
    with pytest.raises(ValueError, match="duplicate"):
        get_footnote(document, "note")
    for invalid in (Footnote(""), Footnote(True), Footnote("n", [TextRun("not a block")])):
        with pytest.raises(ValueError):
            document_to_json(DocumentModel(footnotes=[invalid]))
    document = _document()
    next(iter_footnote_references(document)).node.link = "#old"
    assert any(item.code == "semantic.footnote.conflict" for item in check_document(document).issues)


def test_reference_setters_are_atomic_preserve_unknowns_and_reject_competing_links():
    run = _run("a")
    original = run.properties[FOOTNOTE_REFERENCE_PROPERTY]
    original["extra"] = {"values": [1]}
    set_footnote_reference(run, FootnoteReference("b"))
    run.properties[FOOTNOTE_REFERENCE_PROPERTY]["extra"]["values"].append(2)
    assert original["extra"] == {"values": [1]} and original["note_id"] == "a"
    with pytest.raises(ValueError, match="footnote reference"):
        set_internal_link(run, InternalLink("anchor"))
    set_footnote_reference(run, None)
    set_internal_link(run, InternalLink("anchor"))
    before = deepcopy(run.properties)
    with pytest.raises(ValueError, match="another link role"):
        set_footnote_reference(run, FootnoteReference("a"))
    assert run.properties == before
    for value in ("#old", "https://example.test"):
        external = TextRun("go", link=value)
        with pytest.raises(ValueError):
            set_footnote_reference(external, FootnoteReference("a"))
        assert external.link == value and external.properties == {}
    with pytest.raises(ArtifactLimitError):
        set_footnote_reference(TextRun("x"), FootnoteReference("n"), limits=DocumentLimits(max_nodes=1))
    with pytest.raises(ValueError):
        set_footnote_reference(Paragraph(), FootnoteReference("n"))
    with pytest.raises(ValueError):
        set_footnote_reference(TextRun("x"), {})


@pytest.mark.parametrize("opaque", [None, 7, "old", {}, {"format": "other", "version": 99}])
def test_opaque_reference_extensions_are_neither_interpreted_nor_overwritten(opaque):
    run = TextRun("legacy", properties={FOOTNOTE_REFERENCE_PROPERTY: opaque})
    assert get_footnote_reference(run) is None
    for replacement in (None, FootnoteReference("a")):
        with pytest.raises(ValueError, match="opaque"):
            set_footnote_reference(run, replacement)
    document = DocumentModel(sections=[Section(blocks=[Paragraph([run])])])
    assert document_from_json(document_to_json(document)) == document


def test_definition_mutations_copy_incoming_content_and_roll_back_referenced_removal():
    document = DocumentModel()
    incoming = Footnote("a", [Paragraph([TextRun("first")])], {"x": [1]})
    set_footnote(document, incoming)
    incoming.blocks[0].content[0].text = "changed outside"
    incoming.properties["x"].append(2)
    assert get_footnote(document, "a").blocks[0].plain_text == "first"
    assert get_footnote(document, "a").properties == {"x": [1]}
    document.sections = [Section(blocks=[Paragraph([_run("a")])])]
    before = document_to_json(document)
    with pytest.raises(ValueError, match="unknown footnote"):
        remove_footnote(document, "a")
    with pytest.raises(ValueError):
        set_footnote(document, Footnote("a", [Image("missing")]))
    with pytest.raises(ArtifactLimitError):
        set_footnote(document, Footnote("other"), limits=DocumentLimits(max_nodes=1))
    assert document_to_json(document) == before
    set_footnote(document, Footnote("a", [Paragraph([TextRun("second")])]))
    assert len(document.footnotes) == 1
    set_footnote_reference(next(iter_footnote_references(document)).node, None)
    removed = remove_footnote(document, "a")
    assert document.footnotes == [] and removed.blocks[0].plain_text == "second"
    assert get_footnote(document, "absent") is None
    with pytest.raises(ValueError, match="unknown footnote"):
        remove_footnote(document, "absent")
    with pytest.raises(ValueError):
        set_footnote(document, {})


@pytest.mark.parametrize("version", [1, 2])
def test_independent_json_fixture_roundtrip_and_extension_properties(version):
    payload = {
        "format": "opendoc.document",
        "version": version,
        "document": {
            "metadata": {
                "custom": [0],
                FOOTNOTES_PROPERTY: {
                    "format": FOOTNOTES_PROPERTY,
                    "version": 1,
                    "properties": {"custom": {"x": [1]}},
                    "notes": [
                        {
                            "id": "a",
                            "blocks": [{"type": "paragraph", "content": [{"type": "text", "text": "body"}]}],
                            "properties": {"custom": [2]},
                        }
                    ],
                },
            },
            "sections": [
                {
                    "blocks": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "1",
                                    "properties": {
                                        FOOTNOTE_REFERENCE_PROPERTY: {
                                            "format": FOOTNOTE_REFERENCE_PROPERTY,
                                            "version": 1,
                                            "note_id": "a",
                                            "custom": [3],
                                        }
                                    },
                                }
                            ],
                        }
                    ]
                }
            ],
        },
    }
    document = document_from_json(json.dumps(payload))
    assert document.metadata == {"custom": [0]} and FOOTNOTES_PROPERTY not in document.metadata
    assert document.footnote_properties == {"custom": {"x": [1]}}
    assert document.footnotes[0].properties == {"custom": [2]}
    assert document_from_json(document_to_json(document)) == document
    written = json.loads(document_to_json(document))
    assert written["version"] == 2 and written["document"]["property_schema_version"] == 1
    assert written["document"]["metadata"][FOOTNOTES_PROPERTY]["version"] == 1
    assert "footnotes" not in written["document"]


@pytest.mark.parametrize("version", [True, 0, 2, "1", None])
def test_unknown_tagged_versions_rejected_at_json_boundary(version):
    payload = json.loads(document_to_json(_document()))
    payload["document"]["metadata"][FOOTNOTES_PROPERTY]["version"] = version
    with pytest.raises(ValueError, match="unsupported footnotes version"):
        document_from_json(json.dumps(payload))
    payload = json.loads(document_to_json(_document()))
    payload["document"]["sections"][0]["blocks"][0]["content"][1]["properties"][FOOTNOTE_REFERENCE_PROPERTY]["version"] = version
    with pytest.raises(ValueError, match="unsupported footnote reference version"):
        document_from_json(json.dumps(payload))


@pytest.mark.parametrize("mutation", ["missing-notes", "bad-notes", "bad-block", "missing-id", "duplicate", "missing-resource"])
def test_malformed_registry_cannot_be_silently_accepted(mutation):
    payload = json.loads(document_to_json(_document()))
    registry = payload["document"]["metadata"][FOOTNOTES_PROPERTY]
    if mutation == "missing-notes":
        del registry["notes"]
    elif mutation == "bad-notes":
        registry["notes"] = {}
    elif mutation == "bad-block":
        registry["notes"][0]["blocks"] = [{"type": "future"}]
    elif mutation == "missing-id":
        del registry["notes"][0]["id"]
    elif mutation == "duplicate":
        registry["notes"].append(deepcopy(registry["notes"][0]))
    else:
        registry["notes"][0]["blocks"] = [{"type": "image", "resource_id": "missing"}]
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))


def test_opaque_metadata_key_is_preserved_and_cannot_be_hidden_by_live_definitions():
    document = DocumentModel(metadata={FOOTNOTES_PROPERTY: {"format": "other", "value": [1]}})
    assert document_from_json(document_to_json(document)) == document
    before = document_to_json(document)
    with pytest.raises(ValueError, match="reserved"):
        set_footnote(document, Footnote("a"))
    assert document_to_json(document) == before
    document.metadata[FOOTNOTES_PROPERTY] = {"format": FOOTNOTES_PROPERTY, "version": 1, "notes": []}
    assert any(item.code == "semantic.footnote.metadata-conflict" for item in check_document(document).issues)


def test_merge_renames_note_ids_and_all_alias_references_and_preserves_inputs():
    first, second, third = _document("a"), _document("a"), _document("a~2")
    run = second.sections[0].blocks[0].content[1]
    second.sections[0].blocks[0].content.append(run)
    before = [document_to_json(document) for document in (first, second, third)]
    with pytest.raises(ValueError, match="footnotes.*identifier conflict"):
        merge_documents([first, second, third], metadata_conflicts="keep_first")
    merged = merge_documents([first, second, third], conflicts="rename", metadata_conflicts="keep_first")
    assert [mapping.footnotes for mapping in merged.id_maps] == [{"a": "a"}, {"a": "a~3"}, {"a~2": "a~2"}]
    assert [note.id for note in merged.document.footnotes] == ["a", "a~3", "a~2"]
    assert [get_footnote_reference(item.node).note_id for item in iter_footnote_references(merged.document)] == [
        "a",
        "a~3",
        "a~3",
        "a~2",
    ]
    assert merged.document.sections[1].blocks[0].content[1] is merged.document.sections[1].blocks[0].content[2]
    assert document_from_json(document_to_json(merged.document)) == merged.document
    assert [document_to_json(document) for document in (first, second, third)] == before
    assert DocumentIdMap({}, {}).footnotes == {}


def test_extraction_closes_note_anchor_note_cycle_dependencies_with_resources_and_styles():
    first = _document("a")
    first.footnotes[0].blocks.append(Paragraph([_run("b")]))
    anchor_link = TextRun("to main target")
    set_internal_link(anchor_link, InternalLink("main-target"))
    note_anchor = Paragraph([TextRun("note target")], style_id="note-style")
    set_anchor(note_anchor, Anchor("note-target"))
    first.footnotes.append(Footnote("b", [Paragraph([anchor_link]), note_anchor, Image("asset", "asset")]))
    first.footnotes.append(Footnote("unused", [Paragraph([TextRun("unused")])]))
    target = Paragraph([_run("a")])
    set_anchor(target, Anchor("main-target"))
    first.sections.append(Section(first_page_headers=[target]))
    first.resources["asset"] = Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", b"png")
    first.styles["note-style"] = TextStyle(bold=True)
    before = document_to_json(first)
    extracted = extract_document(first, next(iter_footnote_references(first)))
    assert [note.id for note in extracted.footnotes] == ["a", "b"]
    assert len(extracted.sections) == 2
    assert set(extracted.resources) == {"asset"} and set(extracted.styles) == {"note-style"}
    assert resolve_anchor(extracted, "main-target") is not None
    assert document_from_json(document_to_json(extracted)) == extracted
    assert document_to_json(first) == before
    note_location = next(item for item in iter_footnotes(first) if item.node.id == "b")
    from_note = extract_document(first, note_location)
    assert [note.id for note in from_note.footnotes] == ["a", "b"]
    assert len(from_note.sections) == 1


def test_anchor_target_inside_note_is_included_and_partial_note_expands_without_duplicates():
    target = Paragraph([TextRun("target")])
    set_anchor(target, Anchor("target"))
    link = TextRun("go")
    set_internal_link(link, InternalLink("target"))
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([link])])], footnotes=[Footnote("n", [Paragraph([TextRun("first")]), target])]
    )
    selected = extract_document(document, next(iter_elements(document, TextRun)))
    assert [note.id for note in selected.footnotes] == ["n"]
    assert resolve_anchor(selected, "target").path == "footnotes[0].blocks[1]"
    document.footnotes[0].blocks[0].content.append(deepcopy(link))
    location = next(item for item in iter_elements(document, TextRun) if item.path == "footnotes[0].blocks[0].content[1]")
    selected = extract_document(document, location)
    assert selected.sections == [] and len(selected.footnotes) == 1
    assert selected.footnotes[0] == document.footnotes[0]
    assert selected.validate() == []


def test_compare_notes_body_reference_loss_retargeting_and_derived_numbers():
    document = _document()
    same = compare_documents(document, document)
    assert same.metrics["comparison"]["object_diff"]["footnotes"]["available"]
    changed = clone_model(document)
    changed.footnotes[0].blocks[0].content[0].text = "Updated note"
    result = compare_documents(document, changed)
    issue = next(item for item in result.issues if item.code == "footnote-change")
    assert issue.measurement["source"]["body_hash"] != issue.measurement["target"]["body_hash"]
    changed.footnotes.append(Footnote("other"))
    set_footnote_reference(next(iter_footnote_references(changed)).node, FootnoteReference("other"))
    result = compare_documents(document, changed)
    assert any(item.code == "footnote-reference-change" for item in result.issues)
    stripped = clone_model(document)
    set_footnote_reference(next(iter_footnote_references(stripped)).node, None)
    remove_footnote(stripped, "note")
    result = compare_documents(document, stripped, policies=[QualityPolicy()])
    assert not result.success and {"footnote-loss", "footnote-reference-loss"} <= {item.code for item in result.issues}
    reordered = DocumentModel(
        sections=[Section(blocks=[Paragraph([_run("a", "first"), _run("b", "second")])])],
        footnotes=[Footnote("a"), Footnote("b")],
    )
    target = clone_model(reordered)
    target.sections[0].blocks[0].content.reverse()
    result = compare_documents(reordered, target)
    assert result.metrics["comparison"]["object_diff"]["footnotes"]["changed_references"] == 2
    assert result.lossless


@pytest.mark.parametrize("mutation", ["missing", "version", "hash", "number", "duplicate", "target"])
def test_old_or_corrupt_note_inventory_is_unknown(mutation):
    source = inspect_document_model(_document())
    target = deepcopy(source)
    registry = target.metadata["semantic_footnotes"]
    if mutation == "missing":
        del target.metadata["semantic_footnotes"]
    elif mutation == "version":
        registry["version"] = True
    elif mutation == "hash":
        registry["notes"][0]["body_hash"] = "unknown"
    elif mutation == "number":
        registry["references"][0]["number"] = True
    elif mutation == "duplicate":
        registry["notes"].append(deepcopy(registry["notes"][0]))
    else:
        registry["references"][0]["note_id"] = "absent"
    result = compare_inspections(source, target)
    diff = result.object_diff["footnotes"]
    assert diff["available"] is False and diff["lost_notes"] is diff["lost_references"] is diff["changed_notes"] is None
    assert not any(issue.feature.startswith("footnote-") for issue in result.issues)


def test_cycles_quotas_unknown_nodes_and_no_external_io(monkeypatch):
    document = _document()
    table = Table([TableRow([TableCell()])])
    table.rows[0].cells[0].blocks.append(table)
    document.footnotes[0].blocks = [table]
    with pytest.raises(ValueError, match="cyclic"):
        next(iter_footnotes(document))
    document = _document()
    for iterator in (iter_footnotes, iter_footnote_references, iter_footnote_numbers):
        with pytest.raises(ArtifactLimitError):
            next(iterator(document, limits=DocumentLimits(max_nodes=1)))
    raw = document_to_json(document)
    with pytest.raises(ArtifactLimitError):
        document_from_json(raw, limits=DocumentLimits(max_bytes=len(raw.encode()) - 1))
    document.footnotes[0].blocks.append(Image("external", "external"))
    document.resources["external"] = Resource("external", ResourceKind.RASTER_IMAGE, "image/png", source="https://invalid.test")

    def fail(*args, **kwargs):
        raise AssertionError("external IO")

    monkeypatch.setattr("pathlib.Path.stat", fail)
    monkeypatch.setattr("pathlib.Path.open", fail)
    assert check_document(document).success
    assert document_from_json(document_to_json(document)) == document
    assert extract_document(document, next(iter_footnote_references(document))).validate() == []


def test_note_geometry_is_validated_without_inventing_a_page():
    document = DocumentModel(footnotes=[Footnote("n", [Paragraph([TextRun("note")], box=Box(10000, 10000, 20, 20))])])
    report = inspect_document_model(document)
    assert report.valid and report.pages == [] and report.objects[0]["page"] is None
    assert not any(issue.feature == "element-geometry" for issue in report.issues)
    document.footnotes[0].blocks[0].box.width = -1
    assert not check_document(document).success


def test_unknown_registry_and_definition_fields_survive_in_extensions_and_comparison():
    payload = json.loads(document_to_json(_document()))
    registry = payload["document"]["metadata"][FOOTNOTES_PROPERTY]
    registry["vendor.registry"] = {"values": [1]}
    registry["notes"][0]["vendor.note"] = {"values": [2]}
    document = document_from_json(json.dumps(payload))
    assert document.footnote_extensions == {"vendor.registry": {"values": [1]}}
    assert document.footnotes[0].extensions == {"vendor.note": {"values": [2]}}
    written = json.loads(document_to_json(document))["document"]["metadata"][FOOTNOTES_PROPERTY]
    assert written["vendor.registry"] == {"values": [1]}
    assert written["notes"][0]["vendor.note"] == {"values": [2]}
    assert document_from_json(document_to_json(document)) == document
    changed = clone_model(document)
    changed.footnote_extensions["vendor.registry"]["values"].append(3)
    changed.footnotes[0].extensions["vendor.note"]["values"].append(4)
    comparison = compare_documents(document, changed)
    assert {"footnote-change", "footnote-collection-change"} <= {item.code for item in comparison.issues}
    extracted = extract_document(document, next(iter_footnote_references(document)))
    assert extracted.footnote_extensions == document.footnote_extensions
    merged = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_last")
    assert merged.document.footnote_extensions == document.footnote_extensions


@pytest.mark.parametrize("field,key", [("footnote_extensions", "notes"), ("footnote_extensions", "format"), ("extensions", "id")])
def test_extensions_cannot_override_reserved_schema_fields(field, key):
    document = _document()
    owner = document.footnotes[0] if field == "extensions" else document
    getattr(owner, field)[key] = "override"
    with pytest.raises(ValueError, match="reserved"):
        document_to_json(document)
    assert any(item.code == "semantic.footnote.extension-conflict" for item in check_document(document).issues)


@pytest.mark.parametrize(
    "policy",
    [
        TextPreservationPolicy(),
        TextPreservationPolicy(mode="flow"),
        TextPreservationPolicy(mode="flow", max_text_edits=0),
        ObjectLossPolicy(),
        FormulaLossPolicy(),
        EmphasisLossPolicy(),
    ],
)
def test_old_note_evidence_cannot_verify_aggregate_content_policies(policy, tmp_path):
    source = inspect_document_model(_document())
    target = deepcopy(source)
    del target.metadata["semantic_footnotes"]
    comparison = compare_inspections(source, target)
    assert comparison.object_diff["available"] is False
    assert comparison.retention["characters"]["ratio"] is None
    assert not comparison.has_losses
    report = ConversionReport(tmp_path / "output")
    assert policy.evaluate(report, comparison) is False
