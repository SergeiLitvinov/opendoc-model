"""Structured quota diagnostics and real caller budgets, without native parsers."""

import pickle
from copy import deepcopy

import pytest

from opendoc_model import (
    ArtifactLimitError,
    CheckResult,
    DocumentLimits,
    DocumentModel,
    IntegrationModel,
    MatchingLimits,
    Paragraph,
    Section,
    TextFlowProfile,
    TextPreservationPolicy,
    TextRun,
    check_document,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_json,
    document_to_json,
    get_integration,
    inspect_document_model,
    iter_elements,
    load_document,
    merge_documents,
    save_document,
    set_integration,
    text_flow_profile_to_dict,
)
from opendoc_model.object_matching import match_objects
from opendoc_model.storage import _atomic_write_chunks, atomic_write_text


@pytest.mark.parametrize("args", [(), ("legacy",), ("first", 2)])
def test_legacy_value_error_args_copy_and_pickle(args):
    legacy = ArtifactLimitError(*args)
    assert legacy.args == args and str(legacy) == str(ValueError(*args))
    assert (legacy.path, legacy.quota, legacy.maximum) == (None, None, None)
    error = ArtifactLimitError(*args, path="$.metadata", quota="nodes", maximum=0)
    for restored in (deepcopy(error), pickle.loads(pickle.dumps(error))):
        assert restored.args == args and str(restored) == str(error)
        assert (restored.path, restored.quota, restored.maximum) == ("$.metadata", "nodes", 0)


@pytest.mark.parametrize(
    "limits,quota",
    [(DocumentLimits(max_bytes=1), "bytes"), (DocumentLimits(max_depth=1), "depth"), (DocumentLimits(max_nodes=1), "nodes")],
)
def test_json_errors_keep_text_and_structured_fields(limits, quota):
    with pytest.raises(ArtifactLimitError) as caught:
        document_from_json('{"format":"opendoc.document","version":2,"document":{}}', limits=limits)
    error = caught.value
    assert error.quota == quota and error.maximum == getattr(limits, "max_" + quota)
    assert error.path.startswith("$")
    assert str(error) == f"{error.path}: {quota} quota exceeded ({error.maximum})"


def test_storage_errors_name_destination_and_leave_file_intact(tmp_path):
    target = tmp_path / "own.txt"
    target.write_text("previous", encoding="utf-8")
    for write in (
        lambda: atomic_write_text(target, "new", max_bytes=2),
        lambda: _atomic_write_chunks(target, ["n", "ew"], encoding="utf-8", max_bytes=2),
    ):
        with pytest.raises(ArtifactLimitError) as caught:
            write()
        assert (caught.value.path, caught.value.quota, caught.value.maximum) == (str(target), "bytes", 2)
        assert str(caught.value) == "artifact quota exceeded (2 bytes)"
        assert target.read_text(encoding="utf-8") == "previous"
        assert list(tmp_path.glob(".*.partial")) == []


def test_composition_context_and_matching_global_scope():
    with pytest.raises(ArtifactLimitError) as caught:
        merge_documents([DocumentModel()], limits=DocumentLimits(max_nodes=2))
    error = caught.value
    assert error.path.startswith("documents[0]") and error.quota == "nodes" and error.maximum == 2
    assert isinstance(error.__cause__, ArtifactLimitError)
    assert str(error) == f"documents[0]: {error.__cause__}"
    with pytest.raises(ArtifactLimitError) as caught:
        match_objects([{"location": "own"}], [], limits=MatchingLimits(max_work=0))
    assert (caught.value.path, caught.value.quota, caught.value.maximum) == (None, "work", 0)


def test_explicit_large_budget_reaches_all_model_boundaries(tmp_path):
    document = DocumentModel(metadata={"own": list(range(100_001))}, sections=[Section(blocks=[Paragraph([TextRun("Own")])])])
    original = deepcopy(document)
    budget = DocumentLimits(max_nodes=300_000)
    for operation in (document_to_json, check_document, inspect_document_model, clone_model):
        with pytest.raises(ArtifactLimitError) as caught:
            operation(document)
        assert caught.value.quota == "nodes" and caught.value.maximum == 100_000
    previous = document.metadata
    with pytest.raises(ArtifactLimitError):
        set_integration(document, IntegrationModel())
    assert document == original and document.metadata is previous
    set_integration(document, IntegrationModel(), limits=budget)
    assert get_integration(document, limits=budget) == IntegrationModel()
    restored = document
    for _ in range(2):
        restored = document_from_json(document_to_json(restored, limits=budget), limits=budget)
    assert restored == document and check_document(document, limits=budget).success
    assert clone_model(document, limits=budget) == document
    assert list(iter_elements(document, Paragraph, limits=budget))[0].node.content[0].text == "Own"
    merged = merge_documents([document], limits=budget).document
    assert merged == document
    path = save_document(document, tmp_path / "own.json", limits=budget)
    assert load_document(path, limits=budget) == document
    assert compare_documents(document, restored, limits=budget).success
    set_integration(document, None, limits=budget)
    assert document == original


def test_large_text_profile_budget_is_not_replaced_with_default():
    profile = TextFlowProfile("own", "own", measured=True, complete=True, extra={"future": list(range(100_001))})
    budget = DocumentLimits(max_nodes=300_000)
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("Own text")])])],
        metadata={"text_flow_profile": text_flow_profile_to_dict(profile, limits=budget)},
    )
    policy = TextPreservationPolicy("flow")
    result = compare_documents(document, document, limits=budget, policies=[policy])
    assert result.success and result.metrics["text_quality_gate"]["verified"] is True
    comparison = compare_inspections(
        inspect_document_model(document, limits=budget), inspect_document_model(document, limits=budget)
    )
    assert policy.evaluate(CheckResult(), comparison, limits=budget)
    # Existing standalone behavior: a profile outside its budget is unavailable.
    report = CheckResult()
    assert not policy.evaluate(report, comparison)
    assert report.metrics["text_quality_gate"]["verified"] is False
