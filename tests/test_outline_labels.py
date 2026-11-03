"""Separate rich labels: identity, title binding, transport and composition."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    Anchor,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    FontReference,
    Formula,
    FormulaFormat,
    InternalLink,
    Outline,
    OutlineEntry,
    OutlineLabel,
    OutlineTarget,
    Paragraph,
    Provenance,
    Resource,
    ResourceKind,
    Section,
    TextRun,
    TextStyle,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_font_reference,
    get_internal_link,
    get_outline,
    inspect_document_model,
    iter_font_references,
    iter_outline_inlines,
    merge_documents,
    remap_outline,
    resolve_anchor,
    set_anchor,
    set_font_reference,
    set_internal_link,
    set_outline,
    walk_model,
)


def fixture():
    heading = Paragraph([TextRun("Long visible heading")])
    set_anchor(heading, Anchor("body"))
    document = DocumentModel(
        [Section([heading])],
        resources={"font": Resource("font", ResourceKind.FONT, "font/ttf", b"own")},
        styles={"named": TextStyle(italic=True)},
    )
    run = TextRun("Short ", TextStyle(bold=True, properties={"base_style_id": "named"}), provenance=Provenance("own"))
    set_font_reference(run.style, FontReference("font", 0))
    set_internal_link(run, InternalLink("body"))
    formula = Formula("x^2", FormulaFormat.LATEX, fallback_text="x²")
    label = OutlineLabel("Short x²", (run, formula), extra={"future": {"values": [1]}})
    entry = OutlineEntry("toc", "Short x²", 0, target=OutlineTarget("anchor", "body"), label=label, extra={"custom": [2]})
    set_outline(document, Outline((entry,)))
    return document


def cycles(document):
    before = document_to_dict(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert document_to_dict(document) == before
    return document


def test_rich_cycles_independent_body_walk_and_font_refs():
    document = fixture()
    result = cycles(document)
    labels = list(iter_outline_inlines(result))
    assert [type(loc.node) for loc in labels] == [TextRun, Formula]
    assert [(loc.entry_id, loc.index) for loc in labels] == [("toc", 0), ("toc", 1)]
    assert all("label.content" in loc.path for loc in labels)
    assert [loc.node.text for loc in walk_model(result) if isinstance(loc.node, TextRun)] == ["Long visible heading"]
    assert get_font_reference(labels[0].node.style) == FontReference("font", 0)
    assert any("label.content" in loc.path for loc in iter_font_references(result))
    assert "outline" in inspect_document_model(result).metadata
    labels[0].node.text = "mutated"
    assert get_outline(result).entries[0].label.content[0].text == "Short "
    outline = get_outline(result)
    outline.entries[0].label.extra["future"]["values"].append(9)
    assert get_outline(result).entries[0].label.extra["future"]["values"] == [1]


def test_absent_and_empty_are_distinct_and_old_wire_omits_field():
    document = fixture()
    plain = OutlineEntry("plain", "Old", 0)
    set_outline(document, Outline((plain,)))
    raw = document_to_json(document)
    assert '"label"' not in raw
    set_outline(document, Outline((replace(plain, title="", label=OutlineLabel("")),)))
    assert get_outline(cycles(document)).entries[0].label.content == ()
    set_outline(document, Outline((replace(plain, title="", label=None),)))
    assert get_outline(cycles(document)).entries[0].label is None


def test_plain_edit_requires_explicit_label_update_or_removal():
    document = fixture()
    entry = get_outline(document).entries[0]
    previous = document.metadata
    with pytest.raises(ValueError, match="label.title"):
        set_outline(document, Outline((replace(entry, title="New"),)))
    assert document.metadata is previous
    set_outline(document, Outline((replace(entry, title="New", label=None),)))
    assert get_outline(cycles(document)).entries[0].label is None
    changed = replace(entry, title="New", label=OutlineLabel("New", (TextRun("New", TextStyle(italic=True)),)))
    set_outline(document, Outline((changed,)))
    assert get_outline(cycles(document)).entries[0].label.content[0].style.italic


@pytest.mark.parametrize(
    "node",
    [
        Paragraph(),
        Formula("x", FormulaFormat.LATEX, display=True, fallback_text="x"),
        Formula("x", FormulaFormat.LATEX),
        TextRun("x", TextStyle(properties={"base_style_id": "missing"})),
    ],
)
def test_invalid_content_fails_atomically(node):
    document = fixture()
    before = document_to_json(document)
    entry = get_outline(document).entries[0]
    with pytest.raises(ValueError, match="label"):
        set_outline(document, Outline((replace(entry, label=OutlineLabel(entry.title, (node,))),)))
    assert document_to_json(document) == before


@pytest.mark.parametrize("kind", ["font-missing", "font-kind", "anchor-missing", "declared-anchor", "extra-state"])
def test_references_and_unknown_core_state_fail(kind):
    document = fixture()
    entry = get_outline(document).entries[0]
    run = entry.label.content[0]
    if kind == "font-missing":
        set_font_reference(run.style, FontReference("missing"))
    elif kind == "font-kind":
        document.resources["font"].kind = ResourceKind.ATTACHMENT
    elif kind == "anchor-missing":
        set_internal_link(run, InternalLink("missing"))
    elif kind == "declared-anchor":
        set_anchor(run, Anchor("private"))
    else:
        run.future = 1
    previous = deepcopy(document.metadata)
    with pytest.raises(ValueError):
        set_outline(document, Outline((entry,)))
    assert document.metadata == previous


def test_merge_remap_and_extract_keep_label_dependencies():
    document = fixture()
    merged = merge_documents([document, document], conflicts="rename", metadata_conflicts="keep_last").document
    entry = get_outline(merged).entries[0]
    assert entry.target.target_id == "body~2"
    assert get_internal_link(entry.label.content[0]).target_id == "body~2"
    assert get_font_reference(entry.label.content[0].style).resource_id == "font~2"
    assert entry.label.content[0].style.properties["base_style_id"] == "named~2"
    assert not cycles(merged).validate()
    extracted = extract_document(document, resolve_anchor(document, "body"))
    assert set(extracted.resources) == {"font"} and set(extracted.styles) == {"named"}
    assert get_outline(cycles(extracted)) == get_outline(document)
    remapped = remap_outline(get_outline(document), entry_ids={"toc": "new"}, resource_ids={"font": "replacement"})
    assert remapped.entries[0].id == "new"
    assert get_font_reference(remapped.entries[0].label.content[0].style).resource_id == "replacement"
    assert get_font_reference(get_outline(document).entries[0].label.content[0].style).resource_id == "font"


def test_multiple_labels_can_target_same_heading():
    document = fixture()
    entry = get_outline(document).entries[0]
    other = replace(entry, id="other", order=1, title="Other", label=OutlineLabel("Other", (TextRun("Other"),)))
    set_outline(document, Outline((entry, other)))
    assert len(get_outline(cycles(document)).entries) == 2
    assert document.sections[0].blocks[0].plain_text == "Long visible heading"


@pytest.mark.parametrize("quota", ["max_nodes", "max_depth", "max_bytes", "max_embedded_bytes"])
def test_exact_transport_limits_and_one_below(quota):
    document = fixture()
    wire = document_to_json(document)

    def accepted(value):
        try:
            limits = replace(DocumentLimits(), **{quota: value})
            document_to_json(document, limits=limits)
            document_from_json(wire, limits=limits)
        except ArtifactLimitError:
            return False
        return True

    low, high = 0, 128 if quota == "max_depth" else max(10000, len(wire.encode()))
    while low + 1 < high:
        midpoint = (low + high) // 2
        if accepted(midpoint):
            high = midpoint
        else:
            low = midpoint
    assert accepted(high) and not accepted(high - 1)

    # Setters bound the model/envelope, not the complete document wire; their
    # exact accepted threshold can differ from paired JSON transport.
    def setter_accepted(value):
        previous = document.metadata
        try:
            set_outline(document, get_outline(document), limits=replace(DocumentLimits(), **{quota: value}))
        except ArtifactLimitError:
            assert document.metadata is previous
            return False
        return True

    low, high = 0, 128 if quota == "max_depth" else max(10000, len(wire.encode()))
    while low + 1 < high:
        midpoint = (low + high) // 2
        if setter_accepted(midpoint):
            high = midpoint
        else:
            low = midpoint
    assert setter_accepted(high)
    old = document.metadata
    with pytest.raises(ArtifactLimitError):
        set_outline(document, get_outline(document), limits=replace(DocumentLimits(), **{quota: high - 1}))
    assert document.metadata is old


def test_cyclic_property_rejected_before_encoding():
    document = fixture()
    entry = get_outline(document).entries[0]
    entry.label.content[0].properties["cycle"] = entry.label.content[0].properties
    old = document.metadata
    with pytest.raises(ValueError, match="cyclic"):
        set_outline(document, Outline((entry,)))
    assert document.metadata is old
