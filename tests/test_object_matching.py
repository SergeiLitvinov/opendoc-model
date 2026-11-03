"""Mutation cases for occurrence-preserving structural comparison."""

from opendoc_model.document_model import DocumentModel, Paragraph, Provenance, Section, TextRun
from opendoc_model.inspection import compare_inspections, inspect_document_model


def _inspect(*texts, provenance=None):
    return inspect_document_model(
        DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun(text)], provenance=provenance) for text in texts])])
    )


def _assert_accounted(diff):
    matched = diff["retained"] + diff["changed"]
    assert len(matched) + len(diff["lost"]) == diff["source_count"]
    assert len(matched) + len(diff["added"]) == diff["target_count"]
    assert len({item["source_index"] for item in matched}) == len(matched)
    assert len({item["target_index"] for item in matched}) == len(matched)


def test_reordering_without_provenance_is_a_move_not_content_loss():
    diff = compare_inspections(_inspect("First", "Second"), _inspect("Second", "First")).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == diff["added"] == []
    assert len(diff["changed"]) == 2
    assert all(item["changes"] == ["location"] for item in diff["changed"])
    assert all(item["match_basis"] == "content" for item in diff["changed"])


def test_deleting_first_object_does_not_mark_shifted_objects_as_edited():
    before, after = _inspect("Deleted", "Kept", "Also kept"), _inspect("Kept", "Also kept")
    diff = compare_inspections(before, after).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == [before.objects[0]]
    assert diff["added"] == []
    assert all(item["changes"] == ["location"] for item in diff["changed"])


def test_shared_provenance_does_not_collapse_occurrences():
    origin = Provenance(source_format="pptx", object_id="group-1")
    before = _inspect("First", "Second", "Third", provenance=origin)
    after = _inspect("Third", "First", provenance=origin)
    diff = compare_inspections(before, after).object_diff
    _assert_accounted(diff)
    assert diff["lost"] == [before.objects[1]]
    assert diff["retention_ratio"] == 0.6667


def test_identical_duplicate_removal_is_counted_once_and_pairing_is_ambiguous():
    diff = compare_inspections(_inspect("Same", "Same", "Same"), _inspect("Same", "Same")).object_diff
    _assert_accounted(diff)
    assert len(diff["lost"]) == 1
    assert diff["matching"]["ambiguous"] == 2


def test_edit_in_place_is_explicitly_heuristic_without_provenance():
    diff = compare_inspections(_inspect("Before"), _inspect("After")).object_diff
    assert diff["changed"][0]["changes"] == ["content_hash"]
    assert diff["matching"]["heuristic"] == 1


def test_conflicting_origins_in_same_source_are_not_merged_by_equal_text():
    before = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-1"))
    after = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-2"))
    diff = compare_inspections(before, after).object_diff
    assert len(diff["lost"]) == len(diff["added"]) == 1


def test_reimported_format_can_match_content_despite_new_origins():
    before = _inspect("Same", provenance=Provenance(source_format="pptx", object_id="shape-1"))
    after = _inspect("Same", provenance=Provenance(source_format="docx", object_id="paragraph-1"))
    diff = compare_inspections(before, after).object_diff
    assert not diff["lost"]
    assert diff["retained"][0]["match_basis"] == "content"


def test_page_provenance_without_object_id_is_not_unique_identity():
    inspection = _inspect("First", "Second", provenance=Provenance(source_format="pdf", page=1))
    assert all(item["provenance"]["identity"] is None for item in inspection.objects)


def test_missing_inventory_is_unknown_not_total_loss():
    from opendoc_model.inspection import DocumentInspection

    comparison = compare_inspections(_inspect("Text"), DocumentInspection(None, "html"))
    diff = comparison.object_diff
    assert diff["available"] is False
    assert diff["retention_ratio"] is None
    assert diff["lost"] == []
    assert not any(issue.feature == "object-loss" for issue in comparison.issues)


def test_known_empty_inventory_still_detects_real_deletion():
    diff = compare_inspections(_inspect("Text"), _inspect()).object_diff
    assert diff["available"] is True
    assert len(diff["lost"]) == 1
    assert diff["retention_ratio"] == 0


def test_images_match_by_bytes_not_package_resource_ids():
    from opendoc_model.document_model import Image, Resource, ResourceKind

    def image_inspection(resource_id, data):
        return inspect_document_model(
            DocumentModel(
                resources={resource_id: Resource(resource_id, ResourceKind.RASTER_IMAGE, "image/png", data=data)},
                sections=[Section(blocks=[Image(resource_id=resource_id)])],
            )
        )

    source = image_inspection("image-1", b"first image")
    renamed = image_inspection("image-9", b"first image")
    replaced = image_inspection("image-1", b"different image")
    diff = compare_inspections(source, renamed).object_diff
    assert len(diff["retained"]) == 1
    assert diff["retained"][0]["match_basis"] == "content"
    assert compare_inspections(source, replaced).object_diff["changed"][0]["changes"] == ["content_hash"]


def test_duplicate_index_prefers_equal_location_then_first_compatible_occurrence():
    from opendoc_model.object_matching import match_objects

    source = [{"type": "paragraph", "content_hash": "same", "location": str(index)} for index in range(3000)]
    matches, lost, added = match_objects(source, list(reversed(source[:2000])))
    assert len(matches) == 2000 and len(lost) == 1000 and not added
    assert all(item["source"]["location"] == item["target"]["location"] for item in matches)
    assert all(item["ambiguous"] and item["match_basis"] == "content" for item in matches)
    assert len({item["target_index"] for item in matches}) == 2000


def test_indexed_origin_pools_merge_unknown_and_same_identity_in_original_order():
    from opendoc_model.object_matching import match_objects

    def item(identity, location):
        return {
            "type": "paragraph",
            "content_hash": "same",
            "location": location,
            "provenance": {"identity": identity, "source_format": "custom", "source_path": "same"},
        }

    source = [item("a", "preferred"), item("a", "elsewhere"), item(None, "third"), item("b", "fourth")]
    target = [item("b", "preferred"), item(None, "preferred"), item("a", "none"), item(None, "last")]
    matches, lost, added = match_objects(source, target)
    assert not lost and not added
    assert [(entry["source_index"], entry["target_index"]) for entry in matches] == [(0, 2), (1, 1), (2, 3), (3, 0)]
    assert matches[0]["match_basis"] == "provenance-content"
    assert all(entry["ambiguous"] for entry in matches[:3])
    assert matches[3]["match_basis"] == "provenance" and not matches[3]["ambiguous"]


def test_conflicting_duplicate_origins_do_not_gain_matches_from_indexing():
    from opendoc_model.object_matching import match_objects

    source = [
        {
            "type": "paragraph",
            "content_hash": "same",
            "location": str(index),
            "provenance": {"identity": f"before-{index}", "source_format": "custom", "source_path": "same"},
        }
        for index in range(2000)
    ]
    target = [{**item, "provenance": {**item["provenance"], "identity": f"after-{index}"}} for index, item in enumerate(source)]
    matches, lost, added = match_objects(source, target)
    assert not matches and lost == source and added == target
