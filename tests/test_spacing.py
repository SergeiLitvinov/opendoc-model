"""Own synthetic spacing declarations, isolation, fallback and bounded failures."""

from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    TAB_STOPS_PROPERTY,
    TABLE_INDENT_PROPERTY,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Paragraph,
    QualityPolicy,
    Section,
    Table,
    TableCell,
    TableIndent,
    TableRow,
    TabStop,
    TabStops,
    TextRun,
    check_document,
    clone_model,
    compare_documents,
    compare_inspections,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_tab_stops,
    get_table_indent,
    inspect_document_model,
    iter_elements,
    merge_documents,
    resolve_tab_stops,
    resolve_table_indent,
    set_tab_stop,
    set_tab_stops,
    set_table_indent,
)


def _fixture():
    paragraph = Paragraph([TextRun("Label\tValue")])
    table = Table([TableRow([TableCell([paragraph])])])
    set_table_indent(table, TableIndent(30, extra={"future": [1]}))
    set_tab_stops(
        paragraph,
        TabStops(
            (TabStop(396, alignment="right", leader="line", extra={"native": [2]}),), False, extra={"future": {"kind": "clear"}}
        ),
    )
    return DocumentModel(sections=[Section(blocks=[table])]), table, paragraph


def test_two_json_cycles_and_independent_values():
    document, table, paragraph = _fixture()
    expected = deepcopy(document)
    for _ in range(2):
        document = document_from_json(document_to_json(document))
    assert document == expected and compare_documents(expected, document).success
    raw = paragraph.properties[TAB_STOPS_PROPERTY]
    assert raw["format"] == TAB_STOPS_PROPERTY and raw["version"] == 1
    assert raw["stops"][0]["position_pt"] == 396
    get_tab_stops(paragraph).stops[0].extra["native"].append(3)
    get_table_indent(table).extra["future"].append(2)
    assert get_tab_stops(paragraph).stops[0].extra["native"] == [2]
    assert get_table_indent(table).extra == {"future": [1]}
    raw_document = document_to_dict(document)
    assert raw_document["version"] == 2
    raw_document["version"] = 1
    assert document_from_dict(raw_document) == document


def test_signed_zero_unknown_missing_and_fallback():
    table = Table([])
    fallback = TableIndent(-10, extra={"future": [1]})
    assert get_table_indent(table) is None and resolve_table_indent(table) is None
    resolved = resolve_table_indent(table, inherited=fallback)
    resolved.extra["future"].append(2)
    assert fallback.extra["future"] == [1]
    for value in (0, -30, 30, None):
        set_table_indent(table, TableIndent(value))
        assert resolve_table_indent(table, inherited=fallback).value_pt == value
    set_table_indent(table, None)
    assert resolve_table_indent(table, inherited=fallback) == fallback


def test_position_fallback_edit_clear_remove_and_empty_replacing_set():
    paragraph = Paragraph([])
    fallback = TabStops((TabStop(396, alignment="right", leader="line", extra={"future": [1]}), TabStop(20)))
    assert resolve_tab_stops(paragraph).stops == ()
    resolved = resolve_tab_stops(paragraph, inherited=fallback)
    assert [stop.position_pt for stop in resolved.stops] == [20, 396]
    resolved.stops[1].extra["future"].append(2)
    assert fallback.stops[0].extra["future"] == [1]
    set_tab_stop(paragraph, 396, TabStop(396, alignment="left", leader="none", extra={"vendor": [2]}))
    assert resolve_tab_stops(paragraph, inherited=fallback).stops[1].alignment == "left"
    assert resolve_tab_stops(paragraph, inherited=fallback).stops[1].extra == {"vendor": [2]}
    set_tab_stop(paragraph, 396, TabStop(396, "clear"))
    assert get_tab_stops(paragraph).stops[0].extra == {"vendor": [2]}
    assert [stop.position_pt for stop in resolve_tab_stops(paragraph, inherited=fallback).stops] == [20]
    set_tab_stop(paragraph, 396, None)
    assert resolve_tab_stops(paragraph, inherited=fallback).stops[1] == fallback.stops[0]
    set_tab_stops(paragraph, TabStops(inherit=False))
    assert not resolve_tab_stops(paragraph, inherited=fallback).stops
    set_tab_stops(paragraph, None)
    assert get_tab_stops(paragraph) is None
    assert resolve_tab_stops(paragraph, inherited=fallback).stops[1] == fallback.stops[0]


def test_extra_preservation_and_atomic_refusal():
    _, table, paragraph = _fixture()
    set_table_indent(table, TableIndent(0))
    assert get_table_indent(table).extra == {"future": [1]}
    set_tab_stop(paragraph, 20, TabStop(20))
    assert get_tab_stops(paragraph).stops[1].leader == "line"
    assert get_tab_stops(paragraph).extra == {"future": {"kind": "clear"}}
    before = deepcopy(paragraph)
    with pytest.raises(ValueError):
        set_tab_stop(paragraph, 20, TabStop(21))
    assert paragraph == before
    with pytest.raises(ValueError):
        set_tab_stops(paragraph, TabStops(extra={"version": 2}))
    assert paragraph == before
    with pytest.raises(ValueError):
        set_tab_stops(paragraph, TabStops((TabStop(20, extra={"position_pt": 99}),)))
    assert paragraph == before


@pytest.mark.parametrize("value", [True, "30", float("nan"), float("inf"), -float("inf"), 10**400])
def test_invalid_points(value):
    with pytest.raises(ValueError):
        TableIndent(value)
    with pytest.raises(ValueError):
        TabStop(value)


@pytest.mark.parametrize(
    "factory",
    [
        lambda: TabStop(20, kind="other"),
        lambda: TabStop(20, alignment="other"),
        lambda: TabStop(20, leader="other"),
        lambda: TabStop(20, "clear", "right"),
        lambda: TabStop(20, "clear", leader="none"),
        lambda: TabStops((TabStop(20), TabStop(20.0))),
        lambda: TabStops([], True),
        lambda: TabStops(inherit=1),
        lambda: TabStops((TableIndent(20),)),
    ],
)
def test_invalid_contracts(factory):
    with pytest.raises(ValueError):
        factory()


@pytest.mark.parametrize(
    "key,owner,getter,setter",
    [
        (TABLE_INDENT_PROPERTY, Table, get_table_indent, set_table_indent),
        (TAB_STOPS_PROPERTY, Paragraph, get_tab_stops, set_tab_stops),
    ],
)
def test_opaque_and_unknown_version(key, owner, getter, setter):
    node = owner([])
    for raw in (None, {"future": 1}, {"format": "vendor", "version": 1}, "opaque"):
        node.properties[key] = raw
        assert getter(node) is None
        with pytest.raises(ValueError):
            setter(node, None)
        assert node.properties[key] == raw
    for version in (True, 2, 1.0, "1", None):
        node.properties[key] = {"format": key, "version": version}
        with pytest.raises(ValueError):
            getter(node)


def test_wrong_owner_validation_and_tagged_corruption():
    document, table, paragraph = _fixture()
    table.properties[TAB_STOPS_PROPERTY] = deepcopy(paragraph.properties[TAB_STOPS_PROPERTY])
    issues = check_document(document).issues
    assert any(issue.code == "semantic.spacing.invalid" and "properties" in issue.location for issue in issues)
    with pytest.raises(ValueError):
        document_to_json(document)
    table.properties.pop(TAB_STOPS_PROPERTY)
    paragraph.properties[TAB_STOPS_PROPERTY]["stops"][0]["position_pt"] = True
    assert not check_document(document).success
    with pytest.raises(ValueError):
        get_table_indent(paragraph)
    with pytest.raises(ValueError):
        get_tab_stops(table)


def test_budgets_cycles_and_refusal_leave_inputs_unchanged():
    document, table, paragraph = _fixture()
    limits = DocumentLimits(max_nodes=5)
    for getter, node in ((get_table_indent, table), (get_tab_stops, paragraph)):
        with pytest.raises(ArtifactLimitError):
            getter(node, limits=limits)
    before = deepcopy(table)
    with pytest.raises(ArtifactLimitError):
        set_table_indent(table, TableIndent(20, extra={"huge": list(range(30))}), limits=DocumentLimits(max_nodes=20))
    assert table == before
    cycle = {}
    cycle["cycle"] = cycle
    with pytest.raises(ValueError, match="cyclic"):
        set_tab_stops(paragraph, TabStops(extra=cycle))
    # Explicit higher budgets must survive all inner codec checks.
    large = TableIndent(30, extra={"large": list(range(100_001))})
    set_table_indent(table, large, limits=DocumentLimits(max_nodes=200_000))
    assert len(get_table_indent(table, limits=DocumentLimits(max_nodes=200_000)).extra["large"]) == 100_001


def test_composition_and_clone_keep_direct_declarations_detached():
    document, _, _ = _fixture()
    for copied in (
        clone_model(document),
        extract_document(document, next(iter_elements(document, Table))),
        merge_documents([document, document]).document,
    ):
        table = next(iter_elements(copied, Table)).node
        paragraph = next(iter_elements(copied, Paragraph)).node
        assert get_table_indent(table).value_pt == 30
        assert get_tab_stops(paragraph).stops[0].leader == "line"
        table.properties[TABLE_INDENT_PROPERTY]["future"].append(2)
        assert next(iter_elements(document, Table)).node.properties[TABLE_INDENT_PROPERTY]["future"] == [1]


def test_comparison_reports_changes_losses_and_measurements():
    source, _, _ = _fixture()
    target = clone_model(source)
    table = next(iter_elements(target, Table)).node
    paragraph = next(iter_elements(target, Paragraph)).node
    set_table_indent(table, TableIndent(0))
    set_tab_stop(paragraph, 396, TabStop(396, alignment="left", leader="none"))
    result = compare_documents(source, target, policies=[QualityPolicy(max_loss_issues=0)])
    assert not result.success
    assert {issue.code for issue in result.issues} >= {"table-indent-change", "tab-stops-loss"}
    assert all(
        issue.location and "source" in issue.measurement
        for issue in result.issues
        if issue.code.startswith(("table-indent-", "tab-stops-"))
    )
    set_table_indent(table, None)
    set_tab_stops(paragraph, None)
    assert {issue.code for issue in compare_documents(source, target).issues} >= {"table-indent-loss", "tab-stops-loss"}


def test_order_has_no_semantic_effect_and_older_inventory_is_unknown():
    source, _, paragraph = _fixture()
    set_tab_stop(paragraph, 20, TabStop(20))
    target = clone_model(source)
    target_paragraph = next(iter_elements(target, Paragraph)).node
    record = get_tab_stops(target_paragraph)
    set_tab_stops(target_paragraph, replace(record, stops=tuple(reversed(record.stops))))
    assert compare_documents(source, target).success
    older = inspect_document_model(source)
    current = inspect_document_model(target)
    for item in older.objects:
        item.pop("tab_stops", None)
        item.pop("table_indent", None)
    assert not any(
        issue.feature.startswith(("table-indent-", "tab-stops-")) for issue in compare_inspections(older, current).issues
    )


def test_explicit_larger_limits_through_document_json_copy_and_resolution():
    document, table, paragraph = _fixture()
    limits = DocumentLimits(max_nodes=200_000)
    large = {"large": list(range(100_001))}
    set_tab_stops(paragraph, TabStops((TabStop(396, leader="line", extra=large),), False), limits=limits)
    assert check_document(document, limits=limits).success
    copied = clone_model(document, limits=limits)
    restored = document_from_json(document_to_json(copied, limits=limits), limits=limits)
    restored_paragraph = next(iter_elements(restored, Paragraph, limits=limits)).node
    assert len(resolve_tab_stops(restored_paragraph, limits=limits).stops[0].extra["large"]) == 100_001
    assert resolve_table_indent(table, inherited=TableIndent(0, extra=large), limits=limits).value_pt == 30


@pytest.mark.parametrize("alignment", [None, "left", "right", "center", "decimal", "bar"])
@pytest.mark.parametrize("leader", [None, "none", "dot", "dash", "line", "heavy", "middle-dot"])
def test_supported_alignment_and_leader_round_trip(alignment, leader):
    paragraph = Paragraph([])
    stop = TabStop(-20, alignment=alignment, leader=leader)
    set_tab_stops(paragraph, TabStops((stop,)))
    assert get_tab_stops(paragraph).stops == (stop,)


def test_metadata_is_not_a_spacing_owner():
    document, table, _ = _fixture()
    document.metadata[TABLE_INDENT_PROPERTY] = deepcopy(table.properties[TABLE_INDENT_PROPERTY])
    assert any(
        issue.code == "semantic.spacing.invalid" and "metadata" in issue.location for issue in check_document(document).issues
    )
