"""Independent copies, occurrence-safe structural edits and bounded text."""

import json
from pathlib import Path

import pytest

from opendoc_model import (
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    Box,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    NodeLocation,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    VisualSurrogate,
    clone_model,
    document_from_json,
    document_to_json,
    extract_text,
    insert_node,
    iter_elements,
    iter_sections,
    load_document,
    remove_node,
    replace_node,
    save_document,
    transform_elements,
    walk_model,
)
from opendoc_model.properties import ParagraphProperties


def _paragraph(text):
    return Paragraph([TextRun(text)])


def _document():
    origin = Provenance("source", "source.ext", 0, "paragraph", "/main", [ProvenanceEvent("import", "kept")])
    paragraph = Paragraph(
        [TextRun("Draft", style=TextStyle(bold=True), properties={"custom": {"list": [1]}}), Image("asset", "ALT")],
        style_id="body",
        properties={"custom": {"list": [2]}},
        box=Box(1, 2, 3, 4),
        provenance=origin,
        visual_surrogate=VisualSurrogate("asset", "preview"),
    )
    document = DocumentModel(
        sections=[Section(blocks=[Table([TableRow([TableCell([paragraph])])])], headers=[_paragraph("Header")])],
        resources={"asset": Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", b"bytes", properties={"custom": [3]})},
        styles={"body": TextStyle(properties={"custom": [4]})},
        metadata={"custom": [5]},
        package=PackageGraph(
            "opaque",
            "/main",
            {"/main": PackagePart("/main", "application/octet-stream", b"part")},
            [PackageRelationship("r", "external", "/main", "https://invalid.test", True)],
        ),
    )
    assert document.validate() == []
    return document


def test_clone_preserves_all_fields_and_separates_mutable_data_without_io(monkeypatch):
    document = _document()
    document.resources["external"] = Resource("external", ResourceKind.ATTACHMENT, "application/octet-stream", source="gone.bin")
    before = document_to_json(document)

    def forbidden(*args, **kwargs):
        raise AssertionError("Cloning must not read external sources")

    monkeypatch.setattr(Path, "open", forbidden)
    copied = clone_model(document)
    assert document_to_json(copied) == before
    paragraph = list(iter_elements(copied, Paragraph))[1].node
    assert isinstance(paragraph.properties, ParagraphProperties)
    paragraph.properties["custom"]["list"].append(22)
    paragraph.content[0].properties["custom"]["list"].append(11)
    paragraph.content[0].style.bold = False
    paragraph.box.x = 100
    paragraph.provenance.events[0].detail = "changed"
    paragraph.visual_surrogate.reason = "changed"
    copied.metadata["custom"].append(55)
    copied.styles["body"].properties["custom"].append(44)
    copied.resources["asset"].properties["custom"].append(33)
    copied.package.relationships[0].target = "changed"
    copied.sections[0].page.width.pt = 1000
    copied.sections[0].headers.append(_paragraph("new"))
    assert document_to_json(document) == before
    assert copied.package.parts["/main"] is not document.package.parts["/main"]
    assert copied.resources["asset"] is not document.resources["asset"]


@pytest.mark.parametrize(
    "root",
    [Section(), Table(), TableRow(), TableCell(), Paragraph(), TextRun("a"), Image("missing"), Formula("x", FormulaFormat.LATEX)],
)
def test_clone_subtrees_preserves_type_and_missing_references(root):
    copied = clone_model(root)
    assert copied == root and copied is not root
    assert type(copied) is type(root)


def test_clone_preserves_internal_aliases_but_never_original_mutable_objects():
    paragraph = _paragraph("same")
    document = DocumentModel(sections=[Section(blocks=[paragraph, paragraph])])
    copied = clone_model(document)
    assert copied.sections[0].blocks[0] is copied.sections[0].blocks[1]
    copied.sections[0].blocks[0].content[0].text = "changed"
    assert paragraph.plain_text == "same"
    assert extract_text(copied) == "changed\nchanged"


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_insert_replace_remove_each_section_collection(field):
    document = DocumentModel(sections=[Section()])
    section = next(iter_sections(document))
    source = _paragraph("original")
    inserted = insert_node(document, section, field, 0, source)
    assert inserted.path == f"sections[0].{field}[0]"
    assert inserted.parent is section
    assert inserted.node == source and inserted.node is not source
    source.content[0].text = "outside"
    replaced = replace_node(document, inserted, Image("missing", "image"))
    assert replaced.kind == "block"
    assert replaced.node.alt_text == "image"
    with pytest.raises(ValueError, match="stale"):
        remove_node(document, inserted)
    detached = remove_node(document, replaced)
    assert detached is replaced.node
    assert getattr(document.sections[0], field) == []
    assert document.validate() == []


@pytest.mark.parametrize(
    ("root", "field", "child"),
    [
        (DocumentModel(), "sections", Section()),
        (Table(), "rows", TableRow()),
        (TableRow(), "cells", TableCell()),
        (TableCell(), "blocks", _paragraph("a")),
        (Paragraph(), "content", TextRun("a")),
    ],
)
def test_edit_all_structural_slot_kinds_including_standalone_roots(root, field, child):
    inserted = insert_node(root, next(walk_model(root)), field, 0, child)
    assert getattr(root, field)[0] is inserted.node
    assert remove_node(root, inserted) == child
    assert getattr(root, field) == []


def test_edits_reject_wrong_slot_without_changing_original():
    document = _document()
    before = document_to_json(document)
    inline = next(iter_elements(document, TextRun))
    with pytest.raises(ValueError, match="expected TextRun, Image, Formula"):
        replace_node(document, inline, Table())
    section = next(iter_sections(document))
    with pytest.raises(ValueError, match="not a structural collection"):
        insert_node(document, section, "page", 0, Section())
    with pytest.raises(ValueError, match="expected Paragraph"):
        insert_node(document, section, "blocks", 0, TextRun("wrong"))
    assert document_to_json(document) == before


@pytest.mark.parametrize("index", [-1, 1, True, 1.0, None])
def test_insertion_indices_are_explicit_and_never_clamped(index):
    document = DocumentModel(sections=[Section()])
    with pytest.raises(ValueError, match="index"):
        insert_node(document, next(iter_sections(document)), "blocks", index, _paragraph("x"))
    assert document.sections[0].blocks == []


def test_insert_at_end_and_reject_shifted_detached_foreign_and_root_locations():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("one"), _paragraph("two")])])
    old = list(iter_elements(document, Paragraph))[1]
    insert_node(document, next(iter_sections(document)), "blocks", 0, _paragraph("zero"))
    with pytest.raises(ValueError, match="stale"):
        replace_node(document, old, _paragraph("wrong"))
    foreign = next(iter_elements(clone_model(document), Paragraph))
    with pytest.raises(ValueError, match="does not belong"):
        remove_node(document, foreign)
    section = next(iter_sections(document))
    end = insert_node(document, section, "blocks", 3, _paragraph("last"))
    assert extract_text(document) == "zero\none\ntwo\nlast"
    remove_node(document, end)
    with pytest.raises(ValueError, match="stale"):
        remove_node(document, end)
    root = next(walk_model(document))
    with pytest.raises(ValueError, match="root"):
        replace_node(document, root, DocumentModel())
    with pytest.raises(ValueError, match="root"):
        remove_node(document, root)
    with pytest.raises(ValueError, match="NodeLocation"):
        remove_node(document, None)


def test_stale_ancestor_is_checked_even_when_leaf_slot_still_matches():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("one")])])
    old = next(iter_elements(document, TextRun))
    document.sections.insert(0, Section())
    with pytest.raises(ValueError, match="stale"):
        remove_node(document, old)
    assert extract_text(document) == "\none"


def _value_count(root):
    # Find the independently observable exact input quota, not an implementation constant.
    for count in range(1, 500):
        try:
            list(walk_model(root, limits=DocumentLimits(max_nodes=count)))
        except ArtifactLimitError:
            continue
        return count
    raise AssertionError("fixture exceeds expected small budget")


def test_failed_insert_and_replace_roll_back_total_model_budget_and_list_identity():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("old")])])
    count = _value_count(document)
    budget = DocumentLimits(max_nodes=count)
    blocks = document.sections[0].blocks
    old = blocks[0]
    section = next(iter_sections(document))
    location = next(iter_elements(document, Paragraph))
    before = document_to_json(document)
    with pytest.raises(ArtifactLimitError, match="nodes"):
        insert_node(document, section, "blocks", 1, _paragraph("new"), limits=budget)
    with pytest.raises(ArtifactLimitError, match="nodes"):
        replace_node(document, location, Paragraph([TextRun("a"), TextRun("b")]), limits=budget)
    assert blocks is document.sections[0].blocks
    assert blocks == [old] and blocks[0] is old
    assert document_to_json(document) == before


def test_cycle_and_malformed_incoming_subtree_never_enter_document():
    document = DocumentModel(sections=[Section()])
    table = Table([TableRow([TableCell()])])
    table.rows[0].cells[0].blocks.append(table)
    for incoming, match in ((table, "cyclic"), (Paragraph([Table()]), "content")):
        with pytest.raises(ValueError, match=match):
            insert_node(document, next(iter_sections(document)), "blocks", 0, incoming)
    assert document.sections[0].blocks == []
    document.metadata["cycle"] = document.metadata
    with pytest.raises(ValueError, match="cyclic"):
        clone_model(document)


def test_text_boundaries_nested_tables_headers_empty_nodes_and_fallbacks():
    section = Section(
        blocks=[
            Paragraph([TextRun("A"), TextRun("B"), Formula("SOURCE", FormulaFormat.LATEX, fallback_text="F"), Image("x", "I")]),
            Table(
                [
                    TableRow(
                        [
                            TableCell([_paragraph("C"), _paragraph("D")]),
                            TableCell([Table([TableRow([TableCell([_paragraph("E")]), TableCell([_paragraph("G")])])])]),
                        ]
                    ),
                    TableRow([TableCell(), TableCell([Paragraph(), _paragraph("H")])]),
                ]
            ),
            Formula("NO-FALLBACK", FormulaFormat.LATEX),
            Paragraph(),
        ]
    )
    for field in SECTION_CONTENT_FIELDS:
        if field != "blocks":
            setattr(section, field, [_paragraph(field)])
    document = DocumentModel(sections=[section, Section()])
    assert extract_text(document) == (
        "headers\nfirst_page_headers\neven_page_headers\nABFI\nC\nD\tE\tG\n\t\nH\n\n\n"
        "footers\nfirst_page_footers\neven_page_footers\n"
    )
    assert extract_text(section.blocks[0], include_alt_text=False) == "ABF"
    assert extract_text(section.blocks[2]) == ""
    assert extract_text(section.blocks[2], include_formula_source=True) == "NO-FALLBACK"
    assert extract_text(section.blocks[0], include_formula_source=True) == "ABFI"
    assert extract_text(section.blocks[1], block_separator="|", cell_separator=";", row_separator="/") == "C|D;E;G/;|H"
    assert extract_text(TextRun("only")) == "only"


def test_text_limits_are_utf8_exact_including_separators_and_invalid_unicode():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("Я"), _paragraph("😀")])])
    assert extract_text(document, limits=DocumentLimits(max_bytes=7)) == "Я\n😀"
    with pytest.raises(ArtifactLimitError, match="bytes"):
        extract_text(document, limits=DocumentLimits(max_bytes=6))
    assert extract_text(Paragraph(), limits=DocumentLimits(max_bytes=0)) == ""
    with pytest.raises(ValueError, match="UTF-8"):
        extract_text(TextRun("\ud800"))
    with pytest.raises(ValueError, match="text string"):
        extract_text(TextRun(3))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"block_separator": None},
        {"cell_separator": 0},
        {"row_separator": []},
        {"include_alt_text": 1},
        {"include_formula_source": "yes"},
    ],
)
def test_text_options_are_not_silently_coerced(kwargs):
    with pytest.raises(ValueError):
        extract_text(Paragraph(), **kwargs)


def test_transform_copy_selected_paragraphs_preserves_origin_and_roundtrips(tmp_path):
    document = _document()
    before = document_to_json(document)

    def edit(reference):
        for item in reference.node.content:
            if isinstance(item, TextRun):
                item.text = item.text.replace("Draft", "Final")
        reference.node.provenance = reference.node.provenance.transformed("replace-text", detail="Draft -> Final")
        return reference.node

    result = transform_elements(document, Paragraph, edit, predicate=lambda item: item.node.style_id == "body")
    assert extract_text(result) == "Header\nFinalALT"
    assert result.validate() == []
    changed = list(iter_elements(result, Paragraph))[1].node
    assert changed.provenance.object_id == "paragraph"
    assert [event.operation for event in changed.provenance.events] == ["import", "replace-text"]
    assert changed.provenance.events[0] is not list(iter_elements(document, Paragraph))[1].node.provenance.events[0]
    path = save_document(result, tmp_path / "changed.json")
    assert document_to_json(load_document(path)) == document_to_json(result)
    assert document_to_json(document) == before


def test_transform_deletes_siblings_replaces_types_and_visits_descendants_before_parent():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("keep"), _paragraph("delete"), _paragraph("delete")])])
    calls = []

    def edit(reference):
        calls.append(reference.path)
        node = reference.node
        if isinstance(node, TextRun):
            return Formula(node.text.upper(), FormulaFormat.LATEX, fallback_text=node.text.upper())
        return None if node.plain_text == "DELETE" else node

    result = transform_elements(document, (Paragraph, TextRun), edit)
    assert calls == [
        "sections[0].blocks[2].content[0]",
        "sections[0].blocks[2]",
        "sections[0].blocks[1].content[0]",
        "sections[0].blocks[1]",
        "sections[0].blocks[0].content[0]",
        "sections[0].blocks[0]",
    ]
    assert extract_text(result) == "KEEP"
    assert isinstance(result.sections[0].blocks[0].content[0], Formula)
    assert extract_text(document) == "keep\ndelete\ndelete"


def test_transform_new_elements_are_not_revisited_and_external_replacements_are_copied():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("old")])])
    replacement = Paragraph([TextRun("new"), TextRun("also new")], properties={"x": [1]})
    calls = []

    def edit(reference):
        calls.append(reference.path)
        return replacement

    result = transform_elements(document, Paragraph, edit)
    assert len(calls) == 1
    replacement.properties["x"].append(2)
    replacement.content[0].text = "outside"
    assert extract_text(result) == "newalso new"
    assert result.sections[0].blocks[0].properties["x"] == [1]
    assert result.sections[0].blocks[0].provenance is None


@pytest.mark.parametrize("failure", ["exception", "wrong-slot", "quota", "cycle", "stale"])
def test_transform_failures_leave_original_and_external_replacements_unchanged(failure):
    document = DocumentModel(sections=[Section(blocks=[_paragraph("one"), _paragraph("two")])])
    before = document_to_json(document)

    def edit(reference):
        reference.node.text = "changed"
        if failure == "exception":
            raise RuntimeError("callback failure")
        if failure == "wrong-slot":
            return Table()
        if failure == "quota":
            reference.node.properties["large"] = list(range(500))
        if failure == "cycle":
            reference.node.properties["cycle"] = reference.node.properties
        if failure == "stale":
            reference.parent.node.content.insert(0, TextRun("shift"))
        return reference.node

    error = RuntimeError if failure == "exception" else ArtifactLimitError if failure == "quota" else ValueError
    with pytest.raises(error):
        transform_elements(document, TextRun, edit, limits=DocumentLimits(max_nodes=200))
    assert document_to_json(document) == before


def test_transform_subtree_root_and_invalid_callbacks():
    paragraph = _paragraph("old")
    result = transform_elements(paragraph, Paragraph, lambda item: _paragraph("new"))
    assert result.plain_text == "new" and paragraph.plain_text == "old"
    for callback in (lambda item: None, lambda item: Image("x")):
        with pytest.raises(ValueError, match="root"):
            transform_elements(paragraph, Paragraph, callback)
    for callback, predicate in ((None, None), (lambda item: item.node, 2)):
        with pytest.raises(ValueError, match="callable"):
            transform_elements(paragraph, Paragraph, callback, predicate=predicate)
    assert clone_model(DocumentModel()).validate() == []
    assert transform_elements(paragraph, (), lambda item: None) == paragraph
    with pytest.raises(ValueError, match="element classes"):
        transform_elements(paragraph, str, lambda item: item.node)


def test_transform_aliases_are_occurrences_not_deduplicated_objects():
    paragraph = _paragraph("x")
    document = DocumentModel(sections=[Section(blocks=[paragraph, paragraph])])
    calls = []

    def edit(reference):
        calls.append(reference.path)
        reference.node.text += "!"
        return reference.node

    result = transform_elements(document, TextRun, edit)
    assert calls == ["sections[0].blocks[1].content[0]", "sections[0].blocks[0].content[0]"]
    assert extract_text(result) == "x!!\nx!!"
    assert paragraph.plain_text == "x"


def test_saved_v1_v2_fixtures_clone_without_migrating_user_extensions():
    directory = Path(__file__).parent / "fixtures/compatibility"
    for version in (1, 2):
        document = document_from_json((directory / f"document-v{version}.json").read_bytes())
        copied = clone_model(document)
        assert copied == document
        assert json.loads(document_to_json(copied)) == json.loads(document_to_json(document))


def test_forged_inconsistent_location_is_rejected():
    document = DocumentModel(sections=[Section(blocks=[_paragraph("x")])])
    location = next(iter_elements(document, Paragraph))
    forged = NodeLocation(location.node, "wrong[0]", location.parent, location.field, location.index, location.kind)
    with pytest.raises(ValueError, match="inconsistent path"):
        remove_node(document, forged)


def test_insertion_checks_combined_depth_after_copy_and_restores_exact_list():
    document = DocumentModel(sections=[Section()])
    section = next(iter_sections(document))
    blocks = section.node.blocks
    node = Paragraph([TextRun("x")])
    # Each tree fits separately; the composed tree needs additional ancestor depth.
    list(walk_model(document, limits=DocumentLimits(max_depth=6)))
    list(walk_model(node, limits=DocumentLimits(max_depth=6)))
    with pytest.raises(ArtifactLimitError, match="depth"):
        insert_node(document, section, "blocks", 0, node, limits=DocumentLimits(max_depth=6))
    assert section.node.blocks is blocks and blocks == []


def test_clone_guards_embedded_bytes_and_deep_extension_values_before_copy():
    document = _document()
    assert clone_model(document, limits=DocumentLimits(max_embedded_bytes=9)) == document
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        clone_model(document, limits=DocumentLimits(max_embedded_bytes=8))
    nested = {}
    root = TextRun("deep", properties=nested)
    for _ in range(120):
        nested["next"] = {}
        nested = nested["next"]
    assert clone_model(root, limits=DocumentLimits(max_depth=128)) == root
    with pytest.raises(ArtifactLimitError, match="depth"):
        clone_model(root, limits=DocumentLimits(max_depth=64))


def test_predicate_failure_after_editing_copy_does_not_touch_original():
    document = _document()
    before = document_to_json(document)

    def predicate(location):
        location.node.properties["partial"] = [1]
        raise LookupError("predicate failure")

    with pytest.raises(LookupError, match="predicate failure"):
        transform_elements(document, Paragraph, lambda item: item.node, predicate=predicate)
    assert document_to_json(document) == before


def test_invalid_formula_fallback_is_not_coerced_or_silently_skipped():
    with pytest.raises(ValueError, match="fallback_text"):
        extract_text(Formula("x", FormulaFormat.LATEX, fallback_text=False))
