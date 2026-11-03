"""Mixed scopes are declarations; hidden text remains editable through two JSON cycles."""

from dataclasses import replace

from opendoc_model import (
    Anchor,
    DocumentModel,
    GroupCompositing,
    Paragraph,
    PathCommand,
    SceneOccurrence,
    Section,
    TextRun,
    VectorClip,
    VectorGroup,
    VectorScene,
    document_from_json,
    document_to_json,
    get_vector_scene,
    set_anchor,
    set_scene_clip,
    set_scene_group,
    set_vector_scene,
)


def main():
    run = TextRun("Visible and hidden text 😀")
    set_anchor(run, Anchor("text"))
    document = DocumentModel(sections=[Section(blocks=[Paragraph([run])])])
    clip = VectorClip(
        "clip", (PathCommand("move", (0, 0)), PathCommand("cubic", (10, 0, 10, 20, 0, 20)), PathCommand("close")), "evenodd"
    )
    occurrence = SceneOccurrence("paint-text", "text", compositing=GroupCompositing(1, False, False, "normal"))
    group = VectorGroup("group", ("paint-text",), clip_id="clip", compositing=GroupCompositing(0.5, True, False, "normal"))
    set_vector_scene(
        document, VectorScene("scene", 200, 100, groups=(group,), roots=("group",), clips=(clip,), occurrences=(occurrence,))
    )
    restored = document
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
    assert restored == document
    set_scene_clip(document, "scene", "clip", None)
    scene = get_vector_scene(document, "scene")
    set_scene_group(document, "scene", "group", replace(scene.groups[0], compositing=GroupCompositing(opacity=None)))
    assert get_vector_scene(document, "scene").scope_version == 1
    assert run.text == "Visible and hidden text 😀"
    print("Graphics scopes: clip, group opacity, retained text and two JSON cycles verified")


if __name__ == "__main__":
    main()
