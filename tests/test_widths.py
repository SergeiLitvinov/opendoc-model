"""Preferred widths preserve meaning independently of grid and actual layout."""

import json
from copy import deepcopy

import pytest

from opendoc_model import (
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    WidthMeasure,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    extract_document,
    get_preferred_width,
    inspect_document_model,
    iter_elements,
    merge_documents,
    set_preferred_width,
)


def _document():
    table = Table(
        [TableRow([TableCell([Paragraph([TextRun(f"{row}:{column}")])]) for column in range(3)]) for row in range(20)],
        properties={"grid_widths_twips": [960, 7680, 960], "native": {"type": "dxa", "value": 9600}},
        provenance=Provenance("fixture", object_id="table"),
    )
    set_preferred_width(table, WidthMeasure("absolute", 480, "pt", extra={"future": {"flag": True}}))
    for row in table.rows:
        for cell, ratio in zip(row.cells, (0.1, 0.8, 0.1), strict=True):
            set_preferred_width(cell, WidthMeasure("relative", ratio, "ratio", "table"))
    return DocumentModel(sections=[Section([table])])


def test_20_by_3_two_json_cycles_preserve_preferences_grid_and_provenance():
    original = _document()
    encoded = document_to_json(original)
    restored = original
    for _ in range(2):
        restored = document_from_json(document_to_json(restored))
        assert restored.validate() == []
        table = restored.sections[0].blocks[0]
        assert get_preferred_width(table) == WidthMeasure("absolute", 480, "pt", extra={"future": {"flag": True}})
        assert table.provenance == original.sections[0].blocks[0].provenance
        assert table.properties.grid_widths_twips == [960, 7680, 960]
        for row in table.rows:
            assert [get_preferred_width(cell).value for cell in row.cells] == [0.1, 0.8, 0.1]
        assert compare_documents(original, restored).lossless
    assert document_to_json(restored) == encoded
    assert table.properties["native"] == {"type": "dxa", "value": 9600}
    snapshot = get_preferred_width(table)
    snapshot.extra["future"]["flag"] = False
    assert table.properties.preferred_width.extra["future"]["flag"] is True


@pytest.mark.parametrize(
    "measure",
    [
        WidthMeasure("absolute", 0, "pt"),
        WidthMeasure("relative", 0, "ratio", "table"),
        WidthMeasure("relative", 1.5, "ratio", "table"),
        WidthMeasure("auto"),
        WidthMeasure("unspecified"),
    ],
)
def test_all_width_kinds_zero_and_overflow_are_not_conflated(measure):
    cell = TableCell()
    assert get_preferred_width(cell) is None
    set_preferred_width(cell, measure)
    assert cell.properties.get_typed("preferred_width") == measure
    assert cell.properties.preferred_width == measure
    document = DocumentModel(sections=[Section([Table([TableRow([cell])])])])
    restored = document_from_json(document_to_json(document))
    assert get_preferred_width(restored.sections[0].blocks[0].rows[0].cells[0]) == measure
    set_preferred_width(cell, None)
    assert get_preferred_width(cell) is None


def test_legacy_priority_conflicts_and_failed_setter_are_atomic():
    cell = TableCell(properties={"width_twips": "2400", "native": {"value": 12}})
    before = deepcopy(cell.properties.to_dict())
    assert get_preferred_width(cell) == WidthMeasure("absolute", 120, "pt")
    assert cell.properties.to_dict() == before
    set_preferred_width(cell, WidthMeasure("relative", 0.4, "ratio", "table"))
    assert "width_twips" not in cell.properties
    before = deepcopy(cell.properties.to_dict())
    with pytest.raises(ValueError):
        cell.properties.set_typed("width_twips", 1.2)
    assert cell.properties.to_dict() == before
    cell.properties.set_typed("width_twips", 2000)
    assert "preferred_width" not in cell.properties
    assert get_preferred_width(cell) == WidthMeasure("absolute", 100, "pt")
    cell.properties["preferred_width"] = WidthMeasure("absolute", 100, "pt").to_dict()
    assert get_preferred_width(cell) == WidthMeasure("absolute", 100, "pt")
    cell.properties["preferred_width"]["value"] = 101
    with pytest.raises(ValueError, match="conflicts"):
        get_preferred_width(cell)
    document = DocumentModel(sections=[Section([Table([TableRow([cell])])])])
    assert any("preferred_width" in issue for issue in document.validate())
    with pytest.raises(ValueError):
        document_to_json(document)
    assert cell.properties["native"] == {"value": 12}


@pytest.mark.parametrize(
    "raw",
    [
        {},
        {"kind": "other"},
        {"kind": "absolute", "value": True, "unit": "pt"},
        {"kind": "absolute", "value": -1, "unit": "pt"},
        {"kind": "absolute", "value": float("nan"), "unit": "pt"},
        {"kind": "absolute", "value": float("inf"), "unit": "pt"},
        {"kind": "absolute", "value": 1, "unit": "px"},
        {"kind": "auto", "value": 0},
        {"kind": "unspecified", "unit": "pt"},
        {"kind": "relative", "value": 0.1, "unit": "ratio", "reference": "content"},
        {"kind": "absolute", "value": 10**1000, "unit": "pt"},
    ],
)
def test_invalid_measure_rejected_before_storage_and_at_json_boundary(raw):
    cell = TableCell(properties={"width_twips": 960})
    before = cell.properties.to_dict()
    with pytest.raises(ValueError):
        cell.properties.set_typed("preferred_width", raw)
    assert cell.properties.to_dict() == before
    cell.properties["preferred_width"] = raw
    document = DocumentModel(sections=[Section([Table([TableRow([cell])])])])
    with pytest.raises(ValueError):
        document_to_json(document)


def test_table_relative_reference_and_limits_preserve_previous_data():
    table = Table()
    set_preferred_width(table, WidthMeasure("relative", 0.8, "ratio", "content"))
    before = deepcopy(table.properties.to_dict())
    with pytest.raises(ValueError, match="content"):
        set_preferred_width(table, WidthMeasure("relative", 0.8, "ratio", "table"))
    with pytest.raises(ArtifactLimitError):
        set_preferred_width(table, WidthMeasure("auto", extra={"large": "x" * 100}), limits=DocumentLimits(max_bytes=10))
    cyclic = {"kind": "auto"}
    cyclic["future"] = cyclic
    with pytest.raises(ValueError, match="cyclic"):
        table.properties.set_typed("preferred_width", cyclic)
    assert table.properties.to_dict() == before


def test_composition_cloning_and_comparison_preserve_or_report_preferences():
    original = _document()
    copied = clone_model(original)
    selected = extract_document(original, next(iter_elements(original, Table)))
    merged = merge_documents([original, copied])
    assert get_preferred_width(selected.sections[0].blocks[0]) == get_preferred_width(original.sections[0].blocks[0])
    assert compare_documents(original, copied).lossless
    set_preferred_width(merged.document.sections[1].blocks[0].rows[0].cells[0], WidthMeasure("absolute", 48, "pt"))
    assert get_preferred_width(original.sections[0].blocks[0].rows[0].cells[0]).kind == "relative"
    set_preferred_width(copied.sections[0].blocks[0], WidthMeasure("absolute", 400, "pt"))
    result = compare_documents(original, copied)
    issue = next(issue for issue in result.issues if issue.code == "table-width-change")
    assert issue.measurement["source"]["table"]["value"] == 480
    set_preferred_width(copied.sections[0].blocks[0].rows[0].cells[0], None)
    assert any(issue.code == "table-width-loss" for issue in compare_documents(original, copied).issues)
    assert "preferred_widths" in result.metrics["comparison"]["object_diff"]["changed"][0]["changes"]


def test_unknown_fields_and_missing_preference_survive_old_json():
    document = DocumentModel(sections=[Section([Table([TableRow([TableCell(properties={"width_twips": 960})])])])])
    raw = json.loads(document_to_json(document))
    raw["version"] = 1
    restored = document_from_json(json.dumps(raw))
    assert get_preferred_width(restored.sections[0].blocks[0].rows[0].cells[0]) == WidthMeasure("absolute", 48, "pt")
    # Old bags remain permissive; the new reader reports invalid legacy values
    # without silently narrowing existing accepted JSON.
    restored.sections[0].blocks[0].rows[0].cells[0].properties["width_twips"] = "opaque"
    assert document_from_json(document_to_json(restored)).validate() == []
    with pytest.raises(ValueError):
        get_preferred_width(restored.sections[0].blocks[0].rows[0].cells[0])


def test_explicit_depth_budget_preserves_width_unknown_fields_in_inspection():
    nested = {"leaf": True}
    for _ in range(70):
        nested = {"next": nested}
    table = Table(properties={"preferred_width": {"kind": "absolute", "value": 480, "unit": "pt", "future": nested}})
    document = DocumentModel(sections=[Section([table])])
    budget = DocumentLimits(max_depth=96)
    measure = get_preferred_width(table, limits=budget)
    assert measure.extra["future"] == nested
    set_preferred_width(table, measure, limits=budget)
    assert document.validate(limits=budget) == []
    report = inspect_document_model(document, limits=budget, check_external_sources=False)
    assert report.objects[0]["preferred_widths"]["table"]["future"] == nested
    assert compare_documents(document, document, limits=budget).success
    with pytest.raises(ArtifactLimitError):
        get_preferred_width(table)


def test_standalone_inventory_does_not_hide_width_limit_exhaustion():
    from opendoc_model.object_inventory import inspect_objects

    nested = {"leaf": True}
    for _ in range(70):
        nested = {"next": nested}
    table = Table(properties={"preferred_width": {"kind": "absolute", "value": 1, "unit": "pt", "future": nested}})
    with pytest.raises(ArtifactLimitError):
        list(inspect_objects(table, "table", 0, {}))
