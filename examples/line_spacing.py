"""Own line-spacing declaration, style inheritance and two JSON cycles."""

from opendoc_model import (
    DocumentModel,
    LineSpacing,
    Paragraph,
    QualityPolicy,
    Section,
    TextRun,
    TextStyle,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    resolve_line_spacing,
    set_line_spacing,
)


def main():
    style = TextStyle()
    set_line_spacing(style, LineSpacing("minimum", 14))
    paragraph = Paragraph([TextRun("Own first line\nSecond line")], style_id="body")
    document = DocumentModel(styles={"body": style}, sections=[Section(blocks=[paragraph])])
    assert resolve_line_spacing(paragraph, document=document) == LineSpacing("minimum", 14)
    for rule, value in (("minimum", 14), ("exact", 18), ("relative", 1.5)):
        set_line_spacing(paragraph, LineSpacing(rule, value, extra={"future": [1]}))
        restored = document
        for _ in range(2):
            restored = document_from_json(document_to_json(restored))
        assert restored == document
        assert compare_documents(document, restored).success
    changed = clone_model(document)
    set_line_spacing(changed.sections[0].blocks[0], None)
    result = compare_documents(document, changed, policies=[QualityPolicy(0)])
    assert not result.success and any(issue.code == "line-spacing-loss" for issue in result.issues)
    assert resolve_line_spacing(changed.sections[0].blocks[0], document=changed) == LineSpacing("minimum", 14)
    print("Line spacing: inheritance, edits, two JSON cycles and located loss verified")


if __name__ == "__main__":
    main()
