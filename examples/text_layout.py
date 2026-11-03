"""Placed glyphs retain editable text; invalidation of multiple occurrences is atomic."""

from dataclasses import replace

from opendoc_model import (
    Anchor,
    DocumentModel,
    DocumentPage,
    FontReference,
    IntegrationModel,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TextCluster,
    TextLayout,
    TextPosition,
    TextRange,
    TextRun,
    clone_model,
    document_from_json,
    document_to_json,
    edit_anchored_text,
    get_text_layout,
    invalidate_text_layouts,
    set_anchor,
    set_integration,
    set_text_layout,
)

run = TextRun("fi a\u0301")
set_anchor(run, Anchor("text"))
document = DocumentModel(
    sections=[Section(blocks=[Paragraph([run])])],
    resources={"font": Resource("font", ResourceKind.FONT, "font/own", b"own opaque program")},
)
set_integration(
    document,
    IntegrationModel(
        ranges=(
            TextRange("fi", TextPosition("text", 0), TextPosition("text", 2)),
            TextRange("a", TextPosition("text", 3), TextPosition("text", 4)),
        ),
        pages=(DocumentPage("page", 200, 300),),
    ),
)
layout = TextLayout(
    "paint",
    fonts=(FontReference("font", 0),),
    page_id="page",
    glyphs=((0, 42, 1, 0, 0, 1, 10, 20), (0, 43, 1, 0, 0, 1, 30, 20), (0, 44, 1, 0, 0, 1, 29, 22)),
    clusters=(TextCluster((0,), ("fi",)), TextCluster((1, 2), ("a",))),
    extra={"own": {"retained": [1]}},
)
# The producer explicitly asserts this mapping; the model does not shape these glyphs.
set_text_layout(document, layout, verify=True)
set_text_layout(document, replace(layout, id="stroke"), verify=True)
for _ in range(2):
    document = document_from_json(document_to_json(document))
assert get_text_layout(document, "paint").state == "verified"
changed = edit_anchored_text(document, "text", 0, 2, "ffi")
assert get_text_layout(changed, "paint").state == "stale"
assert get_text_layout(document, "paint").state == "verified"
direct = clone_model(document)
direct.sections[0].blocks[0].content[0].text = "FI a\u0301"
# Both declarations are now stale. Commit their invalidation together; a partial commit must fail.
invalidate_text_layouts(direct, ("paint", "stroke"))
for _ in range(2):
    direct = document_from_json(document_to_json(direct))
assert get_text_layout(direct, "paint").state == get_text_layout(direct, "stroke").state == "stale"
print("Text layout: many-to-many, explicit FONT/face, two JSON cycles and stale edits verified")
