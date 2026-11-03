"""Create, persist and compose document-local links without a format importer."""

from opendoc_model import (
    Anchor,
    DocumentModel,
    InternalLink,
    Paragraph,
    Section,
    TextRun,
    compare_documents,
    document_from_json,
    document_to_json,
    extract_document,
    get_internal_link,
    iter_internal_links,
    merge_documents,
    resolve_anchor,
    set_anchor,
    set_internal_link,
)

target = Paragraph([TextRun("Chapter")])
set_anchor(target, Anchor("chapter"))
run = TextRun("Read the chapter")
set_internal_link(run, InternalLink("chapter"))
document = DocumentModel(sections=[Section(blocks=[Paragraph([run]), target])])
restored = document_from_json(document_to_json(document))
assert resolve_anchor(restored, "chapter").node is restored.sections[0].blocks[1]
selected = extract_document(restored, next(iter_internal_links(restored)))
assert selected.validate() == []
assert resolve_anchor(selected, "chapter") is not None
merged = merge_documents([document, restored], conflicts="rename")
assert merged.id_maps[1].anchors == {"chapter": "chapter~2"}
assert [get_internal_link(item.node).target_id for item in iter_internal_links(merged.document)] == ["chapter", "chapter~2"]
assert compare_documents(document, restored).lossless
print("OpenDoc Model internal references example: OK")
