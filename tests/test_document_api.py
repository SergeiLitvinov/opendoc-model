"""Document library contracts, without importing the consuming application."""

import pytest

from opendoc_model import (
    DocumentModel,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    compare_inspections,
    document_from_dict,
    document_to_dict,
    inspect_document_model,
    load_document,
    save_document,
)


def test_extensions_resources_and_content_survive_two_cycles(tmp_path):
    source = DocumentModel(
        sections=[
            Section(blocks=[Paragraph(content=[TextRun("Текст документа")], properties={"custom": {"category": "draft"}})])
        ],
        metadata={"custom": {"revision": 3}},
    )
    source.add_resource(
        Resource(
            id="attachment",
            kind=ResourceKind.ATTACHMENT,
            media_type="application/octet-stream",
            data=b"original resource",
        )
    )
    expected = document_to_dict(source)
    current = source
    for cycle in range(2):
        current = load_document(save_document(current, tmp_path / f"{cycle}.json"))
        assert document_to_dict(current) == expected
        assert current.validate() == []
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(current))
    assert comparison.retention["characters"]["ratio"] == 1
    assert comparison.matching_resource_hashes == 1


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("explicit_package", [False, True])
def test_reading_preserves_resources_without_inferring_legacy_package_roles(version, explicit_package):
    source = DocumentModel()
    source.add_resource(Resource("docx-footnotes", ResourceKind.ATTACHMENT, "application/xml", data=b"<notes/>"))
    source.add_resource(
        Resource(
            "custom-styles",
            ResourceKind.ATTACHMENT,
            "application/xml",
            data=b"<styles/>",
            properties={"role": "docx-styles", "partname": "/custom/styles.xml"},
        )
    )
    if explicit_package:
        source.package = PackageGraph(format="custom", root="/main")
        source.package.add_part(PackagePart("/main", "application/octet-stream", b"opaque part"))
        source.package.add_relationship(PackageRelationship("asset", "custom-asset", "/main", "/main"))
    expected = document_to_dict(source)
    payload = document_to_dict(source)
    payload["version"] = version

    restored = document_from_dict(payload)

    assert document_to_dict(restored) == expected
    assert restored.validate() == []


@pytest.mark.parametrize("field", ["version", "property_schema_version"])
def test_future_schemas_are_rejected_instead_of_silently_flattened(field):
    payload = document_to_dict(DocumentModel())
    container = payload if field == "version" else payload["document"]
    container[field] = 999
    with pytest.raises(ValueError, match="unsupported .*version"):
        document_from_dict(payload)


def test_invalid_reference_is_reported_before_use():
    payload = {
        "format": "opendoc.document",
        "version": 2,
        "document": {"sections": [{"blocks": [{"type": "image", "resource_id": "missing"}]}]},
    }
    with pytest.raises(ValueError, match="unknown resource"):
        document_from_dict(payload)
