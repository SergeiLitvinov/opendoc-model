"""Own opaque font programs: identity, style cascade and bounded composition."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    FONT_REFERENCE_PROPERTY,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    FontReference,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
    check_document,
    clone_model,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    effective_text_style,
    extract_document,
    get_font_reference,
    inspect_document_model,
    iter_elements,
    iter_font_references,
    merge_documents,
    remove_resource,
    replace_resource,
    resolve_style,
    set_font_reference,
)


def fixture():
    a = Resource("a", ResourceKind.FONT, "font/ttf", data=b"own opaque program A")
    b = Resource("b", ResourceKind.FONT, "font/ttf", data=b"own opaque program B")
    base = TextStyle(font_family="OwnSameFamily", bold=False)
    set_font_reference(base, FontReference("a", extra={"future": [1]}))
    child = TextStyle(properties={"base_style_id": "base"})
    direct = TextStyle(font_family="OwnSameFamily", bold=False)
    set_font_reference(direct, FontReference("b", 0))
    paragraph = Paragraph([TextRun("A", TextStyle()), TextRun("B", direct)], style_id="child")
    return DocumentModel(
        styles={"base": base, "child": child}, resources={"a": a, "b": b}, sections=[Section(blocks=[paragraph])]
    ), paragraph


def test_two_json_cycles_preserve_distinct_programs_unknown_and_explicit_zero():
    document, paragraph = fixture()
    expected = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and check_document(document).success
    for index, resource_id in enumerate(("a", "b")):
        style = effective_text_style(document, document.sections[0].blocks[0], document.sections[0].blocks[0].content[index])
        reference = get_font_reference(style)
        assert style.font_family == "OwnSameFamily" and reference.resource_id == resource_id
        assert reference.face_index == (None if index == 0 else 0)
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    assert get_font_reference(paragraph.content[0].style) is None


def test_resolve_edit_delete_and_independent_binding():
    document, paragraph = fixture()
    assert get_font_reference(resolve_style(document, "child")).resource_id == "a"
    override = TextStyle(properties={"base_style_id": "base"})
    set_font_reference(override, FontReference("b", 2))
    resolved = resolve_style(document, "child", overrides=override)
    assert get_font_reference(resolved) == FontReference("b", 2)
    set_font_reference(document.styles["child"], FontReference("b", None))
    assert get_font_reference(effective_text_style(document, paragraph)).resource_id == "b"
    set_font_reference(document.styles["child"], None)
    assert get_font_reference(effective_text_style(document, paragraph)).resource_id == "a"
    set_font_reference(paragraph.content[1].style, None)
    assert get_font_reference(effective_text_style(document, paragraph, paragraph.content[1])).resource_id == "a"
    copied = get_font_reference(document.styles["base"])
    copied.extra["future"].append(2)
    assert get_font_reference(document.styles["base"]).extra == {"future": [1]}
    set_font_reference(document.styles["base"], FontReference("b", 0))
    assert get_font_reference(document.styles["base"]).extra == {"future": [1]}


def test_no_implicit_family_match_or_default_face():
    document, paragraph = fixture()
    set_font_reference(document.styles["base"], None)
    assert effective_text_style(document, paragraph).font_family == "OwnSameFamily"
    assert get_font_reference(effective_text_style(document, paragraph)) is None
    assert FontReference("a") != FontReference("a", 0)


def test_clone_extract_merge_and_shared_owners_remap_resources():
    source, paragraph = fixture()
    # Repeated inline owners must be mapped once from the captured source ID.
    paragraph.content.append(paragraph.content[1])
    expected = deepcopy(source)
    extracted = extract_document(source, next(iter_elements(source, Paragraph)))
    assert set(extracted.resources) == {"a", "b"}
    assert set(extracted.styles) == {"base", "child"}
    merged = merge_documents([source, source], conflicts="rename")
    for index, section in enumerate(merged.document.sections):
        node = section.blocks[0]
        for run_index, old in enumerate(("a", "b", "b")):
            reference = get_font_reference(effective_text_style(merged.document, node, node.content[run_index]))
            assert reference.resource_id == merged.id_maps[index].resources[old]
            assert merged.document.resources[reference.resource_id].data == source.resources[old].data
    for copied in (clone_model(source), extracted, merged.document):
        for link in iter_font_references(copied):
            link.style.properties[FONT_REFERENCE_PROPERTY]["detached"] = [1]
    assert source == expected


def test_named_style_only_dependencies_and_public_locations():
    source, paragraph = fixture()
    paragraph.content = [TextRun("A", TextStyle(properties={"base_style_id": "child"}))]
    paragraph.style_id = None
    extracted = extract_document(source, next(iter_elements(source, Paragraph)))
    assert set(extracted.resources) == {"a"}
    links = list(iter_font_references(source))
    assert len(links) == 1 and links[0].style is source.styles["base"]
    assert links[0].path == "styles['base'].properties['opendoc.font-reference']"
    assert not any(
        issue.feature == "unused-resource" and "'a'" in issue.message for issue in inspect_document_model(source).issues
    )


@pytest.mark.parametrize("identifier,index", [("", None), ("a", -1), ("a", True), ("a", 1.5), ("a", "0"), ("\ud800", None)])
def test_invalid_reference_values(identifier, index):
    with pytest.raises(ValueError):
        FontReference(identifier, index)


@pytest.mark.parametrize("kind", [None, ResourceKind.RASTER_IMAGE])
def test_dangling_and_wrong_kind_are_located_in_named_and_run_styles(kind):
    document, paragraph = fixture()
    if kind is None:
        del document.resources["a"]
    else:
        document.resources["a"].kind = kind
    issues = check_document(document).issues
    assert any(
        issue.code == ("font.reference.missing" if kind is None else "font.reference.kind")
        and "styles['base']" in issue.location
        and "resource_id" in issue.location
        for issue in issues
    )
    with pytest.raises(ValueError):
        document_to_json(document)
    document, paragraph = fixture()
    set_font_reference(paragraph.content[0].style, FontReference("missing"))
    assert any("content[0].style" in issue.location for issue in check_document(document).issues)


def test_atomic_resource_removal_replacement_and_rollback():
    document, _ = fixture()
    original = deepcopy(document)
    with pytest.raises(ValueError, match="used"):
        remove_resource(document, "a")
    assert document == original
    document.resources["image"] = Resource("image", ResourceKind.RASTER_IMAGE, "image/png", data=b"opaque")
    del document.styles["base"].properties[FONT_REFERENCE_PROPERTY]["face_index"]
    original = deepcopy(document)
    with pytest.raises(ValueError):
        remove_resource(document, "a", replacement_id="image")
    assert document == original
    with pytest.raises(ValueError):
        replace_resource(document, "a", document.resources["image"])
    assert document == original
    remove_resource(document, "a", replacement_id="b")
    assert get_font_reference(document.styles["base"]).resource_id == "b"
    assert get_font_reference(document.styles["base"]).face_index is None


def test_unknown_extensions_opaque_versions_and_limits():
    style = TextStyle()
    set_font_reference(style, FontReference("a", extra={"future": [1]}))
    before = deepcopy(style)
    for invalid in (FontReference("a", extra={"version": 2}), replace(FontReference("a"), extra=[])):
        with pytest.raises(ValueError):
            set_font_reference(style, invalid)
        assert style == before
    with pytest.raises(ArtifactLimitError) as caught:
        set_font_reference(style, FontReference("a", extra={"large": list(range(100))}), limits=DocumentLimits(max_nodes=20))
    assert caught.value.quota == "nodes" and caught.value.maximum == 20 and caught.value.path
    assert style == before
    budget = DocumentLimits(max_nodes=300_000)
    set_font_reference(style, FontReference("a", extra={"large": list(range(100_001))}), limits=budget)
    assert len(get_font_reference(style, limits=budget).extra["large"]) == 100_001
    document, _ = fixture()
    document.styles["base"] = style
    assert check_document(document, limits=budget).success
    assert len(list(iter_font_references(document, limits=budget))) == 2
    for _ in range(2):
        document = document_from_json(document_to_json(document, limits=budget), limits=budget)
    with pytest.raises(ArtifactLimitError):
        get_font_reference(style)
    opaque = TextStyle(properties={FONT_REFERENCE_PROPERTY: {"native": 1}})
    assert get_font_reference(opaque) is None
    with pytest.raises(ValueError, match="opaque"):
        set_font_reference(opaque, None)
    document.styles["base"].properties[FONT_REFERENCE_PROPERTY]["version"] = 99
    with pytest.raises(ValueError):
        document_to_json(document, limits=budget)


def test_wrong_owner_and_raw_invalid_face_are_rejected():
    document, paragraph = fixture()
    raw = deepcopy(document.styles["base"].properties[FONT_REFERENCE_PROPERTY])
    paragraph.properties[FONT_REFERENCE_PROPERTY] = raw
    assert any("owner" in issue.message for issue in check_document(document).issues)
    paragraph.properties.clear()
    document.styles["base"].properties[FONT_REFERENCE_PROPERTY]["face_index"] = -1
    assert any("face_index" in issue.location for issue in check_document(document).issues)
