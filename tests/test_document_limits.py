"""Budgets reject bounded input and preserve files on all encoding failures."""

import io
import json
from dataclasses import replace
from pathlib import Path

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    PackageGraph,
    PackagePart,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    load_document,
    save_document,
)
from opendoc_model.storage import _atomic_write_chunks


def _small_payload(metadata=None):
    return {"format": "opendoc.document", "version": 2, "document": {"metadata": metadata or {}}}


@pytest.mark.parametrize("value", [-1, True, 1.5, "100"])
@pytest.mark.parametrize("field", ["max_bytes", "max_depth", "max_nodes", "max_embedded_bytes"])
def test_invalid_budget_configuration_is_not_an_input_quota_failure(field, value):
    with pytest.raises(ValueError) as caught:
        DocumentLimits(**{field: value})
    assert not isinstance(caught.value, ArtifactLimitError)


@pytest.mark.parametrize("value", [0, 129])
def test_depth_configuration_keeps_the_recursive_codec_bounded(value):
    with pytest.raises(ValueError, match="max_depth"):
        DocumentLimits(max_depth=value)


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-32"])
def test_byte_input_exact_size_boundary(encoding):
    value = json.dumps(_small_payload({"text": "Текст"}), ensure_ascii=False).encode(encoding)
    assert document_from_json(value, limits=DocumentLimits(max_bytes=len(value))).metadata == {"text": "Текст"}
    with pytest.raises(ArtifactLimitError, match="bytes"):
        document_from_json(value, limits=DocumentLimits(max_bytes=len(value) - 1))


def test_string_input_limit_counts_utf8_not_characters():
    value = json.dumps(_small_payload({"text": "🙂"}), ensure_ascii=False)
    size = len(value.encode("utf-8"))
    assert document_from_json(value, limits=DocumentLimits(max_bytes=size)).metadata == {"text": "🙂"}
    with pytest.raises(ArtifactLimitError):
        document_from_json(value, limits=DocumentLimits(max_bytes=size - 1))


def test_invalid_unicode_is_reported_at_the_extension_value():
    with pytest.raises(ValueError, match=r"metadata.*custom.*UTF-8"):
        document_to_json(DocumentModel(metadata={"custom": "\ud800"}))


def test_load_reads_only_budget_plus_one_byte(monkeypatch):
    calls = []

    class Source(io.BytesIO):
        def read(self, size=-1):
            calls.append(size)
            return super().read(size)

    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: Source(b"x" * 1000))
    with pytest.raises(ArtifactLimitError):
        load_document("document.json", limits=DocumentLimits(max_bytes=32))
    assert calls == [33]


def test_depth_limit_ignores_quoted_braces_and_escaped_quotes():
    value = json.dumps(_small_payload({"text": '{} [] " quoted \\" []'}))
    assert document_from_json(value, limits=DocumentLimits(max_depth=3)).metadata["text"].startswith("{}")
    nested = json.dumps(_small_payload({"nested": {"more": {}}}))
    with pytest.raises(ArtifactLimitError, match="depth"):
        document_from_json(nested, limits=DocumentLimits(max_depth=3))
    with pytest.raises(ArtifactLimitError, match="depth"):
        document_from_dict(json.loads(nested), limits=DocumentLimits(max_depth=3))


def test_extreme_depth_is_rejected_before_the_json_parser():
    value = "[" * 2000 + "0" + "]" * 2000
    with pytest.raises(ArtifactLimitError, match="depth"):
        document_from_json(value)


def test_node_count_exact_boundary():
    payload = {"format": "opendoc.document", "version": 2, "document": {}}
    assert document_from_dict(payload, limits=DocumentLimits(max_nodes=4)).validate() == []
    with pytest.raises(ArtifactLimitError, match="nodes"):
        document_from_dict(payload, limits=DocumentLimits(max_nodes=3))
    with pytest.raises(ArtifactLimitError, match="nodes"):
        document_from_dict(_small_payload({"items": list(range(100))}), limits=DocumentLimits(max_nodes=10))


def _with_embedded_data():
    model = DocumentModel()
    model.add_resource(Resource("a", ResourceKind.ATTACHMENT, "application/octet-stream", data=b"abc"))
    model.package = PackageGraph(format="custom", root="/main")
    model.package.add_part(PackagePart("/main", "application/octet-stream", b"de"))
    return model


def test_embedded_data_budget_sums_resources_and_package_parts():
    model = _with_embedded_data()
    payload = document_to_dict(model, limits=DocumentLimits(max_embedded_bytes=5))
    assert document_from_dict(payload, limits=DocumentLimits(max_embedded_bytes=5)).package.parts["/main"].data == b"de"
    for encode in (document_to_dict, document_to_json):
        with pytest.raises(ArtifactLimitError, match="embedded bytes"):
            encode(model, limits=DocumentLimits(max_embedded_bytes=4))
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        document_from_dict(payload, limits=DocumentLimits(max_embedded_bytes=4))


def test_rejected_embedded_size_does_not_decode_the_binary_data(monkeypatch):
    import opendoc_model._json_validation as validation

    payload = document_to_dict(_with_embedded_data())

    def unexpected_decode(*args, **kwargs):
        raise AssertionError("must reject before allocating decoded bytes")

    monkeypatch.setattr(validation.base64, "b64decode", unexpected_decode)
    with pytest.raises(ArtifactLimitError, match="embedded bytes"):
        document_from_dict(payload, limits=DocumentLimits(max_embedded_bytes=4))


def test_cycle_in_table_model_is_invalid_structure_not_quota():
    table = Table(rows=[TableRow(cells=[TableCell()])])
    table.rows[0].cells[0].blocks.append(table)
    model = DocumentModel(sections=[Section(blocks=[table])])
    with pytest.raises(ValueError, match="cyclic document model") as caught:
        document_to_json(model)
    assert not isinstance(caught.value, ArtifactLimitError)


def test_shared_subtrees_are_not_cycles():
    paragraph = Paragraph(content=[TextRun("shared")])
    model = DocumentModel(sections=[Section(blocks=[paragraph, paragraph])])
    assert len(document_from_json(document_to_json(model)).sections[0].blocks) == 2


def test_extremely_nested_model_is_bounded_before_recursive_encoding():
    block = Paragraph(content=[TextRun("deep")])
    for _ in range(1000):
        block = Table(rows=[TableRow(cells=[TableCell(blocks=[block])])])
    with pytest.raises(ArtifactLimitError, match="depth"):
        document_to_json(DocumentModel(sections=[Section(blocks=[block])]))


def test_zero_embedded_budget_permits_an_empty_resource():
    model = DocumentModel()
    model.add_resource(Resource("empty", ResourceKind.ATTACHMENT, "application/octet-stream", data=b""))
    limits = DocumentLimits(max_embedded_bytes=0)
    assert document_from_json(document_to_json(model, limits=limits), limits=limits).resources["empty"].data == b""


def test_model_depth_and_node_budgets_apply_before_encoding():
    model = DocumentModel(sections=[Section(blocks=[Paragraph(content=[TextRun("text")])])])
    for limits in (DocumentLimits(max_depth=2), DocumentLimits(max_nodes=2)):
        with pytest.raises(ArtifactLimitError):
            document_to_dict(model, limits=limits)


def test_serialization_exact_byte_boundary_and_file_bytes(tmp_path):
    model = DocumentModel(metadata={"text": "строка\n🙂"})
    output = document_to_json(model, indent=2)
    size = len(output.encode("utf-8"))
    limits = DocumentLimits(max_bytes=size)
    path = save_document(model, tmp_path / "document.json", limits=limits)
    assert path.read_bytes() == output.encode("utf-8")
    assert load_document(path, limits=limits).metadata == model.metadata
    with pytest.raises(ArtifactLimitError):
        document_to_json(model, indent=2, limits=replace(limits, max_bytes=size - 1))
    with pytest.raises(ArtifactLimitError):
        save_document(model, path, limits=replace(limits, max_bytes=size - 1))
    assert path.read_bytes() == output.encode("utf-8")
    assert list(tmp_path.glob("*.partial")) == []


def test_streaming_atomic_write_preserves_encoding_and_cleans_after_generator_failure(tmp_path):
    path = tmp_path / "document.txt"
    _atomic_write_chunks(path, ["first\n", "second"], encoding="utf-16", max_bytes=26)
    assert path.read_bytes() == "first\nsecond".encode("utf-16")

    def failing_chunks():
        yield "partial"
        raise ValueError("failed during encoding")

    previous = path.read_bytes()
    with pytest.raises(ValueError, match="failed during encoding"):
        _atomic_write_chunks(path, failing_chunks(), encoding="utf-8", max_bytes=100)
    assert path.read_bytes() == previous
    assert list(tmp_path.glob("*.partial")) == []
