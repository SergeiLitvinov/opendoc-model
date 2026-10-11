"""Own two-page declaration: points, fill lines, Unicode ranges and source history."""

from opendoc_model import (
    Anchor,
    Annotation,
    Box,
    ColorValue,
    DocumentModel,
    DocumentPage,
    FormControl,
    IntegrationModel,
    PageGeometry,
    Paint,
    Paragraph,
    PathCommand,
    Provenance,
    ProvenanceEvent,
    Rect2D,
    Section,
    SourceFile,
    SourceMap,
    SourceMapping,
    SourceSpan,
    TextPosition,
    TextRange,
    TextRun,
    VectorPath,
    VectorScene,
    document_from_json,
    document_to_json,
    get_integration,
    get_page_geometry,
    set_anchor,
    set_integration,
    with_page_geometry,
)


def fixture():
    sections, pages, ranges, annotations, forms, scenes, mappings = [], [], [], [], [], [], []
    for index, rotation in enumerate((0, 90)):
        text = "Имя 😀 e\u0301"
        run = TextRun(
            text,
            provenance=Provenance(
                "own-fixed", page=index, object_id=f"text-{index}", events=[ProvenanceEvent("import", "explicit positions")]
            ),
        )
        paragraph = Paragraph(
            [run],
            box=Box(30.125, 50.25, 240.5, 18.75),
            provenance=Provenance("own-fixed", page=index, object_id=f"paragraph-{index}"),
        )
        set_anchor(run, Anchor(f"run-{index}"))
        set_anchor(paragraph, Anchor(f"paragraph-{index}"))
        sections.append(Section(blocks=[paragraph]))
        page = with_page_geometry(
            DocumentPage(f"page-{index}", 600, 800, (f"paragraph-{index}",)),
            PageGeometry(Rect2D(-10, -20, 600, 800), Rect2D(20, 30, 500, 700), rotation, extra={"future": [index]}),
        )
        pages.append(page)
        ranges.append(
            TextRange(f"range-{index}", TextPosition(f"run-{index}", 4, "before"), TextPosition(f"run-{index}", len(text)))
        )
        annotations.append(
            Annotation(f"note-{index}", page.id, "highlight", range_id=f"range-{index}", box=Box(60.25, 50.25, 80.5, 18.75))
        )
        forms.append(FormControl(f"field-{index}", page.id, "text", box=Box(30.125, 80.25, 240.5, 18.75)))
        line = VectorPath(
            f"line-{index}",
            (PathCommand("move", (30.125, 100.5)), PathCommand("line", (270.625, 100.5))),
            stroke=Paint(ColorValue.from_hex("#000000")),
            stroke_width=0.5,
        )
        scenes.append(VectorScene(f"scene-{index}", 600, 800, (line,), roots=(line.id,), node_id=f"paragraph-{index}"))
        mappings.append(
            SourceMapping(
                f"run-{index}", (SourceSpan("source-text", 0, len(text), object_id=f"text-{index}", extra={"page": index}),)
            )
        )
    document = DocumentModel(sections=sections)
    set_integration(
        document,
        IntegrationModel(
            pages=tuple(pages),
            ranges=tuple(ranges),
            annotations=tuple(annotations),
            forms=tuple(forms),
            scenes=tuple(scenes),
            source_map=SourceMap((SourceFile("source-text", "urn:own:fixed-text", size=len(text)),), tuple(mappings)),
        ),
    )
    return document


def main():
    document = fixture()
    restored = document
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
    assert restored == document
    model = get_integration(restored)
    assert len(restored.sections) == len(model.pages) == 2
    assert get_page_geometry(model.pages[1]).rotation == 90
    assert model.scenes[0].paths[0].commands[1].values == (270.625, 100.5)
    assert model.ranges[0].start.offset == 4
    assert restored.sections[0].blocks[0].content[0].provenance.events[0].operation == "import"
    print("Fixed layout: two pages, explicit coordinates, Unicode intervals and provenance survive two JSON cycles")


if __name__ == "__main__":
    main()
