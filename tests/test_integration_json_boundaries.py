"""Standalone JSON carriers reject non-JSON input before copying it."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DiagnosticIssue,
    DocumentLimits,
    DocumentModel,
    IntegrationModel,
    IssueSeverity,
    PreservationRecord,
    PreservationState,
    SceneStyle,
    integration_from_dict,
    integration_to_dict,
    set_integration,
)


class _CopyAsJSON:
    def __init__(self):
        self.calls = 0

    def __deepcopy__(self, memo):
        self.calls += 1
        return {"coerced": True}


class _CopyRaises(_CopyAsJSON):
    def __deepcopy__(self, memo):
        self.calls += 1
        raise RuntimeError("copy must never run")


class _AliasDict(dict):
    def __deepcopy__(self, memo):
        raise AssertionError("JSON dictionaries must not call deepcopy")


class _AliasList(list):
    def __deepcopy__(self, memo):
        raise AssertionError("JSON lists must not call deepcopy")


def _model(location, value):
    record = PreservationRecord(
        DiagnosticIssue("own", IssueSeverity.WARNING, "Retained", reason="unknown"), PreservationState.OPAQUE
    )
    if location == "model-extra":
        return IntegrationModel(extra={"own": value})
    if location == "record-extra":
        return IntegrationModel(preservation=(replace(record, extra={"own": value}),))
    if location == "measurement":
        return IntegrationModel(preservation=(replace(record, issue=replace(record.issue, measurement={"own": value})),))
    return IntegrationModel(scene_styles=(SceneStyle("own", properties={"own": value}),))


@pytest.mark.parametrize("location", ["model-extra", "record-extra", "measurement", "properties"])
@pytest.mark.parametrize("factory", [lambda: memoryview(b"raw"), lambda: (item for item in ()), _CopyAsJSON, _CopyRaises])
def test_non_json_carriers_fail_before_copy_or_coercion(location, factory):
    value = factory()
    model = _model(location, value)
    with pytest.raises(ValueError, match="JSON value"):
        integration_to_dict(model)
    if isinstance(value, _CopyAsJSON):
        assert value.calls == 0
    owner = DocumentModel(metadata={"own": [1]})
    before = deepcopy(owner)
    with pytest.raises(ValueError, match="JSON value"):
        set_integration(owner, model)
    assert owner == before
    if isinstance(value, _CopyAsJSON):
        assert value.calls == 0


@pytest.mark.parametrize("location", ["model-extra", "record-extra", "measurement", "properties"])
def test_json_values_aliases_and_two_cycles_remain_independent(location):
    shared = {"values": [None, False, 0, "", {}, []]}
    model = _model(location, {"first": shared, "second": shared})
    expected = deepcopy(model)
    payload = integration_to_dict(model)
    for _ in range(2):
        decoded = integration_from_dict(json.loads(json.dumps(payload, ensure_ascii=False)))
        assert decoded == expected
        payload = integration_to_dict(decoded)
    shared["values"].append("source edit")
    assert decoded == expected and model != expected


@pytest.mark.parametrize("location", ["model-extra", "record-extra", "measurement", "properties"])
def test_guard_forwards_large_node_and_byte_budgets(location):
    model = _model(location, {"values": [None] * 100_001, "text": "é" * 1000})
    limits = DocumentLimits(max_nodes=300_000)
    with pytest.raises(ArtifactLimitError):
        integration_to_dict(model)
    raw = integration_to_dict(model, limits=limits)
    decoded = integration_from_dict(raw, limits=limits)
    assert decoded == model
    with pytest.raises(ArtifactLimitError) as caught:
        integration_to_dict(model, limits=replace(limits, max_bytes=10))
    assert caught.value.quota == "bytes" and caught.value.maximum == 10


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "\ud800", (1,), b"raw", {1: "bad key"}])
def test_remaining_non_json_values_fail_with_value_errors(value):
    with pytest.raises(ValueError):
        integration_to_dict(IntegrationModel(extra={"own": value}))


def test_nested_cycle_is_refused_without_recursion_and_input_is_not_modified():
    cyclic = {"own": []}
    cyclic["own"].append(cyclic)
    model = IntegrationModel(extra=cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        integration_to_dict(model)
    assert model.extra is cyclic and cyclic["own"][0] is cyclic


@pytest.mark.parametrize("location", ["model-extra", "record-extra", "measurement", "properties"])
@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_json_container_subclasses_are_copied_without_hooks(location, direction):
    value = _AliasDict(values=_AliasList([1, {"more": [2]}]))
    if direction == "encode":
        payload = integration_to_dict(_model(location, value))
        expected = json.dumps(payload)
        value["values"][1]["more"].append(3)
        assert json.dumps(payload) == expected
    else:
        payload = integration_to_dict(_model(location, {}))
        if location == "model-extra":
            carrier = payload["data"]
        elif location == "record-extra":
            carrier = payload["data"]["preservation"][0]
        elif location == "measurement":
            carrier = payload["data"]["preservation"][0]["issue"]["measurement"]
        else:
            carrier = payload["data"]["scene_styles"][0]["properties"]
        carrier["own"] = value
        decoded = integration_from_dict(payload)
        expected = integration_to_dict(decoded)
        value["values"][1]["more"].append(3)
        assert integration_to_dict(decoded) == expected
