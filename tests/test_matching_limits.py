"""Bounded matching gives unknown evidence without fabricated object losses."""

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentModel,
    MatchingLimits,
    ObjectLossPolicy,
    Paragraph,
    Section,
    TextRun,
    compare_documents,
    compare_inspections,
    inspect_document_model,
)
from opendoc_model.object_matching import match_objects


@pytest.mark.parametrize("value", [-1, True, 1.5, None, "100"])
def test_matching_limit_rejects_invalid_work_budget(value):
    with pytest.raises(ValueError):
        MatchingLimits(value)


def test_empty_matching_needs_no_work_and_one_pair_has_an_exact_boundary():
    assert match_objects([], [], limits=MatchingLimits(0)) == ([], [], [])
    objects = [{"type": "paragraph", "content_hash": "same", "location": "one"}]
    matches, lost, added = match_objects(objects, objects, limits=MatchingLimits(17))
    assert len(matches) == 1 and not lost and not added
    with pytest.raises(ArtifactLimitError, match="used 16, next charge 1"):
        match_objects(objects, objects, limits=MatchingLimits(16))
    assert objects == [{"type": "paragraph", "content_hash": "same", "location": "one"}]


def _mixed(size):
    source = [
        {
            "type": "paragraph",
            "content_hash": "same",
            "location": str(index),
            "provenance": {"identity": f"before-{index}", "source_format": "pdf", "source_path": "one"},
        }
        for index in range(size)
    ]
    target = [
        {
            **item,
            "provenance": {"identity": f"after-{index}", "source_format": "pdf" if index % 2 else "docx", "source_path": "one"},
        }
        for index, item in enumerate(source)
    ]
    return source, target


def test_mixed_origin_search_exhausts_mid_group_and_higher_budget_keeps_duplicates():
    source, target = _mixed(40)
    with pytest.raises(ArtifactLimitError):
        match_objects(source, target, limits=MatchingLimits(1000))
    matches, lost, added = match_objects(source, target, limits=MatchingLimits(20_000))
    assert len(matches) == len(lost) == len(added) == 20
    assert all(item["ambiguous"] and item["match_basis"] == "content" for item in matches)
    assert len({item["source_index"] for item in matches}) == len({item["target_index"] for item in matches}) == 20


def test_comparison_discards_partial_matches_and_strict_policy_refuses_unknown():
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("kept")])])])
    result = compare_documents(document, document, matching_limits=MatchingLimits(16))
    diff = result.metrics["comparison"]["object_diff"]
    assert not diff["available"] and diff["retention_ratio"] is None
    assert diff["lost"] == diff["added"] == diff["retained"] == diff["changed"] == []
    issue = next(item for item in result.issues if item.code == "object-matching-unavailable")
    assert issue.reason == "matching-budget-exceeded" and issue.measurement["max_work"] == 16
    generic = next(
        item for item in result.issues if item.code == "measurement.unavailable" and item.location == "comparison.objects"
    )
    assert generic.reason == "matching-budget-exceeded"
    assert generic.measurement["matching_budget"] == diff["matching_budget"]
    assert result.success and not any(item.code == "object-loss" for item in result.issues)
    strict = compare_documents(document, document, policies=[ObjectLossPolicy()], matching_limits=MatchingLimits(16))
    assert not strict.success
    assert strict.metrics["object_quality_gate"]["reason"] == "unavailable"
    assert strict.metrics["object_quality_gate"]["lost_objects"] is None


def test_large_mixed_inspection_returns_unknown_at_default_budget():
    source, target = _mixed(1500)
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("placeholder")])])])
    before, after = inspect_document_model(document), inspect_document_model(document)
    before.objects, after.objects = source, target
    comparison = compare_inspections(before, after)
    assert comparison.valid and not comparison.object_diff["available"]
    assert comparison.object_diff["reason"] == "matching-budget-exceeded"
    assert comparison.object_diff["lost"] == []


def test_invalid_budget_argument_fails_before_inspecting_the_model():
    with pytest.raises(ValueError, match="matching limits"):
        compare_documents(None, None, matching_limits=3)
    with pytest.raises(ValueError, match="matching limits"):
        compare_inspections(None, None, matching_limits=3)
    with pytest.raises(ValueError, match="matching limits"):
        match_objects([], [], limits=3)


def test_indexed_duplicates_fit_default_budget_without_changing_ambiguity():
    source, _ = _mixed(4000)
    matches, lost, added = match_objects(source, list(reversed(source)))
    assert len(matches) == 4000 and not lost and not added
    assert all(not item["ambiguous"] and item["match_basis"] == "provenance" for item in matches)


def test_invalid_models_keep_their_validation_error_with_zero_matching_work():
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("bad")])])])
    document.sections[0].blocks[0].content[0].text = None
    result = compare_documents(document, document, matching_limits=MatchingLimits(0))
    assert not result.success and any(item.code.startswith("model.") for item in result.issues)
    assert not any(item.code == "object-matching-unavailable" for item in result.issues)


def test_comparison_domains_share_work_and_discard_partial_semantic_losses():
    from opendoc_model import Anchor, Footnote, set_anchor

    paragraph = Paragraph([TextRun("target")])
    set_anchor(paragraph, Anchor("target"))
    document = DocumentModel(sections=[Section(blocks=[paragraph])])
    result = compare_documents(document, document, matching_limits=MatchingLimits(17))
    diff = result.metrics["comparison"]["object_diff"]
    assert diff["available"] and not diff["references"]["available"]
    assert diff["references"]["matching_budget"] == {"max_work": 17, "used_work": 17, "requested_work": 2}
    assert diff["references"]["lost_anchors"] is None and not diff["references"]["changes"]
    assert any(
        item.code == "reference-matching-unavailable" and item.reason == "matching-budget-exceeded" for item in result.issues
    )
    notes = DocumentModel(footnotes=[Footnote("unused")])
    result = compare_documents(notes, notes, matching_limits=MatchingLimits(1))
    diff = result.metrics["comparison"]["object_diff"]
    assert diff["available"] and not diff["footnotes"]["available"]
    assert diff["footnotes"]["lost_notes"] is None and not diff["footnotes"]["changes"]
    assert any(
        item.code == "footnote-matching-unavailable" and item.reason == "matching-budget-exceeded" for item in result.issues
    )
