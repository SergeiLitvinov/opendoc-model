"""Own color declarations; no native application or automatic RGB assumptions."""

from copy import deepcopy

import pytest

from opendoc_model import (
    ColorValue,
    DocumentLimits,
    DocumentModel,
    Paragraph,
    QualityPolicy,
    Section,
    TextRun,
    TextStyle,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    effective_text_style,
    extract_document,
    inspect_document_model,
    iter_elements,
    merge_documents,
    resolve_style,
)
from opendoc_model.color import color_to_css
from opendoc_model.object_inventory import inspect_objects


def _fixture(color="auto", background=None):
    paragraph = Paragraph([TextRun("Heading", TextStyle(color=color, background=background))], style_id="heading")
    document = DocumentModel(
        styles={"base": TextStyle(color="#4F81BD"), "heading": TextStyle(properties={"base_style_id": "base"})},
        sections=[Section(blocks=[paragraph])],
    )
    return document, paragraph


@pytest.mark.parametrize("color", [None, "auto", "#000000", "", ColorValue.from_hex("#4F81BD")])
def test_color_json_and_existing_cascade(color):
    document, paragraph = _fixture(color)
    expected = deepcopy(document)
    assert effective_text_style(document, paragraph, paragraph.content[0]).color == (color if color is not None else "#4F81BD")
    assert resolve_style(document, "heading").color == "#4F81BD"
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and compare_documents(expected, document).success
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    paragraph.content[0].style.color = None
    assert effective_text_style(expected, paragraph, paragraph.content[0]).color == "#4F81BD"


@pytest.mark.parametrize("field", ["color", "background"])
@pytest.mark.parametrize("target_color", [None, "#000000", "#4F81BD"])
def test_explicit_auto_loss_is_located_and_rejected(field, target_color):
    source, paragraph = _fixture(None)
    setattr(paragraph.content[0].style, field, "auto")
    target = clone_model(source)
    setattr(target.sections[0].blocks[0].content[0].style, field, target_color)
    result = compare_documents(source, target, policies=[QualityPolicy(0)])
    assert not result.success
    issue = next(issue for issue in result.issues if issue.code == "text-color-loss")
    assert issue.location == "sections[0].blocks[0]"
    assert issue.measurement["source"]["spans"][0]["direct"][field] == "auto"
    assert issue.measurement["target"]["spans"][0]["direct"][field] == target_color


def test_unknown_inherited_and_auto_remain_distinct_without_invented_rgb():
    document, paragraph = _fixture(None)
    inspection = inspect_document_model(document)
    state = inspection.objects[0]["text_colors"]["spans"][0]
    assert state["direct"]["color"] is None and state["resolved"]["color"] == "#4F81BD"
    document.styles["base"].color = None
    state = inspect_document_model(document).objects[0]["text_colors"]["spans"][0]
    assert state["resolved"]["color"] is None
    paragraph.content[0].style.color = "auto"
    state = inspect_document_model(document).objects[0]["text_colors"]["spans"][0]
    assert state["resolved"]["color"] == "auto" and color_to_css("auto") is None


def test_named_and_inline_base_styles_follow_existing_precedence():
    document, paragraph = _fixture(None)
    document.styles["character"] = TextStyle(color="auto")
    run = paragraph.content[0]
    run.style.properties["base_style_id"] = "character"
    assert effective_text_style(document, paragraph, run).color == "auto"
    assert inspect_document_model(document).objects[0]["text_colors"]["spans"][0]["resolved"]["color"] == "auto"
    changed = clone_model(document)
    changed.styles["character"].color = None
    assert any(issue.code == "text-color-loss" for issue in compare_documents(document, changed).issues)
    run.style.color = "#000000"
    assert effective_text_style(document, paragraph, run).color == "#000000"


def test_direct_auto_deletion_is_loss_even_if_inherited_auto_is_same():
    source, _ = _fixture()
    source.styles["base"].color = "auto"
    target = clone_model(source)
    target.sections[0].blocks[0].content[0].style.color = None
    assert any(issue.code == "text-color-loss" for issue in compare_documents(source, target).issues)


def test_named_direct_auto_remains_distinct_from_identical_inheritance():
    source, _ = _fixture(None)
    source.styles["base"].color = source.styles["heading"].color = "auto"
    target = clone_model(source)
    target.styles["heading"].color = None
    assert any(issue.code == "text-color-loss" for issue in compare_documents(source, target).issues)


def test_text_edits_do_not_invent_color_alignment():
    source, _ = _fixture()
    target = clone_model(source)
    target.sections[0].blocks[0].content[0].text = "Different heading"
    assert not any(issue.code.startswith("text-color-") for issue in compare_documents(source, target).issues)


def test_run_segmentation_and_opaque_native_properties_do_not_change_colors():
    source, _ = _fixture()
    target = clone_model(source)
    paragraph = target.sections[0].blocks[0]
    paragraph.content = [TextRun("Head", TextStyle(color="auto")), TextRun("ing", TextStyle(color="auto"))]
    paragraph.properties["color"] = {"native": "auto"}
    paragraph.content[0].style.properties["native_color"] = {"kind": "none"}
    assert compare_documents(source, target).success
    paragraph.content.insert(0, TextRun("", TextStyle(color="#000000")))
    assert compare_documents(source, target).success


def test_known_color_change_and_removal_are_different():
    source, _ = _fixture("#000000")
    target = clone_model(source)
    target.sections[0].blocks[0].content[0].style.color = "#4F81BD"
    assert any(issue.code == "text-color-change" for issue in compare_documents(source, target).issues)
    target.sections[0].blocks[0].content[0].style.color = None
    assert any(issue.code == "text-color-loss" for issue in compare_documents(source, target).issues)


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"paragraph": {}, "spans": []},
        {"paragraph": {"color": None, "background": None}, "spans": [{"start": True, "end": 2}]},
    ],
)
def test_missing_or_malformed_inventory_is_unavailable(bad):
    source, _ = _fixture()
    before = inspect_document_model(source)
    after = deepcopy(before)
    after.objects[0]["text_colors"] = bad
    result = compare_inspections(before, after)
    assert not result.object_diff["text_colors_available"]
    assert not any(issue.feature.startswith("text-color-") for issue in result.issues)
    after.objects[0].pop("text_colors")
    assert not compare_inspections(before, after).object_diff["text_colors_available"]


def test_copy_composition_and_explicit_limits():
    source, _ = _fixture()
    for document in (
        clone_model(source),
        extract_document(source, next(iter_elements(source, Paragraph))),
        merge_documents([source, source], conflicts="rename").document,
    ):
        paragraph = next(iter_elements(document, Paragraph)).node
        assert effective_text_style(document, paragraph, paragraph.content[0]).color == "auto"
        assert document_from_json(document_to_json(document)) == document
    source.styles["base"].properties["large"] = list(range(100_001))
    limits = DocumentLimits(max_nodes=200_000)
    restored = document_from_json(document_to_json(source, limits=limits), limits=limits)
    assert compare_documents(source, restored, limits=limits).success


def test_subtree_without_named_style_context_is_unknown():
    document, paragraph = _fixture()
    entry = next(inspect_objects(paragraph, "paragraph", 0, document.resources))
    assert entry["text_colors"] is None


def test_missing_and_null_json_fields_inherit_but_auto_does_not():
    document, _ = _fixture()
    raw = document_to_dict(document)
    run = raw["document"]["sections"][0]["blocks"][0]["content"][0]
    run["style"].pop("color")
    inherited = document_from_dict(raw)
    paragraph = inherited.sections[0].blocks[0]
    assert effective_text_style(inherited, paragraph, paragraph.content[0]).color == "#4F81BD"
    run["style"]["color"] = None
    assert document_from_dict(raw) == inherited
    assert any(issue.code == "text-color-loss" for issue in compare_documents(document, inherited).issues)


def test_canonical_color_and_snapshot_never_mutate_document():
    document, paragraph = _fixture(ColorValue.from_hex("#4F81BD"), ColorValue.from_hex("#FFFFFF"))
    before = deepcopy(document)
    inspection = inspect_document_model(document)
    inspection.objects[0]["text_colors"]["spans"][0]["direct"]["color"]["components"][0] = 0
    assert document == before
    resolved = effective_text_style(document, paragraph, paragraph.content[0])
    assert resolved.color == before.sections[0].blocks[0].content[0].style.color
