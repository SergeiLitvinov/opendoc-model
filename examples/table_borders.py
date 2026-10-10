"""Independent border declaration, inheritance, editing and two JSON cycles."""

from dataclasses import replace

from opendoc_model import (
    Border,
    BorderSet,
    ColorValue,
    DocumentModel,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    compare_documents,
    document_from_json,
    document_to_json,
    get_borders,
    resolve_borders,
    set_border,
    set_borders,
)

cell = TableCell([Paragraph([TextRun("Own synthetic fixture")])])
table = Table([TableRow([cell])])
document = DocumentModel(sections=[Section(blocks=[table])])
line = Border(style="solid", color=ColorValue.from_hex("#336699"), width_pt=0.75, offset_pt=2.0, extra={"source": "fixture"})
set_borders(table, BorderSet({"top": line, "inside-horizontal": replace(line, style="dotted")}, extra={"retained": True}))
set_borders(cell, BorderSet({"diagonal-down": line, "top": Border("none")}))
fallback = BorderSet({"top": line, "left": line})
assert resolve_borders(cell, inherited=fallback).sides["top"].kind == "none"
restored = document_from_json(document_to_json(document_from_json(document_to_json(document))))
assert restored == document
assert compare_documents(document, restored).success
record = get_borders(table)
assert record is not None
set_border(table, "top", replace(record.sides["top"], width_pt=1.5))
assert get_borders(table).sides["top"].extra == {"source": "fixture"}
set_border(cell, "top", Border("nil"))
assert resolve_borders(cell, inherited=fallback).sides["top"].kind == "nil"
set_border(cell, "top", None)
assert resolve_borders(cell, inherited=fallback).sides["top"] == line
set_borders(cell, None)
assert get_borders(cell) is None
record = get_borders(table)
set_borders(table, replace(record, extra={**record.extra, "opaque": {"kind": "line"}}))
baseline = document_from_json(document_to_json(document))
record = get_borders(table)
record.extra["opaque"]["kind"] = "none"
set_borders(table, record)
border_issues = [issue for issue in compare_documents(baseline, document).issues if issue.code.startswith("table-border-")]
assert len(border_issues) == 1 and border_issues[0].code == "table-border-change"
print("Table/cell borders: declarations, unknown fields, inheritance and JSON cycles OK")
