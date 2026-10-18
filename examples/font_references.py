"""Own opaque FONT programs with equal family names remain explicitly distinct."""

from opendoc_model import (
    DocumentModel,
    FontReference,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
    document_from_json,
    document_to_json,
    effective_text_style,
    get_font_reference,
    set_font_reference,
)


def main():
    base = TextStyle(font_family="OwnFamily")
    set_font_reference(base, FontReference("font-a"))
    direct = TextStyle(font_family="OwnFamily")
    set_font_reference(direct, FontReference("font-b", 0))
    paragraph = Paragraph([TextRun("A"), TextRun("B", direct)], style_id="body")
    document = DocumentModel(
        styles={"body": base},
        sections=[Section(blocks=[paragraph])],
        resources={
            name: Resource(name, ResourceKind.FONT, "font/ttf", data=payload)
            for name, payload in (("font-a", b"own opaque A"), ("font-b", b"own opaque B"))
        },
    )
    restored = document
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
    assert restored == document
    assert get_font_reference(effective_text_style(document, paragraph, paragraph.content[0])) == FontReference("font-a")
    assert get_font_reference(effective_text_style(document, paragraph, paragraph.content[1])) == FontReference("font-b", 0)
    set_font_reference(direct, None)
    assert get_font_reference(effective_text_style(document, paragraph, paragraph.content[1])) == FontReference("font-a")
    print("Font references: distinct programs, inheritance, deletion and two JSON cycles verified")


if __name__ == "__main__":
    main()
