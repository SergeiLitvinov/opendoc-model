"""Own occurrence fixture; declarations never imply a rendered or published native file."""

import json
import runpy
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from socket import socket

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    DiagnosticIssue,
    DocumentLimits,
    DocumentModel,
    IssueSeverity,
    NativeObjectLocator,
    ObjectMapping,
    ObjectMappingEntry,
    ObjectOccurrence,
    PreservationState,
    Provenance,
    ResourceKind,
    document_from_json,
    document_to_json,
    object_mapping_from_dict,
    object_mapping_to_dict,
    remap_object_mapping,
    resolve_anchor,
    set_anchor,
    validate_object_mapping,
    with_mapping_publication,
)


def _fixture():
    namespace = runpy.run_path(str(Path(__file__).parents[1] / "examples/object_mapping.py"))
    return namespace["mapping"], namespace["source"], namespace["target"]


def test_staged_publication_requires_fresh_locator_evidence():
    mapping, source, target = _fixture()
    staged = replace(mapping, publication="staged", result_id="result-1", extra={"future": [1]})
    validate_object_mapping(staged, source=source, target=target)
    published = with_mapping_publication(staged, "published")
    assert published.result_id == "result-1" and published.assessment_complete
    assert all(item.native_locator is None for item in published.targets)
    assert staged.targets[0].native_locator is not None
    confirmed = with_mapping_publication(
        staged, "published", target_locators={"output-0": NativeObjectLocator("fixture", "final/0")}
    )
    assert confirmed.targets[0].native_locator.value == "final/0"
    assert confirmed.targets[1].native_locator is None
    confirmed.extra["future"].append(2)
    assert staged.extra["future"] == [1]


@pytest.mark.parametrize("status", ["rejected", "invalidated", "attempted", "unknown"])
def test_discarded_result_clears_current_targets_and_keeps_original_evidence(status):
    mapping, _, _ = _fixture()
    staged = replace(
        mapping,
        publication="staged",
        result_id="stable-result",
        entries=(
            replace(mapping.entries[0], replacement=replace(mapping.entries[0].replacement, scope="target")),
            mapping.entries[1],
        ),
    )
    issue = DiagnosticIssue("fixture.cancelled", IssueSeverity.ERROR, "Caller cancelled", reason="caller-cancelled")
    discarded = with_mapping_publication(staged, status, issue=issue)
    assert discarded.targets == () and not discarded.assessment_complete
    assert all(entry.target_ids is None for entry in discarded.entries)
    assert discarded.entries[0].replacement is None
    assert discarded.entries[1].replacement == staged.entries[1].replacement
    assert discarded.sources == staged.sources and discarded.result_id == "stable-result"
    assert object_mapping_from_dict(object_mapping_to_dict(discarded)).publication_issue == issue
    assert staged.targets and staged.entries[0].target_ids == ("output-0",)
    if status in ("rejected", "invalidated"):
        with pytest.raises(ValueError, match="fresh mapping"):
            with_mapping_publication(discarded, "published")
    with pytest.raises(ValueError):
        with_mapping_publication(staged, status, target_locators={"output-0": None})


def test_lifecycle_failure_is_atomic_and_rerun_has_new_identity():
    mapping, _, _ = _fixture()
    staged = replace(mapping, publication="staged", result_id="run-1")
    before = object_mapping_to_dict(staged)
    with pytest.raises(ValueError):
        with_mapping_publication(staged, "published", target_locators={"missing": None})
    assert object_mapping_to_dict(staged) == before
    invalid = with_mapping_publication(staged, "invalidated")
    fresh = replace(staged, result_id="run-2")
    assert fresh.result_id != invalid.result_id
    assert with_mapping_publication(fresh, "published").targets


def test_known_resource_must_match_anchored_object():
    mapping, source, _ = _fixture()
    inconsistent = replace(mapping, sources=(replace(mapping.sources[0], resource_id="fallback"), mapping.sources[1]))
    with pytest.raises(ValueError, match="anchored object's"):
        validate_object_mapping(inconsistent, source=source)
    assert mapping.sources[0].resource_id == "vector"


def test_exact_envelope_unknown_fields_independence_and_document_compatibility():
    mapping, _, _ = _fixture()
    raw = object_mapping_to_dict(mapping)
    assert raw["format"] == "opendoc.object-mapping" and raw["version"] == 1
    assert raw["publication"] == "published" and raw["assessment_complete"] is True
    assert raw["entries"][0]["source_ids"] == ["input-0"]
    assert raw["entries"][0]["target_ids"] == ["output-0"]
    assert raw["entries"][0]["replacement"] == {"kind": "raster", "resource_id": "fallback", "scope": "source"}
    raw["future"] = {"kind": "line", "value": [1, None]}
    raw["sources"][0]["future"] = {"source": True}
    raw["entries"][0]["replacement"]["future"] = [False]
    raw["targets"][0]["native_locator"]["future"] = "inert"
    for _ in range(2):
        raw = json.loads(json.dumps(object_mapping_to_dict(object_mapping_from_dict(raw))))
    restored = object_mapping_from_dict(raw)
    assert restored.extra == {"future": {"kind": "line", "value": [1, None]}}
    output = object_mapping_to_dict(restored)
    output["future"]["value"].append("changed")
    assert restored.extra["future"]["value"] == [1, None]
    document = DocumentModel(metadata={"org.example.mapping": raw})
    assert document_from_json(document_to_json(document)) == document
    assert "org.example.mapping" not in document_from_json(document_to_json(DocumentModel())).metadata


def test_reordering_renumbering_deletion_and_dangling_references():
    mapping, source, target = _fixture()
    before = deepcopy(mapping)
    target.sections[0].blocks.reverse()
    validate_object_mapping(mapping, source=source, target=target)
    set_anchor(resolve_anchor(target, "target-0").node, Anchor("renamed"))
    renamed = remap_object_mapping(
        mapping,
        target_nodes={"target-0": "renamed"},
        target_locators={"output-0": NativeObjectLocator("fixture", "renumbered/item")},
    )
    validate_object_mapping(renamed, source=source, target=target)
    assert renamed.targets[0].id == "output-0" and renamed.targets[0].native_locator.value == "renumbered/item"
    assert mapping == before
    target.sections[0].blocks.pop()
    with pytest.raises(ValueError, match="dangling anchor"):
        validate_object_mapping(renamed, target=target)
    target.resources.clear()
    with pytest.raises(ValueError):
        validate_object_mapping(renamed, target=target)


@pytest.mark.parametrize("publication", ["unknown", "attempted", "rejected"])
def test_attempt_does_not_claim_actual_target_or_complete_result(publication):
    mapping, _, _ = _fixture()
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(mapping, publication=publication))
    attempted = replace(
        mapping,
        publication=publication,
        targets=(),
        assessment_complete=False,
        entries=tuple(replace(entry, target_ids=None) for entry in mapping.entries),
    )
    raw = object_mapping_to_dict(attempted)
    assert raw["entries"][0]["target_ids"] is None and raw["targets"] == []
    assert object_mapping_from_dict(raw) == attempted
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(attempted, assessment_complete=True))


def test_unknown_and_confirmed_absent_targets_remain_distinct():
    mapping, _, _ = _fixture()
    unknown = replace(
        mapping,
        targets=(),
        assessment_complete=False,
        entries=tuple(replace(entry, target_ids=None) for entry in mapping.entries),
    )
    missing = replace(
        unknown,
        assessment_complete=True,
        entries=tuple(replace(entry, target_ids=(), state=PreservationState.LOST) for entry in unknown.entries),
    )
    assert object_mapping_to_dict(unknown)["entries"][0]["target_ids"] is None
    assert object_mapping_to_dict(missing)["entries"][0]["target_ids"] == []
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(unknown, assessment_complete=True))
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(missing, entries=(replace(missing.entries[0], state=PreservationState.SEMANTIC),)))


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "bool-version",
        "source",
        "target",
        "duplicate",
        "repeated-node",
        "raster-semantic",
        "reason",
        "format",
        "empty-handle",
        "coverage",
        "reserved",
    ],
)
def test_invalid_json_refuses_without_changing_input(mutation):
    mapping, _, _ = _fixture()
    raw = object_mapping_to_dict(mapping)
    if mutation == "version":
        raw["version"] = 2
    elif mutation == "bool-version":
        raw["version"] = True
    elif mutation in ("source", "target"):
        raw["entries"][0][mutation + "_ids"] = ["missing"]
    elif mutation == "duplicate":
        raw["sources"][1]["id"] = raw["sources"][0]["id"]
    elif mutation == "repeated-node":
        raw["sources"][1]["node_id"] = raw["sources"][0]["node_id"]
    elif mutation == "raster-semantic":
        raw["entries"][0]["state"] = "semantic"
        raw["entries"][0]["issue"]["severity"] = "info"
    elif mutation == "reason":
        raw["entries"][0]["issue"]["reason"] = None
    elif mutation == "format":
        raw["targets"][0]["native_locator"]["format"] = "other"
    elif mutation == "empty-handle":
        raw["sources"][0].update(node_id=None, resource_id=None, provenance=None, native_locator=None)
    elif mutation == "coverage":
        raw["entries"].pop()
    else:
        raw["extra"] = {}
    before = deepcopy(raw)
    with pytest.raises(ValueError) as caught:
        object_mapping_from_dict(raw)
    assert caught.value.code == "mapping.invalid" and caught.value.location
    assert raw == before


def test_explicit_many_to_many_groups_without_double_counting():
    mapping, _, _ = _fixture()
    joined = replace(
        mapping, entries=(replace(mapping.entries[0], source_ids=("input-0", "input-1"), target_ids=("output-0", "output-1")),)
    )
    assert object_mapping_from_dict(object_mapping_to_dict(joined)) == joined
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(joined, entries=(joined.entries[0], replace(joined.entries[0], id="twice"))))


def test_limits_cycles_reserved_fields_and_remap_collisions_are_atomic():
    mapping, _, _ = _fixture()
    before = deepcopy(mapping)
    with pytest.raises(ArtifactLimitError):
        object_mapping_to_dict(mapping, limits=DocumentLimits(max_nodes=5))
    with pytest.raises(ArtifactLimitError):
        object_mapping_from_dict(object_mapping_to_dict(mapping), limits=DocumentLimits(max_depth=2))
    with pytest.raises(ValueError):
        remap_object_mapping(mapping, target_nodes={"target-0": "target-1"})
    with pytest.raises(ValueError):
        remap_object_mapping(mapping, target_locators={"absent": None})
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(mapping, extra={"version": 1}))
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(mapping, extra=cyclic))
    assert mapping == before


def test_provenance_only_source_and_partial_scope_no_implicit_io(monkeypatch):
    mapping = ObjectMapping(
        sources=(ObjectOccurrence("known", provenance=Provenance("fixture", object_id="item")),),
        entries=(
            ObjectMappingEntry(
                "entry",
                ("known",),
                PreservationState.REJECTED,
                DiagnosticIssue("fixture.reject", IssueSeverity.ERROR, "Rejected", reason="unsupported"),
            ),
        ),
        publication="rejected",
    )

    def forbidden(*args, **kwargs):
        raise AssertionError("mapping must not inspect files or native locators")

    monkeypatch.setattr(Path, "open", forbidden)
    monkeypatch.setattr(socket, "connect", forbidden)
    validate_object_mapping(object_mapping_from_dict(object_mapping_to_dict(mapping)))


@pytest.mark.parametrize("scope", ["source", "target"])
def test_replacement_resource_kind_and_missing_references(scope):
    mapping, source, target = _fixture()
    documents = {"source": source, "target": target}
    mapping = replace(
        mapping, entries=tuple(replace(entry, replacement=replace(entry.replacement, scope=scope)) for entry in mapping.entries)
    )
    document = documents[scope]
    document.resources["fallback"].kind = ResourceKind.VECTOR_IMAGE
    document.resources["fallback"].media_type = "image/svg+xml"
    with pytest.raises(ValueError, match="raster replacement"):
        validate_object_mapping(mapping, source=source, target=target)


def test_explicit_resource_maps_locator_reset_and_large_limits():
    mapping, _, _ = _fixture()
    remapped = remap_object_mapping(
        mapping,
        source_resources={"fallback": "source-raster"},
        target_resources={"fallback": "target-raster"},
        target_locators={"output-0": None},
    )
    assert remapped.entries[0].replacement.resource_id == "source-raster"
    assert remapped.targets[0].resource_id == "target-raster"
    assert remapped.targets[0].native_locator is None
    assert mapping.targets[0].native_locator is not None
    nested = "inert"
    for _ in range(70):
        nested = {"item": nested}
    mapping = replace(mapping, extra={"deep": nested})
    limits = replace(DocumentLimits(), max_depth=100)
    raw = object_mapping_to_dict(mapping, limits=limits)
    assert object_mapping_from_dict(raw, limits=limits) == mapping
    with pytest.raises(ArtifactLimitError):
        object_mapping_to_dict(mapping)


def test_visual_completeness_and_unpublished_target_replacement_refuse():
    mapping, _, _ = _fixture()
    with pytest.raises(ValueError):
        object_mapping_to_dict(replace(mapping, entries=tuple(replace(entry, replacement=None) for entry in mapping.entries)))
    attempt = replace(
        mapping,
        targets=(),
        publication="attempted",
        assessment_complete=False,
        entries=tuple(
            replace(entry, target_ids=None, replacement=replace(entry.replacement, scope="target")) for entry in mapping.entries
        ),
    )
    with pytest.raises(ValueError, match="target resources"):
        object_mapping_to_dict(attempt)
