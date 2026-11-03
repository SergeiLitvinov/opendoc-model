"""Caption ownership and table-local header/group relations survive safe operations."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    TABLE_CELL_SEMANTICS_PROPERTY,
    TABLE_SEMANTICS_PROPERTY,
    Accessibility,
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    IntegrationModel,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableCellSemantics,
    TableColumnGroup,
    TableRow,
    TableRowGroup,
    TableRowSemantics,
    TableSemantics,
    TextRun,
    TextStyle,
    check_document,
    check_extensions,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    extract_document,
    get_integration,
    get_table_cell_semantics,
    get_table_row_semantics,
    get_table_semantics,
    inspect_document_model,
    iter_elements,
    merge_documents,
    remove_node,
    resolve_anchor,
    set_anchor,
    set_integration,
    set_table_cell_semantics,
    set_table_row_semantics,
    set_table_semantics,
    transform_elements,
    walk_model,
)


def _cell(identifier, role, scope=None, headers=(), column_group_id=None, row_span=1):
    cell = TableCell([Paragraph([TextRun(identifier)])], row_span=row_span)
    set_table_cell_semantics(cell, TableCellSemantics(identifier, role, scope, headers, column_group_id))
    return cell


def _document():
    run = TextRun("Mesures", style=TextStyle(bold=True))
    set_anchor(run, Anchor("caption-fr"))
    caption = Paragraph([TextRun("Report: "), run], provenance=Provenance("fixture", object_id="caption"))
    set_anchor(caption, Anchor("caption"))
    table = Table(
        [
            TableRow(
                [
                    _cell("h0", "header", "column"),
                    _cell("h1", "header", "column-group", column_group_id="values"),
                    _cell("h2", "header", "column"),
                ]
            ),
            TableRow(
                [
                    _cell("a", "header", "row", row_span=2),
                    _cell("d1", "data", headers=("h1", "a")),
                    _cell("d2", "data", headers=("h2", "a")),
                ]
            ),
            TableRow([_cell("d3", "data", headers=("h1", "a")), _cell("d4", "data", headers=("h2", "a"))]),
            TableRow(
                [
                    _cell("b", "header", "row-group"),
                    _cell("d5", "data", headers=("h1", "b")),
                    _cell("d6", "data", headers=("h2", "b")),
                ]
            ),
            TableRow([_cell("f0", "data"), _cell("f1", "data"), _cell("f2", "data")]),
        ],
        provenance=Provenance("fixture", object_id="table"),
    )
    set_anchor(table, Anchor("table"))
    set_table_semantics(
        table,
        TableSemantics(
            ("caption",),
            (
                TableRowGroup("head", "head"),
                TableRowGroup("a", "body"),
                TableRowGroup("b", "body"),
                TableRowGroup("foot", "foot"),
            ),
            (TableColumnGroup("labels", 0, 1), TableColumnGroup("values", 1, 2)),
            extra={"future": {"flag": True}},
        ),
    )
    for index, (row, group) in enumerate(zip(table.rows, ("head", "a", "a", "b", "foot"), strict=True)):
        set_table_row_semantics(row, TableRowSemantics(f"row-{index}", group))
    document = DocumentModel(sections=[Section([caption]), Section([table])])
    set_integration(document, IntegrationModel(accessibility=(Accessibility("caption-fr", "text", language="fr"),)))
    assert document.validate() == []
    return document


def _table(document):
    return resolve_anchor(document, "table").node


def test_two_json_cycles_keep_formatted_caption_language_groups_and_headers():
    original = _document()
    before = document_to_json(original)
    restored = original
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
        assert restored.validate() == []
        assert get_table_semantics(_table(restored)) == get_table_semantics(_table(original))
        assert get_table_row_semantics(_table(restored).rows[2]).group_id == "a"
        assert get_table_cell_semantics(_table(restored).rows[2].cells[0]).headers == ("h1", "a")
        assert get_integration(restored).accessibility[0].language == "fr"
        assert resolve_anchor(restored, "caption-fr").node.style.bold is True
        assert resolve_anchor(restored, "caption").node.provenance == resolve_anchor(original, "caption").node.provenance
        assert compare_documents(original, restored).lossless
        assert check_extensions(restored, []).success
    assert document_to_json(restored) == before
    snapshot = get_table_semantics(_table(restored))
    snapshot.extra["future"]["flag"] = False
    assert get_table_semantics(_table(restored)).extra["future"]["flag"] is True


def test_merge_remaps_caption_anchors_and_keeps_local_ids_independent():
    original = _document()
    before = document_to_json(original)
    merged = merge_documents([original, original], conflicts="rename", metadata_conflicts="keep_first")
    first = resolve_anchor(merged.document, "table").node
    second = resolve_anchor(merged.document, "table~2").node
    assert get_table_semantics(second).caption_ids == ("caption~2",)
    assert get_table_cell_semantics(second.rows[1].cells[1]).headers == ("h1", "a")
    set_table_cell_semantics(second.rows[1].cells[1], TableCellSemantics("d1", "data", headers=("h1",)))
    assert get_table_cell_semantics(first.rows[1].cells[1]).headers == ("h1", "a")
    assert merged.document.validate() == []
    assert document_to_json(original) == before


def test_extraction_closes_caption_dependencies_and_rejects_partial_header_graph():
    original = _document()
    before = document_to_json(original)
    selected = extract_document(original, next(iter_elements(original, Table)))
    assert resolve_anchor(selected, "caption-fr").node.text == "Mesures"
    assert selected.validate() == []
    caption = next(item for item in iter_elements(original, Paragraph) if item.node is resolve_anchor(original, "caption").node)
    selected_caption = extract_document(original, caption)
    assert resolve_anchor(selected_caption, "table") is not None
    assert selected_caption.validate() == []
    cell = next(item for item in walk_model(original) if item.node is _table(original).rows[1].cells[1])
    with pytest.raises(ValueError):
        extract_document(original, cell)
    assert document_to_json(original) == before


@pytest.mark.parametrize(
    "mutation",
    [
        "missing-caption",
        "wrong-caption",
        "missing-owner",
        "missing-header",
        "data-header",
        "duplicate-cell",
        "cycle",
        "unknown-row-group",
        "row-order",
        "cross-group-span",
        "wrong-column-group",
        "column-overlap",
        "column-outside",
        "scope-without-group",
    ],
)
def test_invalid_relations_fail_with_locations_without_serializing(mutation):
    document = _document()
    table = _table(document)
    sem = get_table_semantics(table)
    if mutation == "missing-caption":
        set_table_semantics(table, replace(sem, caption_ids=("gone",)))
    elif mutation == "wrong-caption":
        set_table_semantics(table, replace(sem, caption_ids=("table",)))
    elif mutation == "missing-owner":
        set_anchor(table, None)
    elif mutation == "missing-header":
        set_table_cell_semantics(table.rows[1].cells[1], TableCellSemantics("d1", "data", headers=("gone",)))
    elif mutation == "data-header":
        set_table_cell_semantics(table.rows[1].cells[1], TableCellSemantics("d1", "data", headers=("d2",)))
    elif mutation == "duplicate-cell":
        set_table_cell_semantics(table.rows[1].cells[1], TableCellSemantics("h0", "data"))
    elif mutation == "cycle":
        set_table_cell_semantics(table.rows[0].cells[0], TableCellSemantics("h0", "header", headers=("h2",)))
        set_table_cell_semantics(table.rows[0].cells[2], TableCellSemantics("h2", "header", headers=("h0",)))
    elif mutation == "unknown-row-group":
        set_table_row_semantics(table.rows[1], TableRowSemantics("row-1", "gone"))
    elif mutation == "row-order":
        set_table_row_semantics(table.rows[3], TableRowSemantics("row-3", "head"))
    elif mutation == "cross-group-span":
        table.rows[1].cells[0].row_span = 3
    elif mutation == "wrong-column-group":
        set_table_cell_semantics(
            table.rows[0].cells[1], TableCellSemantics("h1", "header", "column-group", column_group_id="labels")
        )
    elif mutation == "column-overlap":
        table.properties[TABLE_SEMANTICS_PROPERTY]["column_groups"][1]["start"] = 0
    elif mutation == "column-outside":
        set_table_semantics(table, replace(sem, column_groups=(TableColumnGroup("values", 1, 10),)))
    elif mutation == "scope-without-group":
        set_table_row_semantics(table.rows[3], TableRowSemantics("row-3"))
    result = check_document(document)
    assert not result.success
    assert any(issue.code == "semantic.table.invalid" and issue.location for issue in result.issues)
    with pytest.raises(ValueError):
        document_to_json(document)


def test_structural_removal_rolls_back_caption_or_header_references():
    document = _document()
    before = document_to_json(document)
    caption = next(item for item in iter_elements(document, Paragraph) if item.node is resolve_anchor(document, "caption").node)
    with pytest.raises(ValueError):
        remove_node(document, caption)
    header = next(item for item in walk_model(document) if item.node is _table(document).rows[0].cells[1])
    with pytest.raises(ValueError):
        remove_node(document, header)
    with pytest.raises(ValueError):
        transform_elements(document, Table, lambda item: replace(item.node, rows=item.node.rows[1:]))
    assert document_to_json(document) == before


def test_comparison_reports_header_association_and_caption_ownership_loss():
    document = _document()
    target = clone_model(document)
    cell = _table(target).rows[1].cells[1]
    set_table_cell_semantics(cell, TableCellSemantics("d1", "data", headers=("h1",)))
    result = compare_documents(document, target)
    issue = next(issue for issue in result.issues if issue.code == "table-semantics-loss")
    assert issue.measurement["source"]["rows"][1]["cells"][1]["headers"] == ["h1", "a"]
    assert not result.lossless
    target = clone_model(document)
    table = _table(target)
    set_table_semantics(table, replace(get_table_semantics(table), caption_ids=()))
    assert any(issue.code == "table-semantics-loss" for issue in compare_documents(document, target).issues)


def test_opaque_extensions_versions_and_bounded_atomic_setters():
    table = Table(properties={TABLE_SEMANTICS_PROPERTY: {"old": "opaque"}})
    assert get_table_semantics(table) is None
    with pytest.raises(ValueError, match="opaque"):
        set_table_semantics(table, TableSemantics())
    document = _document()
    table = _table(document)
    before = document_to_json(document)
    with pytest.raises(ArtifactLimitError):
        set_table_semantics(table, TableSemantics(extra={"large": "x" * 100}), limits=DocumentLimits(max_bytes=10))
    cyclic = {}
    cyclic["cycle"] = cyclic
    with pytest.raises(ValueError):
        set_table_semantics(table, TableSemantics(extra=cyclic))
    assert document_to_json(document) == before
    raw = json.loads(before)
    raw["version"] = 1
    assert document_from_json(json.dumps(raw)).validate() == []
    table.properties[TABLE_SEMANTICS_PROPERTY]["version"] = True
    with pytest.raises(ValueError, match="version"):
        document_to_json(document)


@pytest.mark.parametrize(
    "raw",
    [
        {"id": "x", "role": "unknown"},
        {"id": "x", "role": "data", "scope": "row"},
        {"id": "x", "headers": ["x"]},
        {"id": "x", "headers": ["h", "h"]},
        {"id": "x", "headers": "h"},
        {"id": "x", "scope": "column-group", "role": "header"},
    ],
)
def test_malformed_cell_declarations_rejected_at_document_boundary(raw):
    document = _document()
    _table(document).rows[1].cells[1].properties[TABLE_CELL_SEMANTICS_PROPERTY] = {
        "format": TABLE_CELL_SEMANTICS_PROPERTY,
        "version": 1,
        **raw,
    }
    with pytest.raises(ValueError):
        document_to_json(document)


def test_duplicate_caption_ownership_and_wrong_owner_are_rejected():
    document = _document()
    second = Table()
    set_anchor(second, Anchor("other-table"))
    set_table_semantics(second, TableSemantics(("caption",)))
    document.sections[1].blocks.append(second)
    assert document.validate()
    document = _document()
    caption = resolve_anchor(document, "caption").node
    caption.properties[TABLE_CELL_SEMANTICS_PROPERTY] = deepcopy(
        _table(document).rows[0].cells[0].properties[TABLE_CELL_SEMANTICS_PROPERTY]
    )
    assert not check_document(document).success


def test_large_span_uses_intervals_and_explicit_work_budget():
    header = _cell("h", "header", "column")
    header.column_span = 10**8
    table = Table([TableRow([header])])
    document = DocumentModel(sections=[Section([table])])
    assert document.validate() == []
    # A wide grid is never expanded into one entry per logical column.
    table = Table([TableRow([_cell(f"h{i}", "header", "column") for i in range(256)])])
    document = DocumentModel(sections=[Section([table])])
    budget = DocumentLimits(max_nodes=25000)
    clone_model(document, limits=budget)  # Input tree fits; the grid work does not.
    with pytest.raises(ArtifactLimitError):
        document.validate(limits=budget)


@pytest.mark.parametrize("reverse", [False, True])
def test_headers_depth_budget_is_independent_of_cell_order(reverse):
    cells = []
    for index in range(13):
        cell = TableCell()
        set_table_cell_semantics(cell, TableCellSemantics(f"h{index}", "header", headers=(f"h{index - 1}",) if index else ()))
        cells.append(cell)
    if reverse:
        cells.reverse()
    document = DocumentModel(sections=[Section([Table([TableRow([cell]) for cell in cells])])])
    budget = DocumentLimits(max_depth=12)
    clone_model(document, limits=budget)
    assert document.validate(limits=DocumentLimits(max_depth=13)) == []
    before = document_to_json(document)
    with pytest.raises(ArtifactLimitError, match="headers depth"):
        document.validate(limits=budget)
    assert document_to_json(document) == before


@pytest.mark.parametrize("owner", ["table", "row", "cell"])
def test_inspection_preserves_semantics_with_explicit_deeper_budget(owner):
    nested = {"leaf": True}
    for _ in range(70):
        nested = {"next": nested}
    cell = TableCell()
    row = TableRow([cell])
    table = Table([row])
    budget = DocumentLimits(max_depth=96)
    if owner == "table":
        set_table_semantics(table, TableSemantics(extra={"future": nested}), limits=budget)
    elif owner == "row":
        set_table_row_semantics(row, TableRowSemantics("row", extra={"future": nested}), limits=budget)
    else:
        set_table_cell_semantics(cell, TableCellSemantics("cell", "data", extra={"future": nested}), limits=budget)
    document = DocumentModel(sections=[Section([table])])
    assert document.validate(limits=budget) == []
    report = inspect_document_model(document, limits=budget, check_external_sources=False)
    snapshot = report.objects[0]["table_semantics"]
    record = (
        snapshot["table"]
        if owner == "table"
        else snapshot["rows"][0]["record"]
        if owner == "row"
        else snapshot["rows"][0]["cells"][0]
    )
    assert record["future"] == nested
    assert compare_documents(document, document, limits=budget).success
