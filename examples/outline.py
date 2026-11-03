"""Inert hierarchical navigation with structural and page destinations."""

from opendoc_model import (
    Anchor,
    DocumentModel,
    DocumentPage,
    IntegrationModel,
    Outline,
    OutlineEntry,
    OutlineTarget,
    Paragraph,
    Point2D,
    Section,
    TextRun,
    document_from_json,
    document_to_json,
    extract_document,
    get_outline,
    iter_elements,
    merge_documents,
    set_anchor,
    set_integration,
    set_outline,
)


def main():
    intro, detail = Paragraph([TextRun("Introduction")]), Paragraph([TextRun("Details")])
    set_anchor(intro, Anchor("intro"))
    set_anchor(detail, Anchor("detail"))
    document = DocumentModel(sections=[Section([intro]), Section([detail])])
    set_integration(document, IntegrationModel(pages=(DocumentPage("page", 600, 800),)))
    outline = Outline(
        (
            OutlineEntry("root", "Introduction", 0, target=OutlineTarget("anchor", "intro")),
            OutlineEntry("child", "Details", 0, "root", OutlineTarget("anchor", "detail")),
            OutlineEntry("page", "Page", 1, "root", OutlineTarget("page", "page", point=Point2D(20, 30), zoom=1.25)),
            OutlineEntry("external", "External", 1, target=OutlineTarget("external", uri="urn:example:document")),
        )
    )
    set_outline(document, outline)
    restored = document_from_json(document_to_json(document))
    assert get_outline(restored) == outline
    extracted = extract_document(restored, next(iter_elements(restored, Paragraph)))
    assert len(extracted.sections) == 2
    assert get_outline(extracted) == outline
    merged = merge_documents([document, restored], conflicts="rename", metadata_conflicts="keep_last")
    assert get_outline(merged.document).entries[1].target.target_id == "detail~2"
    assert get_outline(document) == outline
    print("Outline: hierarchy, explicit destinations, JSON, remapping and extraction OK")


if __name__ == "__main__":
    main()
