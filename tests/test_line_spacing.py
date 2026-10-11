"""Own paragraph line-spacing declarations, model cascade and two JSON cycles."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    LINE_SPACING_PROPERTY,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    LineSpacing,
    Paragraph,
    QualityPolicy,
    Section,
    TextRun,
    TextStyle,
    check_document,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    effective_text_style,
    extract_document,
    get_line_spacing,
    inspect_document_model,
    iter_elements,
    merge_documents,
    resolve_line_spacing,
    set_line_spacing,
)


def fixture():
    base, child = TextStyle(), TextStyle(properties={"base_style_id": "base"})
    set_line_spacing(base, LineSpacing("minimum", 14, extra={"future": [1]}))
    paragraph = Paragraph([TextRun("Own line 😀\nSecond")], style_id="child")
    return DocumentModel(styles={"base": base, "child": child}, sections=[Section(blocks=[paragraph])]), paragraph


@pytest.mark.parametrize("rule,value", [("minimum", 14), ("exact", 18), ("relative", 1.5), (None, None)])
def test_two_cycles_old_version_and_independence(rule, value):
    document, paragraph = fixture()
    set_line_spacing(paragraph, LineSpacing(rule, value, extra={"unknown": {"items": [2]}}))
    original = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == original
    assert compare_documents(original, document).success
    assert (
        compare_inspections(inspect_document_model(original), inspect_document_model(document)).object_diff[
            "line_spacing_available"
        ]
        is True
    )
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    result = get_line_spacing(paragraph)
    result.extra["unknown"]["items"].append(3)
    assert get_line_spacing(paragraph).extra["unknown"]["items"] == [2]
    result = resolve_line_spacing(paragraph, document=original)
    result.extra["unknown"]["items"].append(3)
    assert get_line_spacing(paragraph).extra["unknown"]["items"] == [2]


def test_inheritance_edit_delete_unknown_and_explicit_fallback():
    document, paragraph = fixture()
    assert resolve_line_spacing(paragraph, document=document).rule == "minimum"
    set_line_spacing(document.styles["child"], LineSpacing("relative", 1.25))
    assert resolve_line_spacing(paragraph, document=document) == LineSpacing("relative", 1.25)
    assert get_line_spacing(effective_text_style(document, paragraph)) == LineSpacing("relative", 1.25)
    set_line_spacing(paragraph, LineSpacing("exact", 12))
    assert resolve_line_spacing(paragraph, document=document) == LineSpacing("exact", 12)
    set_line_spacing(paragraph, LineSpacing())
    assert resolve_line_spacing(paragraph, document=document, inherited=LineSpacing("exact", 20)) == LineSpacing()
    set_line_spacing(paragraph, None)
    assert resolve_line_spacing(paragraph, document=document) == LineSpacing("relative", 1.25)
    set_line_spacing(document.styles["child"], None)
    assert resolve_line_spacing(paragraph, document=document).rule == "minimum"
    set_line_spacing(document.styles["base"], None)
    assert resolve_line_spacing(paragraph, document=document) is None
    assert resolve_line_spacing(paragraph, document=document, inherited=LineSpacing("exact", 20)) == LineSpacing("exact", 20)
    with pytest.raises(ValueError, match="document required"):
        resolve_line_spacing(paragraph)


def test_run_style_does_not_set_paragraph_spacing():
    document, paragraph = fixture()
    set_line_spacing(paragraph.content[0].style, LineSpacing("exact", 99))
    assert resolve_line_spacing(paragraph, document=document).value == 14
    assert inspect_document_model(document).objects[0]["line_spacing"]["resolved"]["value"] == 14


@pytest.mark.parametrize(
    "target,feature",
    [
        (LineSpacing("minimum", 18), "line-spacing-change"),
        (LineSpacing("exact", 14), "line-spacing-change"),
        (LineSpacing("relative", 1), "line-spacing-change"),
        (LineSpacing(), "line-spacing-loss"),
        (None, "line-spacing-loss"),
    ],
)
def test_located_comparison_direct_and_style_edits(target, feature):
    source, paragraph = fixture()
    set_line_spacing(paragraph, LineSpacing("minimum", 14))
    changed = clone_model(source)
    set_line_spacing(changed.sections[0].blocks[0], target)
    result = compare_documents(source, changed, policies=[QualityPolicy(0)])
    issue = next(item for item in result.issues if item.code == feature)
    assert issue.location == "sections[0].blocks[0]"
    assert issue.measurement["source"]["direct"]["rule"] == "minimum"
    if feature.endswith("loss"):
        assert not result.success
    # A changed named declaration affects an otherwise unchanged paragraph.
    source, _ = fixture()
    changed = clone_model(source)
    set_line_spacing(changed.styles["base"], target)
    assert any(item.code == feature for item in compare_documents(source, changed).issues)


def test_opaque_legacy_unavailable_and_extensions_not_compared():
    source = DocumentModel(
        sections=[
            Section(
                blocks=[
                    Paragraph(
                        [TextRun("Own")],
                        properties={
                            "line_spacing_pt": 14,
                            "docx_line_spacing_rule": "atLeast",
                        },
                    )
                ]
            )
        ]
    )
    expected = deepcopy(source)
    for _ in range(2):
        source = document_from_json(document_to_json(source))
    assert source == expected
    for props in (
        {"line_spacing_pt": 18, "docx_line_spacing_rule": "atLeast"},
        {"line_spacing_pt": 14, "docx_line_spacing_rule": "exact"},
        {"line_spacing_pt": 14},
        {},
    ):
        target = clone_model(source)
        target.sections[0].blocks[0].properties = props
        result = compare_documents(source, target)
        assert (
            compare_inspections(inspect_document_model(source), inspect_document_model(target)).object_diff[
                "line_spacing_available"
            ]
            is False
        )
        assert not any(item.code.startswith("line-spacing-") for item in result.issues)
    source, paragraph = fixture()
    set_line_spacing(paragraph, LineSpacing("exact", 14, extra={"opaque": [1]}))
    target = clone_model(source)
    set_line_spacing(target.sections[0].blocks[0], LineSpacing("exact", 14, extra={"opaque": [2]}))
    assert not any(item.code.startswith("line-spacing-") for item in compare_documents(source, target).issues)
    before, after = inspect_document_model(source), inspect_document_model(target)
    del before.objects[0]["line_spacing"]
    assert compare_inspections(before, after).object_diff["line_spacing_available"] is False
    before = inspect_document_model(source)
    before.objects[0]["line_spacing"] = {"direct": {"rule": "exact", "value": False}, "resolved": None}
    assert compare_inspections(before, after).object_diff["line_spacing_available"] is False


@pytest.mark.parametrize(
    "rule,value",
    [
        ("bad", 14),
        (None, 14),
        ("minimum", None),
        ("relative", 0),
        ("exact", -1),
        ("minimum", float("nan")),
        ("exact", float("inf")),
        ("relative", True),
        ("exact", "14"),
    ],
)
def test_invalid_values(rule, value):
    with pytest.raises(ValueError):
        LineSpacing(rule, value)


def test_atomic_limits_unknown_versions_and_owner_validation():
    document, paragraph = fixture()
    set_line_spacing(paragraph, LineSpacing("minimum", 14, extra={"future": [1]}))
    before = deepcopy(paragraph)
    for value in (LineSpacing("exact", 18, extra={"version": 2}), replace(LineSpacing("exact", 18), extra=[])):
        with pytest.raises(ValueError):
            set_line_spacing(paragraph, value)
        assert paragraph == before
    with pytest.raises(ArtifactLimitError):
        set_line_spacing(
            paragraph, LineSpacing("exact", 18, extra={"large": list(range(100))}), limits=DocumentLimits(max_nodes=20)
        )
    assert paragraph == before
    set_line_spacing(paragraph, LineSpacing("exact", 18))
    assert get_line_spacing(paragraph).extra == {"future": [1]}
    assert get_line_spacing(paragraph).rule == "exact"
    for props in ({LINE_SPACING_PROPERTY: {"opaque": 1}}, {LINE_SPACING_PROPERTY: None}):
        opaque = Paragraph([], properties=props)
        assert get_line_spacing(opaque) is None
        with pytest.raises(ValueError, match="occupied"):
            set_line_spacing(opaque, None)
        assert opaque.properties == props
    for owner in (document.styles["base"], paragraph, paragraph.content[0].style):
        set_line_spacing(owner, LineSpacing("exact", 14))
        owner.properties[LINE_SPACING_PROPERTY]["version"] = 2
        assert any(item.code == "semantic.spacing.invalid" for item in check_document(document).issues)
        with pytest.raises(ValueError):
            document_to_json(document)
        owner.properties[LINE_SPACING_PROPERTY]["version"] = 1
    document.metadata[LINE_SPACING_PROPERTY] = deepcopy(paragraph.properties[LINE_SPACING_PROPERTY])
    assert any(item.code == "semantic.spacing.invalid" for item in check_document(document).issues)


def test_composition_keeps_style_chain_and_properties():
    source, paragraph = fixture()
    set_line_spacing(paragraph, LineSpacing("exact", 14, extra={"future": [2]}))
    for result in (
        clone_model(source),
        extract_document(source, next(iter_elements(source, Paragraph))),
        merge_documents([source, source], conflicts="rename").document,
    ):
        for section in result.sections:
            node = section.blocks[0]
            assert resolve_line_spacing(node, document=result).value == 14
            node.properties[LINE_SPACING_PROPERTY]["future"].append(3)
    assert get_line_spacing(paragraph).extra["future"] == [2]


def test_partial_profile_does_not_hide_known_changes():
    source, paragraph = fixture()
    source.sections[0].blocks.append(Paragraph([TextRun("Opaque")], properties={"line_spacing_pt": 12}))
    target = clone_model(source)
    set_line_spacing(target.sections[0].blocks[0], LineSpacing("exact", 18))
    result = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert result.object_diff["line_spacing_available"] is False
    assert any(issue.feature == "line-spacing-change" for issue in result.issues)


def test_style_unknown_cyclic_reference_and_extension_budgets():
    document, paragraph = fixture()
    set_line_spacing(document.styles["child"], LineSpacing())
    assert resolve_line_spacing(paragraph, document=document) == LineSpacing()
    document.styles["base"].properties["base_style_id"] = "child"
    with pytest.raises(ValueError):
        resolve_line_spacing(paragraph, document=document)
    node = Paragraph([])
    value = LineSpacing("relative", 1.5, extra={"future": list(range(100_001))})
    limits = DocumentLimits(max_nodes=200_000)
    set_line_spacing(node, value, limits=limits)
    assert len(get_line_spacing(node, limits=limits).extra["future"]) == 100_001
    before = deepcopy(node)
    with pytest.raises(ArtifactLimitError):
        get_line_spacing(node)
    cycle = {}
    cycle["self"] = cycle
    with pytest.raises(ValueError):
        set_line_spacing(node, LineSpacing("exact", 14, extra=cycle), limits=limits)
    assert node == before
