"""Resolve inherited styles and edit typed properties without an application."""

from opendoc_model import (
    DocumentModel,
    Length,
    Paragraph,
    Section,
    TextRun,
    TextStyle,
    document_from_json,
    document_to_json,
    effective_text_style,
    resolve_style,
)

document = DocumentModel(
    styles={
        "base": TextStyle(
            font_family="Serif", font_size=Length(12), bold=True, properties={"left_indent_pt": 10, "custom": {"tags": ["draft"]}}
        ),
        "body": TextStyle(bold=False, properties={"base_style_id": "base"}),
    }
)
paragraph = Paragraph([TextRun("Independent styles", TextStyle(italic=True))], style_id="body")
paragraph.properties.set_typed("left_indent_pt", "0")
document.sections = [Section(blocks=[paragraph])]
assert paragraph.properties.get_typed("left_indent_pt") == 0.0
style = effective_text_style(document, paragraph, paragraph.content[0])
assert style.bold is False and style.italic is True
assert style.font_family == "Serif" and style.font_size.pt == 12
assert style.properties["left_indent_pt"] == 0.0
style.properties["custom"]["tags"].append("resolved")
assert document.styles["base"].properties["custom"]["tags"] == ["draft"]
restored = document_from_json(document_to_json(document))
assert effective_text_style(restored, restored.sections[0].blocks[0]) == effective_text_style(document, paragraph)
assert resolve_style(restored, "body").bold is False
try:
    paragraph.properties.set_typed("numbering_level", "1.5")
except ValueError:
    pass
else:
    raise AssertionError("Fractional numbering level must be rejected")
assert "numbering_level" not in paragraph.properties
assert document.validate() == []
