"""Merge identifier conflicts and extract a self-contained nested paragraph."""

from pathlib import Path
from tempfile import TemporaryDirectory

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
    TextStyle,
    document_to_json,
    extract_document,
    extract_text,
    iter_elements,
    load_document,
    merge_documents,
    save_document,
)


def document(label):
    paragraph = Paragraph([TextRun(label), Image("image", "Diagram")], style_id="body")
    return DocumentModel(
        sections=[Section(blocks=[Table([TableRow([TableCell([paragraph])])])])],
        styles={"body": TextStyle(properties={"base_style_id": "base"}), "base": TextStyle(bold=True)},
        resources={"image": Resource("image", ResourceKind.RASTER_IMAGE, "image/png", label.encode())},
        metadata={label: {"custom": [label]}},
    )


def main():
    first, second = document("First"), document("Second")
    before = [document_to_json(item) for item in (first, second)]
    try:
        merge_documents([first, second])
    except ValueError as error:
        assert "identifier conflict" in str(error)
    else:
        raise AssertionError("Conflicts must require an explicit decision")
    merged = merge_documents([first, second], conflicts="rename")
    assert merged.id_maps[1].styles == {"body": "body~2", "base": "base~2"}
    assert merged.id_maps[1].resources == {"image": "image~2"}
    selected = list(iter_elements(merged.document, Paragraph))[1]
    extracted = extract_document(merged.document, selected)
    assert extract_text(extracted) == "SecondDiagram"
    assert set(extracted.styles) == {"body~2", "base~2"}
    assert set(extracted.resources) == {"image~2"}
    assert extracted.resources["image~2"].data == b"Second"
    assert merged.document.validate() == extracted.validate() == []
    output = Path(".opendoc")
    output.mkdir(exist_ok=True)
    with TemporaryDirectory(dir=output, prefix="composition-example-") as directory:
        path = save_document(extracted, Path(directory) / "extracted.json")
        assert document_to_json(load_document(path)) == document_to_json(extracted)
    extracted.styles["base~2"].bold = False
    assert merged.document.styles["base~2"].bold is True
    assert [document_to_json(item) for item in (first, second)] == before
    print("OpenDoc Model composition example: OK")


if __name__ == "__main__":
    main()
