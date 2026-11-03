"""Caption ownership, scoped headers and separate row groups using public API."""

from opendoc_model import (
    Anchor,
    DocumentModel,
    Paragraph,
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
    compare_documents,
    document_from_json,
    document_to_json,
    extract_document,
    get_table_semantics,
    iter_elements,
    merge_documents,
    set_anchor,
    set_table_cell_semantics,
    set_table_row_semantics,
    set_table_semantics,
)

caption = Paragraph([TextRun("Measurements", style=TextStyle(bold=True))])
set_anchor(caption, Anchor("caption"))
header = TableCell([Paragraph([TextRun("Values")])], column_span=2)
cells = [TableCell([Paragraph([TextRun("A")])]), TableCell([Paragraph([TextRun("10")])])]
table = Table([TableRow([header]), TableRow(cells)])
set_anchor(table, Anchor("table"))
set_table_semantics(
    table,
    TableSemantics(
        ("caption",), (TableRowGroup("head", "head"), TableRowGroup("body", "body")), (TableColumnGroup("values", 0, 2),)
    ),
)
set_table_row_semantics(table.rows[0], TableRowSemantics("r0", "head"))
set_table_row_semantics(table.rows[1], TableRowSemantics("r1", "body"))
set_table_cell_semantics(header, TableCellSemantics("header", "header", "column-group", column_group_id="values"))
for index, cell in enumerate(cells):
    set_table_cell_semantics(cell, TableCellSemantics(f"cell-{index}", "data", headers=("header",)))
document = DocumentModel(sections=[Section([caption]), Section([table])])
restored = document_from_json(document_to_json(document))
assert restored.validate() == []
assert compare_documents(document, restored).lossless
extracted = extract_document(document, next(iter_elements(document, Table)))
assert len(extracted.sections) == 2  # Caption dependency is retained.
merged = merge_documents([document, restored], conflicts="rename")
assert get_table_semantics(merged.document.sections[3].blocks[0]).caption_ids == ("caption~2",)
print("Table semantics: caption, header links, groups, JSON and composition OK")
