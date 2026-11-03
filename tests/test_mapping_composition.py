"""Own model snapshots and declared maps; no native conversion or inferred correspondence."""

import json
import runpy
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
    document_from_json,
    document_to_json,
    extract_document,
    merge_documents,
    object_mapping_from_dict,
    object_mapping_to_dict,
    remap_object_mapping,
    resolve_anchor,
    validate_object_mapping,
    with_mapping_publication,
)


def _fixture():
    data = runpy.run_path(str(Path(__file__).parents[1] / "examples/object_mapping.py"))
    mapping, source, target = data["mapping"], data["source"], data["target"]
    mapping = replace(mapping, extra={"future": {"id": "opaque-original", "values": [None, 1]}})
    source.resources["fallback"].properties["future"] = [1]
    source.metadata["own.mapping.history"] = object_mapping_to_dict(mapping)
    return mapping, source, target


def _cycles(document, mapping):
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        mapping = object_mapping_from_dict(json.loads(json.dumps(object_mapping_to_dict(mapping))))
    return document, mapping


@pytest.mark.parametrize("replacement_scope", ["source", "target"])
def test_merge_rebases_both_sides_and_replacements_without_changing_history(replacement_scope):
    mapping, source, target = _fixture()
    mapping = replace(
        mapping,
        entries=tuple(
            replace(entry, replacement=replace(entry.replacement, scope=replacement_scope)) for entry in mapping.entries
        ),
    )
    before = deepcopy((mapping, source, target))
    source_merge = merge_documents([source, source], conflicts="rename", metadata_conflicts="keep_first")
    target_merge = merge_documents([target, target], conflicts="rename")
    rebased = remap_object_mapping(
        mapping,
        source_nodes=source_merge.id_maps[1].anchors,
        source_resources=source_merge.id_maps[1].resources,
        target_nodes=target_merge.id_maps[1].anchors,
        target_resources=target_merge.id_maps[1].resources,
        target_locators={item.id: None for item in mapping.targets},
    )
    assert rebased.sources[0].node_id == "source-0~2" and rebased.sources[0].resource_id == "vector~2"
    assert rebased.targets[0].node_id == "target-0~2" and rebased.targets[0].resource_id == "fallback~2"
    assert all(entry.replacement.resource_id == "fallback~2" for entry in rebased.entries)
    assert all(item.native_locator is None for item in rebased.targets)
    assert rebased.extra == mapping.extra and rebased.result_id == mapping.result_id
    merged_source, rebased = _cycles(source_merge.document, rebased)
    merged_target, rebased = _cycles(target_merge.document, rebased)
    validate_object_mapping(rebased, source=merged_source, target=merged_target)
    assert merged_source.metadata["own.mapping.history"] == source.metadata["own.mapping.history"]
    rebased.extra["future"]["values"].append(2)
    merged_source.resources["fallback~2"].properties["future"].append(2)
    assert (mapping, source, target) == before
    invalidated = with_mapping_publication(rebased, "invalidated")
    assert invalidated.targets == () and not invalidated.assessment_complete
    assert rebased.targets and mapping.targets[0].native_locator is not None


def test_split_extract_and_merge_preserve_explicit_selected_scope_and_json():
    mapping, source, target = _fixture()
    before = deepcopy((mapping, source, target))
    sources, targets, selected_maps = [], [], []
    for index in range(2):
        source_location = resolve_anchor(source, f"source-{index}")
        target_location = resolve_anchor(target, f"target-{index}")
        plain = extract_document(source, source_location)
        assert set(plain.resources) == {"vector"}
        assert object_mapping_from_dict(plain.metadata["own.mapping.history"]) == mapping
        with pytest.raises(ValueError, match="dangling"):
            validate_object_mapping(mapping, source=plain)
        selected_source = extract_document(source, source_location, additional_resources=["fallback"])
        selected_target = extract_document(target, target_location)
        selected = replace(
            mapping,
            sources=(mapping.sources[index],),
            targets=(mapping.targets[index],),
            entries=(mapping.entries[index],),
            assessment_complete=False,
        )
        selected_source, selected = _cycles(selected_source, selected)
        selected_target, selected = _cycles(selected_target, selected)
        validate_object_mapping(selected, source=selected_source, target=selected_target)
        sources.append(selected_source)
        targets.append(selected_target)
        selected_maps.append(selected)
    source_merge = merge_documents(sources, conflicts="rename", metadata_conflicts="keep_first")
    target_merge = merge_documents(targets, conflicts="rename")
    for index, selected in enumerate(selected_maps):
        rebased = remap_object_mapping(
            selected,
            source_nodes=source_merge.id_maps[index].anchors,
            source_resources=source_merge.id_maps[index].resources,
            target_nodes=target_merge.id_maps[index].anchors,
            target_resources=target_merge.id_maps[index].resources,
            target_locators={item.id: None for item in selected.targets},
        )
        validate_object_mapping(rebased, source=source_merge.document, target=target_merge.document)
        assert rebased.sources[0].id == f"input-{index}" and rebased.targets[0].id == f"output-{index}"
        assert not rebased.assessment_complete
    assert (mapping, source, target) == before


def test_composition_remap_conflicts_and_limits_leave_inputs_and_maps_unchanged():
    mapping, source, target = _fixture()
    before = deepcopy((mapping, source, target))
    with pytest.raises(ValueError, match="conflict"):
        merge_documents([source, source])
    with pytest.raises(ArtifactLimitError):
        merge_documents([source, source], conflicts="rename", limits=DocumentLimits(max_nodes=2))
    with pytest.raises(ValueError):
        remap_object_mapping(mapping, source_nodes={"source-0": "same", "source-1": "same"})
    with pytest.raises(ArtifactLimitError):
        extract_document(source, resolve_anchor(source, "source-0"), limits=DocumentLimits(max_nodes=2))
    assert (mapping, source, target) == before


def test_explicit_split_and_join_groups_have_known_references_without_inferred_coverage():
    mapping, source, target = _fixture()
    split = replace(
        mapping, sources=(mapping.sources[0],), entries=(replace(mapping.entries[0], target_ids=("output-0", "output-1")),)
    )
    validate_object_mapping(split, source=source, target=target)
    joined_target = extract_document(target, resolve_anchor(target, "target-0"))
    joined = replace(
        mapping, targets=(mapping.targets[0],), entries=(replace(mapping.entries[0], source_ids=("input-0", "input-1")),)
    )
    validate_object_mapping(joined, source=source, target=joined_target)
    for declared, document in ((split, target), (joined, joined_target)):
        copied_document, copied_map = _cycles(document, declared)
        validate_object_mapping(copied_map, source=source, target=copied_document)
        assert copied_map.assessment_complete
    with pytest.raises(ValueError, match="duplicate"):
        object_mapping_to_dict(replace(split, entries=(split.entries[0], replace(split.entries[0], id="double-count"))))


@pytest.mark.parametrize("field", ["source_nodes", "target_nodes", "source_resources", "target_resources"])
def test_remap_rejects_empty_original_identifier_atomically(field):
    mapping, _, _ = _fixture()
    before = deepcopy(mapping)
    with pytest.raises(ValueError):
        remap_object_mapping(mapping, **{field: {"": "new"}})
    assert mapping == before
