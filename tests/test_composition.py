"""Complete dependencies, explicit conflicts, known links and independent inputs."""

from pathlib import Path

import pytest

from opendoc_model import (
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    ConversionMode,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    NodeLocation,
    PackageGraph,
    PackagePart,
    PackageRelationship,
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
    clone_model,
    document_from_json,
    document_to_json,
    extract_document,
    extract_text,
    iter_elements,
    iter_resource_references,
    iter_sections,
    load_document,
    merge_documents,
    save_document,
    walk_model,
)


def _resource(identifier, label):
    return Resource(
        identifier,
        ResourceKind.RASTER_IMAGE,
        "image/png",
        f"{label}:{identifier}".encode(),
        properties={"vendor:resource_id": "image", "custom": [label]},
    )


def _document(label):
    run = TextRun(
        label,
        style=TextStyle(properties={"base_style_id": "body"}),
        properties={"resource_id": "text", "vendor:style_id": "body"},
        visual_surrogate=VisualSurrogate("run-preview", "run"),
    )
    image = Image(
        "image",
        "ALT",
        properties={"fallback_resource_id": "fallback", "vendor:resource_id": "image"},
        visual_surrogate=VisualSurrogate("image-preview", "image"),
    )
    paragraph = Paragraph(
        [run, image, Formula("x", FormulaFormat.LATEX, visual_surrogate=VisualSurrogate("formula-preview", "formula"))],
        style_id="body",
        properties={"numbering_source_style_id": "numbering", "custom": [label]},
        provenance=Provenance("source", label, 0, label, events=[ProvenanceEvent("read")]),
        visual_surrogate=VisualSurrogate("paragraph-preview", "paragraph"),
    )
    table = Table(
        [TableRow([TableCell([paragraph]), TableCell([Paragraph([TextRun("Other")])])], properties={"custom": [label]})],
        style_id="table",
        properties={"custom": [label]},
        visual_surrogate=VisualSurrogate("table-preview", "table"),
    )
    identifiers = [
        "image",
        "fallback",
        "text",
        "run-preview",
        "image-preview",
        "formula-preview",
        "paragraph-preview",
        "table-preview",
        "unused",
    ]
    document = DocumentModel(
        sections=[
            Section(
                blocks=[table],
                headers=[Paragraph([TextRun("Header")])],
                properties={"custom": [label]},
                provenance=Provenance("source", label),
            )
        ],
        resources={identifier: _resource(identifier, label) for identifier in identifiers},
        styles={
            "base": TextStyle(font_family=label, properties={"custom": [label]}),
            "body": TextStyle(bold=True, properties={"base_style_id": "base", "numbering_source_style_id": "numbering"}),
            "numbering": TextStyle(italic=True, properties={"base_style_id": "base"}),
            "table": TextStyle(properties={"base_style_id": "base"}),
            "spare": TextStyle(properties={"custom": [label]}),
        },
        metadata={label: {"custom": [label]}},
        source_format="source",
    )
    assert document.validate() == []
    return document


def _package(label="one", format_="opaque", root="/main"):
    return PackageGraph(
        format_,
        root,
        {root: PackagePart(root, "application/octet-stream", label.encode())},
        [PackageRelationship("external", "link", root, "https://invalid.test", True)],
    )


def _assert_roundtrip(document, tmp_path):
    assert document.validate() == []
    assert document_from_json(document_to_json(document)) == document
    assert load_document(save_document(document, tmp_path / "document.json")) == document


def test_merge_no_conflicts_retains_order_and_all_definitions_in_independent_model(tmp_path):
    first = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("First")])])],
        resources={"unused": _resource("unused", "first")},
        metadata={"one": [1]},
    )
    second = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("Second")], style_id="body")])],
        styles={"body": TextStyle(bold=True)},
        metadata={"two": [2]},
    )
    before = [document_to_json(item) for item in (first, second)]
    merged = merge_documents(iter((first, second)))
    assert extract_text(merged.document) == "First\nSecond"
    assert list(merged.document.resources) == ["unused"]
    assert list(merged.document.styles) == ["body"]
    assert merged.document.metadata == {"one": [1], "two": [2]}
    assert merged.id_maps[0].resources == {"unused": "unused"}
    assert merged.id_maps[0].styles == {}
    assert merged.id_maps[1].styles == {"body": "body"}
    _assert_roundtrip(merged.document, tmp_path)
    merged.document.sections[0].blocks[0].content[0].text = "changed"
    merged.document.resources["unused"].properties["custom"].append("changed")
    merged.document.styles["body"].bold = False
    merged.document.metadata["one"].append(11)
    assert [document_to_json(item) for item in (first, second)] == before


@pytest.mark.parametrize("domain", ["styles", "resources"])
def test_default_conflict_diagnoses_input_domain_and_identifier_even_equal_definitions(domain):
    first = DocumentModel()
    if domain == "styles":
        first.styles["same"] = TextStyle()
    else:
        first.resources["same"] = _resource("same", "a")
    second = clone_model(first)
    before = document_to_json(first)
    with pytest.raises(ValueError, match=r"documents\[1\]." + domain + r"\['same'\].*conflict"):
        merge_documents([first, second])
    assert document_to_json(first) == before == document_to_json(second)


def test_rename_reserved_ids_and_all_links_preserves_meanings_aliases_and_extensions(tmp_path):
    first, second = _document("one"), _document("two")
    second.styles["body~2"] = TextStyle()
    second.resources["image~2"] = _resource("image~2", "reserved")
    paragraph = list(iter_elements(second, Paragraph))[1].node
    paragraph.content.append(paragraph.content[1])
    second.sections[0].blocks[0].rows[0].cells[0].blocks.append(paragraph)
    # Force both mapping sources and targets to exist: a second rewrite of a
    # shared field would silently redirect to the reserved resource instead.
    first.resources["image~2"] = _resource("image~2", "first-reserved")
    before = [document_to_json(item) for item in (first, second)]
    merged = merge_documents([first, second], conflicts="rename")
    maps = merged.id_maps[1]
    assert maps.styles["body"] == "body~3"
    assert maps.styles["body~2"] == "body~2"
    assert maps.resources["image"] == "image~3"
    assert maps.resources["image~2"] == "image~2~2"
    result = merged.document
    assert len(result.styles) == 11
    assert len(result.resources) == 20
    assert result.styles[maps.styles["body"]].properties["base_style_id"] == maps.styles["base"]
    assert result.styles[maps.styles["body"]].properties["numbering_source_style_id"] == maps.styles["numbering"]
    paragraphs = list(iter_elements(result.sections[1], Paragraph))
    para = paragraphs[1].node
    assert para.style_id == maps.styles["body"]
    assert para.properties["numbering_source_style_id"] == maps.styles["numbering"]
    assert para.content[0].style.properties["base_style_id"] == maps.styles["body"]
    assert para.content[0].properties["vendor:style_id"] == "body"
    image = para.content[1]
    assert image is para.content[3]
    assert para is result.sections[1].blocks[0].rows[0].cells[0].blocks[1]
    assert image.resource_id == maps.resources["image"]
    assert image.properties["fallback_resource_id"] == maps.resources["fallback"]
    assert image.visual_surrogate.resource_id == maps.resources["image-preview"]
    assert image.properties["vendor:resource_id"] == "image"
    assert para.provenance.object_id == "two" and para.provenance.events[0].operation == "read"
    assert result.sections[1].blocks[0].style_id == maps.styles["table"]
    original_ids = [ref.resource_id for ref in iter_resource_references(second)]
    assert [ref.resource_id for ref in iter_resource_references(result.sections[1])] == [
        maps.resources[name] for name in original_ids
    ]
    assert all(resource.id == identifier for identifier, resource in result.resources.items())
    assert result.resources[maps.resources["image"]].data == b"two:image"
    _assert_roundtrip(result, tmp_path)
    maps.resources["image"] = "outside-map-change"
    assert image.resource_id == "image~3"
    assert [document_to_json(item) for item in (first, second)] == before


def test_rename_is_deterministic_across_many_inputs_and_reserves_later_originals():
    documents = [DocumentModel(resources={"x": _resource("x", str(index))}) for index in range(4)]
    documents[3].resources["x~2"] = _resource("x~2", "reserved")
    result = merge_documents(documents, conflicts="rename")
    assert [mapping.resources["x"] for mapping in result.id_maps] == ["x", "x~3", "x~4", "x~5"]
    assert result.id_maps[3].resources["x~2"] == "x~2"
    assert document_to_json(result.document) == document_to_json(merge_documents(documents, conflicts="rename").document)


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_merge_rewrites_resource_and_style_links_in_every_section_collection(field):
    first, second = _document("one"), _document("two")
    table = second.sections[0].blocks[0]
    for name in SECTION_CONTENT_FIELDS:
        setattr(second.sections[0], name, [])
    setattr(second.sections[0], field, [table])
    merged = merge_documents([first, second], conflicts="rename")
    assert getattr(merged.document.sections[1], field)[0].style_id == "table~2"
    assert all(ref.resource_id.endswith("~2") for ref in iter_resource_references(merged.document.sections[1]))
    assert merged.document.validate() == []


@pytest.mark.parametrize("policy", ["error", "keep_first", "keep_last"])
def test_metadata_conflicts_are_separate_explicit_and_copy_nested_values(policy):
    first = DocumentModel(metadata={"same": {"value": [1]}, "first": True})
    second = DocumentModel(metadata={"same": {"value": [2]}, "last": True})
    before = [document_to_json(item) for item in (first, second)]
    if policy == "error":
        with pytest.raises(ValueError, match=r"documents\[1\].metadata\['same'\].*conflict"):
            merge_documents([first, second])
    else:
        result = merge_documents([first, second], metadata_conflicts=policy).document
        assert result.metadata == {"same": {"value": [1 if policy == "keep_first" else 2]}, "first": True, "last": True}
        result.metadata["same"]["value"].append(3)
    assert [document_to_json(item) for item in (first, second)] == before


def test_modes_require_explicit_selection_and_mixed_source_is_unknown():
    first = DocumentModel(mode=ConversionMode.EDITABLE, source_format="one", version=1)
    second = DocumentModel(mode=ConversionMode.FAITHFUL, source_format="two")
    with pytest.raises(ValueError, match="modes differ"):
        merge_documents([first, second])
    result = merge_documents([first, second], mode=ConversionMode.BALANCED).document
    assert result.mode is ConversionMode.BALANCED and result.version == 2
    assert result.source_format is None
    assert merge_documents([first], mode=ConversionMode.FAITHFUL).document.mode is ConversionMode.FAITHFUL
    assert merge_documents([first]).document.source_format == "one"
    with pytest.raises(ValueError, match="ConversionMode"):
        merge_documents([first], mode="balanced")


@pytest.mark.parametrize("change", ["missing", "format", "root", "bytes", "relationships"])
def test_package_preserve_rejects_incompatible_graphs_and_drop_is_explicit(change, tmp_path):
    first = DocumentModel(package=_package())
    second = clone_model(first)
    if change == "missing":
        second.package = None
    elif change == "format":
        second.package.format = "another"
    elif change == "root":
        second.package.root = "/logical-root"
    elif change == "bytes":
        second.package.parts["/main"].data = b"different"
    else:
        second.package.relationships[0].target = "https://different.test"
    assert first.validate() == second.validate() == []
    before = [document_to_json(item) for item in (first, second)]
    with pytest.raises(ValueError, match="explicit"):
        merge_documents([first, second])
    with pytest.raises(ValueError, match="identical"):
        merge_documents([first, second], package_policy="preserve")
    result = merge_documents([first, second], package_policy="drop").document
    assert result.package is None
    _assert_roundtrip(result, tmp_path)
    assert [document_to_json(item) for item in (first, second)] == before


def test_identical_opaque_packages_are_preserved_only_on_explicit_request(tmp_path):
    first, second = _document("one"), _document("two")
    first.package = _package()
    second.package = clone_model(DocumentModel(package=_package())).package
    with pytest.raises(ValueError, match="explicit"):
        merge_documents([first, second], conflicts="rename")
    result = merge_documents([first, second], conflicts="rename", package_policy="preserve").document
    assert result.package == first.package == second.package
    assert result.package is not first.package and result.package is not second.package
    assert result.package.parts["/main"].data == b"one"
    _assert_roundtrip(result, tmp_path)


@pytest.mark.parametrize("policy", ["error", "preserve", "drop"])
def test_single_input_copies_package_and_all_definitions_and_root_extraction(policy):
    original = _document("one")
    original.package = _package()
    merged = merge_documents([original], package_policy=policy).document
    extracted = extract_document(original, next(walk_model(original)), package_policy=policy)
    expected = clone_model(original)
    if policy == "drop":
        expected.package = None
    assert merged == extracted == expected
    assert merged is not original and extracted is not original


def test_extract_paragraph_copies_transitive_styles_and_every_resource_use(tmp_path):
    document = _document("one")
    before = document_to_json(document)
    location = list(iter_elements(document, Paragraph))[1]
    result = extract_document(document, location)
    assert list(result.styles) == ["base", "body", "numbering"]
    assert list(result.resources) == [
        "image",
        "fallback",
        "text",
        "run-preview",
        "image-preview",
        "formula-preview",
        "paragraph-preview",
    ]
    assert extract_text(result) == "oneALT"
    assert result.sections[0].page == document.sections[0].page
    assert result.sections[0].properties == document.sections[0].properties
    assert result.sections[0].provenance == document.sections[0].provenance
    assert result.metadata == document.metadata
    assert result.mode == document.mode and result.source_format == "source"
    assert result.sections[0].blocks[0].provenance == location.node.provenance
    _assert_roundtrip(result, tmp_path)
    result.sections[0].blocks[0].properties["custom"].append("changed")
    result.sections[0].blocks[0].provenance.events[0].operation = "changed"
    result.styles["base"].properties["custom"].append("changed")
    result.resources["image"].properties["custom"].append("changed")
    result.metadata["one"]["custom"].append("changed")
    result.sections[0].page.width.pt = 1000
    assert document_to_json(document) == before


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_extract_section_keeps_all_collections_and_selected_block_keeps_header_position(field):
    document = _document("one")
    paragraph = list(iter_elements(document, Paragraph))[1].node
    setattr(document.sections[0], field, [paragraph])
    section = next(iter_sections(document))
    full = extract_document(document, section)
    assert full.sections[0] == section.node
    assert "spare" not in full.styles and "unused" not in full.resources
    location = next(item for item in iter_elements(document, Paragraph) if item.field == field and item.parent.kind == "section")
    partial = extract_document(document, location)
    assert getattr(partial.sections[0], field) == [paragraph]
    assert all(getattr(partial.sections[0], name) == [] for name in SECTION_CONTENT_FIELDS if name != field)
    assert partial.validate() == []


@pytest.mark.parametrize("type_", [Table, TableRow, TableCell, Paragraph, TextRun, Image, Formula])
def test_extraction_wraps_each_subtree_in_minimal_valid_context(type_, tmp_path):
    document = _document("one")
    # Header's plain paragraph/run are not the intended context-rich subtree.
    location = next(item for item in walk_model(document) if isinstance(item.node, type_) and ".blocks[0]" in item.path)
    result = extract_document(document, location)
    nodes = [item.node for item in walk_model(result)]
    assert any(item == location.node for item in nodes)
    assert all(item is not location.node for item in nodes)
    if type_ in (TableRow, TableCell):
        assert result.sections[0].blocks[0].style_id == "table"
        assert result.sections[0].blocks[0].visual_surrogate.resource_id == "table-preview"
        assert len(result.sections[0].blocks[0].rows) == 1
        if type_ is TableCell:
            assert len(result.sections[0].blocks[0].rows[0].cells) == 1
    if type_ in (TextRun, Image, Formula):
        paragraph = result.sections[0].blocks[0]
        assert isinstance(paragraph, Paragraph)
        assert paragraph.style_id == "body" and len(paragraph.content) == 1
        assert paragraph.visual_surrogate.resource_id == "paragraph-preview"
        assert "paragraph-preview" in result.resources
    _assert_roundtrip(result, tmp_path)


def test_extract_inline_header_uses_paragraph_shell_in_original_header_collection():
    document = DocumentModel(
        sections=[Section(even_page_headers=[Paragraph([TextRun("selected"), TextRun("omitted")], style_id="header")])],
        styles={"header": TextStyle()},
    )
    result = extract_document(document, next(iter_elements(document, TextRun)))
    assert result.sections[0].blocks == []
    assert len(result.sections[0].even_page_headers) == 1
    assert result.sections[0].even_page_headers[0].plain_text == "selected"
    assert result.sections[0].even_page_headers[0].style_id == "header"
    assert result.validate() == []


@pytest.mark.parametrize("policy", ["error", "preserve", "drop"])
def test_partial_extraction_of_package_has_explicit_contract(policy, tmp_path):
    document = _document("one")
    document.package = _package()
    before = document_to_json(document)
    location = list(iter_elements(document, Paragraph))[1]
    if policy == "error":
        with pytest.raises(ValueError, match="partial extraction.*explicit"):
            extract_document(document, location)
    else:
        result = extract_document(document, location, package_policy=policy)
        assert result.package == (document.package if policy == "preserve" else None)
        _assert_roundtrip(result, tmp_path)
        if policy == "preserve":
            result.package.relationships[0].target = "changed"
    assert document_to_json(document) == before


def test_composition_does_not_load_external_sources_or_infer_unknown_extension_links(monkeypatch):
    document = DocumentModel(
        sections=[Section(blocks=[Image("asset", properties={"vendor:resource_id": "unused"})])],
        resources={
            "asset": Resource("asset", ResourceKind.RASTER_IMAGE, "image/png", source="gone.png"),
            "unused": _resource("unused", "unused"),
        },
        metadata={"external": "gone.png"},
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("Composition must not read resource sources")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(Path, "is_file", forbidden)
    extracted = extract_document(document, next(iter_elements(document, Image)))
    assert set(extracted.resources) == {"asset"}
    assert extracted.resources["asset"].source == "gone.png"
    assert extracted.sections[0].blocks[0].properties["vendor:resource_id"] == "unused"
    result = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_first").document
    assert result.resources["asset~2"].source == "gone.png" and result.resources["asset~2"].data is None


@pytest.mark.parametrize("bad", [None, "id", 1])
def test_inputs_are_documents_and_nonempty(bad):
    with pytest.raises(ValueError):
        merge_documents(bad)
    with pytest.raises(ValueError, match="expected DocumentModel"):
        merge_documents([bad])
    with pytest.raises(ValueError, match="at least one"):
        merge_documents([])


@pytest.mark.parametrize("option", ["conflicts", "metadata_conflicts", "package_policy"])
def test_unknown_policies_do_not_fall_back(option):
    with pytest.raises(ValueError, match=option):
        merge_documents([DocumentModel()], **{option: "unknown"})
    if option == "package_policy":
        with pytest.raises(ValueError, match=option):
            extract_document(DocumentModel(), None, **{option: "unknown"})


def test_invalid_input_semantics_or_unknown_numbering_style_never_produce_result():
    invalid = _document("one")
    invalid.sections[0].blocks[0].style_id = "missing"
    with pytest.raises(ValueError, match="unknown style"):
        merge_documents([invalid])
    valid = _document("two")
    location = list(iter_elements(valid, Paragraph))[1]
    location.node.properties["numbering_source_style_id"] = "missing"
    assert valid.validate() == []  # General property validation is intentionally unchanged.
    with pytest.raises(ValueError, match="numbering_source_style_id.*unknown style"):
        merge_documents([valid])
    with pytest.raises(ValueError, match="numbering_source_style_id.*unknown style"):
        extract_document(valid, location)
    location.node.properties["numbering_source_style_id"] = 3
    with pytest.raises(ValueError, match="numbering_source_style_id.*style identifier"):
        extract_document(valid, location)


def test_style_dependency_cycles_through_numbering_are_closed_without_recursion():
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("x")], style_id="a")])],
        styles={
            "a": TextStyle(properties={"numbering_source_style_id": "b"}),
            "b": TextStyle(properties={"numbering_source_style_id": "a"}),
            "unused": TextStyle(),
        },
    )
    result = extract_document(document, next(iter_sections(document)))
    assert list(result.styles) == ["a", "b"] and result.validate() == []


def test_stale_or_foreign_extraction_location_never_selects_another_node():
    document = _document("one")
    location = next(iter_elements(document, TextRun))
    document.sections.insert(0, Section())
    with pytest.raises(ValueError, match="stale"):
        extract_document(document, location)
    foreign = next(iter_sections(clone_model(document)))
    with pytest.raises(ValueError, match="does not belong"):
        extract_document(document, foreign)
    with pytest.raises(ValueError, match="NodeLocation"):
        extract_document(document, None)


def test_input_budget_is_cumulative_and_bounds_generator_consumption():
    consumed = []

    def inputs():
        for index in range(100):
            consumed.append(index)
            yield DocumentModel()

    assert merge_documents([DocumentModel(), DocumentModel()], limits=DocumentLimits(max_nodes=18)).document.validate() == []
    with pytest.raises(ArtifactLimitError, match="nodes"):
        merge_documents(inputs(), limits=DocumentLimits(max_nodes=18))
    assert consumed == [0, 1, 2]
    with pytest.raises(ArtifactLimitError, match="nodes"):
        merge_documents([DocumentModel(), DocumentModel()], limits=DocumentLimits(max_nodes=17))


def test_input_embedded_budget_is_cumulative_even_when_identical_packages_are_preserved_once():
    first = DocumentModel(package=_package())
    second = clone_model(first)
    assert merge_documents(
        [first, second], package_policy="preserve", limits=DocumentLimits(max_embedded_bytes=6)
    ).document.package
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        merge_documents([first, second], package_policy="preserve", limits=DocumentLimits(max_embedded_bytes=5))


def test_extraction_requires_valid_full_source_and_applies_result_limits():
    document = _document("one")
    location = next(iter_sections(document))
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        extract_document(document, location, limits=DocumentLimits(max_embedded_bytes=1))
    document.styles["spare"].properties["base_style_id"] = "spare"
    with pytest.raises(ValueError, match="cyclic style inheritance"):
        extract_document(document, location)


def test_same_input_twice_has_independent_per_input_copies_and_identity_maps_for_first():
    document = _document("one")
    merged = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_first")
    assert merged.id_maps[0].styles == {identifier: identifier for identifier in document.styles}
    assert merged.document.sections[0] is not merged.document.sections[1]
    first, second = merged.document.sections
    first.blocks[0].rows[0].cells[0].blocks[0].content[0].text = "changed"
    assert second.blocks[0].rows[0].cells[0].blocks[0].content[0].text == "one"
    assert extract_text(document).startswith("Header\none")


def test_shared_styles_surrogates_and_property_bags_are_rewritten_once_per_original_value():
    first = _document("one")
    second = _document("two")
    first.styles["base~2"] = TextStyle()
    second.styles["base~2"] = TextStyle()
    shared_style = second.styles["body"]
    paragraph = list(iter_elements(second, Paragraph))[1].node
    paragraph.content[0].style = shared_style
    shared_properties = paragraph.content[1].properties
    shared_surrogate = paragraph.content[1].visual_surrogate
    other_image = Image("image", properties=shared_properties, visual_surrogate=shared_surrogate)
    paragraph.content.append(other_image)
    merged = merge_documents([first, second], conflicts="rename")
    map_ = merged.id_maps[1]
    copied = list(iter_elements(merged.document.sections[1], Paragraph))[1].node
    assert copied.content[0].style is merged.document.styles[map_.styles["body"]]
    assert copied.content[0].style.properties["base_style_id"] == "base~3"
    assert copied.content[1].properties is copied.content[3].properties
    assert copied.content[1].visual_surrogate is copied.content[3].visual_surrogate
    assert copied.content[3].properties["fallback_resource_id"] == map_.resources["fallback"]
    assert copied.content[3].visual_surrogate.resource_id == map_.resources["image-preview"]
    assert shared_style.properties["base_style_id"] == "base"


def test_dependency_closure_covers_long_chain_and_excludes_unrelated_invalid_numbering_extensions():
    styles = {f"s{index}": TextStyle(properties={"base_style_id": f"s{index + 1}"}) for index in range(99)}
    styles["s99"] = TextStyle()
    styles["unused"] = TextStyle(properties={"numbering_source_style_id": "unresolved-origin"})
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("x")], style_id="s0")])], styles=styles)
    extracted = extract_document(document, next(iter_sections(document)))
    assert len(extracted.styles) == 100 and "unused" not in extracted.styles
    assert extracted.validate() == []
    with pytest.raises(ValueError, match="unresolved-origin"):
        merge_documents([document])


@pytest.mark.parametrize("version", [1, 2])
def test_persisted_fixtures_compose_without_consumer_migrations(version, tmp_path):
    source = Path(__file__).parent / f"fixtures/compatibility/document-v{version}.json"
    document = document_from_json(source.read_bytes())
    merged = merge_documents([document]).document
    assert merged == document
    _assert_roundtrip(merged, tmp_path)
    extracted = extract_document(document, next(iter_sections(document)), package_policy="preserve")
    assert extracted.sections[0] == document.sections[0]
    _assert_roundtrip(extracted, tmp_path)


def test_explicit_extension_dependencies_include_full_style_closure_and_opaque_resources(tmp_path):
    document = _document("one")
    document.styles["spare"].properties["base_style_id"] = "base"
    document.resources["font"] = Resource("font", ResourceKind.FONT, "font/ttf", b"font")
    paragraph = list(iter_elements(document, Paragraph))[1]
    result = extract_document(
        document, paragraph, additional_styles=["spare", "spare"], additional_resources=iter(["unused", "font"])
    )
    assert list(result.styles) == ["base", "body", "numbering", "spare"]
    assert result.resources["font"].data == b"font"
    assert "unused" in result.resources
    _assert_roundtrip(result, tmp_path)


@pytest.mark.parametrize("argument", ["additional_styles", "additional_resources"])
@pytest.mark.parametrize("values", [None, "one", [""], [1], ["missing"]])
def test_additional_dependencies_are_explicit_valid_identifiers(argument, values):
    document = _document("one")
    with pytest.raises(ValueError, match=argument):
        extract_document(document, next(iter_sections(document)), **{argument: values})


def test_dependency_hint_generator_is_bounded_even_if_it_repeats_one_identifier_forever():
    document = DocumentModel(styles={"a": TextStyle()})
    consumed = []

    def repeated():
        for index in range(100):
            consumed.append(index)
            yield "a"

    with pytest.raises(ArtifactLimitError, match="additional_styles.*nodes"):
        extract_document(document, next(walk_model(document)), additional_styles=repeated(), limits=DocumentLimits(max_nodes=30))
    assert consumed == list(range(31))


def test_unicode_case_sensitive_names_have_exact_maps_and_intact_links():
    first = DocumentModel(styles={"Стиль": TextStyle(), "стиль": TextStyle()})
    second = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("Текст")], style_id="Стиль")])],
        styles={"Стиль": TextStyle(), "Стиль~2": TextStyle()},
    )
    result = merge_documents([first, second], conflicts="rename")
    assert result.id_maps[1].styles == {"Стиль": "Стиль~3", "Стиль~2": "Стиль~2"}
    assert result.document.sections[0].blocks[0].style_id == "Стиль~3"
    assert "стиль" in result.document.styles
    assert document_from_json(document_to_json(result.document)) == result.document


def test_extraction_uses_containing_section_page_properties_and_trace_from_second_section():
    document = DocumentModel(
        sections=[
            Section(),
            Section(
                footers=[Paragraph([TextRun("Second")])], properties={"custom": [2]}, provenance=Provenance("source", page=1)
            ),
        ]
    )
    document.sections[1].page.width.pt = 700
    location = next(iter_elements(document, TextRun))
    result = extract_document(document, location)
    assert result.sections[0].page.width.pt == 700
    assert result.sections[0].properties["custom"] == [2]
    assert result.sections[0].provenance.page == 1
    assert result.sections[0].footers[0].plain_text == "Second"
    assert result.sections[0].blocks == []
    result.sections[0].properties["custom"].append(3)
    assert document.sections[1].properties["custom"] == [2]


def test_inconsistent_inline_role_in_manually_created_location_is_rejected():
    document = _document("one")
    location = next(iter_elements(document, Image))
    forged = NodeLocation(location.node, location.path, location.parent, location.field, location.index, "block")
    with pytest.raises(ValueError, match="inconsistent node kind"):
        extract_document(document, forged)
    root = NodeLocation(document, "", None, None, None, "section")
    with pytest.raises(ValueError, match="inconsistent root kind"):
        extract_document(document, root)
