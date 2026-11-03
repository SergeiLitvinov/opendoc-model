"""Group colorimetry declarations and opaque profile links, without ICC processing."""

from copy import deepcopy

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    ColorValue,
    DocumentLimits,
    DocumentModel,
    GroupColorSpace,
    GroupCompositing,
    Paint,
    Paragraph,
    PathCommand,
    Resource,
    ResourceKind,
    SceneOccurrence,
    Section,
    TextRun,
    VectorGroup,
    VectorPath,
    VectorScene,
    check_document,
    clone_model,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_scope_color_space,
    get_vector_scene,
    integration_resource_uses,
    iter_elements,
    merge_documents,
    remove_resource,
    replace_resource,
    set_anchor,
    set_scope_color_space,
    set_vector_scene,
)


def fixture():
    run = TextRun("Own color scope")
    set_anchor(run, Anchor("text"))
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([run])])],
        resources={
            key: Resource(key, ResourceKind.ATTACHMENT, "application/vnd.iccprofile", data=b"own opaque profile " + key.encode())
            for key in ("p", "q")
        },
    )
    scene = VectorScene(
        "scene",
        100,
        100,
        paths=(VectorPath("path", (PathCommand("move", (0, 0)),), fill=Paint(ColorValue.from_hex("#ff0000"))),),
        groups=(
            VectorGroup(
                "g",
                ("path", "paint-text"),
                opacity=0.25,
                compositing=GroupCompositing(0.5, True, False, "normal"),
                extra={"native_CS": "inert-Gray"},
            ),
        ),
        roots=("g",),
        occurrences=(SceneOccurrence("paint-text", "text", compositing=GroupCompositing(1, False, False, "normal")),),
    )
    set_vector_scene(document, scene)
    return document


@pytest.mark.parametrize(
    "space,profile",
    [("rgb", None), ("gray", None), ("cmyk", None), ("srgb", None), ("icc", "p"), ("rgb", "p"), (None, None), (None, "p")],
)
def test_two_json_cycles_distinguish_spaces_profiles_and_unknown(space, profile):
    document = fixture()
    value = GroupColorSpace(space, profile, extra={"future": [1]})
    set_scope_color_space(document, "scene", "g", value)
    expected = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and get_scope_color_space(document, "scene", "g") == value
    assert get_vector_scene(document, "scene").paths[0].fill.color == ColorValue.from_hex("#ff0000")
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    assert get_scope_color_space(document, "scene", "paint-text") is None  # no inferred parent space
    issues = check_document(document).issues
    assert any(issue.code == "graphics-color-space-unknown" and ".groups[0]." in issue.location for issue in issues) == (
        space is None
    )


def test_edit_delete_and_explicit_unknown_without_legacy_defaults():
    document = fixture()
    before = get_vector_scene(document, "scene")
    assert get_scope_color_space(document, "scene", "g") is None
    set_scope_color_space(document, "scene", "g", GroupColorSpace("rgb", extra={"future": [1]}))
    set_scope_color_space(document, "scene", "g", GroupColorSpace("gray"))
    value = get_scope_color_space(document, "scene", "g")
    assert value.space == "gray" and value.extra == {"future": [1]}
    value.extra["future"].append(2)
    assert get_scope_color_space(document, "scene", "g").extra["future"] == [1]
    set_scope_color_space(document, "scene", "paint-text", GroupColorSpace("srgb"))
    set_scope_color_space(document, "scene", "g", GroupColorSpace())
    assert get_scope_color_space(document, "scene", "g").space is None
    set_scope_color_space(document, "scene", "g", None)
    assert get_scope_color_space(document, "scene", "g") is None
    after = get_vector_scene(document, "scene")
    assert after.scope_version == 1 and after.groups[0] == before.groups[0]
    assert get_scope_color_space(document, "scene", "paint-text").space == "srgb"
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert get_scope_color_space(document, "scene", "g") is None


def test_remap_extract_profile_resource_uses_and_atomic_replacement():
    document = fixture()
    set_scope_color_space(document, "scene", "g", GroupColorSpace("icc", "p"))
    set_scope_color_space(document, "scene", "paint-text", GroupColorSpace(None, "p"))
    expected = deepcopy(document)
    extracted = extract_document(document, next(iter_elements(document, Paragraph)))
    assert set(extracted.resources) == {"p"}
    assert get_scope_color_space(extracted, "scene", "g").profile_resource_id == "p"
    other = fixture()
    other.metadata.clear()
    merged = merge_documents([other, document], conflicts="rename", metadata_conflicts="keep_last")
    assert get_scope_color_space(merged.document, "scene", "g").profile_resource_id == merged.id_maps[1].resources["p"]
    assert get_vector_scene(merged.document, "scene").occurrences[0].node_id == merged.id_maps[1].anchors["text"]
    assert len(integration_resource_uses(document, "p")) == 2
    assert not any(issue.code == "unused-resource" and "'p'" in issue.message for issue in check_document(document).issues)
    with pytest.raises(ValueError, match="used"):
        remove_resource(document, "p")
    assert document == expected
    remove_resource(document, "p", replacement_id="q")
    assert get_scope_color_space(document, "scene", "g").profile_resource_id == "q"
    assert get_scope_color_space(document, "scene", "paint-text").profile_resource_id == "q"
    assert "p" in expected.resources and "p" not in document.resources
    copied = clone_model(document)
    set_scope_color_space(copied, "scene", "g", None)
    assert get_scope_color_space(document, "scene", "g").space == "icc"


@pytest.mark.parametrize(
    "value",
    [
        GroupColorSpace("icc"),
        GroupColorSpace("icc", "missing"),
        GroupColorSpace("rgb", ""),
        GroupColorSpace("lab"),
        GroupColorSpace(True),
        GroupColorSpace("srgb", "p"),
        GroupColorSpace("icc", True),
        GroupColorSpace("rgb", extra={"space": "gray"}),
    ],
)
def test_invalid_declarations_and_references_are_atomic(value):
    document = fixture()
    before = deepcopy(document)
    with pytest.raises(ValueError):
        set_scope_color_space(document, "scene", "g", value)
    assert document == before


def test_wrong_kind_profiles_and_unknown_scope_do_not_mutate_model():
    document = fixture()
    document.resources["image"] = Resource("image", ResourceKind.RASTER_IMAGE, "image/png", data=b"opaque")
    before = deepcopy(document)
    with pytest.raises(ValueError):
        set_scope_color_space(document, "scene", "g", GroupColorSpace("icc", "image"))
    with pytest.raises(ValueError):
        set_scope_color_space(document, "scene", "missing", GroupColorSpace("rgb"))
    assert document == before
    set_scope_color_space(document, "scene", "g", GroupColorSpace("icc", "p"))
    before = deepcopy(document)
    with pytest.raises(ValueError):
        remove_resource(document, "p", replacement_id="image")
    with pytest.raises(ValueError):
        replace_resource(document, "p", document.resources["image"])
    assert document == before
    del document.resources["p"]
    assert any("profile_resource_id" in issue.location for issue in check_document(document).issues)


def test_limits_keep_budget_and_old_default_json_stays_exact():
    document = fixture()
    raw = document_to_dict(document)
    group_data = raw["document"]["metadata"]["opendoc.integration"]["data"]["scenes"][0]["groups"][0]
    assert "color_space" not in group_data["compositing"]
    assert document_to_dict(document_from_dict(raw)) == raw
    before = deepcopy(document)
    with pytest.raises(ArtifactLimitError) as caught:
        set_scope_color_space(
            document, "scene", "g", GroupColorSpace("rgb", extra={"large": list(range(100))}), limits=DocumentLimits(max_nodes=10)
        )
    assert caught.value.path and caught.value.quota == "nodes" and caught.value.maximum == 10
    assert document == before
    with pytest.raises(ArtifactLimitError) as caught:
        set_scope_color_space(document, "scene", "g", GroupColorSpace("icc", "p"), limits=DocumentLimits(max_embedded_bytes=0))
    assert caught.value.quota == "embedded bytes" and caught.value.maximum == 0
    assert document == before
    budget = DocumentLimits(max_nodes=300_000)
    set_scope_color_space(document, "scene", "g", GroupColorSpace("rgb", extra={"large": list(range(100_001))}), limits=budget)
    for _ in range(2):
        document = document_from_json(document_to_json(document, limits=budget), limits=budget)
    assert len(get_scope_color_space(document, "scene", "g", limits=budget).extra["large"]) == 100_001
    with pytest.raises(ArtifactLimitError):
        get_scope_color_space(document, "scene", "g")


def test_legacy_vector_scope_requires_explicit_migration_for_edit():
    document = DocumentModel()
    set_vector_scene(document, VectorScene("legacy", 10, 10, groups=(VectorGroup("g", (), opacity=0.5),), roots=("g",)))
    before = deepcopy(document)
    assert get_scope_color_space(document, "legacy", "g") is None
    with pytest.raises(ValueError, match="scope_version"):
        set_scope_color_space(document, "legacy", "g", GroupColorSpace("gray"))
    assert document == before
