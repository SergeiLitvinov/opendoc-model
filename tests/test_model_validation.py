"""Structural failures are consistent in memory, persistence and inspection."""

import copy
import json
import re
from collections.abc import MutableMapping
from pathlib import Path

import pytest

from opendoc_model import (
    ArtifactLimitError,
    Box,
    ColorValue,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    compare_inspections,
    document_from_dict,
    document_to_dict,
    inspect_document_model,
    save_document,
)

COLLECTIONS = (
    "blocks",
    "headers",
    "footers",
    "first_page_headers",
    "first_page_footers",
    "even_page_headers",
    "even_page_footers",
)


def _fixture():
    return json.loads((Path(__file__).parent / "fixtures/compatibility/document-v2.json").read_text(encoding="utf-8"))


def _replace(root, path, value):
    parts = path.split("/")
    node = root
    for part in parts[:-1]:
        node = (
            node[int(part)] if isinstance(node, list) else node[part] if isinstance(node, MutableMapping) else getattr(node, part)
        )
    part = parts[-1]
    if isinstance(node, list):
        node[int(part)] = value
    elif isinstance(node, MutableMapping):
        node[part] = value
    else:
        setattr(node, part, value)


P = "sections/0/blocks/0/rows/0/cells/0/blocks/0"


@pytest.mark.parametrize(
    ("model_path", "json_path", "value", "location"),
    [
        (P + "/style_id", P + "/style_id", "missing", "style_id"),
        ("sections/0/blocks/0/style_id", "sections/0/blocks/0/style_id", "missing", "blocks[0].style_id"),
        ("styles/accent/properties/base_style_id", "styles/accent/properties/base_style_id", "missing", "base_style_id"),
        (P + "/content/0/properties/resource_id", P + "/content/0/properties/resource_id", "missing", "resource_id"),
        (
            "sections/0/even_page_headers/0/resource_id",
            "sections/0/even_page_headers/0/resource_id",
            "missing",
            "even_page_headers[0]",
        ),
        (P + "/visual_surrogate/resource_id", P + "/visual_surrogate/resource_id", "missing", "blocks[0]"),
        ("resources/preview/id", "resources/preview/id", "different", "resources['preview'].id"),
        ("resources/preview/kind", "resources/preview/kind", "unknown", "resources['preview'].kind"),
        (P + "/content/0/style/bold", P + "/content/0/style/bold", "yes", "style.bold"),
        (P + "/content/0/text", P + "/content/0/text", 42, "text"),
        (P + "/content/1/display", P + "/content/1/display", 1, "display"),
        (P + "/content/1/value", P + "/content/1/value", "", "value"),
        (P + "/content/1/format", P + "/content/1/format", "unknown", "format"),
        (P + "/provenance/page", P + "/provenance/page", -1, "provenance.page"),
        (P + "/provenance/events/0/operation", P + "/provenance/events/0/operation", 3, "events[0].operation"),
        (P + "/visual_surrogate/fidelity", P + "/visual_surrogate/fidelity", 2, "visual_surrogate.fidelity"),
        ("sections/0/blocks/0/rows/0/cells/0/row_span", "sections/0/blocks/0/rows/0/cells/0/row_span", 0, "row_span"),
        ("sections/0/blocks/0/rows/0/cells/0/column_span", "sections/0/blocks/0/rows/0/cells/0/column_span", True, "column_span"),
        ("sections/0/page/width/pt", "sections/0/page/width_pt", 0, "page"),
        ("sections/0/page/margin_left/pt", "sections/0/page/margin_left_pt", -1, "page"),
        ("sections/0/page/margin_left/pt", "sections/0/page/margin_left_pt", 600, "page"),
        ("sections/0/even_page_headers/0/box/width", "sections/0/even_page_headers/0/box/width", -1, "box.width"),
        ("sections/0/even_page_headers/0/box/x", "sections/0/even_page_headers/0/box/x", float("inf"), "box"),
        ("sections/0/even_page_headers/0/box/rotation", "sections/0/even_page_headers/0/box/rotation", True, "box.rotation"),
        ("sections/0/even_page_headers/0/crop/left", "sections/0/even_page_headers/0/crop/left", -0.1, "crop.left"),
        ("sections/0/even_page_headers/0/crop/top", "sections/0/even_page_headers/0/crop/top", 2, "crop.top"),
        ("sections/0/even_page_headers/0/crop/right", "sections/0/even_page_headers/0/crop/right", 0.9, "crop"),
        ("package/root", "package/root", "relative", "package.root"),
        ("package/relationships/0/source", "package/relationships/0/source", "/missing", "relationships[0].source"),
        ("package/relationships/0/target", "package/relationships/0/target", "/missing", "relationships[0].target"),
        ("package/relationships/0/id", "package/relationships/0/id", "", "relationships[0].id"),
        ("package/relationships/0/external", "package/relationships/0/external", 1, "relationships[0].external"),
    ],
)
def test_memory_and_json_reject_same_structural_failures(model_path, json_path, value, location):
    payload = _fixture()
    model = document_from_dict(payload)
    # Add explicit default objects omitted in the independent fixture.
    paragraph = payload["document"]["sections"][0]["blocks"][0]["rows"][0]["cells"][0]["blocks"][0]
    paragraph["content"][0]["style"] = {}
    payload["document"]["sections"][0]["page"] = {}
    payload["document"]["styles"]["accent"]["properties"] = {}
    _replace(model, model_path, value)
    _replace(payload["document"], json_path, value)
    errors = model.validate()
    assert any(location in error for error in errors), errors
    with pytest.raises(ValueError, match=re.escape(location)):
        document_from_dict(payload)
    with pytest.raises(ValueError, match=re.escape(location)):
        document_to_dict(model)
    report = inspect_document_model(model)
    assert not report.valid
    assert report.metrics == report.metadata == {}
    assert any(location in issue.location or location in issue.message for issue in report.issues)


@pytest.mark.parametrize("collection", COLLECTIONS)
@pytest.mark.parametrize("violation", ["span", "inline", "block", "resource", "style"])
def test_nested_tables_and_every_section_collection_are_validated(collection, violation):
    paragraph = Paragraph(content=[TextRun("text")])
    inner = TableCell(blocks=[paragraph])
    table = Table(rows=[TableRow(cells=[TableCell(blocks=[Table(rows=[TableRow(cells=[inner])])])])])
    section = Section()
    setattr(section, collection, [table])
    model = DocumentModel(sections=[section])
    payload = document_to_dict(model)
    nested = payload["document"]["sections"][0][collection][0]["rows"][0]["cells"][0]["blocks"][0]["rows"][0]["cells"][0]
    if violation == "span":
        inner.row_span = nested["row_span"] = 1.5
    elif violation == "inline":
        paragraph.content.append(Table())
        nested["blocks"][0]["content"].append({"type": "table"})
    elif violation == "block":
        inner.blocks.append(TextRun("wrong kind"))
        nested["blocks"].append({"type": "text", "text": "wrong kind"})
    elif violation == "resource":
        paragraph.content.append(Image("missing"))
        nested["blocks"][0]["content"].append({"type": "image", "resource_id": "missing"})
    else:
        paragraph.style_id = nested["blocks"][0]["style_id"] = "missing"
    path = f"sections[0].{collection}[0].rows[0].cells[0].blocks[0].rows[0].cells[0]"
    assert all(path in error for error in model.validate())
    assert model.validate()
    with pytest.raises(ValueError, match=re.escape(path)):
        document_from_dict(payload)


def test_style_cycles_and_duplicate_package_edges_have_paths_on_read_and_write():
    payload = _fixture()
    payload["document"]["styles"]["accent"]["properties"] = {"base_style_id": "accent"}
    with pytest.raises(ValueError, match="cyclic style inheritance"):
        document_from_dict(payload)
    model = document_from_dict(_fixture())
    model.styles["accent"].properties["base_style_id"] = "accent"
    assert "styles['accent'].properties.base_style_id" in model.validate()[0]
    model.styles["accent"].properties.clear()
    model.package.relationships.append(copy.deepcopy(model.package.relationships[0]))
    assert "relationships[2].id: duplicate relationship" in model.validate()[0]
    payload = _fixture()
    payload["document"]["package"]["relationships"].append(copy.deepcopy(payload["document"]["package"]["relationships"][0]))
    with pytest.raises(ValueError, match=r"relationships\[2\].id: duplicate relationship"):
        document_from_dict(payload)


@pytest.mark.parametrize("name", ["/", "/a/../b", "/a//b", "/a/./b", "/a/"])
def test_package_part_names_are_normalized_and_match_keys(name):
    graph = PackageGraph("custom", root="/")
    graph.parts[name] = PackagePart(name, "application/octet-stream", b"")
    assert "parts" in graph.validate()[0]
    with pytest.raises(ValueError, match="parts"):
        document_to_dict(DocumentModel(package=graph))


def test_package_anchor_and_external_target_are_format_independent():
    graph = PackageGraph("custom", root="/anchor")
    graph.add_part(PackagePart("/asset", "application/octet-stream", b""))
    graph.add_relationship(PackageRelationship("container", "custom", "/", "/asset"))
    graph.add_relationship(PackageRelationship("anchor", "custom", "/anchor", "urn:opaque:thing", external=True))
    assert graph.validate() == []
    assert document_from_dict(document_to_dict(DocumentModel(package=graph))).package == graph


@pytest.mark.parametrize("field", ["sections", "styles", "resources", "metadata"])
def test_mutable_containers_can_be_corrupted_without_crashing_diagnostics(field):
    document = DocumentModel()
    setattr(document, field, None)
    assert field in document.validate()[0]
    assert not inspect_document_model(document).valid


def test_validation_distinguishes_quota_and_cycle_from_unknown_measurement(tmp_path):
    model = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("text")])])])
    with pytest.raises(ArtifactLimitError, match="nodes"):
        model.validate(limits=DocumentLimits(max_nodes=2))
    with pytest.raises(ArtifactLimitError, match="nodes"):
        inspect_document_model(model, limits=DocumentLimits(max_nodes=2))
    model.sections[0].blocks[0].content.append(model.sections[0].blocks[0])
    assert "cyclic" in model.validate()[0]
    report = inspect_document_model(model)
    assert not report.valid
    comparison = compare_inspections(inspect_document_model(DocumentModel()), report)
    assert comparison.object_diff["available"] is False
    assert comparison.object_diff["lost"] == []
    path = tmp_path / "document.json"
    path.write_bytes(b"previous")
    with pytest.raises(ValueError, match="cyclic"):
        save_document(model, path)
    assert path.read_bytes() == b"previous"


def test_inspection_warnings_do_not_reject_valid_structure():
    model = document_from_dict(_fixture())
    model.resources.pop("external")
    model.sections[0].blocks.append(Formula("x", FormulaFormat.LATEX, box=Box(-1, 0, 5, 5)))
    model.sections[0].blocks.append(Image("preview", crop=ImageCrop(0.1, 0, 0.1, 0)))
    assert model.validate() == []
    report = inspect_document_model(model)
    assert report.valid
    assert report.has_warnings
    assert {"formula-fallback", "element-geometry", "image-alt-text"} <= {issue.feature for issue in report.issues}


def test_color_metadata_has_same_rules_in_memory_and_json():
    document = DocumentModel(styles={"bad": TextStyle(color=ColorValue.from_hex("#123", icc_profile=123))})
    assert "styles['bad'].color.icc_profile" in document.validate()[0]
    payload = {
        "format": "opendoc.document",
        "version": 2,
        "document": {"styles": {"bad": {"color": {"space": "srgb", "components": [0, 0, 0], "icc_profile": 123}}}},
    }
    with pytest.raises(ValueError, match="color.icc_profile"):
        document_from_dict(payload)
