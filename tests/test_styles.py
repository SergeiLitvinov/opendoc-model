"""Effective styles use explicit values, bounded chains and independent output."""

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
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


def _document():
    return DocumentModel(
        styles={
            "base": TextStyle(
                font_family="Serif",
                font_size=Length(12),
                bold=True,
                italic=True,
                color="#123456",
                properties={"left_indent_pt": 20, "custom": {"a": [1]}, "empty": "base"},
            ),
            "body": TextStyle(
                bold=False, language="ru", properties={"base_style_id": "base", "left_indent_pt": 0, "custom": None, "empty": ""}
            ),
        }
    )


def test_named_style_resolves_values_and_json_roundtrip():
    document = _document()
    original = document_to_json(document)
    style = resolve_style(document, "body")
    assert style == TextStyle(
        font_family="Serif",
        font_size=Length(12),
        bold=False,
        italic=True,
        color="#123456",
        language="ru",
        properties={"left_indent_pt": 0, "custom": {"a": [1]}, "empty": ""},
    )
    style.font_size.pt = 18
    style.properties["custom"]["a"].append(2)
    assert document_to_json(document) == original
    assert resolve_style(document_from_json(original), "body") == resolve_style(document, "body")


def test_inline_chain_then_override_chain_has_explicit_precedence():
    document = _document()
    document.styles["accent"] = TextStyle(bold=True, properties={"custom": {"b": 2}})
    inline = TextStyle(italic=False, properties={"base_style_id": "body", "left_indent_pt": None})
    override = TextStyle(underline=False, properties={"base_style_id": "accent", "left_indent_pt": 3})
    result = resolve_style(document, inline, overrides=override)
    assert result.bold is True and result.italic is False and result.underline is False
    assert result.font_family == "Serif"
    assert result.properties.to_dict() == {"left_indent_pt": 3, "custom": {"b": 2}, "empty": ""}
    assert inline.properties["base_style_id"] == "body"
    assert override.properties["base_style_id"] == "accent"


def test_paragraph_run_effective_style_can_be_obtained_without_consumer_resolution():
    document = _document()
    run = TextRun("text", TextStyle(bold=True, properties={"left_indent_pt": None, "custom": []}))
    paragraph = Paragraph([run], style_id="body", alignment="center", properties={"left_indent_pt": 2})
    document.sections = [Section(blocks=[paragraph])]
    style = effective_text_style(document, paragraph, run)
    assert style.bold is True and style.italic is True
    assert style.properties["left_indent_pt"] == 2
    assert style.properties["custom"] == []
    assert "alignment" not in style.properties
    assert effective_text_style(document, paragraph).bold is False
    assert paragraph.alignment == "center"


def test_no_defaults_or_empty_properties_are_invented():
    assert resolve_style(DocumentModel()) == TextStyle()
    assert effective_text_style(DocumentModel(), Paragraph()) == TextStyle()
    result = resolve_style(DocumentModel(), TextStyle(properties={"custom": None}))
    assert result.properties.to_dict() == {}


@pytest.mark.parametrize(
    "field,value",
    [
        ("font_family", ""),
        ("language", ""),
        ("bold", False),
        ("italic", False),
        ("underline", False),
        ("superscript", False),
        ("subscript", False),
        ("color", ""),
        ("background", ""),
    ],
)
def test_explicit_text_fields_override_none_semantics(field, value):
    document = DocumentModel(styles={"base": TextStyle(**{field: True if isinstance(value, bool) else "text"})})
    assert getattr(resolve_style(document, "base", overrides=TextStyle(**{field: value})), field) == value


@pytest.mark.parametrize("mutation", ["missing", "cycle", "inline_missing", "bad_base", "bad_bold"])
def test_invalid_styles_fail_without_changing_input(mutation):
    document = _document()
    inline = TextStyle()
    if mutation == "missing":
        document.styles["body"].properties["base_style_id"] = "absent"
    elif mutation == "cycle":
        document.styles["base"].properties["base_style_id"] = "body"
    elif mutation == "inline_missing":
        inline.properties["base_style_id"] = "missing"
    elif mutation == "bad_base":
        inline.properties["base_style_id"] = 7
    else:
        inline.bold = "yes"
    with pytest.raises(ValueError):
        resolve_style(document, inline)


@pytest.mark.parametrize(
    "document,style,override",
    [
        (None, None, None),
        (DocumentModel(), 1, None),
        (DocumentModel(), "missing", None),
        (DocumentModel(), "", None),
        (DocumentModel(), None, 3),
    ],
)
def test_bad_arguments(document, style, override):
    with pytest.raises(ValueError):
        resolve_style(document, style, overrides=override)


def test_detached_paragraph_and_foreign_run_are_distinguished():
    document = _document()
    paragraph = Paragraph([TextRun("same")], style_id="body")
    assert effective_text_style(document, paragraph).font_family == "Serif"
    with pytest.raises(ValueError, match="contained"):
        effective_text_style(document, paragraph, TextRun("same"))
    with pytest.raises(ValueError, match="Paragraph"):
        effective_text_style(document, TextRun("bad"))
    paragraph.content = None
    with pytest.raises(ValueError):
        effective_text_style(document, paragraph, TextRun("bad"))


def test_chain_is_iterative_and_limits_bound_output():
    document = DocumentModel(styles={"s0": TextStyle(bold=True)})
    for index in range(1, 300):
        document.styles[f"s{index}"] = TextStyle(properties={"base_style_id": f"s{index - 1}"})
    assert resolve_style(document, "s299").bold is True
    with pytest.raises(ArtifactLimitError):
        resolve_style(document, "s299", limits=DocumentLimits(max_nodes=100))
    with pytest.raises(ValueError, match="limits"):
        resolve_style(document, limits=3)


def test_unrelated_invalid_document_is_not_silently_accepted():
    document = _document()
    document.sections = [Section(blocks=[Paragraph(style_id="missing")])]
    with pytest.raises(ValueError, match="unknown style"):
        resolve_style(document, "body")
