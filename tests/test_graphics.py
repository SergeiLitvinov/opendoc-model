"""Own mixed paint scopes; declarations and references, without a native renderer."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    AffineTransform,
    Anchor,
    ArtifactLimitError,
    ColorValue,
    DocumentLimits,
    DocumentModel,
    GroupCompositing,
    Image,
    IntegrationModel,
    Paint,
    Paragraph,
    PathCommand,
    Resource,
    ResourceKind,
    SceneOccurrence,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VectorClip,
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
    get_integration,
    get_vector_scene,
    iter_elements,
    merge_documents,
    remove_node,
    remove_resource,
    remove_vector_scene,
    set_anchor,
    set_integration,
    set_scene_clip,
    set_scene_group,
    set_vector_scene,
    walk_model,
)

IDENTITY = GroupCompositing(1, False, False, "normal")


def fixture():
    text = TextRun("Visible and hidden 😀 glyphs")
    image = Image("image-resource")
    table = Table([TableRow([TableCell([Paragraph([TextRun("Cell")])])])])
    for node, identifier in ((text, "text"), (image, "image"), (table, "table")):
        set_anchor(node, Anchor(identifier))
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph([text, image]), table])],
        resources={
            "image-resource": Resource("image-resource", ResourceKind.RASTER_IMAGE, "image/png", data=b"own opaque image"),
        },
    )
    commands = (
        PathCommand("move", (0, 0)),
        PathCommand("cubic", (30, 0, 30, 40, 0, 40)),
        PathCommand("close"),
        PathCommand("move", (5, 5)),
        PathCommand("cubic", (10, 5, 10, 10, 5, 10)),
        PathCommand("close"),
    )
    clip = VectorClip("curved", commands, "evenodd", AffineTransform(e=2.125, f=-3.5), extra={"future": [1]})
    small = VectorClip("small", (PathCommand("move", (1, 1)), PathCommand("line", (4, 9)), PathCommand("close")), "nonzero")
    path = VectorPath(
        "red", (PathCommand("move", (0, 0)), PathCommand("line", (20, 20))), fill=Paint(ColorValue.from_hex("#ff0000"))
    )
    blue = replace(path, id="blue", fill=Paint(ColorValue.from_hex("#0000ff"), 0.5))
    background = replace(path, id="background", fill=Paint(ColorValue.from_hex("#00ff00")))
    occurrences = (
        SceneOccurrence("text-paint", "text", clip_id="curved", compositing=IDENTITY),
        SceneOccurrence("image-a", "image", AffineTransform(e=80), "curved", compositing=IDENTITY),
        SceneOccurrence("image-b", "image", AffineTransform(e=160), "small", compositing=IDENTITY),
        SceneOccurrence("table-paint", "table", compositing=IDENTITY),
    )
    group = VectorGroup(
        "mixed",
        ("red", "blue", *(item.id for item in occurrences)),
        clip_id="curved",
        opacity=0.9,
        compositing=GroupCompositing(0.5, True, False, "normal", extra={"future": [2]}),
    )
    scene = VectorScene(
        "own-scene",
        600,
        800,
        (background, path, blue),
        (group,),
        ("background", "mixed"),
        clips=(clip, small),
        occurrences=occurrences,
        extra={"native_legacy": {"clip": "inert"}},
    )
    set_vector_scene(document, scene)
    return document, replace(scene, scope_version=1)


def test_two_cycles_exact_geometry_group_opacity_and_occurrence_identity():
    document, scene = fixture()
    expected = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and get_vector_scene(document, scene.id) == scene
    assert check_document(document).success
    assert get_vector_scene(document, scene.id).groups[0].compositing.opacity == 0.5
    assert get_vector_scene(document, scene.id).paths[2].fill.opacity == 0.5
    assert document.sections[0].blocks[0].content[0].text == "Visible and hidden 😀 glyphs"
    assert scene.occurrences[1].node_id == scene.occurrences[2].node_id
    assert scene.occurrences[1].clip_id != scene.occurrences[2].clip_id
    raw = document_to_dict(document)
    raw["version"] = 1
    assert document_from_dict(raw) == document
    detached = get_vector_scene(document, scene.id)
    detached.clips[0].extra["future"].append(3)
    assert get_vector_scene(document, scene.id).clips[0].extra["future"] == [1]


def test_edit_remove_clip_and_opacity_never_revives_legacy():
    document, scene = fixture()
    set_scene_clip(document, scene.id, "curved", replace(scene.clips[0], fill_rule="nonzero", transform=AffineTransform(e=9)))
    set_scene_clip(document, scene.id, "curved", None)
    edited = get_vector_scene(document, scene.id)
    assert all(item.clip_id != "curved" for item in (*edited.paths, *edited.groups, *edited.occurrences))
    assert edited.occurrences[2].clip_id == "small"
    set_scene_group(
        document, scene.id, "mixed", replace(edited.groups[0], compositing=replace(edited.groups[0].compositing, opacity=None))
    )
    edited = get_vector_scene(document, scene.id)
    assert edited.groups[0].opacity == 0.9 and edited.groups[0].compositing.opacity is None
    assert edited.extra["native_legacy"] == {"clip": "inert"}
    assert any(item.code == "graphics-scope-unknown" for item in check_document(document).issues)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert get_vector_scene(document, scene.id).groups[0].compositing.opacity is None
    set_scene_group(document, scene.id, "mixed", None)
    edited = get_vector_scene(document, scene.id)
    assert not edited.groups and edited.roots == ("background", *scene.groups[0].children)
    assert edited.paths[2].fill.opacity == 0.5
    assert document.sections[0].blocks[0].content[0].text == "Visible and hidden 😀 glyphs"
    remove_vector_scene(document, scene.id)
    assert get_vector_scene(document, scene.id) is None
    assert len(document.sections[0].blocks) == 2


def test_clone_extract_and_merge_remap_only_document_ids():
    source, scene = fixture()
    expected = deepcopy(source)
    # Selecting the entire section retains all referenced anchors.
    extracted = extract_document(source, next(location for location in walk_model(source) if isinstance(location.node, Section)))
    assert get_vector_scene(extracted, scene.id) == scene
    other, _ = fixture()
    remove_vector_scene(other, scene.id)
    other.metadata.clear()
    merged = merge_documents([other, source], conflicts="rename", metadata_conflicts="keep_last")
    result = get_vector_scene(merged.document, scene.id)
    assert result.occurrences[0].id == "text-paint"
    assert result.occurrences[0].node_id == merged.id_maps[1].anchors["text"]
    assert result.occurrences[1].node_id == merged.id_maps[1].anchors["image"]
    assert source == expected
    copied = clone_model(source)
    get_integration(copied).scenes[0].clips[0].extra["future"].append(5)
    assert source == expected
    # Existing extraction expands the selected container to retain anchor dependencies.
    partial = extract_document(source, next(iter_elements(source, Paragraph)))
    assert get_vector_scene(partial, scene.id) == scene
    assert len(list(iter_elements(partial, Table))) == 1
    assert source == expected


@pytest.mark.parametrize(
    "change",
    [
        lambda s: replace(s, occurrences=(replace(s.occurrences[0], node_id="missing"), *s.occurrences[1:])),
        lambda s: replace(s, groups=(replace(s.groups[0], clip_id="missing"),)),
        lambda s: replace(s, groups=("invalid",)),
        lambda s: replace(s, clips=(replace(s.clips[0], fill_rule="unsupported"), s.clips[1])),
        lambda s: replace(s, groups=(replace(s.groups[0], compositing=GroupCompositing(2)),)),
        lambda s: replace(s, groups=(replace(s.groups[0], compositing=GroupCompositing(blend_mode="native-unknown")),)),
        lambda s: replace(s, clips=(replace(s.clips[0], transform=AffineTransform(e=float("nan"))), s.clips[1])),
        lambda s: replace(s, clips=(replace(s.clips[0], commands=(PathCommand("cubic", (1, 2)),)), s.clips[1])),
        lambda s: replace(s, groups=(replace(s.groups[0], children=(*s.groups[0].children, "mixed")),)),
        lambda s: replace(s, roots=(*s.roots, "text-paint")),
        lambda s: replace(s, groups=(replace(s.groups[0], children=("red", "blue")),)),
        lambda s: replace(s, occurrences=(replace(s.occurrences[0], mask_resource_id="missing"), *s.occurrences[1:])),
    ],
)
def test_invalid_references_modes_geometry_and_ownership_are_atomic(change):
    document, scene = fixture()
    expected = deepcopy(document)
    with pytest.raises(ValueError):
        set_vector_scene(document, change(scene))
    assert document == expected


def test_unknown_is_not_normal_or_neutral_and_masks_are_resource_links():
    document, scene = fixture()
    document.resources["mask"] = Resource("mask", ResourceKind.RASTER_IMAGE, "image/png", data=b"own opaque mask")
    unknown = replace(
        scene,
        groups=(replace(scene.groups[0], compositing=GroupCompositing()),),
        clips=(replace(scene.clips[0], fill_rule=None), scene.clips[1]),
        occurrences=(replace(scene.occurrences[0], mask_resource_id="mask"), *scene.occurrences[1:]),
    )
    set_vector_scene(document, unknown)
    assert len([issue for issue in check_document(document).issues if issue.code == "graphics-scope-unknown"]) == 2
    assert get_vector_scene(document, scene.id).groups[0].compositing.blend_mode is None
    with pytest.raises(ValueError, match="used"):
        remove_resource(document, "mask")
    assert not any(item.code == "unused-resource" and "mask" in item.message for item in check_document(document).issues)
    # A known empty clip is explicit geometry, distinct from no/unknown clip.
    set_scene_clip(document, scene.id, "curved", VectorClip("curved", (), "evenodd"))
    assert get_vector_scene(document, scene.id).clips[0].commands == ()


def test_old_scene_fields_and_legacy_clips_keep_exact_json():
    document = DocumentModel()
    path = VectorPath("path", (PathCommand("move", (0, 0)), PathCommand("line", (1, 1))))
    scene = VectorScene(
        "old", 10, 10, (path,), (VectorGroup("old-group", ("path",), clip_id="path", opacity=0.5),), ("old-group",)
    )
    set_integration(document, IntegrationModel(scenes=(scene,)))
    raw = document_to_dict(document)
    data = raw["document"]["metadata"]["opendoc.integration"]["data"]["scenes"][0]
    assert "clips" not in data and "occurrences" not in data and "compositing" not in data["groups"][0]
    assert "scope_version" not in data
    assert document_to_dict(document_from_dict(raw)) == raw
    assert not any(issue.code == "graphics-scope-unknown" for issue in check_document(document).issues)


def test_limits_commands_extensions_and_graph_depth_in_both_storage_orders():
    document, scene = fixture()
    expected = deepcopy(document)
    with pytest.raises(ArtifactLimitError) as caught:
        set_scene_clip(
            document,
            scene.id,
            "curved",
            replace(scene.clips[0], commands=(PathCommand("move", (0, 0)),) * 1000),
            limits=DocumentLimits(max_nodes=2000),
        )
    assert caught.value.quota == "nodes" and caught.value.maximum == 2000
    assert document == expected
    large = replace(scene.clips[0], extra={"future": [1], "large": list(range(100_001))})
    budget = DocumentLimits(max_nodes=300_000)
    set_scene_clip(document, scene.id, "curved", large, limits=budget)
    for _ in range(2):
        document = document_from_json(document_to_json(document, limits=budget), limits=budget)
    assert len(get_vector_scene(document, scene.id, limits=budget).clips[0].extra["large"]) == 100_001
    path = VectorPath("leaf", ())
    groups = tuple(VectorGroup(f"g{i}", ("leaf" if i == 0 else f"g{i - 1}",)) for i in range(20))
    for ordered in (groups, tuple(reversed(groups))):
        before = DocumentModel()
        with pytest.raises(ArtifactLimitError) as caught:
            set_vector_scene(before, VectorScene("deep", 10, 10, (path,), ordered, ("g19",)), limits=DocumentLimits(max_depth=12))
        assert caught.value.quota == "graph depth" and caught.value.maximum == 12
        assert before == DocumentModel()


def test_removing_all_new_controls_keeps_explicit_scope_version():
    document = DocumentModel()
    scene = VectorScene("pure", 10, 10, groups=(VectorGroup("g", (), opacity=0.25, compositing=IDENTITY),), roots=("g",))
    set_vector_scene(document, scene)
    current = get_vector_scene(document, "pure")
    assert current.scope_version == 1
    set_scene_group(document, "pure", "g", replace(current.groups[0], compositing=None))
    current = get_vector_scene(document, "pure")
    assert current.scope_version == 1 and current.groups[0].compositing is None
    assert current.groups[0].opacity == 0.25
    assert any(issue.code == "graphics-scope-unknown" for issue in check_document(document).issues)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert get_vector_scene(document, "pure").scope_version == 1


def test_removing_bound_model_object_and_invalid_edits_leave_source_intact():
    document, scene = fixture()
    before = deepcopy(document)
    with pytest.raises(ValueError):
        remove_node(document, next(iter_elements(document, Table)))
    assert document == before
    for operation in (
        lambda: set_scene_clip(document, scene.id, "curved", replace(scene.clips[0], id="other")),
        lambda: set_scene_group(document, scene.id, "mixed", replace(scene.groups[0], id="other")),
        lambda: set_vector_scene(document, replace(scene, extra=[])),
        lambda: set_scene_clip(document, scene.id, "curved", replace(scene.clips[0], extra={"id": "shadow"})),
    ):
        with pytest.raises(ValueError):
            operation()
        assert document == before
