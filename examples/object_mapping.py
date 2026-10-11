"""Own declaration fixture: two occurrences of one resource and a raster replacement."""

import json
from dataclasses import replace

from opendoc_model import (
    Anchor,
    DiagnosticIssue,
    DocumentModel,
    Image,
    IssueSeverity,
    MappingReplacement,
    NativeObjectLocator,
    ObjectMapping,
    ObjectMappingEntry,
    ObjectOccurrence,
    PreservationState,
    Resource,
    ResourceKind,
    Section,
    object_mapping_from_dict,
    object_mapping_to_dict,
    set_anchor,
    validate_object_mapping,
    with_mapping_publication,
)

# Bytes and native addresses are synthetic declarations, not a rendered output file.
vector = Resource("vector", ResourceKind.VECTOR_IMAGE, "image/svg+xml", b'<svg xmlns="http://www.w3.org/2000/svg"/>')
png = Resource("fallback", ResourceKind.RASTER_IMAGE, "image/png", b"own synthetic resource bytes")
source_images = [Image("vector"), Image("vector")]
target_images = [Image("fallback"), Image("fallback")]
for index, (original, result) in enumerate(zip(source_images, target_images, strict=True)):
    set_anchor(original, Anchor(f"source-{index}"))
    set_anchor(result, Anchor(f"target-{index}"))
source = DocumentModel(sections=[Section(source_images)], resources={"vector": vector, "fallback": png})
target = DocumentModel(sections=[Section(target_images)], resources={"fallback": png})
mapping = ObjectMapping(
    sources=tuple(ObjectOccurrence(f"input-{i}", node_id=f"source-{i}", resource_id="vector") for i in range(2)),
    targets=tuple(
        ObjectOccurrence(
            f"output-{i}",
            node_id=f"target-{i}",
            resource_id="fallback",
            native_locator=NativeObjectLocator("fixture", f"items/{i}"),
        )
        for i in range(2)
    ),
    entries=tuple(
        ObjectMappingEntry(
            f"group-{i}",
            (f"input-{i}",),
            PreservationState.VISUAL,
            DiagnosticIssue("fixture.raster", IssueSeverity.LOSS, "Raster replacement", f"source-{i}", reason="raster-fallback"),
            (f"output-{i}",),
            MappingReplacement("raster", "fallback", "source"),
        )
        for i in range(2)
    ),
    publication="published",
    output_format="fixture",
    assessment_complete=True,
    result_id="fixture-run-1",
)
for _ in range(2):
    mapping = object_mapping_from_dict(json.loads(json.dumps(object_mapping_to_dict(mapping))))
validate_object_mapping(mapping, source=source, target=target)
target.sections[0].blocks.reverse()
validate_object_mapping(mapping, source=source, target=target)
assert mapping.sources[0].resource_id == mapping.sources[1].resource_id
assert mapping.sources[0].id != mapping.sources[1].id
staged = replace(mapping, publication="staged")
published = with_mapping_publication(staged, "published")
assert published.result_id == staged.result_id
assert all(item.native_locator is None for item in published.targets)
native_only = replace(staged, targets=tuple(replace(item, node_id=None, resource_id=None) for item in staged.targets))
native_published = with_mapping_publication(
    native_only,
    "published",
    target_locators={item.id: NativeObjectLocator("fixture", f"final/{index}") for index, item in enumerate(native_only.targets)},
)
assert native_published.assessment_complete
assert native_published.targets[0].native_locator.value == "final/0"
rejected = with_mapping_publication(
    staged,
    "rejected",
    issue=DiagnosticIssue("fixture.quality", IssueSeverity.ERROR, "Quality rejected", reason="quality-rejected"),
)
assert not rejected.targets and not rejected.assessment_complete
assert staged.targets and staged.assessment_complete
print("Object mapping: distinct occurrences, raster declarations, scoped references and two JSON cycles OK")
