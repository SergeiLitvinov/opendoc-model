"""Create, edit, find, save and compare a semantic heading independently."""

from opendoc_model import (
    DocumentModel,
    Heading,
    Paragraph,
    Section,
    TextRun,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    get_heading,
    iter_headings,
    set_heading,
)

paragraph = Paragraph([TextRun("Chapter")])
set_heading(paragraph, Heading(1))
document = DocumentModel(sections=[Section(blocks=[paragraph])])
restored = document_from_json(document_to_json(document))
assert get_heading(next(iter_headings(restored)).node) == Heading(1)
changed = clone_model(restored)
set_heading(next(iter_headings(changed)).node, Heading(2))
comparison = compare_documents(restored, changed)
assert comparison.metrics["comparison"]["object_diff"]["changed_headings"] == 1
assert get_heading(paragraph) == Heading(1)
print("OpenDoc Model heading example: OK")
