"""Group blending space stays independent of individual paint colors."""

from opendoc_model import (
    DocumentModel,
    GroupColorSpace,
    GroupCompositing,
    Resource,
    ResourceKind,
    VectorGroup,
    VectorScene,
    document_from_json,
    document_to_json,
    get_scope_color_space,
    set_scope_color_space,
    set_vector_scene,
)


def main():
    document = DocumentModel(
        resources={
            "profile": Resource("profile", ResourceKind.ATTACHMENT, "application/vnd.iccprofile", data=b"own opaque profile"),
        }
    )
    group = VectorGroup("group", (), compositing=GroupCompositing(0.5, True, False, "normal"))
    set_vector_scene(document, VectorScene("scene", 100, 100, groups=(group,), roots=("group",)))
    for space in (GroupColorSpace("rgb"), GroupColorSpace("gray"), GroupColorSpace("icc", "profile"), GroupColorSpace()):
        set_scope_color_space(document, "scene", "group", space)
        restored = document
        for _ in range(2):
            restored = document_from_json(document_to_json(restored))
        assert restored == document
        assert get_scope_color_space(restored, "scene", "group") == space
    set_scope_color_space(document, "scene", "group", None)
    assert get_scope_color_space(document, "scene", "group") is None
    assert "profile" in document.resources
    print("Group color space: RGB/Gray/ICC/unknown, deletion and two JSON cycles verified")


if __name__ == "__main__":
    main()
