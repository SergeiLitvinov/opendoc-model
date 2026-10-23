"""Standalone integration transport reuses the document schema without claiming owner validity."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    INTEGRATION_PROPERTY,
    ArtifactLimitError,
    DiagnosticIssue,
    DocumentLimits,
    DocumentModel,
    Field,
    IntegrationModel,
    IssueSeverity,
    PreservationRecord,
    PreservationState,
    Provenance,
    ProvenanceEvent,
    get_integration,
    integration_from_dict,
    integration_to_dict,
    set_integration,
)


def _model(state=PreservationState.OPAQUE):
    return IntegrationModel(
        preservation=(
            PreservationRecord(
                DiagnosticIssue(
                    "own.feature",
                    IssueSeverity.WARNING,
                    "Kept declaration",
                    "section[0].item",
                    measurement={"own": [1, None, False]},
                    reason="No semantic projection",
                ),
                state,
                provenance=Provenance(
                    "own",
                    source_path="inert/source",
                    object_id="item",
                    events=[ProvenanceEvent("retain", detail="original", fallback_reason="unsupported")],
                ),
                extra={"future_record": {"items": [1]}},
            ),
        ),
        assessed_features=("own.feature",),
        assessment_complete=False,
        extra={"future_model": {"items": [1]}},
    )


@pytest.mark.parametrize("state", list(PreservationState))
def test_two_dict_and_json_cycles_preserve_diagnostics_provenance_and_unknown_fields(state):
    model = _model(state)
    owner = DocumentModel()
    set_integration(owner, model)
    expected = deepcopy(owner.metadata[INTEGRATION_PROPERTY])
    assert integration_to_dict(model) == expected
    for _ in range(2):
        model = integration_from_dict(json.loads(json.dumps(integration_to_dict(model), ensure_ascii=False)))
        assert model == get_integration(owner)
        assert integration_to_dict(model) == expected
        issue = model.preservation[0].issue
        assert issue.reason == "No semantic projection" and issue.location == "section[0].item"
        assert model.preservation[0].state is state


def test_encode_decode_detach_every_mutable_boundary_without_changing_inputs():
    model = _model()
    original = deepcopy(model)
    data = integration_to_dict(model)
    expected = deepcopy(data)
    decoded = integration_from_dict(data)
    data["data"]["future_model"]["items"].append(2)
    record = data["data"]["preservation"][0]
    record["future_record"]["items"].append(2)
    record["issue"]["measurement"]["own"].append(2)
    record["provenance"]["events"][0]["detail"] = "edited"
    assert model == decoded == original
    decoded.extra["future_model"]["items"].append(3)
    decoded.preservation[0].issue.measurement["own"].append(3)
    decoded.preservation[0].provenance.events[0].detail = "decoded edit"
    assert integration_to_dict(model) == expected
    assert record["provenance"]["events"][0]["detail"] == "edited"


@pytest.mark.parametrize(
    "bad",
    [
        None,
        [],
        {},
        {"format": "consumer.own", "version": 1, "data": {}},
        {"format": INTEGRATION_PROPERTY, "version": True, "data": {}},
        {"format": INTEGRATION_PROPERTY, "version": 2, "data": {}},
        {"format": INTEGRATION_PROPERTY, "version": "1", "data": {}},
        {"format": INTEGRATION_PROPERTY, "version": 1},
        {"format": INTEGRATION_PROPERTY, "version": 1, "data": []},
    ],
)
def test_invalid_envelopes_are_explicit_failures(bad):
    with pytest.raises(ValueError):
        integration_from_dict(bad)


@pytest.mark.parametrize(
    "change",
    [
        lambda data: data.update(assessment_complete=1),
        lambda data: data.update(preservation={}),
        lambda data: data["preservation"][0].update(state="future"),
        lambda data: data["preservation"][0]["issue"].update(severity="future"),
        lambda data: data["preservation"][0]["issue"].update(reason=7),
        lambda data: data["preservation"][0]["provenance"].update(page=True),
        lambda data: data.update(extra={}),
        lambda data: data.update(future=float("nan")),
    ],
)
def test_corrupt_payloads_are_rejected_without_mutation(change):
    raw = integration_to_dict(_model())
    change(raw["data"])
    before = deepcopy(raw)
    with pytest.raises(ValueError):
        integration_from_dict(raw)
    # NaN needs identity-aware comparison; the decoder must not edit the tree.
    assert repr(raw) == repr(before)


@pytest.mark.parametrize("bad", [None, {}, [], "model"])
def test_encoder_rejects_wrong_model_types(bad):
    with pytest.raises(ValueError):
        integration_to_dict(bad)


def test_standalone_transport_does_not_claim_reference_or_document_semantics():
    model = replace(_model(), fields=(Field("reference", "reference", target_id="missing"),))
    assert integration_from_dict(integration_to_dict(model)) == model
    owner = DocumentModel(metadata={"retained": [1]})
    before = deepcopy(owner)
    with pytest.raises(ValueError, match="missing"):
        set_integration(owner, model)
    assert owner == before
    # The codec preserves a structurally valid ledger even without assessment declarations.
    undeclared = replace(_model(), assessed_features=())
    assert integration_from_dict(integration_to_dict(undeclared)) == undeclared
    with pytest.raises(ValueError):
        set_integration(owner, undeclared)


def test_transport_envelope_extras_remain_owner_data_like_get_integration():
    raw = integration_to_dict(_model())
    raw["owner.transport"] = {"retained": [1]}
    owner = DocumentModel(metadata={INTEGRATION_PROPERTY: deepcopy(raw)})
    model = integration_from_dict(raw)
    assert model == get_integration(owner)
    set_integration(owner, model)
    assert owner.metadata[INTEGRATION_PROPERTY] == raw
    assert "owner.transport" not in integration_to_dict(model)


def test_cycle_shadowing_non_json_and_invalid_limits_fail_without_recursion():
    cyclic = {}
    cyclic["self"] = cyclic
    for extra in (cyclic, {"assessment_complete": True}, {"extra": {}}, {"bytes": b"raw"}):
        with pytest.raises(ValueError):
            integration_to_dict(IntegrationModel(extra=extra))
    for function, value in ((integration_to_dict, _model()), (integration_from_dict, integration_to_dict(_model()))):
        with pytest.raises(ValueError):
            function(value, limits=3)
        with pytest.raises(ArtifactLimitError) as caught:
            function(value, limits=DocumentLimits(max_nodes=1))
        assert caught.value.quota == "nodes" and caught.value.maximum == 1 and caught.value.path


def test_large_budget_is_forwarded_and_embedded_zero_does_not_invent_resources():
    model = replace(_model(), extra={"large": [None] * 100_001})
    limits = DocumentLimits(max_nodes=300_000, max_embedded_bytes=0)
    with pytest.raises(ArtifactLimitError):
        integration_to_dict(model)
    payload = integration_to_dict(model, limits=limits)
    with pytest.raises(ArtifactLimitError):
        integration_from_dict(payload)
    for _ in range(2):
        model = integration_from_dict(json.loads(json.dumps(payload)), limits=limits)
        payload = integration_to_dict(model, limits=limits)
    assert len(model.extra["large"]) == 100_001


def test_decode_uses_same_envelope_budget_as_existing_getter():
    raw = integration_to_dict(IntegrationModel())
    owner = DocumentModel(metadata={INTEGRATION_PROPERTY: raw})
    for maximum in range(1, 50):
        limits = DocumentLimits(max_nodes=maximum)
        try:
            expected = get_integration(owner, limits=limits)
        except ArtifactLimitError:
            with pytest.raises(ArtifactLimitError):
                integration_from_dict(raw, limits=limits)
        else:
            assert integration_from_dict(raw, limits=limits) == expected
