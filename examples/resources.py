"""Build a portable document and manage its resources through the public API."""

from pathlib import Path
from tempfile import TemporaryDirectory

from opendoc_model import (
    DocumentModel,
    Image,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    VisualSurrogate,
    add_resource,
    embed_resources,
    find_duplicate_resources,
    find_resource_uses,
    load_document,
    remove_resource,
    replace_resource,
    save_document,
)

workspace = Path(".opendoc")
workspace.mkdir(exist_ok=True)
with TemporaryDirectory(prefix="resource-example-", dir=workspace) as temporary:
    directory = Path(temporary).resolve()
    (directory / "preview.bin").write_bytes(b"preview")
    document = DocumentModel()
    identifier = add_resource(document, Resource("preview", ResourceKind.RASTER_IMAGE, "image/png", source="preview.bin"))
    paragraph = Paragraph(
        [Image(identifier, "Preview", properties={"fallback_resource_id": identifier})],
        visual_surrogate=VisualSurrogate(identifier, "preview"),
    )
    document.sections = [Section(blocks=[paragraph])]
    assert len(find_resource_uses(document, identifier)) == 3
    portable = embed_resources(document, base_dir=directory)
    assert portable.resources[identifier].data == b"preview"
    assert document.resources[identifier].data is None
    copy_id = add_resource(portable, portable.resources[identifier], conflicts="rename")
    assert copy_id == "preview~2"
    assert find_duplicate_resources(portable) == (("preview", "preview~2"),)
    remove_resource(portable, identifier, replacement_id=copy_id)
    assert len(find_resource_uses(portable, copy_id)) == 3
    replace_resource(portable, copy_id, Resource("replacement", ResourceKind.RASTER_IMAGE, "image/png", b"updated"))
    assert portable.validate() == []
    assert load_document(save_document(portable, directory / "document.json")) == portable
print("OpenDoc Model resources example: OK")
