"""Independent declared spacing, explicit fallback and JSON round trips."""

from opendoc_model import (
    DocumentModel,
    Paragraph,
    Section,
    Table,
    TableIndent,
    TabStop,
    TabStops,
    TextRun,
    compare_documents,
    document_from_json,
    document_to_json,
    get_tab_stops,
    get_table_indent,
    resolve_tab_stops,
    set_tab_stop,
    set_tab_stops,
    set_table_indent,
)

table = Table([])
paragraph = Paragraph([TextRun("Label\tValue")])
document = DocumentModel(sections=[Section(blocks=[paragraph, table])])
set_table_indent(table, TableIndent(30))
set_tab_stops(paragraph, TabStops((TabStop(396, alignment="right", leader="line"),), inherit=False))
restored = document
for _ in range(2):
    restored = document_from_json(document_to_json(restored))
assert compare_documents(document, restored).success
assert get_table_indent(restored.sections[0].blocks[1]) == TableIndent(30)
assert get_tab_stops(restored.sections[0].blocks[0]).stops[0].leader == "line"
set_tab_stop(paragraph, 396, TabStop(396, "clear"))
fallback = TabStops((TabStop(396, alignment="right", leader="line"),))
assert not resolve_tab_stops(paragraph, inherited=fallback).stops
set_tab_stops(paragraph, None)
assert resolve_tab_stops(paragraph, inherited=fallback).stops == fallback.stops
print("Declared table indentation and tab stops: JSON, clear and fallback OK")
