"""Signed source viewport declarations, independent of native units and pixels."""

from opendoc_model import (
    DocumentModel,
    Image,
    ImageCrop,
    ImageSourceRect,
    Resource,
    ResourceKind,
    Section,
    document_from_json,
    document_to_json,
    get_image_source_rect,
    set_image_source_rect,
)

image = Image("picture", crop=ImageCrop(0.1, 0.2, 0.3, 0.1))
document = DocumentModel(
    sections=[Section(blocks=[image])],
    resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/own", b"own opaque bytes")},
)
legacy = get_image_source_rect(image)
assert legacy == ImageSourceRect(0.1, 0.2, 0.7, 0.9)
set_image_source_rect(image, legacy)
assert image.crop is None
viewport = ImageSourceRect(-0.13333, 0.26667, 0.86667, 0.86667, extra={"own": [1]})
set_image_source_rect(image, viewport)
for _ in range(2):
    document = document_from_json(document_to_json(document))
    image = document.sections[0].blocks[0]
    assert get_image_source_rect(image) == viewport
set_image_source_rect(image, None)
assert image.crop is None and get_image_source_rect(image) is None
print("Image source rectangles: signed coordinates, crop migration, independent JSON and removal OK")
