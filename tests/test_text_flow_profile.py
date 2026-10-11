"""Independent measured text declarations do not attest native extraction or object inventory."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from opendoc_model import (
    ArtifactLimitError,
    ConversionReport,
    DocumentInspection,
    DocumentLimits,
    DocumentModel,
    FormulaLossPolicy,
    IssueSeverity,
    ObjectLossPolicy,
    TextFlowProfile,
    TextPreservationPolicy,
    compare_inspections,
    document_from_json,
    document_to_json,
    inspect_document_model,
    text_flow_profile_from_dict,
    text_flow_profile_to_dict,
)
from opendoc_model.text_flow import MAX_TEXT_TOKENS, TextFlowFingerprint


def _inspection(text, *, profile=None):
    flow = TextFlowFingerprint()
    flow.add(text)
    measured = profile or TextFlowProfile("own-visible-text-v1", "own-selection-v1", measured=True, complete=True)
    return DocumentInspection(
        None,
        "fixture",
        metadata={
            "text_flow": flow.to_dict(),
            "text_flow_profile": text_flow_profile_to_dict(measured),
        },
    )


def _gate(source, target, budget=0):
    report = ConversionReport(Path("unused.fixture"))
    accepted = TextPreservationPolicy("flow", budget).evaluate(report, compare_inspections(source, target))
    return accepted, report.metrics["text_quality_gate"]


def test_measured_flow_passes_without_inventory_and_does_not_unlock_other_gates():
    source, target = _inspection("one\t two"), _inspection("one two")
    accepted, gate = _gate(source, target)
    assert accepted and gate["verified"] and gate["text_edits"] == 0
    assert gate["coverage"] == "declared-text-scope" and gate["scope"] == "own-selection-v1"
    assert "object_inventory_scope" not in source.metadata
    comparison = compare_inspections(source, target)
    for policy in (ObjectLossPolicy(), FormulaLossPolicy(), TextPreservationPolicy()):
        report = ConversionReport(Path("unused.fixture"))
        assert not policy.evaluate(report, comparison)
        assert next(iter(report.metrics.values()))["verified"] is False


@pytest.mark.parametrize("budget", [None, 0])
def test_changed_native_text_fails_and_known_empty_is_distinct_from_unknown(budget):
    accepted, gate = _gate(_inspection("one two"), _inspection("one new"), budget)
    assert not accepted and gate["verified"]
    assert _gate(_inspection(""), _inspection(" \t\n"), budget)[0]
    unknown = _inspection("")
    unknown.metadata.pop("text_flow")
    accepted, gate = _gate(_inspection(""), unknown, budget)
    assert not accepted and not gate["verified"] and gate["reason"] == "unavailable"


@pytest.mark.parametrize("reason", ["unknown", "partial", "encrypted", "extraction-limit"])
def test_unavailable_measurement_cannot_pass_identical_hash(reason):
    profile = TextFlowProfile("own-visible-text-v1", "own-selection-v1", measured=reason == "partial", reason=reason)
    accepted, gate = _gate(_inspection("same"), _inspection("same", profile=profile))
    assert not accepted and not gate["verified"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("profile", "other-extractor-v1"),
        ("scope", "another-selection-v1"),
        ("recipe", "nfkc-guess-v1"),
        ("version", 2),
        ("version", True),
        ("complete", False),
        ("measured", False),
        ("complete", 1),
    ],
)
def test_incompatible_or_invalid_profile_never_falls_back_to_full_inventory(field, value):
    source, target = _inspection("same"), _inspection("same")
    target.metadata["text_flow_profile"][field] = value
    for item in (source, target):
        item.metadata["object_inventory_scope"] = "model-recursive-objects-v1"
    accepted, gate = _gate(source, target)
    assert not accepted and not gate["verified"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("sha256", "not-a-hash"),
        ("characters", True),
        ("paragraphs", -1),
        ("token_count", 0),
        ("tokens", None),
        ("tokens", ["bad"]),
        ("tokenization", "nfkc"),
    ],
)
def test_malformed_flow_is_unavailable(field, value):
    source, target = _inspection("same"), _inspection("same")
    target.metadata["text_flow"][field] = value
    assert _gate(source, target)[1]["verified"] is False


def test_missing_profile_invalid_inspection_and_legacy_inspection():
    source, target = _inspection("same"), _inspection("same")
    target.metadata.pop("text_flow_profile")
    assert _gate(source, target)[1]["verified"] is False
    known = inspect_document_model(DocumentModel())
    assert _gate(known, deepcopy(known))[0]
    source.metadata["text_flow_profile"] = None
    assert _gate(source, target)[1]["verified"] is False
    source = _inspection("same")
    target = _inspection("same")
    target.add(IssueSeverity.ERROR, "fixture", "Invalid measurement")
    assert _gate(source, target)[1]["verified"] is False


def test_equal_hash_with_inconsistent_counts_and_cycles_is_unavailable():
    source, target = _inspection("same"), _inspection("same")
    target.metadata["text_flow"]["characters"] += 1
    assert _gate(source, target)[1]["verified"] is False
    target = _inspection("same")
    target.metadata["text_flow_profile"]["cycle"] = target.metadata["text_flow_profile"]
    assert _gate(source, target)[1]["verified"] is False


def test_fragment_resegmentation_and_token_limit_preserve_exact_fingerprint():
    source, target = _inspection("one two"), _inspection("one two")
    flow = TextFlowFingerprint()
    flow.add("one")
    flow.add("two")
    target.metadata["text_flow"] = flow.to_dict()
    assert _gate(source, target)[0]
    large = _inspection(" ".join(["word"] * (MAX_TEXT_TOKENS + 1)))
    assert large.metadata["text_flow"]["tokens"] is None
    assert _gate(large, deepcopy(large))[0]
    changed = _inspection(" ".join(["word"] * MAX_TEXT_TOKENS + ["changed"]))
    assert _gate(large, changed, 1)[1]["verified"] is False


def test_normalization_preserves_unicode_and_word_order_and_edit_budget():
    assert not _gate(_inspection("ﬁle"), _inspection("file"))[0]
    assert not _gate(_inspection("one two"), _inspection("two one"))[0]
    assert not _gate(_inspection("Ａ"), _inspection("A"))[0]
    assert _gate(_inspection("one two"), _inspection("one new"), 1)[0]


def test_profile_json_unknown_fields_limits_and_failure_independence():
    profile = TextFlowProfile("fixture-v1", "selection-v1", measured=True, complete=True, extra={"future": [None, 1]})
    raw = text_flow_profile_to_dict(profile)
    assert raw["format"] == "opendoc.text-flow-profile" and raw["version"] == 1
    for _ in range(2):
        raw = json.loads(json.dumps(text_flow_profile_to_dict(text_flow_profile_from_dict(raw))))
    document = DocumentModel(metadata={"text_flow_profile": raw})
    assert document_from_json(document_to_json(document)) == document
    copied = text_flow_profile_from_dict(raw)
    copied.extra["future"].append(2)
    assert profile.extra["future"] == [None, 1]
    before = deepcopy(raw)
    with pytest.raises(ArtifactLimitError):
        text_flow_profile_from_dict(raw, limits=DocumentLimits(max_nodes=2))
    assert raw == before
    with pytest.raises(ValueError):
        text_flow_profile_to_dict(replace(profile, extra={"version": 2}))
    with pytest.raises(ValueError):
        text_flow_profile_to_dict(replace(profile, measured=False))
    raw["cycle"] = raw
    with pytest.raises(ValueError):
        text_flow_profile_from_dict(raw)
