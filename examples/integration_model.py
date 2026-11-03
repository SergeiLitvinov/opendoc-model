"""Finite import assessment and range-aware edits without an adapter or editor."""

from opendoc_model import (
    Anchor,
    DiagnosticIssue,
    DocumentModel,
    IntegrationModel,
    IssueSeverity,
    Paragraph,
    PreservationRecord,
    PreservationState,
    Section,
    TextPosition,
    TextRange,
    TextRun,
    document_from_json,
    document_to_json,
    edit_anchored_text,
    get_integration,
    preservation_result,
    set_anchor,
    set_integration,
)


def main():
    run = TextRun("Текст 😀")
    set_anchor(run, Anchor("run-1"))
    document = DocumentModel(sections=[Section([Paragraph([run])])])
    model = IntegrationModel(
        assessed_features=("text",),
        assessment_complete=True,
        preservation=(
            PreservationRecord(
                DiagnosticIssue("text", IssueSeverity.INFO, "Текст сохранён"), PreservationState.SEMANTIC, node_id="run-1"
            ),
        ),
        ranges=(TextRange("comment-range", TextPosition("run-1", 0, "before"), TextPosition("run-1", len(run.text))),),
    )
    set_integration(document, model)
    edited = edit_anchored_text(document, "run-1", 0, 5, "Документ")
    restored = document_from_json(document_to_json(edited))
    after = get_integration(restored)
    assert after is not None
    assert after.ranges[0].end.offset == len("Документ 😀")
    assert run.text == "Текст 😀"
    assert preservation_result(model).lossless
    assert not preservation_result(IntegrationModel()).lossless
    assert restored.validate() == []
    print("Integration model: JSON, Unicode ranges and explicit assessment OK")


if __name__ == "__main__":
    main()
