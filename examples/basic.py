"""Runnable guide example, including persistence and structural comparison."""

from pathlib import Path
from tempfile import TemporaryDirectory

from opendoc_model import (
    DocumentModel,
    Paragraph,
    Section,
    TextRun,
    compare_inspections,
    inspect_document_model,
    load_document,
    save_document,
)


def main():
    document = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("Первый документ")])])])
    assert document.validate() == []
    with TemporaryDirectory() as directory:
        path = save_document(document, Path(directory) / "document.json")
        restored = load_document(path)
    assert restored.validate() == []
    assert restored.sections[0].blocks[0].content[0].text == "Первый документ"
    comparison = compare_inspections(inspect_document_model(document), inspect_document_model(restored))
    assert comparison.retention["characters"]["ratio"] == 1
    print("OpenDoc Model guide example: OK")


if __name__ == "__main__":
    main()
