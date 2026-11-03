"""Relative preferences survive JSON independently of grid and measured layout."""

from dataclasses import replace

from opendoc_model import (
    DocumentModel,
    Section,
    Table,
    TableCell,
    TableRow,
    WidthMeasure,
    compare_documents,
    document_from_json,
    document_to_json,
    get_preferred_width,
    set_preferred_width,
)

table = Table([TableRow([TableCell(), TableCell(), TableCell()])], properties={"grid_widths_twips": [960, 7680, 960]})
set_preferred_width(table, WidthMeasure("absolute", 480, "pt", extra={"future": {"flag": True}}))
for cell, ratio in zip(table.rows[0].cells, (0.1, 0.8, 0.1), strict=True):
    set_preferred_width(cell, WidthMeasure("relative", ratio, "ratio", "table"))
document = DocumentModel(sections=[Section([table])])
restored = document_from_json(document_to_json(document))
assert compare_documents(document, restored).lossless
cell = restored.sections[0].blocks[0].rows[0].cells[0]
assert get_preferred_width(cell) == WidthMeasure("relative", 0.1, "ratio", "table")
cell.properties.set_typed("width_twips", 960)
assert get_preferred_width(cell) == WidthMeasure("absolute", 48, "pt")
assert table.properties.grid_widths_twips == [960, 7680, 960]
assert any(issue.code == "table-width-change" for issue in compare_documents(document, restored).issues)
restored_table = restored.sections[0].blocks[0]
measure = get_preferred_width(restored_table)
assert measure is not None
set_preferred_width(restored_table, replace(measure, value=500))
assert get_preferred_width(restored_table).extra == {"future": {"flag": True}}
assert get_preferred_width(table).value == 480
print("Preferred widths: typed units, JSON, legacy edit and comparison OK")
