"""Find and edit nested document content through the standalone traversal API."""

from opendoc_model import (
    DocumentModel,
    Image,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VisualSurrogate,
    document_from_json,
    document_to_json,
    inspect_document_model,
    iter_elements,
    iter_resource_references,
    walk_model,
)


def main():
    paragraph = Paragraph(
        [TextRun("Draft: nested text"), Image("diagram", "Diagram")],
        visual_surrogate=VisualSurrogate("preview", "Companion appearance"),
    )
    document = DocumentModel(
        sections=[
            Section(
                blocks=[Table([TableRow([TableCell([paragraph])])])],
                headers=[Paragraph([TextRun("Draft: header")])],
            )
        ],
        resources={
            name: Resource(name, ResourceKind.RASTER_IMAGE, "image/png", data=b"example") for name in ("diagram", "preview")
        },
    )
    images = list(iter_elements(document, Image))
    assert len(images) == 1
    assert images[0].path == "sections[0].blocks[0].rows[0].cells[0].blocks[0].content[1]"
    assert images[0].parent.node is paragraph
    for reference in iter_elements(document, TextRun):
        reference.node.text = reference.node.text.replace("Draft: ", "")
    assert [item.resource_id for item in iter_resource_references(document)] == ["preview", "diagram"]
    assert len({item.path for item in walk_model(document)}) == len(list(walk_model(document)))
    assert document.validate() == []
    assert not any(issue.feature == "unused-resource" for issue in inspect_document_model(document).issues)
    restored = document_from_json(document_to_json(document))
    assert [item.node.text for item in iter_elements(restored, TextRun)] == ["header", "nested text"]
    print("OpenDoc Model traversal example: OK")


if __name__ == "__main__":
    main()
