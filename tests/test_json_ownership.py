"""JSON dictionary boundaries detach references and reject ambiguous object keys."""

from copy import deepcopy

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    FontReference,
    Footnote,
    FootnoteReference,
    InternalLink,
    ListItem,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    get_anchor,
    get_list_item,
    load_document,
    set_anchor,
    set_font_reference,
    set_footnote_reference,
    set_internal_link,
    set_list_item,
)


def _document():
    head = Paragraph([TextRun("First")], style_id="body")
    set_anchor(head, Anchor("head"))
    set_list_item(head, ListItem("items"))
    continuation = Paragraph([TextRun("Continued"), TextRun("note")])
    set_list_item(continuation, ListItem("items", continuation_of="head"))
    set_internal_link(continuation.content[0], InternalLink("head"))
    set_footnote_reference(continuation.content[1], FootnoteReference("note"))
    style = TextStyle(properties={"custom": [1]})
    set_font_reference(style, FontReference("font"))
    return DocumentModel(
        sections=[Section(blocks=[head, continuation])],
        metadata={"custom": [1]},
        styles={"body": style},
        resources={"font": Resource("font", ResourceKind.FONT, "font/own", b"own", properties={"custom": [1]})},
        footnotes=[Footnote("note", blocks=[Paragraph([TextRun("Note")])])],
        footnote_properties={"custom": [1]},
        footnote_extensions={"custom": [1]},
    )


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_json_dictionary_boundary_detaches_nested_semantic_and_unknown_values(direction):
    source = _document()
    payload = document_to_dict(source)
    expected = deepcopy(payload)
    model = source if direction == "encode" else document_from_dict(payload)
    raw = payload["document"]
    raw["metadata"]["custom"].append(2)
    raw["metadata"]["opendoc.footnotes"]["properties"]["custom"].append(2)
    raw["styles"]["body"]["properties"]["custom"].append(2)
    raw["resources"]["font"]["properties"]["custom"].append(2)
    head, continuation = raw["sections"][0]["blocks"]
    head["properties"]["opendoc.anchor"]["id"] = "mutated"
    continuation["properties"]["opendoc.list-item"]["continuation_of"] = "mutated"
    continuation["content"][0]["properties"]["opendoc.internal-link"]["target_id"] = "mutated"
    continuation["content"][1]["properties"]["opendoc.footnote-reference"]["note_id"] = "mutated"
    assert document_to_dict(model) == expected
    assert model.validate() == []
    assert get_anchor(model.sections[0].blocks[0]).id == "head"
    assert get_list_item(model.sections[0].blocks[1]).continuation_of == "head"


def test_model_edits_cannot_change_input_or_previously_encoded_snapshot():
    original = document_to_dict(_document())
    before = deepcopy(original)
    model = document_from_dict(original)
    snapshot = document_to_dict(model)
    model.metadata["custom"].append(2)
    model.styles["body"].properties["custom"].append(2)
    model.resources["font"].properties["custom"].append(2)
    model.footnote_properties["custom"].append(2)
    model.footnote_extensions["custom"].append(2)
    model.sections[0].blocks[0].properties["opendoc.anchor"]["extra"] = [2]
    assert original == snapshot == before
    assert document_from_json(document_to_json(document_from_json(document_to_json(model)))) == model


@pytest.mark.parametrize(
    "text",
    [
        '{"format":"opendoc.document","version":1,"version":2,"document":{}}',
        '{"format":"opendoc.document","version":2,"document":{"metadata":{"a":1,"a":2}}}',
        '{"format":"opendoc.document","version":2,"document":{"metadata":{"a":1,"a":1}}}',
        r'{"format":"opendoc.document","version":2,"document":{"metadata":{"a":1,"\u0061":2}}}',
        '{"format":"opendoc.document","version":2,"document":{"metadata":{"link":{"target_id":"a","target_id":"b"}}}}',
    ],
)
@pytest.mark.parametrize("encoding", ["text", "utf-8", "utf-16", "utf-32"])
def test_duplicate_object_keys_are_refused_instead_of_losing_values(text, encoding, tmp_path):
    value = text if encoding == "text" else text.encode(encoding)
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        document_from_json(value)
    path = tmp_path / "ambiguous.json"
    path.write_bytes(text.encode("utf-8") if encoding == "text" else value)
    with pytest.raises(ValueError, match="duplicate JSON object key"):
        load_document(path)


def test_same_keys_in_distinct_objects_remain_valid_and_custom_limits_are_preserved():
    document = DocumentModel(metadata={"one": {"id": "a"}, "two": {"id": "b"}, "custom": [None] * 100_001})
    limits = DocumentLimits(max_nodes=300_000)
    with pytest.raises(ArtifactLimitError):
        document_to_dict(document)
    payload = document_to_dict(document, limits=limits)
    restored = document_from_dict(payload, limits=limits)
    for _ in range(2):
        restored = document_from_json(document_to_json(restored, limits=limits), limits=limits)
    assert restored == document
    payload["document"]["metadata"]["custom"].append(1)
    assert restored.metadata["custom"][-1] is None
