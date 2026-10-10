"""Own synthetic border contract: persistence, inheritance, edits, failures and diagnostics."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    CELL_BORDERS_PROPERTY,
    TABLE_BORDERS_PROPERTY,
    ArtifactLimitError,
    Border,
    BorderSet,
    ColorValue,
    DocumentLimits,
    DocumentModel,
    IssueSeverity,
    Paragraph,
    Provenance,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    check_document,
    check_extensions,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_json,
    document_to_json,
    extract_document,
    get_borders,
    inspect_document_model,
    iter_elements,
    merge_documents,
    replace_node,
    resolve_borders,
    set_border,
    set_borders,
    transform_elements,
)


def _fixture():
    cells = [TableCell([Paragraph([TextRun(str(index))])]) for index in range(4)]
    table = Table([TableRow(cells[:2]), TableRow(cells[2:])], provenance=Provenance("own-fixture", object_id="table"))
    line = Border(style="solid", color=ColorValue.from_hex("#336699"), width_pt=0.75, offset_pt=2, extra={"vendor": [1, 2]})
    set_borders(table, BorderSet(dict.fromkeys(("top", "right", "bottom", "left", "inside-horizontal", "inside-vertical"), line)))
    set_borders(cells[0], BorderSet({"top": Border("none"), "diagonal-down": line, "diagonal-up": replace(line, style="dotted")}))
    return DocumentModel(sections=[Section(blocks=[table])]), table, cells[0], line


def test_two_cycles_and_explicit_json_contract():
    document, table, cell, line = _fixture()
    table.properties[TABLE_BORDERS_PROPERTY]["future"] = {"safe": [1, True]}
    expected = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected
    assert compare_documents(expected, document).success
    assert check_extensions(document, []).success
    raw = table.properties[TABLE_BORDERS_PROPERTY]
    assert raw["format"] == TABLE_BORDERS_PROPERTY and raw["version"] == 1
    assert raw["sides"]["top"] == {
        "kind": "line",
        "style": "solid",
        "color": {"space": "srgb", "components": [0.2, 0.4, 0.6], "alpha": 1.0, "icc_profile": None, "blend_mode": "normal"},
        "width_pt": 0.75,
        "offset_pt": 2.0,
        "vendor": [1, 2],
    }
    record = get_borders(table)
    record.sides["top"].extra["vendor"].append(3)
    assert get_borders(table).sides["top"].extra == line.extra
    assert get_borders(cell).sides["top"].kind == "none"


def test_inheritance_edit_and_deletion_never_resurrect_direct_side():
    _, table, cell, line = _fixture()
    inherited = BorderSet({"top": line, "left": line}, extra={"fallback": [1]})
    assert resolve_borders(cell, inherited=inherited).sides["top"].kind == "none"
    set_border(cell, "top", Border("nil"))
    assert resolve_borders(cell, inherited=inherited).sides["top"].kind == "nil"
    set_border(cell, "top", Border(width_pt=3))
    direct = resolve_borders(cell, inherited=inherited).sides["top"]
    assert direct.width_pt == 3 and direct.color is None and direct.style is None
    set_border(cell, "top", None)
    assert "top" not in get_borders(cell).sides
    assert "top" not in resolve_borders(cell).sides
    assert resolve_borders(cell, inherited=inherited).sides["top"] == line
    record = get_borders(table)
    set_border(table, "left", replace(record.sides["left"], width_pt=2))
    assert get_borders(table).sides["left"].extra == line.extra
    assert get_borders(table).sides["right"] == line
    resolved = resolve_borders(cell, inherited=inherited)
    resolved.sides["left"].extra["vendor"].append(3)
    assert inherited.sides["left"].extra == line.extra
    set_borders(cell, None)
    assert CELL_BORDERS_PROPERTY not in cell.properties


@pytest.mark.parametrize("value", [True, "1", -1, float("nan"), float("inf"), 10**400])
@pytest.mark.parametrize("field", ["width_pt", "offset_pt"])
def test_invalid_points(value, field):
    with pytest.raises(ValueError):
        Border(**{field: value})


@pytest.mark.parametrize("mutation", ["version", "bool-version", "side", "color", "negative", "none-attrs", "kind", "extra"])
def test_malformed_tagged_data_is_located_and_atomic(mutation):
    document, table, _, _ = _fixture()
    raw = table.properties[TABLE_BORDERS_PROPERTY]
    if mutation == "version":
        raw["version"] = 2
    elif mutation == "bool-version":
        raw["version"] = True
    elif mutation == "side":
        raw["sides"]["diagonal-down"] = raw["sides"]["top"]
    elif mutation == "color":
        raw["sides"]["top"]["color"]["components"] = [2, 0, 0]
    elif mutation == "negative":
        raw["sides"]["top"]["width_pt"] = -1
    elif mutation == "none-attrs":
        raw["sides"]["top"]["kind"] = "none"
    elif mutation == "kind":
        raw["sides"]["top"]["kind"] = "native-unsupported"
    else:
        raw["sides"]["top"]["extra"] = {}
    before = deepcopy(document)
    result = check_document(document)
    assert not result.success
    assert any(issue.code == "semantic.border.invalid" and "properties" in issue.location for issue in result.issues)
    with pytest.raises(ValueError):
        document_to_json(document)
    with pytest.raises(ValueError):
        set_borders(table, BorderSet({}))
    assert document == before


@pytest.mark.parametrize("opaque", [None, "old", {}, {"native": "custom"}])
def test_opaque_occupied_key_is_preserved(opaque):
    document, table, _, _ = _fixture()
    table.properties[TABLE_BORDERS_PROPERTY] = opaque
    assert get_borders(table) is None
    assert document_from_json(document_to_json(document)) == document
    for value in (None, BorderSet({})):
        with pytest.raises(ValueError, match="opaque"):
            set_borders(table, value)
        assert table.properties[TABLE_BORDERS_PROPERTY] == opaque


def test_wrong_owner_and_rejected_side_or_shadow_leave_data_unchanged():
    document, table, cell, line = _fixture()
    before = deepcopy(cell)
    for value in (
        BorderSet({"inside-horizontal": line}),
        BorderSet({}, extra={"version": 1}),
        BorderSet({}, extra={"sides": {}}),
    ):
        with pytest.raises(ValueError):
            set_borders(cell, value)
        assert cell == before
    document.metadata[TABLE_BORDERS_PROPERTY] = deepcopy(table.properties[TABLE_BORDERS_PROPERTY])
    assert any(issue.code == "semantic.border.invalid" for issue in check_document(document).issues)
    document.metadata.clear()
    cell.properties[TABLE_BORDERS_PROPERTY] = deepcopy(table.properties[TABLE_BORDERS_PROPERTY])
    assert not check_document(document).success


def test_limits_and_cycles_refuse_atomically():
    document, table, _, line = _fixture()
    before = deepcopy(table)
    limits = replace(DocumentLimits(), max_depth=3)
    with pytest.raises(ArtifactLimitError):
        get_borders(table, limits=limits)
    with pytest.raises(ArtifactLimitError):
        set_borders(table, BorderSet({"top": line}), limits=limits)
    assert table == before
    cyclic = {}
    cyclic["self"] = cyclic
    with pytest.raises((ArtifactLimitError, ValueError)):
        set_borders(table, BorderSet({}, extra=cyclic))
    assert table == before
    assert inspect_document_model(document).valid


def test_loss_change_and_composition():
    document, _, _, _ = _fixture()
    target = clone_model(document)
    table = target.sections[0].blocks[0]
    set_border(table, "top", None)
    result = compare_documents(document, target)
    issue = next(issue for issue in result.issues if issue.code == "table-border-loss")
    assert issue.severity == IssueSeverity.LOSS and issue.location
    assert issue.measurement["source"]["table"]["sides"]["top"]["width_pt"] == 0.75
    target = clone_model(document)
    set_border(target.sections[0].blocks[0], "top", Border(width_pt=3))
    assert any(
        issue.code == "table-border-loss" for issue in compare_documents(document, target).issues
    )  # lost known color/style
    target = clone_model(document)
    record = get_borders(target.sections[0].blocks[0])
    set_border(target.sections[0].blocks[0], "top", replace(record.sides["top"], width_pt=3))
    assert any(issue.code == "table-border-change" for issue in compare_documents(document, target).issues)
    assert clone_model(document) == document
    extracted = extract_document(document, next(iter_elements(document, Table)))
    assert get_borders(extracted.sections[0].blocks[0]) == get_borders(document.sections[0].blocks[0])
    merged = merge_documents([document, document]).document
    assert check_document(merged).success
    assert document_from_json(document_to_json(merged)) == merged


def test_legacy_document_has_no_invented_borders():
    document = DocumentModel(sections=[Section(blocks=[Table([TableRow([TableCell([])])])])])
    raw = json.loads(document_to_json(document))
    raw["version"] = 1
    restored = document_from_json(json.dumps(raw))
    assert get_borders(restored.sections[0].blocks[0]) is None
    assert compare_documents(document, restored).success


def test_old_inventory_does_not_invent_border_loss():
    document, _, _, _ = _fixture()
    current = inspect_document_model(document)
    legacy = deepcopy(current)
    for item in legacy.objects:
        item.pop("table_borders", None)
    comparison = compare_inspections(current, legacy)
    assert not any(issue.feature.startswith("table-border-") for issue in comparison.issues)


def test_table_shape_change_without_declarations_is_not_border_loss():
    document, table, _, _ = _fixture()
    set_borders(table, None)
    for row in table.rows:
        for cell in row.cells:
            set_borders(cell, None)
    target = clone_model(document)
    target.sections[0].blocks[0].rows.pop()
    result = compare_documents(document, target)
    assert not any(issue.code.startswith("table-border-") for issue in result.issues)


def test_custom_large_limits_reach_border_inventory_and_comparison():
    document, table, _, _ = _fixture()
    nested = "inert"
    for _ in range(70):
        nested = {"value": nested}
    limits = replace(DocumentLimits(), max_depth=100)
    set_borders(table, BorderSet({"top": Border(extra={"future": nested})}), limits=limits)
    with pytest.raises(ArtifactLimitError):
        get_borders(table)
    restored = document_from_json(document_to_json(document, limits=limits), limits=limits)
    assert inspect_document_model(restored, limits=limits).valid
    assert compare_documents(document, restored, limits=limits).success


def test_structural_replacement_rolls_back_invalid_border():
    document, _, _, _ = _fixture()
    invalid = clone_model(document.sections[0].blocks[0])
    invalid.properties[TABLE_BORDERS_PROPERTY]["version"] = 2
    before = deepcopy(document)
    with pytest.raises(ValueError):
        replace_node(document, next(iter_elements(document, Table)), invalid)
    assert document == before
    with pytest.raises(ValueError):
        transform_elements(document, Table, lambda _: invalid)
    assert document == before


def test_inheritance_combined_budget_and_invalid_color_are_atomic():
    cell = TableCell([])
    limits = replace(DocumentLimits(), max_nodes=150)
    set_borders(cell, BorderSet({"top": Border(extra={"data": list(range(100))})}), limits=limits)
    fallback = BorderSet({"left": Border(extra={"data": list(range(100))})})
    before = deepcopy(cell)
    with pytest.raises(ArtifactLimitError):
        resolve_borders(cell, inherited=fallback, limits=limits)
    assert cell == before
    color = ColorValue.from_hex("#336699")
    object.__setattr__(color, "alpha", 2)
    with pytest.raises(ValueError):
        set_border(cell, "right", Border(color=color))
    assert cell == before
