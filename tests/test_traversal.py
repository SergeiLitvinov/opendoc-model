"""Public occurrences, paths and references agree across model consumers."""

import copy
import hashlib
from dataclasses import FrozenInstanceError

import pytest

from opendoc_model import (
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VisualSurrogate,
    document_from_json,
    document_to_json,
    inspect_document_model,
    iter_blocks,
    iter_elements,
    iter_inlines,
    iter_resource_references,
    iter_sections,
    walk_model,
)
from opendoc_model.object_inventory import inspect_objects


def _document():
    paragraph = Paragraph([TextRun("body"), Image("image", "inline"), Formula("x", FormulaFormat.LATEX, fallback_text="x")])
    table = Table([TableRow([TableCell([paragraph]), TableCell([Image("image", "block")], row_span=2)])])
    section = Section(blocks=[table])
    for name, text in (
        ("headers", "header"),
        ("first_page_headers", "first"),
        ("even_page_headers", "even"),
        ("footers", "footer"),
        ("first_page_footers", "first-footer"),
        ("even_page_footers", "even-footer"),
    ):
        setattr(section, name, [Paragraph([TextRun(text)])])
    return DocumentModel(
        sections=[section, Section(blocks=[Paragraph([TextRun("second")])])],
        resources={"image": Resource("image", ResourceKind.RASTER_IMAGE, "image/png", b"image")},
    )


def test_preorder_paths_include_real_row_cell_parents_and_all_section_collections():
    document = _document()
    references = list(walk_model(document))
    assert [item.path for item in references] == [
        "",
        "sections[0]",
        "sections[0].headers[0]",
        "sections[0].headers[0].content[0]",
        "sections[0].first_page_headers[0]",
        "sections[0].first_page_headers[0].content[0]",
        "sections[0].even_page_headers[0]",
        "sections[0].even_page_headers[0].content[0]",
        "sections[0].blocks[0]",
        "sections[0].blocks[0].rows[0]",
        "sections[0].blocks[0].rows[0].cells[0]",
        "sections[0].blocks[0].rows[0].cells[0].blocks[0]",
        "sections[0].blocks[0].rows[0].cells[0].blocks[0].content[0]",
        "sections[0].blocks[0].rows[0].cells[0].blocks[0].content[1]",
        "sections[0].blocks[0].rows[0].cells[0].blocks[0].content[2]",
        "sections[0].blocks[0].rows[0].cells[1]",
        "sections[0].blocks[0].rows[0].cells[1].blocks[0]",
        "sections[0].footers[0]",
        "sections[0].footers[0].content[0]",
        "sections[0].first_page_footers[0]",
        "sections[0].first_page_footers[0].content[0]",
        "sections[0].even_page_footers[0]",
        "sections[0].even_page_footers[0].content[0]",
        "sections[1]",
        "sections[1].blocks[0]",
        "sections[1].blocks[0].content[0]",
    ]
    assert len({item.path for item in references}) == len(references)
    assert references[0].node is document
    assert references[0].parent is references[0].section is references[0].index is references[0].field is None
    for reference in references[1:]:
        assert reference.parent is not None
        assert getattr(reference.parent.node, reference.field)[reference.index] is reference.node
        assert reference.section is document.sections[reference.section_index]
    nested = next(item for item in references if item.path.endswith("cells[0].blocks[0]"))
    assert isinstance(nested.parent.node, TableCell)
    assert nested.parent.parent.kind == "row"


def test_filters_distinguish_slots_but_find_images_in_both_block_and_inline_positions():
    document = _document()
    images = list(iter_elements(document, Image))
    assert [item.kind for item in images] == ["inline", "block"]
    assert len(list(iter_elements(document, Paragraph))) == 8
    assert len(list(iter_elements(document, (Image, Formula)))) == 3
    assert len(list(iter_inlines(document))) == 10
    assert len(list(iter_blocks(document))) == 10
    assert [item.index for item in iter_sections(document)] == [0, 1]
    assert list(iter_elements(document, ())) == []
    assert list(iter_elements(DocumentModel(), Image)) == []


@pytest.mark.parametrize("types", [None, "Image", [Image], Resource, DocumentModel, (Image, str), (123,)])
def test_type_filter_rejects_non_element_classes(types):
    with pytest.raises(ValueError, match="types"):
        list(iter_elements(_document(), types))


def test_subtree_paths_are_relative_and_standalone_image_is_a_block_root():
    document = _document()
    table = document.sections[0].blocks[0]
    references = list(walk_model(table))
    assert references[0].path == ""
    assert references[0].parent is references[0].section is references[0].section_index is None
    assert list(iter_elements(table, Image))[0].path == "rows[0].cells[0].blocks[0].content[1]"
    standalone = Image("missing")
    assert list(iter_blocks(standalone))[0].node is standalone
    assert list(iter_inlines(standalone)) == []
    assert list(iter_inlines(TextRun("text")))[0].path == ""
    section = next(iter_sections(document.sections[0]))
    assert section.section is document.sections[0]
    assert section.section_index is None


def test_aliases_are_distinct_occurrences_and_node_values_are_live():
    paragraph = Paragraph([TextRun("shared")])
    document = DocumentModel(sections=[Section(blocks=[paragraph, paragraph])])
    references = list(iter_elements(document, Paragraph))
    assert references[0] is not references[1]
    assert references[0].node is references[1].node is paragraph
    assert [item.path for item in references] == ["sections[0].blocks[0]", "sections[0].blocks[1]"]
    before = copy.deepcopy(document)
    references[0].node.content[0].text = "changed"
    assert document.sections[0].blocks[1].plain_text == "changed"
    assert before.sections[0].blocks[0].plain_text == "shared"
    with pytest.raises(FrozenInstanceError):
        references[0].path = "changed"


def test_structure_edit_requires_fresh_paths_and_does_not_change_saved_locations():
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("first")]), Paragraph([TextRun("second")])])])
    old = list(iter_elements(document, Paragraph))
    document.sections[0].blocks.insert(0, Paragraph())
    fresh = list(iter_elements(document, Paragraph))
    assert old[0].path == "sections[0].blocks[0]"
    assert fresh[1].path == "sections[0].blocks[1]"
    assert fresh[1].node is old[0].node
    assert fresh[0].node is not old[0].node


@pytest.mark.parametrize(
    "collection",
    ["headers", "first_page_headers", "even_page_headers", "blocks", "footers", "first_page_footers", "even_page_footers"],
)
def test_all_nested_resource_slots_are_shared_with_validation_and_inspection(collection):
    run = TextRun(
        "text",
        properties={"resource_id": "font", "vendor:resource_id": "unknown-is-not-a-reference"},
        visual_surrogate=VisualSurrogate("preview", "run"),
    )
    paragraph = Paragraph(
        [
            run,
            Image("main", properties={"fallback_resource_id": "fallback"}, visual_surrogate=VisualSurrogate("preview", "image")),
            Formula("x", FormulaFormat.LATEX, visual_surrogate=VisualSurrogate("preview", "formula")),
        ],
        visual_surrogate=VisualSurrogate("preview", "paragraph"),
    )
    table = Table([TableRow([TableCell([paragraph])])], visual_surrogate=VisualSurrogate("preview", "table"))
    section = Section()
    setattr(section, collection, [table])
    document = DocumentModel(
        sections=[section],
        resources={
            name: Resource(name, ResourceKind.RASTER_IMAGE, "image/png", data=b"image")
            for name in ("font", "preview", "main", "fallback")
        },
    )
    references = list(iter_resource_references(document))
    assert [item.kind for item in references] == [
        "surrogate",
        "surrogate",
        "text",
        "surrogate",
        "image",
        "fallback",
        "surrogate",
        "surrogate",
    ]
    prefix = f"sections[0].{collection}[0]"
    assert all(item.path.startswith(prefix) for item in references)
    assert all(item.path == f"{item.owner.path}.{item.field}" for item in references)
    assert document.validate() == []
    inspection = inspect_document_model(document)
    assert not any(issue.feature == "unused-resource" for issue in inspection.issues)
    for resource_id in ("font", "preview", "main", "fallback"):
        broken = copy.deepcopy(document)
        del broken.resources[resource_id]
        missing = list(iter_resource_references(broken))
        assert any(item.resource_id == resource_id for item in missing)
        assert any(f"'{resource_id}'" in error for error in broken.validate())
        assert not inspect_document_model(broken).valid
    restored = document_from_json(document_to_json(document))
    assert [(item.path, item.kind, item.resource_id) for item in iter_resource_references(restored)] == [
        (item.path, item.kind, item.resource_id) for item in references
    ]


@pytest.mark.parametrize(
    ("node", "field", "value"),
    [
        (Image("x"), "resource_id", None),
        (Image("x"), "resource_id", ""),
        (Image("x"), "properties", None),
        (TextRun("text"), "properties", None),
        (Paragraph(), "visual_surrogate", "invalid"),
    ],
)
def test_reference_iteration_rejects_damaged_reference_fields(node, field, value):
    setattr(node, field, value)
    with pytest.raises(ValueError, match=field):
        list(iter_resource_references(node))


@pytest.mark.parametrize(
    "node", [Image("x", properties={"fallback_resource_id": 0}), TextRun("x", properties={"resource_id": False})]
)
def test_reference_identifiers_are_not_coerced_to_strings(node):
    with pytest.raises(ValueError, match="properties.*resource_id"):
        list(iter_resource_references(node))


def test_walk_is_not_semantic_validation_or_external_resource_loading(monkeypatch):
    document = DocumentModel(
        sections=[Section(blocks=[Image("missing")])],
        resources={"external": Resource("external", ResourceKind.ATTACHMENT, "application/octet-stream", source="missing.bin")},
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Walking must not access resource files")

    monkeypatch.setattr("pathlib.Path.open", forbidden)
    monkeypatch.setattr("pathlib.Path.is_file", forbidden)
    assert list(iter_elements(document, Image))[0].node.resource_id == "missing"
    assert next(iter_resource_references(document)).resource_id == "missing"
    assert document.validate()


@pytest.mark.parametrize(
    ("root", "path"),
    [
        (DocumentModel(sections=[None]), "sections[0]"),
        (Paragraph(content=[Table()]), "content[0]"),
        (Table(rows=[Paragraph()]), "rows[0]"),
        (TableRow(cells=[Image("missing")]), "cells[0]"),
        (TableCell(blocks=[TextRun("wrong")]), "blocks[0]"),
    ],
)
def test_malformed_slots_have_precise_paths_even_with_no_filter_matches(root, path):
    for iterate in (walk_model, lambda root: iter_elements(root, ())):
        with pytest.raises(ValueError, match=path.replace("[", r"\[").replace("]", r"\]")):
            list(iterate(root))


@pytest.mark.parametrize("root", [None, "text", [], Resource("x", ResourceKind.ATTACHMENT, "text/plain", b"x")])
def test_unsupported_roots_are_not_silently_empty(root):
    with pytest.raises(ValueError, match="root"):
        list(walk_model(root))


def test_cycles_and_budget_fail_before_returning_first_occurrence():
    table = Table([TableRow([TableCell()])])
    table.rows[0].cells[0].blocks.append(table)
    with pytest.raises(ValueError, match="cyclic"):
        next(walk_model(table))
    document = DocumentModel()
    assert len(list(walk_model(document, limits=DocumentLimits(max_nodes=9, max_depth=2)))) == 1
    with pytest.raises(ArtifactLimitError, match="nodes"):
        next(walk_model(document, limits=DocumentLimits(max_nodes=8)))
    with pytest.raises(ArtifactLimitError, match="depth"):
        next(walk_model(document, limits=DocumentLimits(max_depth=1)))
    document.add_resource(Resource("asset", ResourceKind.ATTACHMENT, "application/octet-stream", b"ab"))
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        next(walk_model(document, limits=DocumentLimits(max_embedded_bytes=1)))


def test_inspection_inventory_and_metrics_match_shared_occurrences():
    document = _document()
    locations = list(walk_model(document))
    report = inspect_document_model(document)
    assert report.valid
    assert [item["location"] for item in report.objects] == [
        item.path for item in locations if isinstance(item.node, (Paragraph, Table, Formula, Image))
    ]
    assert report.metrics["blocks"] == 10
    assert report.metrics["paragraphs"] == 8
    assert report.metrics["table_rows"] == 1
    assert report.metrics["table_cells"] == 2
    assert report.metrics["merged_cells"] == 1
    assert report.metrics["text_runs"] == 8
    assert report.metrics["images"] == 2
    assert report.metrics["formulas"] == 1
    flow = "header first even body footer first-footer even-footer second"
    assert report.metadata["text_flow"]["sha256"] == hashlib.sha256(flow.encode()).hexdigest()
    table_entries = list(inspect_objects(document.sections[0].blocks[0], "sections[0].blocks[0]", 0, document.resources))
    assert table_entries == [item for item in report.objects if item["location"].startswith("sections[0].blocks[0]")]
    nested = next(item for item in table_entries if item["type"] == "paragraph")
    assert nested["parent_location"] == "sections[0].blocks[0]"
    assert SECTION_CONTENT_FIELDS == (
        "headers",
        "first_page_headers",
        "even_page_headers",
        "blocks",
        "footers",
        "first_page_footers",
        "even_page_footers",
    )
