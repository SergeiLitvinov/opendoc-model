"""Source viewports are model declarations, independent of formats and renderers."""

import json
from copy import deepcopy

import pytest

from opendoc_model import (
    IMAGE_SOURCE_RECT_PROPERTY,
    ArtifactLimitError,
    Box,
    DocumentLimits,
    DocumentModel,
    Image,
    ImageCrop,
    ImageSourceRect,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    check_document,
    clone_model,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_image_source_rect,
    inspect_document_model,
    iter_elements,
    merge_documents,
    set_image_source_rect,
)


def owner():
    image = Image("picture", box=Box(10, 20, 90, 135), properties={"own": {"values": [1]}})
    return DocumentModel(
        sections=[Section(blocks=[image])],
        resources={"picture": Resource("picture", ResourceKind.RASTER_IMAGE, "image/own", b"own opaque image bytes")},
    ), image


def rectangle():
    return ImageSourceRect(-0.13333, 0.26667, 0.86667, 0.86667, extra={"future": {"values": [2]}})


def test_signed_outside_and_unknown_fields_survive_standalone_and_document_json_twice():
    document, image = owner()
    value = rectangle()
    set_image_source_rect(image, value)
    expected = deepcopy(value)
    value.extra["future"]["values"].append(999)
    for _ in range(2):
        raw = get_image_source_rect(image).to_dict()
        assert ImageSourceRect.from_dict(json.loads(json.dumps(raw))) == expected
        document = document_from_json(document_to_json(document))
        image = document.sections[0].blocks[0]
        assert get_image_source_rect(image) == expected and image.crop is None
        assert image.box == Box(10, 20, 90, 135)
        assert image.properties["own"] == {"values": [1]}
    independent = get_image_source_rect(image)
    independent.extra["future"]["values"].append(3)
    assert get_image_source_rect(image) == expected
    raw["future"]["values"].append(4)
    assert get_image_source_rect(image) == expected


@pytest.mark.parametrize(
    "coordinates",
    [(-1, -2, 3, 4), (0, 0, 1, 1), (1, 1, 2, 2), (-2, -2, -1, -1), (0, 0, 1e-300, 1e-300)],
)
def test_rectangles_can_be_inside_outside_or_disjoint_without_pixel_extrapolation(coordinates):
    document, image = owner()
    set_image_source_rect(image, ImageSourceRect(*coordinates))
    assert document.validate() == []
    assert get_image_source_rect(image) == ImageSourceRect(*coordinates)


@pytest.mark.parametrize("field", ["left", "top", "right", "bottom"])
@pytest.mark.parametrize(
    "bad", [True, "0.1", None, float("nan"), float("inf"), -float("inf"), pytest.param(10**400, id="overflow")]
)
def test_nonfinite_nonnumeric_and_bool_coordinates_are_located_and_refused(field, bad):
    raw = dict(left=0.0, top=0.0, right=1.0, bottom=1.0)
    raw[field] = bad
    with pytest.raises(ValueError, match=field):
        ImageSourceRect.from_dict(raw)
    with pytest.raises(ValueError, match=field):
        ImageSourceRect(**raw)


@pytest.mark.parametrize("coordinates", [(0, 0, 0, 1), (1, 0, 0, 1), (0, 1, 1, 1), (0, 2, 1, 1)])
def test_degenerate_or_reversed_rectangles_are_refused(coordinates):
    with pytest.raises(ValueError, match="right > left"):
        ImageSourceRect(*coordinates)


def test_legacy_fallback_is_read_only_and_setter_explicitly_migrates_or_removes():
    document, image = owner()
    image.crop = ImageCrop(0.1, 0.2, 0.3, 0.1)
    before = document_to_json(document)
    assert inspect_document_model(document).metrics["cropped_images"] == 1
    old = get_image_source_rect(image)
    assert old == ImageSourceRect(0.1, 0.2, 0.7, 0.9)
    assert document_to_json(document) == before and IMAGE_SOURCE_RECT_PROPERTY not in image.properties
    set_image_source_rect(image, old)
    assert image.crop is None and get_image_source_rect(image) == old
    assert inspect_document_model(document).metrics["cropped_images"] == 1
    set_image_source_rect(image, ImageSourceRect(-1, 0, 1, 1))
    assert get_image_source_rect(image).left == -1
    set_image_source_rect(image, None)
    assert get_image_source_rect(image) is None and IMAGE_SOURCE_RECT_PROPERTY not in image.properties
    image.crop = ImageCrop(0.1, 0, 0, 0)
    set_image_source_rect(image, None)
    assert image.crop is None and image.properties["own"] == {"values": [1]}
    image.crop = ImageCrop(-0.1, 0, 0, 0)
    assert not check_document(document).success
    with pytest.raises(ValueError, match="crop.left"):
        get_image_source_rect(image)


def test_both_declarations_conflict_even_if_equivalent_and_setter_can_resolve_explicitly():
    document, image = owner()
    set_image_source_rect(image, ImageSourceRect(0, 0, 1, 1))
    image.crop = ImageCrop()
    with pytest.raises(ValueError, match="mutually exclusive"):
        get_image_source_rect(image)
    result = check_document(document)
    assert not result.success
    assert any("sections[0].blocks[0].crop" in issue.location for issue in result.issues)
    with pytest.raises(ValueError, match="mutually exclusive"):
        document_to_json(document)
    set_image_source_rect(image, rectangle())
    assert image.crop is None and document.validate() == []


@pytest.mark.parametrize("mode", ["version", "coordinate", "missing", "conflict", "extra"])
def test_dict_document_decoder_checks_new_carrier_with_node_path(mode):
    document, image = owner()
    set_image_source_rect(image, rectangle())
    raw = document_to_dict(document)
    data = raw["document"]["sections"][0]["blocks"][0]
    carrier = data["properties"][IMAGE_SOURCE_RECT_PROPERTY]
    if mode == "version":
        carrier["version"] = True
    elif mode == "coordinate":
        carrier["left"] = "bad"
    elif mode == "missing":
        del carrier["right"]
    elif mode == "extra":
        carrier["extra"] = {}
    else:
        data["crop"] = dict(left=0, top=0, right=0, bottom=0)
    before = deepcopy(raw)
    with pytest.raises(ValueError, match=r"sections\[0\].blocks\[0\]"):
        document_from_dict(raw)
    assert raw == before


@pytest.mark.parametrize("opaque", [None, "opaque", {"format": "future", "values": [1]}])
def test_opaque_carrier_is_not_interpreted_or_overwritten(opaque):
    document, image = owner()
    image.properties[IMAGE_SOURCE_RECT_PROPERTY] = opaque
    before = deepcopy(image)
    assert get_image_source_rect(image) is None
    assert document.validate() == []
    for value in (rectangle(), None):
        with pytest.raises(ValueError, match="opaque"):
            set_image_source_rect(image, value)
        assert image == before


def test_setter_preserves_unknown_fields_and_fails_atomically_for_quota_or_reserved_extra():
    _, image = owner()
    set_image_source_rect(image, rectangle())
    set_image_source_rect(image, ImageSourceRect(0, -1, 2, 1, extra={"another": [3]}))
    assert get_image_source_rect(image).extra == {"future": {"values": [2]}, "another": [3]}
    before = deepcopy(image)
    properties = image.properties
    for value, budget in (
        (ImageSourceRect(0, 0, 1, 1, extra={"version": 1}), None),
        (rectangle(), DocumentLimits(max_nodes=10)),
        (rectangle(), DocumentLimits(max_bytes=1)),
        (rectangle(), DocumentLimits(max_depth=1)),
    ):
        with pytest.raises((ValueError, ArtifactLimitError)):
            set_image_source_rect(image, value, limits=budget)
        assert image == before and image.properties is properties


def test_large_unknown_data_respects_custom_budget_without_constructor_default_override():
    value = ImageSourceRect(0, 0, 1, 1, extra={"future": [None] * 100_001})
    _, image = owner()
    with pytest.raises(ArtifactLimitError):
        set_image_source_rect(image, value)
    assert get_image_source_rect(image) is None
    budget = DocumentLimits(max_nodes=500_000)
    set_image_source_rect(image, value, limits=budget)
    for _ in range(2):
        raw = get_image_source_rect(image, limits=budget).to_dict(limits=budget)
        assert len(ImageSourceRect.from_dict(raw, limits=budget).extra["future"]) == 100_001


def test_composition_and_json_detect_viewport_edits_without_inventing_native_freshness():
    document, image = owner()
    set_image_source_rect(image, rectangle())
    baseline = document_to_json(document)
    copied = clone_model(document)
    set_image_source_rect(copied.sections[0].blocks[0], ImageSourceRect(-1, 0, 1, 1))
    assert document_to_json(document) == baseline and document_to_json(copied) != baseline
    merged = merge_documents([document, copied], conflicts="rename").document
    location = next(item for item in iter_elements(merged, Image) if item.node is merged.sections[1].blocks[0])
    selected = extract_document(merged, location)
    for _ in range(2):
        selected = document_from_json(document_to_json(selected))
    assert get_image_source_rect(selected.sections[0].blocks[0]).left == -1
    assert merged.sections[0].blocks[0].properties is not merged.sections[1].blocks[0].properties


def test_legacy_wire_stays_sparse_and_core_constructor_is_unchanged():
    document, image = owner()
    before = document_to_json(document)
    assert get_image_source_rect(image) is None
    assert document_to_json(document) == before and IMAGE_SOURCE_RECT_PROPERTY not in before
    assert Image("id", "alt", None, {}, ImageCrop()).crop == ImageCrop()
    assert Paragraph([image]).content[0] is image
