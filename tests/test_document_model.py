"""Тесты богатой промежуточной модели документа."""

import pytest

from opendoc_model.document_model import (
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    VisualSurrogate,
    attach_visual_surrogate,
)


def test_paragraph_plain_text_preserves_formula_and_image_fallbacks():
    paragraph = Paragraph(
        content=[
            TextRun("Energy: ", style=TextStyle(bold=True)),
            Formula("E=mc^2", FormulaFormat.LATEX, fallback_text="E = mc²"),
            Image("diagram", alt_text=" [diagram]"),
        ]
    )

    assert paragraph.plain_text == "Energy: E = mc² [diagram]"


def test_document_accepts_raster_and_vector_resources():
    document = DocumentModel(mode=ConversionMode.FAITHFUL)
    document.add_resource(Resource("photo", ResourceKind.RASTER_IMAGE, "image/png", data=b"png"))
    document.add_resource(Resource("chart", ResourceKind.VECTOR_IMAGE, "image/svg+xml", data=b"<svg/>"))

    assert document.resources["photo"].kind is ResourceKind.RASTER_IMAGE
    assert document.resources["chart"].kind is ResourceKind.VECTOR_IMAGE
    assert document.validate() == []


def test_resource_requires_content_or_source():
    with pytest.raises(ValueError, match="data or source"):
        Resource("missing", ResourceKind.RASTER_IMAGE, "image/png")


def test_duplicate_resource_is_rejected():
    document = DocumentModel()
    resource = Resource("same", ResourceKind.RASTER_IMAGE, "image/png", data=b"x")
    document.add_resource(resource)

    with pytest.raises(ValueError, match="duplicate resource"):
        document.add_resource(resource)


def test_validate_reports_nested_missing_resource():
    table = Table(rows=[TableRow(cells=[TableCell(blocks=[Paragraph(content=[Image("missing")])])])])
    document = DocumentModel(sections=[Section(blocks=[table])])

    errors = document.validate()

    assert len(errors) == 1
    assert "unknown resource 'missing'" in errors[0]
    assert "rows[0].cells[0]" in errors[0]


def test_validate_reports_missing_image_fallback_resource():
    document = DocumentModel(
        resources={"vector": Resource("vector", ResourceKind.VECTOR_IMAGE, "image/svg+xml", data=b"<svg/>")},
        sections=[Section(blocks=[Paragraph(content=[Image("vector", properties={"fallback_resource_id": "missing-preview"})])])],
    )

    assert document.validate() == ["sections[0].blocks[0].content[0]: unknown fallback resource 'missing-preview'"]


def test_validate_reports_missing_visual_surrogate_resource():
    document = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        content=[TextRun("editable")],
                        visual_surrogate=VisualSurrogate(
                            resource_id="missing-preview",
                            reason="native shape is approximate",
                        ),
                    )
                ]
            )
        ]
    )

    assert document.validate() == ["sections[0].blocks[0]: unknown visual surrogate resource 'missing-preview'"]


def test_visual_surrogate_validates_reason_and_fidelity():
    with pytest.raises(ValueError, match="reason"):
        VisualSurrogate(resource_id="preview", reason="")
    with pytest.raises(ValueError, match="between 0 and 1"):
        VisualSurrogate(resource_id="preview", reason="approximation", fidelity=1.1)


def test_attach_visual_surrogate_records_provenance_reason():
    preview = Resource("preview", ResourceKind.RASTER_IMAGE, "image/png", data=b"png")
    paragraph = Paragraph(provenance=Provenance(source_format="pdf", page=1, object_id="shape-2"))

    attach_visual_surrogate(paragraph, preview, reason="native chart geometry is approximate", fidelity=0.92)

    assert paragraph.visual_surrogate is not None
    assert paragraph.visual_surrogate.resource_id == "preview"
    assert paragraph.provenance.events[-1].fallback_reason == "native chart geometry is approximate"
