"""Malformed input errors identify the field before model construction."""

import copy
import json
import re
from pathlib import Path

import pytest

from opendoc_model import DocumentModel, document_from_dict, document_from_json, document_to_dict, document_to_json, save_document

FIXTURES = Path(__file__).parent / "fixtures/compatibility"


def _payload():
    return json.loads((FIXTURES / "document-v2.json").read_text(encoding="utf-8"))


def _replace(payload, path, value):
    node = payload
    for part in path[:-1]:
        node = node[part]
    if value is _MISSING:
        del node[path[-1]]
    else:
        node[path[-1]] = value


_MISSING = object()
_PARAGRAPH = ["document", "sections", 0, "blocks", 0, "rows", 0, "cells", 0, "blocks", 0]
_PARAGRAPH_PATH = "$.document.sections[0].blocks[0].rows[0].cells[0].blocks[0]"


@pytest.mark.parametrize("value", [None, [], 1, "text", True])
def test_root_must_be_json_object(value):
    with pytest.raises(ValueError, match=r"\$: expected an object"):
        document_from_dict(value)


@pytest.mark.parametrize("field", ["version", "property_schema_version"])
@pytest.mark.parametrize("value", [True, False, 1.0, 2.0, "1", [], {}, None])
def test_schema_versions_are_integers_not_coercible_values(field, value):
    payload = _payload()
    node = payload if field == "version" else payload["document"]
    node[field] = value
    with pytest.raises(ValueError, match=f"unsupported .*version: {re.escape(repr(value))}"):
        document_from_dict(payload)


@pytest.mark.parametrize(
    ("path", "value", "error_path"),
    [
        (["document"], [], "$.document"),
        (["document"], _MISSING, "$.document"),
        (["document", "sections"], {}, "$.document.sections"),
        (["document", "sections", 0], None, "$.document.sections[0]"),
        (["document", "sections", 0, "even_page_headers"], {}, "$.document.sections[0].even_page_headers"),
        (["document", "styles"], [], "$.document.styles"),
        (["document", "styles", "accent"], [], "$.document.styles['accent']"),
        (["document", "styles", "accent", "bold"], 1, "$.document.styles['accent'].bold"),
        (["document", "styles", "accent", "font_size_pt"], "large", "$.document.styles['accent'].font_size_pt"),
        (["document", "styles", "accent", "font_size_pt"], 10**1000, "$.document.styles['accent'].font_size_pt"),
        (["document", "styles", "accent", "color"], {"space": "srgb"}, "$.document.styles['accent'].color.components"),
        (["document", "styles", "accent", "color", "components"], [0, 1], "$.document.styles['accent'].color.components"),
        (["document", "styles", "accent", "color", "components"], [0, 1, 2], "$.document.styles['accent'].color.components[2]"),
        (["document", "styles", "accent", "color", "blend_mode"], "  ", "$.document.styles['accent'].color.blend_mode"),
        (["document", "metadata"], None, "$.document.metadata"),
        (["document", "resources"], [], "$.document.resources"),
        (["document", "resources", "preview", "id"], "other", "$.document.resources['preview'].id"),
        (["document", "resources", "preview", "id"], _MISSING, "$.document.resources['preview'].id"),
        (["document", "resources", "preview", "media_type"], _MISSING, "$.document.resources['preview'].media_type"),
        (["document", "resources", "preview", "kind"], [], "$.document.resources['preview'].kind"),
        (["document", "resources", "preview", "data_base64"], "%%%", "$.document.resources['preview'].data_base64"),
        (["document", "resources", "preview", "data_base64"], "я", "$.document.resources['preview'].data_base64"),
        (["document", "resources", "preview", "data_base64"], [], "$.document.resources['preview'].data_base64"),
        (["document", "resources", "preview", "data_base64"], None, "$.document.resources['preview']"),
        (["document", "resources", "external", "source"], 3, "$.document.resources['external'].source"),
        (["document", "mode"], "unknown", "$.document.mode"),
        (["document", "package"], [], "$.document.package"),
        (["document", "package", "parts", "/main", "name"], "/other", "$.document.package.parts['/main'].name"),
        (["document", "package", "parts", "/main", "data_base64"], _MISSING, "$.document.package.parts['/main'].data_base64"),
        (["document", "package", "relationships", 0, "external"], "false", "$.document.package.relationships[0].external"),
        (["document", "package", "relationships", 0, "target"], _MISSING, "$.document.package.relationships[0].target"),
        ([*_PARAGRAPH, "content"], {}, _PARAGRAPH_PATH + ".content"),
        ([*_PARAGRAPH, "type"], "unknown", _PARAGRAPH_PATH + ".type"),
        ([*_PARAGRAPH, "content", 0, "type"], "table", _PARAGRAPH_PATH + ".content[0].type"),
        ([*_PARAGRAPH, "content", 0, "text"], 7, _PARAGRAPH_PATH + ".content[0].text"),
        ([*_PARAGRAPH, "content", 0, "style"], None, _PARAGRAPH_PATH + ".content[0].style"),
        ([*_PARAGRAPH, "content", 1, "format"], _MISSING, _PARAGRAPH_PATH + ".content[1].format"),
        ([*_PARAGRAPH, "provenance", "events", 0, "operation"], _MISSING, _PARAGRAPH_PATH + ".provenance.events[0].operation"),
        ([*_PARAGRAPH, "visual_surrogate", "fidelity"], True, _PARAGRAPH_PATH + ".visual_surrogate.fidelity"),
        ([*_PARAGRAPH, "visual_surrogate", "reason"], "", _PARAGRAPH_PATH + ".visual_surrogate.reason"),
        ([*_PARAGRAPH, "properties"], [], _PARAGRAPH_PATH + ".properties"),
    ],
)
def test_malformed_fields_have_their_location(path, value, error_path):
    payload = _payload()
    _replace(payload, path, value)
    before = copy.deepcopy(payload)
    with pytest.raises(ValueError, match=re.escape(error_path)):
        document_from_dict(payload)
    if value is not _MISSING:
        assert payload == before


@pytest.mark.parametrize("field", ["box", "crop"])
def test_geometry_does_not_forward_unknown_constructor_arguments(field):
    payload = _payload()
    image = payload["document"]["sections"][0]["even_page_headers"][0]
    image[field]["unknown"] = 3
    with pytest.raises(ValueError, match=rf"{field}\.unknown: unsupported field"):
        document_from_dict(payload)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), (1, 2), {1: "key"}, b"bytes", object()])
def test_extensions_accept_only_json_values_on_read_and_write(value):
    payload = _payload()
    payload["document"]["metadata"]["custom"] = value
    with pytest.raises(ValueError, match=r"metadata.*custom"):
        document_from_dict(payload)
    model = DocumentModel(metadata={"custom": value})
    for serialize in (document_to_dict, document_to_json):
        with pytest.raises(ValueError, match=r"metadata.*custom"):
            serialize(model)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e400"])
def test_nonfinite_json_numbers_are_rejected_at_the_field(literal):
    payload = '{"format":"opendoc.document","version":2,"document":{"metadata":{"custom":' + literal + "}}}"
    with pytest.raises(ValueError, match=r"metadata.*custom.*number must be finite"):
        document_from_json(payload)


def test_cyclic_extension_has_a_value_error_not_a_recursion_error():
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        document_to_dict(DocumentModel(metadata=cyclic))


def test_failed_json_validation_does_not_replace_previous_file(tmp_path):
    path = tmp_path / "document.json"
    path.write_bytes(b"previous document")
    with pytest.raises(ValueError, match="finite"):
        save_document(DocumentModel(metadata={"invalid": float("nan")}), path)
    assert path.read_bytes() == b"previous document"
    assert list(tmp_path.glob("*.partial")) == []


def test_valid_extensions_are_preserved_without_changing_input():
    payload = _payload()
    payload["document"]["metadata"]["custom"]["extra"] = [False, 0, "", {}, [], None]
    before = copy.deepcopy(payload)
    document = document_from_dict(payload)
    assert payload == before
    assert document.metadata == payload["document"]["metadata"]
    assert document_from_json(document_to_json(document)).metadata == document.metadata


@pytest.mark.parametrize("value", [None, 1, [], {}])
def test_json_api_rejects_wrong_input_types(value):
    with pytest.raises(ValueError, match="JSON input must be"):
        document_from_json(value)
