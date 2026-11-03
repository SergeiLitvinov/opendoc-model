"""List membership survives JSON and remains independent during composition."""

from opendoc_model import (
    Anchor,
    DocumentModel,
    ListItem,
    Paragraph,
    Section,
    TextRun,
    document_from_json,
    document_to_json,
    iter_list_numbers,
    merge_documents,
    set_anchor,
    set_list_item,
)

paragraphs = [Paragraph([TextRun(text)]) for text in ("First", "Nested", "Second")]
for paragraph, level in zip(paragraphs, (0, 1, 0), strict=True):
    set_list_item(paragraph, ListItem("tasks", level=level))
document = DocumentModel(sections=[Section(blocks=paragraphs)])
assert [item.number for item in iter_list_numbers(document)] == [1, 1, 2]
restored = document_from_json(document_to_json(document))
merged = merge_documents([document, restored], conflicts="rename")
assert merged.id_maps[1].lists == {"tasks": "tasks~2"}
assert [item.number for item in iter_list_numbers(merged.document)] == [1, 1, 2, 1, 1, 2]
head, continuation, outside, empty_parent, child = [
    Paragraph([TextRun(text)] if text else [])
    for text in ("First paragraph", "Same item, second paragraph", "Outside", "", "Nested item")
]
set_anchor(head, Anchor("item-head"))
set_list_item(head, ListItem("multi"))
set_list_item(continuation, ListItem("multi", continuation_of="item-head"))
set_anchor(empty_parent, Anchor("empty-parent"))
set_list_item(empty_parent, ListItem("multi"))
set_list_item(child, ListItem("nested", parent_id="empty-parent"))
bounded = DocumentModel(sections=[Section(blocks=[head, continuation, outside, empty_parent, child])])
for _ in range(2):
    bounded = document_from_json(document_to_json(bounded))
assert [item.number for item in iter_list_numbers(bounded)] == [1, None, 2, 1]
print("Lists: numbering, JSON, boundaries and independent composition OK")
