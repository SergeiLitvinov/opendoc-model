"""Explicit cropped page coordinates, without a native parser or rendering engine."""

from opendoc_model import (
    Annotation,
    Box,
    DocumentModel,
    DocumentPage,
    IntegrationModel,
    PageGeometry,
    Point2D,
    Rect2D,
    document_from_json,
    document_to_json,
    get_integration,
    get_page_geometry,
    page_display_size,
    page_point_from_display,
    page_point_to_display,
    page_rect_to_display,
    set_integration,
    with_page_geometry,
)


def main():
    geometry = PageGeometry(Rect2D(-10, -20, 600, 800), Rect2D(20, 30, 500, 700), 90)
    page = with_page_geometry(DocumentPage("page-1", 600, 800), geometry)
    box = Box(30, 50, 40, 60)
    annotation = Annotation("note-1", page.id, "note", text="Note", box=box)
    document = DocumentModel()
    set_integration(document, IntegrationModel(pages=(page,), annotations=(annotation,)))
    restored = document_from_json(document_to_json(document))
    model = get_integration(restored)
    assert model is not None
    after = get_page_geometry(model.pages[0])
    assert after == geometry
    assert page_display_size(geometry) == (700, 500)
    assert page_point_to_display(geometry, Point2D(30, 50)) == Point2D(680, 10)
    assert page_point_from_display(geometry, Point2D(680, 10)) == Point2D(30, 50)
    assert page_rect_to_display(geometry, Rect2D(box.x, box.y, box.width, box.height)) == Rect2D(620, 10, 60, 40)
    assert model.annotations[0].box == box
    assert restored.validate() == []
    print("Page geometry: cropped quarter turns, inverse coordinates and JSON OK")


if __name__ == "__main__":
    main()
