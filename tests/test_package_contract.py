"""Explicit package topology is format-neutral while legacy defaults remain readable."""

import json

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    document_from_json,
    document_to_json,
)


def test_neutral_factory_preserves_arbitrary_bytes_types_sources_and_input_independence():
    parts = [PackagePart("/entry", "application/x-example", b"\x00\xff"), PackagePart("/blob/empty", "custom/type", b"")]
    relationships = [
        PackageRelationship("blob", "org.example.blob", "/entry", "/blob/empty"),
        PackageRelationship("external", "org.example.reference", "/", "urn:opaque:thing", True),
        PackageRelationship("loop", "org.example.loop", "/entry", "/entry"),
    ]
    graph = PackageGraph.create("org.example.bundle", root="/entry", parts=iter(parts), relationships=iter(relationships))
    assert graph.validate() == []
    assert document_from_json(document_to_json(DocumentModel(package=graph))).package == graph
    parts[0].data = b"changed"
    relationships[0].target = "/entry"
    assert graph.parts["/entry"].data == b"\x00\xff" and graph.relationships[0].target == "/blob/empty"
    assert graph.related_part("/entry", "org.example.blob").data == b""
    assert graph.related_part("/", "org.example.reference") is None
    assert PackageGraph.create("custom").root == "/"
    assert PackageGraph("custom").root == "/word/document.xml"


@pytest.mark.parametrize("root", ["/", "/virtual-anchor", "/actual-part", "/unicode/привет"])
def test_roots_can_be_container_virtual_anchor_or_physical_part(root):
    graph = PackageGraph.create(
        "custom",
        root=root,
        parts=[PackagePart("/actual-part", "custom", b"")],
        relationships=[PackageRelationship("part", "custom", root, "/actual-part")],
    )
    assert graph.validate() == []
    assert document_from_json(document_to_json(DocumentModel(package=graph))).package == graph


@pytest.mark.parametrize("root", ["", "relative", "/a/../b", "/a//b", "/a/./b", "/a/", 1, None])
def test_invalid_root_rejected_before_input_iterators_run(root):
    def parts():
        pytest.fail("invalid root must fail first")
        yield

    with pytest.raises(ValueError):
        PackageGraph.create("custom", root=root, parts=parts())


@pytest.mark.parametrize("format", ["", None, 7, True])
def test_factory_requires_explicit_nonempty_format(format):
    with pytest.raises(ValueError):
        PackageGraph.create(format)


def test_relationship_ids_are_scoped_by_source_and_duplicates_fail():
    graph = PackageGraph.create(
        "custom",
        parts=[PackagePart("/part", "custom", b"")],
        relationships=[PackageRelationship("id", "kind", "/", "/part"), PackageRelationship("id", "kind", "/part", "/part")],
    )
    assert len(graph.relationships) == 2
    with pytest.raises(ValueError, match="duplicate"):
        PackageGraph.create("custom", parts=[PackagePart("/part", "custom", b""), PackagePart("/part", "custom", b"")])
    with pytest.raises(ValueError, match="duplicate"):
        PackageGraph.create("custom", relationships=[PackageRelationship("id", "kind", "/", "urn:1", True)] * 2)
    with pytest.raises(ValueError, match="unknown relationship target"):
        PackageGraph.create("custom", relationships=[PackageRelationship("id", "kind", "/", "/missing")])
    with pytest.raises(ValueError, match="unknown relationship source"):
        PackageGraph.create("custom", relationships=[PackageRelationship("id", "kind", "/missing", "urn:1", True)])


def test_factory_bounds_input_generators_nodes_and_combined_bytes():
    consumed = []

    def parts():
        for index in range(1000):
            consumed.append(index)
            yield PackagePart(f"/part{index}", "custom", b"12")

    with pytest.raises(ArtifactLimitError):
        PackageGraph.create("custom", parts=parts(), limits=DocumentLimits(max_embedded_bytes=3))
    assert consumed == [0, 1]
    consumed.clear()
    with pytest.raises(ArtifactLimitError):
        PackageGraph.create("custom", parts=parts(), limits=DocumentLimits(max_nodes=13))
    assert consumed == [0, 1, 2]
    exact = PackageGraph.create(
        "custom", parts=[PackagePart("/part", "custom", b"12")], limits=DocumentLimits(max_nodes=9, max_embedded_bytes=2)
    )
    assert exact.parts["/part"].data == b"12"


@pytest.mark.parametrize("parts,relationships", [(None, ()), ([{}], ()), ((), None), ((), [{}])])
def test_bad_iterables_do_not_become_silent_empty_packages(parts, relationships):
    with pytest.raises(ValueError):
        PackageGraph.create("custom", parts=parts, relationships=relationships)


@pytest.mark.parametrize("version", [1, 2])
def test_independent_json_uses_explicit_format_root_and_preserves_legacy_omission(version):
    payload = {
        "format": "opendoc.document",
        "version": version,
        "document": {
            "package": {
                "format": "org.example.bundle",
                "root": "/anchor",
                "parts": {"/item": {"name": "/item", "media_type": "custom", "data_base64": "AP8="}},
                "relationships": [
                    {"id": "part", "relationship_type": "custom", "source": "/anchor", "target": "/item", "external": False}
                ],
            }
        },
    }
    document = document_from_json(json.dumps(payload))
    assert document.package.root == "/anchor" and document.package.parts["/item"].data == b"\x00\xff"
    assert document_from_json(document_to_json(document)) == document
    payload["document"]["package"] = {"format": "legacy", "parts": {}, "relationships": []}
    legacy = document_from_json(json.dumps(payload))
    assert legacy.package.root == "/word/document.xml"
    assert json.loads(document_to_json(legacy))["document"]["package"]["root"] == "/word/document.xml"


def test_no_uri_or_path_is_opened_and_names_are_literal_logical_identifiers(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("no external IO")

    monkeypatch.setattr("pathlib.Path.stat", fail)
    monkeypatch.setattr("pathlib.Path.open", fail)
    graph = PackageGraph.create(
        "custom",
        parts=[PackagePart("/a%2Fb", "custom", b"data")],
        relationships=[PackageRelationship("remote", "custom", "/", "https://invalid.test/data", True)],
    )
    assert graph.parts["/a%2Fb"].name == "/a%2Fb"
    assert document_from_json(document_to_json(DocumentModel(package=graph))).package == graph
