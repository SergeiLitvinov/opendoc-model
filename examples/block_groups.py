"""A quotation and one compound list item, with independent anchors."""

from opendoc_model import (
    Anchor,
    BlockGroup,
    BlockGroupListOwner,
    DocumentModel,
    ListItem,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    document_from_json,
    document_to_json,
    get_anchor,
    iter_list_numbers,
    set_anchor,
    set_list_item,
)

primary = Paragraph([TextRun("Before")])
set_anchor(primary, Anchor("item-owner"))
set_list_item(primary, ListItem("items"))
group = BlockGroup(
    [primary, Table([TableRow([TableCell([Paragraph([TextRun("Cell")])])])]), Paragraph([TextRun("After")])],
    role="quotation",
    list_owner=BlockGroupListOwner("item-owner"),
)
set_anchor(group, Anchor("quotation"))
following = Paragraph([TextRun("Next item")])
set_list_item(following, ListItem("items"))
model = DocumentModel([Section([group, following])])
wire = document_to_json(model)
for _ in range(2):
    model = document_from_json(wire)
    assert document_to_json(model) == wire
assert [item.number for item in iter_list_numbers(model)] == [1, 2]
assert get_anchor(model.sections[0].blocks[0]) == Anchor("quotation")
assert not model.validate()
