"""Rich notes and their links work without a consuming application."""

from opendoc_model import (
    DocumentModel,
    Footnote,
    FootnoteReference,
    Paragraph,
    Section,
    TextRun,
    document_from_json,
    document_to_json,
    extract_document,
    get_footnote,
    iter_footnote_numbers,
    iter_footnote_references,
    merge_documents,
    set_footnote,
    set_footnote_reference,
)

document = DocumentModel()
set_footnote(document, Footnote("source", [Paragraph([TextRun("Source and explanation")])]))
reference = TextRun("1")
set_footnote_reference(reference, FootnoteReference("source"))
document.sections = [Section(blocks=[Paragraph([TextRun("A statement"), reference])])]
restored = document_from_json(document_to_json(document))
assert restored == document
assert [item.number for item in iter_footnote_numbers(restored)] == [1]
selected = extract_document(restored, next(iter_footnote_references(restored)))
assert get_footnote(selected, "source").blocks[0].plain_text == "Source and explanation"
merged = merge_documents([document, restored], conflicts="rename")
assert merged.id_maps[1].footnotes == {"source": "source~2"}
assert [item.number for item in iter_footnote_numbers(merged.document)] == [1, 2]
print("OpenDoc Model rich footnotes example: OK")
