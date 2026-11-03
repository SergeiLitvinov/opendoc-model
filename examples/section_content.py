"""Nested tables and all six header/footer collections survive public operations."""

from opendoc_model import (
    DocumentModel,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    check_document,
    clone_model,
    document_from_json,
    document_to_json,
    iter_elements,
)


def paragraph(text):
    return Paragraph([TextRun(text)])


inner = Table([TableRow([TableCell([paragraph("Nested body")])])])
outer = Table([TableRow([TableCell([inner])])])
document = DocumentModel(
    sections=[
        Section(
            blocks=[outer],
            headers=[paragraph("Header")],
            first_page_headers=[paragraph("First header")],
            even_page_headers=[paragraph("Even header")],
            footers=[paragraph("Footer")],
            first_page_footers=[paragraph("First footer")],
            even_page_footers=[paragraph("Even footer")],
        )
    ]
)
expected = [
    "sections[0].headers[0]",
    "sections[0].first_page_headers[0]",
    "sections[0].even_page_headers[0]",
    "sections[0].blocks[0].rows[0].cells[0].blocks[0].rows[0].cells[0].blocks[0]",
    "sections[0].footers[0]",
    "sections[0].first_page_footers[0]",
    "sections[0].even_page_footers[0]",
]
assert [item.path for item in iter_elements(document, Paragraph)] == expected
restored = document_from_json(document_to_json(document))
assert restored == document
assert [item.path for item in iter_elements(restored, Paragraph)] == expected
for item in iter_elements(restored, TextRun):
    item.node.text += " (edited)"
assert all(item.node.text.endswith("(edited)") for item in iter_elements(restored, TextRun))
assert all(not item.node.text.endswith("(edited)") for item in iter_elements(document, TextRun))
assert check_document(restored).success
broken = clone_model(document)
broken.sections[0].blocks[0].rows[0].cells[0].column_span = 0
result = check_document(broken)
assert not result.success
assert any(issue.location.endswith("cells[0].column_span") for issue in result.issues)
print("Nested tables and all header/footer collections: JSON, traversal, editing and diagnostics OK")
