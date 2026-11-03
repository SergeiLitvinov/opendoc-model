"""Existing color API: explicit auto, inheritance, JSON and located loss."""

from opendoc_model import (
    DocumentModel,
    Paragraph,
    QualityPolicy,
    Section,
    TextRun,
    TextStyle,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    effective_text_style,
)
from opendoc_model.color import color_to_css

paragraph = Paragraph([TextRun("Heading", TextStyle(color="auto"))], style_id="heading")
document = DocumentModel(styles={"heading": TextStyle(color="#4F81BD")}, sections=[Section(blocks=[paragraph])])
assert effective_text_style(document, paragraph, paragraph.content[0]).color == "auto"
assert color_to_css("auto") is None
restored = document
for _ in range(2):
    restored = document_from_json(document_to_json(restored))
assert compare_documents(document, restored).success
changed = clone_model(document)
changed_paragraph = changed.sections[0].blocks[0]
changed_paragraph.content[0].style.color = None
assert effective_text_style(changed, changed_paragraph, changed_paragraph.content[0]).color == "#4F81BD"
result = compare_documents(document, changed, policies=[QualityPolicy(0)])
assert not result.success
assert any(issue.code == "text-color-loss" and issue.location for issue in result.issues)
print("Text colors: auto, inheritance, two JSON cycles and located loss OK")
