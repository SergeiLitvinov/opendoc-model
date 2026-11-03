"""Resource operations preserve identities, links, quotas and explicit I/O."""

from itertools import repeat
from pathlib import Path

import pytest

from opendoc_model import (
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Formula,
    FormulaFormat,
    Image,
    PackageGraph,
    PackagePart,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VisualSurrogate,
    add_resource,
    document_from_json,
    document_to_json,
    embed_resources,
    find_duplicate_resources,
    find_resource_uses,
    remove_resource,
    replace_resource,
)


def _resource(identifier, data=b"data", source=None):
    return Resource(
        identifier,
        ResourceKind.RASTER_IMAGE,
        "image/png",
        data=data,
        source=source,
        properties={"custom": {"tags": [1]}},
        provenance=Provenance("native", source_path="origin"),
    )


def _document():
    image = Image("old", properties={"fallback_resource_id": "old"}, visual_surrogate=VisualSurrogate("old", "preview"))
    run = TextRun("text", properties={"resource_id": "old", "custom_id": "old"}, visual_surrogate=image.visual_surrogate)
    formula = Formula("x", FormulaFormat.LATEX, visual_surrogate=image.visual_surrogate)
    paragraph = Paragraph([image, run, formula], visual_surrogate=image.visual_surrogate)
    table = Table([TableRow([TableCell([paragraph])])], visual_surrogate=image.visual_surrogate)
    return DocumentModel(sections=[Section(blocks=[table])], resources={"old": _resource("old"), "new": _resource("new", b"new")})


def test_add_clone_explicit_conflict_policies_and_actual_id():
    document = DocumentModel()
    incoming = _resource("asset")
    mapping = document.resources
    assert add_resource(document, incoming) == "asset"
    assert document.resources is mapping
    assert document.resources["asset"] == incoming and document.resources["asset"] is not incoming
    incoming.properties["custom"]["tags"].append(2)
    incoming.provenance.events.append(None)
    assert document.resources["asset"].properties["custom"]["tags"] == [1]
    assert document.resources["asset"].provenance.events == []
    before = document_to_json(document)
    with pytest.raises(ValueError, match="duplicate"):
        add_resource(document, _resource("asset"))
    assert document_to_json(document) == before
    assert add_resource(document, _resource("asset~2")) == "asset~2"
    assert add_resource(document, _resource("asset"), conflicts="rename") == "asset~3"
    assert add_resource(document, _resource("asset", b"replacement"), conflicts="replace") == "asset"
    assert document.resources["asset"].data == b"replacement"
    assert list(document.resources) == ["asset", "asset~2", "asset~3"]


def test_replace_definition_preserves_structure_and_all_ids():
    document = _document()
    uses = find_resource_uses(document, "old")
    old = document.resources["old"]
    incoming = _resource("different", b"replacement")
    assert replace_resource(document, "old", incoming) is old
    assert document.resources["old"].id == "old" and incoming.id == "different"
    assert all(reference.owner.node is other.owner.node for reference, other in zip(uses, find_resource_uses(document, "old")))
    assert document.resources["old"].data == b"replacement"
    assert document.validate() == []


def test_all_reference_kinds_and_exact_nested_paths_are_found():
    document = _document()
    uses = find_resource_uses(document, "old")
    base = "sections[0].blocks[0].rows[0].cells[0].blocks[0]"
    assert [(link.path, link.kind) for link in uses] == [
        ("sections[0].blocks[0].visual_surrogate.resource_id", "surrogate"),
        (base + ".visual_surrogate.resource_id", "surrogate"),
        (base + ".content[0].resource_id", "image"),
        (base + ".content[0].properties.fallback_resource_id", "fallback"),
        (base + ".content[0].visual_surrogate.resource_id", "surrogate"),
        (base + ".content[1].properties.resource_id", "text"),
        (base + ".content[1].visual_surrogate.resource_id", "surrogate"),
        (base + ".content[2].visual_surrogate.resource_id", "surrogate"),
    ]
    assert find_resource_uses(document, "new") == ()


@pytest.mark.parametrize("field", SECTION_CONTENT_FIELDS)
def test_remove_redirects_in_every_section_collection_and_shared_objects(field):
    document = _document()
    table = document.sections[0].blocks[0]
    document.sections = [Section(**{field: [table, table]})]
    original_surrogate = table.visual_surrogate
    mapping = document.resources
    old = document.resources["old"]
    with pytest.raises(ValueError, match="used at"):
        remove_resource(document, "old")
    assert remove_resource(document, "old", replacement_id="new") is old
    assert document.resources is mapping
    assert "old" not in document.resources
    assert len(find_resource_uses(document, "new")) == 16
    assert table.visual_surrogate is original_surrogate and original_surrogate.resource_id == "new"
    run = table.rows[0].cells[0].blocks[0].content[1]
    assert run.properties["custom_id"] == "old"
    assert document.validate() == []
    assert document_from_json(document_to_json(document)) == document


def test_unreferenced_removal_returns_original_and_preserves_other_definitions():
    document = _document()
    old = document.resources["new"]
    assert remove_resource(document, "new") is old
    assert list(document.resources) == ["old"]


def test_failed_redirection_restores_values_identities_and_order():
    document = _document()
    long_id = "x" * 200
    document.resources[long_id] = _resource(long_id)
    before = document_to_json(document)
    owners = tuple(link.owner.node for link in find_resource_uses(document, "old"))
    with pytest.raises(ArtifactLimitError):
        remove_resource(document, "old", replacement_id=long_id, limits=DocumentLimits(max_bytes=100))
    assert document_to_json(document) == before
    assert all(link.owner.node is owner for link, owner in zip(find_resource_uses(document, "old"), owners))


@pytest.mark.parametrize("operation", ["add", "replace", "remove"])
def test_invalid_document_is_rejected_before_changes(operation):
    document = _document()
    document.sections[0].blocks[0].rows[0].cells[0].blocks[0].content[0].resource_id = "missing"
    mapping = dict(document.resources)
    with pytest.raises(ValueError, match="missing"):
        if operation == "add":
            add_resource(document, _resource("next"))
        elif operation == "replace":
            replace_resource(document, "old", _resource("next"))
        else:
            remove_resource(document, "new")
    assert document.resources == mapping


def test_add_and_replace_exceeding_total_embedded_quota_leave_original_intact():
    document = DocumentModel(resources={"one": _resource("one", b"123")})
    document.package = PackageGraph("custom", root="/main", parts={"/main": PackagePart("/main", "type", b"12")})
    before = document_to_json(document)
    limits = DocumentLimits(max_embedded_bytes=6)
    with pytest.raises(ArtifactLimitError):
        add_resource(document, _resource("two", b"12"), limits=limits)
    with pytest.raises(ArtifactLimitError):
        replace_resource(document, "one", _resource("one", b"12345"), limits=limits)
    assert document_to_json(document) == before


@pytest.mark.parametrize("identifier", ["", "missing", None, 1, []])
def test_unknown_and_invalid_ids_are_value_errors(identifier):
    document = _document()
    for operation in (find_resource_uses, remove_resource):
        with pytest.raises(ValueError):
            operation(document, identifier)
    with pytest.raises(ValueError):
        replace_resource(document, identifier, _resource("next"))
    with pytest.raises(ValueError):
        remove_resource(document, "old", replacement_id=identifier)


def test_policy_arguments_bad_resources_and_legacy_builder_remain_explicit():
    document = _document()
    with pytest.raises(ValueError):
        add_resource(document, _resource("old"), conflicts="skip")
    with pytest.raises(ValueError):
        add_resource(document, None)
    with pytest.raises(ValueError):
        add_resource(None, _resource("new"))
    with pytest.raises(ValueError):
        remove_resource(document, "old", replacement_id="old")
    with pytest.raises(ValueError):
        find_resource_uses(document, "old", limits=1)
    invalid = _resource("next")
    invalid.data = "bytes"
    with pytest.raises(ValueError):
        add_resource(document, invalid)
    builder = DocumentModel()
    legacy = _resource("legacy")
    assert builder.add_resource(legacy) is None
    assert builder.resources["legacy"] is legacy
    with pytest.raises(ValueError, match="duplicate"):
        builder.add_resource(legacy)


def test_duplicate_bytes_include_empty_and_ignore_media_metadata_and_external_sources(monkeypatch):
    document = DocumentModel(
        resources={
            "a": _resource("a", b"same"),
            "different": _resource("different", b"other"),
            "empty1": _resource("empty1", b""),
            "b": _resource("b", b"same"),
            "empty2": _resource("empty2", b""),
            "external1": _resource("external1", None, "same.bin"),
            "external2": _resource("external2", None, "same.bin"),
        }
    )
    document.resources["b"].media_type = "application/octet-stream"
    document.resources["b"].kind = ResourceKind.ATTACHMENT
    document.resources["b"].properties.clear()
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("No external I/O"))
    assert find_duplicate_resources(document) == (("a", "b"), ("empty1", "empty2"))
    assert find_duplicate_resources(DocumentModel()) == ()


def test_embedding_relative_absolute_unused_and_empty_files_is_independent(tmp_path):
    (tmp_path / "data.bin").write_bytes(b"file")
    (tmp_path / "empty.bin").write_bytes(b"")
    document = DocumentModel(
        resources={
            "relative": _resource("relative", None, "data.bin"),
            "absolute": _resource("absolute", None, str(tmp_path / "data.bin")),
            "empty": _resource("empty", None, "empty.bin"),
            "embedded": _resource("embedded", b"original", "https://invalid.test/never-open"),
        },
        metadata={"custom": {"tags": [1]}},
    )
    before = document_to_json(document)
    embedded = embed_resources(document, base_dir=tmp_path)
    assert {key: value.data for key, value in embedded.resources.items()} == {
        "relative": b"file",
        "absolute": b"file",
        "empty": b"",
        "embedded": b"original",
    }
    assert all(resource.source is None for resource in embedded.resources.values())
    assert embedded.resources["relative"].provenance.source_path == "origin"
    embedded.resources["relative"].properties["custom"]["tags"].append(2)
    embedded.metadata["custom"]["tags"].append(2)
    assert document_to_json(document) == before
    assert document_from_json(document_to_json(embedded)) == embedded
    assert (tmp_path / "data.bin").read_bytes() == b"file"


def test_selection_keeps_unselected_external_and_deduplicates_requested_ids(tmp_path, monkeypatch):
    file = tmp_path / "data.bin"
    file.write_bytes(b"file")
    document = DocumentModel(
        resources={"local": _resource("local", None, str(file)), "remote": _resource("remote", None, "https://invalid.test/a")}
    )
    from opendoc_model import resources

    original = resources._read_local
    calls = []

    def read(path, maximum):
        calls.append(path)
        return original(path, maximum)

    monkeypatch.setattr(resources, "_read_local", read)
    result = embed_resources(document, resource_ids=["local", "local"])
    assert calls == [file]
    assert result.resources["local"].data == b"file"
    assert result.resources["remote"].source == "https://invalid.test/a"
    assert embed_resources(document, resource_ids=[]) == document


@pytest.mark.parametrize(
    "source",
    [
        "http://example/a",
        "https://example/a",
        "file:///tmp/a",
        "data:text/plain,a",
        "//server/share/a",
        "\\\\server\\share\\a",
        "\\\\?\\C:\\a",
        "C:relative",
        "",
    ],
)
def test_disallowed_sources_fail_before_any_file_is_opened(tmp_path, monkeypatch, source):
    document = DocumentModel(
        resources={"first": _resource("first", None, str(tmp_path / "first")), "bad": _resource("bad", None, source)}
    )
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("I/O must not begin"))
    with pytest.raises(ValueError):
        embed_resources(document, base_dir=tmp_path)


@pytest.mark.parametrize("base_dir", [None, "relative", "", 3, "\\\\server\\share", "//server/share"])
def test_relative_paths_require_explicit_absolute_local_base(base_dir):
    document = DocumentModel(resources={"r": _resource("r", None, "file.bin")})
    with pytest.raises(ValueError):
        embed_resources(document, base_dir=base_dir)


def test_parent_components_resolve_against_given_anchor(tmp_path):
    child = tmp_path / "child"
    child.mkdir()
    (tmp_path / "data").write_bytes(b"outside-child")
    document = DocumentModel(resources={"r": _resource("r", None, "../data")})
    assert embed_resources(document, base_dir=child).resources["r"].data == b"outside-child"


@pytest.mark.parametrize("selection", ["r", b"r", 3, ["unknown"], [None]])
def test_invalid_selection(selection):
    document = DocumentModel(resources={"r": _resource("r")})
    with pytest.raises(ValueError):
        embed_resources(document, resource_ids=selection)


def test_infinite_selection_is_bounded_without_io():
    document = DocumentModel(resources={"r": _resource("r")})
    with pytest.raises(ArtifactLimitError, match="resource_ids"):
        embed_resources(document, resource_ids=repeat("r"), limits=DocumentLimits(max_nodes=100))


def test_filesystem_failure_keeps_original_and_nonregular_sources_are_rejected(tmp_path):
    first = tmp_path / "first"
    first.write_bytes(b"first")
    document = DocumentModel(
        resources={
            "first": _resource("first", None, str(first)),
            "missing": _resource("missing", None, str(tmp_path / "missing")),
        }
    )
    before = document_to_json(document)
    with pytest.raises(FileNotFoundError):
        embed_resources(document)
    assert document_to_json(document) == before
    document.resources["missing"].source = str(tmp_path)
    with pytest.raises(ValueError, match="regular file"):
        embed_resources(document)


def test_budgets_exact_boundaries_include_package_and_multiple_files(tmp_path):
    file = tmp_path / "data"
    file.write_bytes(b"1234")
    document = DocumentModel(resources={"r": _resource("r", None, str(file))})
    document.package = PackageGraph("custom", root="/main", parts={"/main": PackagePart("/main", "type", b"12")})
    limits = DocumentLimits(max_embedded_bytes=6)
    assert embed_resources(document, limits=limits).resources["r"].data == b"1234"
    with pytest.raises(ArtifactLimitError):
        embed_resources(document, limits=DocumentLimits(max_embedded_bytes=5))
    document.resources["second"] = _resource("second", None, str(file))
    with pytest.raises(ArtifactLimitError):
        embed_resources(document, limits=limits)
    assert all(resource.data is None for resource in document.resources.values())


def test_per_file_budget_and_read_plus_one_boundary(tmp_path, monkeypatch):
    file = tmp_path / "data"
    file.write_bytes(b"x" * 1000)
    document = DocumentModel(resources={"r": _resource("r", None, str(file))})
    opened = Path.open
    reads = []

    class Reader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def fileno(self):
            return self.stream.fileno()

        def read(self, size):
            reads.append(size)
            return self.stream.read(size)

    monkeypatch.setattr(Path, "open", lambda path, *args, **kwargs: Reader(opened(path, *args, **kwargs)))
    with pytest.raises(ArtifactLimitError):
        embed_resources(document, limits=DocumentLimits(max_bytes=100))
    assert reads == [101]
    assert document.resources["r"].data is None


def test_huge_explicit_quota_does_not_overflow_read_size(tmp_path):
    file = tmp_path / "data"
    file.write_bytes(b"x")
    document = DocumentModel(resources={"r": _resource("r", None, str(file))})
    assert (
        embed_resources(document, limits=DocumentLimits(max_bytes=10**30, max_embedded_bytes=10**30)).resources["r"].data == b"x"
    )


def test_empty_file_can_be_embedded_when_package_uses_entire_budget(tmp_path):
    file = tmp_path / "empty"
    file.write_bytes(b"")
    document = DocumentModel(resources={"r": _resource("r", None, str(file))})
    document.package = PackageGraph("custom", root="/main", parts={"/main": PackagePart("/main", "type", b"12")})
    result = embed_resources(document, limits=DocumentLimits(max_embedded_bytes=2))
    assert result.resources["r"].data == b"" and result.package == document.package
    assert result.package is not document.package


def test_block_reads_span_multiple_chunks_without_changing_bytes(tmp_path):
    file = tmp_path / "large"
    data = b"01234567" * (1024 * 1024 // 8 + 1)
    file.write_bytes(data)
    document = DocumentModel(resources={"r": _resource("r", None, str(file))})
    limits = DocumentLimits(max_bytes=len(data), max_embedded_bytes=len(data))
    assert embed_resources(document, limits=limits).resources["r"].data == data


def test_json_read_and_resource_management_never_load_external_sources(monkeypatch):
    document = _document()
    document.resources["external"] = _resource("external", None, "https://invalid.test/data")
    payload = document_to_json(document)
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: pytest.fail("Unexpected external I/O"))
    restored = document_from_json(payload)
    assert find_resource_uses(restored, "external") == ()
    replace_resource(restored, "external", _resource("other", None, "missing-file"))
    add_resource(restored, _resource("another", None, "missing-file"))
    assert remove_resource(restored, "external").source == "missing-file"
