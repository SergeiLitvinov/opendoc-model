"""Two persisted cycles preserve every supported model field and collection."""

import copy
import json

import pytest

from opendoc_model import (
    Box,
    ColorSpace,
    ColorValue,
    ConversionMode,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    Length,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    PageSettings,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    VisualSurrogate,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    load_document,
    save_document,
)
from opendoc_model.properties import VersionedProperties

COLLECTIONS = (
    "blocks",
    "headers",
    "footers",
    "first_page_headers",
    "first_page_footers",
    "even_page_headers",
    "even_page_footers",
)


def _properties(label):
    return {"vendor:extension": {"label": label, "values": [None, False, True, 0, 1.25, "Юникод\n😀", [], {}]}}


def _origin(label):
    return Provenance(
        "independent",
        "inputs/example.ext",
        0,
        label,
        "/opaque/main",
        [ProvenanceEvent("create", "source", None), ProvenanceEvent("transform", "detail", "reason")],
    )


def _surrogate():
    return VisualSurrogate("raster", "Companion appearance", media_type="image/png", fidelity=0.0)


def _blocks(label):
    style = TextStyle(
        font_family="Example Font",
        font_size=Length(11.5),
        bold=False,
        italic=True,
        underline=False,
        superscript=True,
        subscript=False,
        color=ColorValue(ColorSpace.CMYK, (0.1, 0.2, 0.3, 0.4), alpha=0.6, icc_profile="custom", blend_mode="multiply"),
        background=ColorValue.from_hex("#12345678"),
        language="ru-RU",
        properties={**_properties(label), "base_style_id": "base"},
    )
    run = TextRun(
        "Текст\n😀",
        style=style,
        link="https://example.invalid/item",
        properties=_properties(label),
        provenance=_origin(label),
        visual_surrogate=_surrogate(),
    )
    image = Image(
        "vector",
        "Схема",
        Box(0, -1, 120.5, 80.25, -15),
        {**_properties(label), "fallback_resource_id": "raster"},
        ImageCrop(0.1, 0.2, 0.3, 0.1),
        _origin(label),
        _surrogate(),
    )
    formulas = [
        Formula(
            value,
            format_,
            display=True,
            fallback_text="x/2",
            box=Box(3, 4, 50, 0, 90),
            properties=_properties(label),
            provenance=_origin(label),
            visual_surrogate=_surrogate(),
        )
        for format_, value in (
            (FormulaFormat.LATEX, r"\frac{x}{2}"),
            (FormulaFormat.MATHML, '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'),
            (FormulaFormat.OMML, '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"/>'),
        )
    ]
    paragraph = Paragraph(
        [run, TextRun("", style=TextStyle(color="theme:accent", background="")), copy.deepcopy(image), *copy.deepcopy(formulas)],
        "accent",
        "center",
        Box(1, 2, 400, 60, 0),
        _properties(label),
        _origin(label),
        _surrogate(),
    )
    nested = Table(
        [TableRow([TableCell([copy.deepcopy(paragraph)], 2, 3, _properties("cell"))], _properties("row"))],
        "base",
        Box(5, 6, 200, 150, 30),
        _properties("nested"),
        _origin(label),
        _surrogate(),
    )
    table = Table(
        [
            TableRow(
                [TableCell([nested, copy.deepcopy(image), *copy.deepcopy(formulas)], properties=_properties("outer-cell"))],
                _properties("outer-row"),
            )
        ],
        "accent",
        Box(10, 20, 300, 200, 180),
        _properties(label),
        _origin(label),
        _surrogate(),
    )
    return [paragraph, table, image, *formulas, Paragraph(), Table(rows=[TableRow(cells=[TableCell()])])]


def _document(mode):
    sections = []
    for index in range(2):
        section = Section(
            page=PageSettings(Length(612 + index), Length(792 + index), Length(20), Length(21), Length(22), Length(23)),
            properties=_properties(f"section{index}"),
            provenance=_origin(f"section{index}"),
        )
        for name in COLLECTIONS:
            setattr(section, name, _blocks(f"{index}:{name}"))
        sections.append(section)
    resources = {
        "raster": Resource(
            "raster",
            ResourceKind.RASTER_IMAGE,
            "image/png",
            b"\x00\xff\x01",
            "original/image.png",
            "preview.png",
            {**_properties("raster"), "role": "docx-preview"},
            _origin("raster"),
        ),
        "vector": Resource("vector", ResourceKind.VECTOR_IMAGE, "image/svg+xml", b"<svg/>", properties=_properties("vector")),
        "font": Resource("font", ResourceKind.FONT, "font/ttf", b"font", properties=_properties("font")),
        "docx-styles": Resource(
            "docx-styles",
            ResourceKind.ATTACHMENT,
            "application/octet-stream",
            b"",
            properties={**_properties("empty"), "role": "docx-styles", "partname": "/consumer/styles"},
        ),
        "external": Resource(
            "external",
            ResourceKind.ATTACHMENT,
            "application/octet-stream",
            source="assets/relative.bin",
            filename="relative.bin",
            provenance=_origin("external"),
        ),
        "remote": Resource("remote", ResourceKind.ATTACHMENT, "application/octet-stream", source="urn:opaque:data"),
    }
    package = PackageGraph(
        "independent",
        root="/anchor",
        parts={
            "/opaque/main": PackagePart("/opaque/main", "application/octet-stream", bytes(range(256))),
            "/opaque/empty": PackagePart("/opaque/empty", "application/octet-stream", b""),
        },
        relationships=[
            PackageRelationship("start", "vendor:main", "/anchor", "/opaque/main"),
            PackageRelationship("asset", "vendor:asset", "/opaque/main", "/opaque/empty"),
            PackageRelationship("asset", "vendor:reference", "/opaque/empty", "urn:opaque:external", True),
            PackageRelationship("container", "vendor:main", "/", "/opaque/main"),
        ],
    )
    return DocumentModel(
        sections=sections,
        resources=resources,
        styles={
            "base": TextStyle(bold=True, color="#123", properties=_properties("base")),
            "accent": TextStyle(italic=False, properties={**_properties("accent"), "base_style_id": "base"}),
            "default": TextStyle(),
        },
        metadata=_properties("document"),
        package=package,
        mode=mode,
        source_format="independent",
    )


@pytest.mark.parametrize("mode", list(ConversionMode))
@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("transport", ["dict", "json", "file"])
def test_complete_model_survives_two_cycles(mode, version, transport, tmp_path):
    expected = _document(mode)
    original = copy.deepcopy(expected)
    payload = document_to_dict(expected)
    payload["version"] = version
    input_copy = copy.deepcopy(payload)
    if transport == "dict":
        current = document_from_dict(payload)
    elif transport == "json":
        current = document_from_json(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    else:
        initial = tmp_path / "v1-or-v2.json"
        initial.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        current = load_document(initial)
    for cycle in range(2):
        if transport == "dict":
            saved = document_to_dict(current)
            assert saved["version"] == 2
            current = document_from_dict(saved)
        elif transport == "json":
            current = document_from_json(document_to_json(current, indent=None if cycle == 0 else 2))
        else:
            current = load_document(save_document(current, tmp_path / f"{cycle}.json", indent=None if cycle == 0 else 2))
        assert current == expected
        assert current.validate() == []
        assert current.version == 2
        assert current.resources["docx-styles"].data == b""
        assert current.resources["external"].data is None
        assert current.resources["remote"].source == "urn:opaque:data"
        for section in current.sections:
            for collection in COLLECTIONS:
                run = getattr(section, collection)[0].content[0]
                assert run.style.bold is False and run.style.italic is True
                assert run.provenance.page == 0
                assert run.visual_surrogate.fidelity == 0.0
                assert run.properties["vendor:extension"]["values"][1] is False
    assert expected == original
    assert payload == input_copy


def test_reading_external_sources_and_opaque_parts_never_opens_them(monkeypatch):
    payload = document_to_dict(_document(ConversionMode.BALANCED))

    def forbidden(*args, **kwargs):
        raise AssertionError("Resource source must remain an opaque reference")

    monkeypatch.setattr("pathlib.Path.open", forbidden)
    current = document_from_json(json.dumps(payload))
    assert current.resources["external"].data is None
    assert current.resources["remote"].data is None
    assert current.package.parts["/opaque/main"].data == bytes(range(256))


def test_missing_optional_values_preserve_none_empty_and_false():
    source = DocumentModel(
        sections=[Section(blocks=[Paragraph(content=[TextRun(""), Formula("x", FormulaFormat.LATEX, display=False)])])]
    )
    for _ in range(2):
        source = document_from_json(document_to_json(source))
    paragraph = source.sections[0].blocks[0]
    assert paragraph.content[0].text == ""
    assert paragraph.content[0].style.bold is None
    assert paragraph.content[1].display is False
    assert paragraph.content[1].fallback_text == ""
    assert paragraph.provenance is paragraph.visual_surrogate is paragraph.box is None


def test_generic_property_bags_preserve_data_where_model_accepts_them():
    bag = VersionedProperties({"vendor:value": [None, 0, False, "text"]})
    document = DocumentModel(
        sections=[Section(blocks=[Formula("x", FormulaFormat.LATEX, properties=copy.deepcopy(bag))])],
        resources={
            "asset": Resource("asset", ResourceKind.ATTACHMENT, "application/octet-stream", b"", properties=copy.deepcopy(bag))
        },
        metadata=copy.deepcopy(bag),
    )
    assert document.validate() == []
    current = document_from_json(document_to_json(document))
    current = document_from_json(document_to_json(current))
    assert current.metadata == bag
    assert current.resources["asset"].properties == bag
    assert current.sections[0].blocks[0].properties == bag
