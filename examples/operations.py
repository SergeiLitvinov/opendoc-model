"""Copy, transform selected paragraphs, edit structure, check and save."""

from pathlib import Path
from tempfile import TemporaryDirectory

from opendoc_model import (
    DocumentModel,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    clone_model,
    document_to_json,
    extract_text,
    insert_node,
    iter_elements,
    iter_sections,
    load_document,
    remove_node,
    replace_node,
    save_document,
    transform_elements,
)


def main():
    original = DocumentModel(
        sections=[
            Section(
                headers=[Paragraph([TextRun("Draft header")])],
                blocks=[
                    Table(
                        [
                            TableRow(
                                [
                                    TableCell(
                                        [
                                            Paragraph(
                                                [TextRun("Draft body")],
                                                properties={"selected": True},
                                                provenance=Provenance("example", object_id="body"),
                                            )
                                        ]
                                    )
                                ]
                            )
                        ]
                    )
                ],
            )
        ]
    )
    snapshot = document_to_json(original)
    copied = clone_model(original)

    def finalize(location):
        for run in iter_elements(location.node, TextRun):
            run.node.text = run.node.text.replace("Draft", "Final")
        location.node.provenance = location.node.provenance.transformed("finalize", detail="Draft -> Final")
        return location.node

    result = transform_elements(copied, Paragraph, finalize, predicate=lambda item: item.node.properties.get("selected", False))
    assert extract_text(result) == "Draft header\nFinal body"
    section = next(iter_sections(result))
    added = insert_node(result, section, "blocks", 1, Paragraph([TextRun("Appendix")]))
    replaced = replace_node(result, added, Paragraph([TextRun("Temporary")]))
    assert remove_node(result, replaced).plain_text == "Temporary"
    assert result.validate() == []
    assert document_to_json(original) == snapshot
    assert document_to_json(copied) == snapshot
    generated_dir = Path(".opendoc")
    generated_dir.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=generated_dir, prefix="operations-example-") as directory:
        path = save_document(result, Path(directory) / "document.json")
        assert extract_text(load_document(path)) == "Draft header\nFinal body"
    print("OpenDoc Model operations example: OK")


if __name__ == "__main__":
    main()
