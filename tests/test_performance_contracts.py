"""Optimization retains occurrence semantics and does not cache across operations."""

import hashlib

from opendoc_model import DocumentModel, Paragraph, Section, Table, TableCell, TableRow, TextRun, inspect_document_model


def test_nested_table_content_is_computed_once_without_collapsing_aliased_occurrences(monkeypatch):
    paragraph = Paragraph([TextRun("kept")])
    inner = Table([TableRow([TableCell([paragraph, paragraph])])])
    outer = Table([TableRow([TableCell([inner, inner])])])
    document = DocumentModel(sections=[Section(blocks=[outer])])
    reads = []
    original = Paragraph.plain_text.fget

    def counted(node):
        reads.append(node)
        return original(node)

    monkeypatch.setattr(Paragraph, "plain_text", property(counted))
    report = inspect_document_model(document)
    assert len(reads) == 1
    tables = [item for item in report.objects if item["type"] == "table"]
    paragraphs = [item for item in report.objects if item["type"] == "paragraph"]
    assert len(tables) == 3 and len(paragraphs) == 4
    assert tables[0]["content_hash"] == hashlib.sha256(b"kept kept kept kept").hexdigest()
    assert tables[1]["content_hash"] == tables[2]["content_hash"] == hashlib.sha256(b"kept kept").hexdigest()
    assert report.metrics["paragraphs"] == 4
    paragraph.content[0].text = "edited"
    changed = inspect_document_model(document)
    assert len(reads) == 2
    assert changed.objects[0]["content_hash"] == hashlib.sha256(b"edited edited edited edited").hexdigest()


def test_unknown_table_content_remains_unknown_with_repeated_occurrences():
    from opendoc_model import Image, Resource, ResourceKind

    table = Table([TableRow([TableCell([Image("remote")])])])
    document = DocumentModel(
        sections=[Section(blocks=[table, table])],
        resources={"remote": Resource("remote", ResourceKind.RASTER_IMAGE, "image/png", source="https://invalid.test/data")},
    )
    report = inspect_document_model(document)
    assert len(report.objects) == 4
    assert all(item["content_hash"] is None for item in report.objects)
