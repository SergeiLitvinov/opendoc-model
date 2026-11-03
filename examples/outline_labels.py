"""A rich outline caption distinct from its visible body heading."""

from dataclasses import replace

from opendoc_model import (
    Anchor,
    DocumentModel,
    Formula,
    FormulaFormat,
    Outline,
    OutlineEntry,
    OutlineLabel,
    OutlineTarget,
    Paragraph,
    Section,
    TextRun,
    TextStyle,
    document_from_json,
    document_to_json,
    get_outline,
    iter_outline_inlines,
    set_anchor,
    set_outline,
)

heading = Paragraph([TextRun("Long visible heading")])
set_anchor(heading, Anchor("heading"))
model = DocumentModel([Section([heading])])
label = OutlineLabel(
    "Short x²", (TextRun("Short ", TextStyle(bold=True)), Formula("x^2", FormulaFormat.LATEX, fallback_text="x²"))
)
set_outline(model, Outline((OutlineEntry("toc", "Short x²", 0, target=OutlineTarget("anchor", "heading"), label=label),)))
wire = document_to_json(model)
for _ in range(2):
    model = document_from_json(wire)
    assert document_to_json(model) == wire
assert len(list(iter_outline_inlines(model))) == 2
assert model.sections[0].blocks[0].plain_text == "Long visible heading"
entry = get_outline(model).entries[0]
set_outline(model, Outline((replace(entry, title="Plain edit", label=None),)))
assert get_outline(model).entries[0].label is None
assert not model.validate()
