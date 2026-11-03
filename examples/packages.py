"""Keep an arbitrary opaque package independently of application formats."""

from opendoc_model import DocumentModel, PackageGraph, PackagePart, PackageRelationship, document_from_json, document_to_json

part = PackagePart("/данные%2Fraw", "application/octet-stream", b"\x00\xffopaque")
graph = PackageGraph.create(
    "example.archive",
    parts=[part, PackagePart("/empty", "application/octet-stream", b"")],
    relationships=[
        PackageRelationship("main", "example.main", "/", part.name),
        PackageRelationship("self", "example.self", part.name, part.name),
        PackageRelationship("remote", "example.external", "/", "https://invalid.test/opaque", external=True),
    ],
)
document = DocumentModel(package=graph)
restored = document_from_json(document_to_json(document))
assert restored == document
assert restored.package.root == "/"
assert restored.package.related_part("/", "example.main").data == b"\x00\xffopaque"
part.data = b"changed input"
assert graph.parts[part.name].data == b"\x00\xffopaque"
assert PackageGraph("example.archive").root == "/word/document.xml"
assert graph.validate() == []
print("OpenDoc Model format-neutral package example: OK")
