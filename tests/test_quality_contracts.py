"""Quality gates require positive evidence and preserve exact budget boundaries."""

import copy
import itertools
from pathlib import Path

import pytest

from opendoc_model import (
    Box,
    ConversionReport,
    DocumentInspection,
    DocumentModel,
    EmphasisLossPolicy,
    Formula,
    FormulaFormat,
    FormulaLossPolicy,
    Image,
    IssueSeverity,
    ObjectLossPolicy,
    PackageGraph,
    PackagePart,
    Paragraph,
    Provenance,
    QualityPolicy,
    Resource,
    ResourceKind,
    Section,
    TextPreservationPolicy,
    TextRun,
    TextStyle,
    compare_inspections,
    inspect_document_model,
)
from opendoc_model.emphasis_quality import MAX_EMPHASIS_RUNS, EmphasisInventory
from opendoc_model.text_edit_budget import MAX_DISTANCE_CELLS, bounded_word_distance
from opendoc_model.text_flow import MAX_TEXT_TOKENS, TextFlowFingerprint


def _report():
    return ConversionReport(Path("result.json"))


def _inspect(*texts):
    return inspect_document_model(DocumentModel(sections=[Section(blocks=[Paragraph([TextRun(text)]) for text in texts])]))


def _compare(*texts, target):
    return compare_inspections(_inspect(*texts), _inspect(*target))


@pytest.mark.parametrize("policy", [QualityPolicy, ObjectLossPolicy, FormulaLossPolicy, EmphasisLossPolicy])
@pytest.mark.parametrize("value", [-1, True, 1.5, "1", None])
def test_count_budgets_require_nonnegative_integers(policy, value):
    with pytest.raises(ValueError):
        policy(value)


@pytest.mark.parametrize("value", [-1, True, 1.5, "1"])
def test_word_edit_budget_rejects_invalid_count(value):
    with pytest.raises(ValueError):
        TextPreservationPolicy("flow", value)


def test_loss_issue_budget_counts_events_and_does_not_replace_other_errors():
    report = _report()
    report.add(IssueSeverity.LOSS, "loss", "first")
    report.add(IssueSeverity.WARNING, "warning", "warning")
    report.add(IssueSeverity.ERROR, "other", "independent failure")
    assert QualityPolicy(1).evaluate(report)
    assert not report.success
    report.add(IssueSeverity.LOSS, "loss", "second")
    assert not QualityPolicy(1).evaluate(report)
    assert not QualityPolicy(1).evaluate(report)
    assert len([issue for issue in report.issues if issue.feature == "quality-budget"]) == 1
    gate = report.metrics["quality_gate"]
    assert gate["loss_issues"] == 2
    assert gate["visual_score"] is gate["editability_score"] is None


@pytest.mark.parametrize(
    "policy",
    [
        ObjectLossPolicy(),
        TextPreservationPolicy(),
        TextPreservationPolicy("flow"),
        TextPreservationPolicy("flow", 0),
        FormulaLossPolicy(),
        EmphasisLossPolicy(),
    ],
)
def test_known_empty_model_passes_strict_gates_but_missing_inspection_does_not(policy):
    comparison = compare_inspections(inspect_document_model(DocumentModel()), inspect_document_model(DocumentModel()))
    assert policy.evaluate(_report(), comparison)
    for unknown in (None, compare_inspections(_inspect("text"), DocumentInspection(None, "unknown"))):
        report = _report()
        assert not policy.evaluate(report, unknown)
        assert not report.success
        gate = next(iter(report.metrics.values()))
        assert gate["verified"] is False
        assert gate["reason"] == "unavailable"


def test_object_budget_exact_threshold_and_excess():
    comparison = _compare("kept", "removed", target=["kept"])
    assert ObjectLossPolicy(1).evaluate(_report(), comparison)
    report = _report()
    assert not ObjectLossPolicy(0).evaluate(report, comparison)
    assert report.metrics["object_quality_gate"]["lost_objects"] == 1
    assert report.metrics["object_quality_gate"]["reason"] == "budget-exceeded"


@pytest.mark.parametrize(("source", "target"), [("before", "after"), ("same", "same")])
def test_object_gate_rejects_heuristic_and_duplicate_matching(source, target):
    comparison = _compare(source, source, target=[target])
    report = _report()
    assert not ObjectLossPolicy(100).evaluate(report, comparison)
    gate = report.metrics["object_quality_gate"]
    assert gate["lost_objects"] is None
    assert gate["reason"] == "uncertain-matching"


def test_provenance_makes_edit_identity_certain_without_claiming_text_preserved():
    source = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("before")], provenance=Provenance("custom", object_id="p1"))])]
    )
    target = copy.deepcopy(source)
    target.sections[0].blocks[0].content[0].text = "after"
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert ObjectLossPolicy().evaluate(_report(), comparison)
    assert not TextPreservationPolicy().evaluate(_report(), comparison)
    assert comparison.object_diff["matching"]["heuristic"] == 0


def test_empty_paragraph_and_empty_embedded_image_have_known_content():
    document = DocumentModel(
        sections=[Section(blocks=[Paragraph(), Image("empty")])],
        resources={"empty": Resource("empty", ResourceKind.RASTER_IMAGE, "image/png", data=b"")},
    )
    before = inspect_document_model(document)
    assert all(item["content_hash"] for item in before.objects)
    comparison = compare_inspections(before, inspect_document_model(copy.deepcopy(document)))
    assert ObjectLossPolicy().evaluate(_report(), comparison)


def test_provenance_page_zero_and_missing_page_are_distinct():
    source = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("same")], provenance=Provenance("custom", page=0, object_id="p"))])]
    )
    target = copy.deepcopy(source)
    target.sections[0].blocks[0].provenance.page = None
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert len(comparison.object_diff["lost"]) == len(comparison.object_diff["added"]) == 1


def test_paragraph_text_preservation_counts_duplicates_and_allows_additions_and_moves():
    policy = TextPreservationPolicy()
    assert policy.evaluate(_report(), _compare("a", "b", target=["b", "a", "new"]))
    report = _report()
    assert not policy.evaluate(report, _compare("a", "a", target=["a"]))
    assert report.metrics["text_quality_gate"]["unmatched_source_paragraphs"] == 1


def test_flow_allows_resegmentation_and_whitespace_but_requires_word_order():
    exact, flow = TextPreservationPolicy(), TextPreservationPolicy("flow")
    comparison = _compare("one two", "three", target=["one", "two \n three"])
    assert not exact.evaluate(_report(), comparison)
    assert flow.evaluate(_report(), comparison)
    assert not flow.evaluate(_report(), _compare("one two", target=["two one"]))
    assert not flow.evaluate(_report(), _compare("one", target=["one new"]))


def test_text_gates_exclude_formula_markup_and_image_alternative_text():
    source = DocumentModel(
        sections=[Section(blocks=[Paragraph([TextRun("visible"), Formula("x", FormulaFormat.LATEX), Image("img", "old")])])],
        resources={"img": Resource("img", ResourceKind.RASTER_IMAGE, "image/png", data=b"image")},
    )
    target = copy.deepcopy(source)
    target.sections[0].blocks[0].content[1].value = "different"
    target.sections[0].blocks[0].content[2].alt_text = "new"
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert TextPreservationPolicy().evaluate(_report(), comparison)
    assert TextPreservationPolicy("flow").evaluate(_report(), comparison)
    assert not FormulaLossPolicy().evaluate(_report(), comparison)


@pytest.mark.parametrize(
    ("source", "target", "distance"),
    [
        ([], [], 0),
        (["a"], [], 1),
        ([], ["a"], 1),
        (["a"], ["b"], 1),
        (["a", "b"], ["b", "a"], 2),
        (["a", "a"], ["a"], 1),
        (["prefix", "a", "suffix"], ["prefix", "b", "suffix"], 1),
    ],
)
def test_word_distance_exact_boundary_and_proven_excess(source, target, distance):
    assert bounded_word_distance(source, target, distance) == (distance, True)
    if distance:
        assert bounded_word_distance(source, target, distance - 1) == (None, True)


def test_word_edit_policy_reports_exact_count_or_lower_bound():
    comparison = _compare("one two three", target=["one changed three"])
    accepted = _report()
    assert TextPreservationPolicy("flow", 1).evaluate(accepted, comparison)
    assert accepted.metrics["text_quality_gate"]["text_edits"] == 1
    assert accepted.issues[0].severity is IssueSeverity.WARNING
    rejected = _report()
    assert not TextPreservationPolicy("flow", 0).evaluate(rejected, comparison)
    gate = rejected.metrics["text_quality_gate"]
    assert gate["text_edits"] is None
    assert gate["text_edits_lower_bound"] == 1
    assert gate["verified"] is True


def test_word_work_limit_produces_unknown_without_an_invented_lower_bound():
    size = int(MAX_DISTANCE_CELLS**0.5) + 1
    assert bounded_word_distance(["left"] * size, ["right"] * size, size) == (None, False)
    comparison = _compare(" ".join(["left"] * size), target=[" ".join(["right"] * size)])
    report = _report()
    assert not TextPreservationPolicy("flow", size).evaluate(report, comparison)
    gate = report.metrics["text_quality_gate"]
    assert gate["reason"] == "unavailable"
    assert gate["text_edits_lower_bound"] is None


def test_bounded_distance_agrees_with_independent_full_matrix():
    def distance(left, right):
        matrix = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
        for row in range(len(left) + 1):
            matrix[row][0] = row
        for column in range(len(right) + 1):
            matrix[0][column] = column
        for row, a in enumerate(left, 1):
            for column, b in enumerate(right, 1):
                matrix[row][column] = min(
                    matrix[row - 1][column] + 1, matrix[row][column - 1] + 1, matrix[row - 1][column - 1] + (a != b)
                )
        return matrix[-1][-1]

    sequences = [list(value) for size in range(5) for value in itertools.product("ab", repeat=size)]
    for left, right in itertools.product(sequences, repeat=2):
        expected = distance(left, right)
        for limit in range(5):
            assert bounded_word_distance(left, right, limit) == (expected if expected <= limit else None, True)


def test_word_work_budget_exact_boundary(monkeypatch):
    monkeypatch.setattr("opendoc_model.text_edit_budget.MAX_DISTANCE_CELLS", 12)
    assert bounded_word_distance(["a"] * 3, ["b"] * 3, 3) == (3, True)
    monkeypatch.setattr("opendoc_model.text_edit_budget.MAX_DISTANCE_CELLS", 11)
    assert bounded_word_distance(["a"] * 3, ["b"] * 3, 3) == (None, False)


def test_word_token_limit_retains_exact_flow_but_disables_changed_flow_budget():
    flow = TextFlowFingerprint()
    flow.add(" ".join(["word"] * MAX_TEXT_TOKENS))
    assert len(flow.to_dict()["tokens"]) == MAX_TEXT_TOKENS
    flow.add("overflow")
    assert flow.to_dict()["tokens"] is None
    before = _inspect(" ".join(["word"] * (MAX_TEXT_TOKENS + 1)))
    report = _report()
    assert TextPreservationPolicy("flow", 0).evaluate(report, compare_inspections(before, copy.deepcopy(before)))
    after = _inspect(" ".join(["other"] * (MAX_TEXT_TOKENS + 1)))
    report = _report()
    assert not TextPreservationPolicy("flow", MAX_TEXT_TOKENS + 1).evaluate(report, compare_inspections(before, after))
    assert report.metrics["text_quality_gate"]["reason"] == "unavailable"


def test_formula_budget_counts_occurrences_and_exact_latex_source():
    def inspect(values):
        return inspect_document_model(
            DocumentModel(sections=[Section(blocks=[Formula(value, FormulaFormat.LATEX) for value in values])])
        )

    comparison = compare_inspections(inspect(["x", "x", "y"]), inspect(["y", "x"]))
    assert FormulaLossPolicy(1).evaluate(_report(), comparison)
    report = _report()
    assert not FormulaLossPolicy(0).evaluate(report, comparison)
    assert report.metrics["formula_quality_gate"]["changed_formulas"] == 1
    assert not FormulaLossPolicy().evaluate(_report(), compare_inspections(inspect(["x"]), inspect([" x "])))
    assert FormulaLossPolicy().evaluate(_report(), compare_inspections(inspect(["x"]), inspect(["x", "new"])))


def test_missing_formula_fingerprint_is_unavailable_even_with_large_budget():
    before = inspect_document_model(DocumentModel(sections=[Section(blocks=[Formula("x", FormulaFormat.LATEX)])]))
    after = copy.deepcopy(before)
    after.objects[0]["formula_hash"] = None
    report = _report()
    assert not FormulaLossPolicy(999).evaluate(report, compare_inspections(before, after))
    assert report.metrics["formula_quality_gate"]["changed_formulas"] is None


def test_emphasis_counts_characters_once_and_is_independent_of_run_boundaries():
    def inspect(runs):
        return inspect_document_model(DocumentModel(sections=[Section(blocks=[Paragraph(runs)])]))

    source = inspect([TextRun("a b", style=TextStyle(bold=True, italic=True)), TextRun("c")])
    same = inspect(
        [
            TextRun("a", style=TextStyle(bold=True, italic=True)),
            TextRun("b", style=TextStyle(bold=True, italic=True)),
            TextRun(" c"),
        ]
    )
    assert EmphasisLossPolicy().evaluate(_report(), compare_inspections(source, same))
    changed = inspect([TextRun("ab"), TextRun("c")])
    comparison = compare_inspections(source, changed)
    assert EmphasisLossPolicy(2).evaluate(_report(), comparison)
    report = _report()
    assert not EmphasisLossPolicy(1).evaluate(report, comparison)
    assert report.metrics["emphasis_quality_gate"]["changed_characters"] == 2
    assert not EmphasisLossPolicy(99).evaluate(_report(), compare_inspections(source, inspect([TextRun("different")])))


def test_emphasis_run_limit_disables_measurement_at_first_excess():
    inventory = EmphasisInventory()
    for index in range(MAX_EMPHASIS_RUNS):
        inventory.add(TextRun("x", style=TextStyle(bold=bool(index % 2))))
    assert len(inventory.to_dict()["runs"]) == MAX_EMPHASIS_RUNS
    inventory.add(TextRun("x", style=TextStyle(bold=False)))
    assert inventory.to_dict()["runs"] is None
    before = _inspect("text")
    before.metadata["text_emphasis"] = inventory.to_dict()
    report = _report()
    assert not EmphasisLossPolicy(99).evaluate(report, compare_inspections(before, copy.deepcopy(before)))
    assert report.metrics["emphasis_quality_gate"]["changed_characters"] is None


def test_unknown_inspection_does_not_claim_any_proven_loss_or_zero_measurement():
    comparison = compare_inspections(_inspect("text"), DocumentInspection(None, "unknown"))
    assert comparison.retention["characters"] == {"source": 4, "target": None, "delta": None, "ratio": None}
    assert not comparison.has_losses
    assert comparison.geometry_summary["available"] is False
    assert comparison.geometry_summary["max_dimension_error_pt"] is None
    assert comparison.resource_comparison["available"] is False
    assert comparison.package_comparison["available"] is False
    assert comparison.font_comparison["available"] is False
    assert comparison.font_comparison["missing_families"] is None


def test_page_addition_is_not_diagnosed_as_loss_of_source_pages():
    before = inspect_document_model(DocumentModel(sections=[Section()]))
    after = inspect_document_model(DocumentModel(sections=[Section(), Section()]))
    comparison = compare_inspections(before, after)
    assert comparison.retention["pages"]["ratio"] == 1
    assert not comparison.has_losses


@pytest.mark.parametrize("metric", ["text_characters", "emphasis_characters", "token_count"])
def test_corrupted_boolean_measurement_is_unavailable(metric):
    before, after = _inspect("a"), _inspect("b")
    if metric == "text_characters":
        after.objects[0]["text_characters"] = True
        policy = TextPreservationPolicy()
    elif metric == "emphasis_characters":
        after = copy.deepcopy(before)
        after.metadata["text_emphasis"]["characters"] = True
        policy = EmphasisLossPolicy()
    else:
        after.metadata["text_flow"]["token_count"] = True
        policy = TextPreservationPolicy("flow", 1)
    report = _report()
    assert not policy.evaluate(report, compare_inspections(before, after))
    assert next(iter(report.metrics.values()))["reason"] == "unavailable"


@pytest.mark.parametrize("delta", [0.5, 0.5004])
def test_page_dimension_and_margin_tolerance_uses_unrounded_values(delta):
    document = DocumentModel(sections=[Section()])
    target = copy.deepcopy(document)
    target.sections[0].page.width.pt += delta
    target.sections[0].page.margin_left.pt += delta
    comparison = compare_inspections(inspect_document_model(document), inspect_document_model(target))
    assert comparison.page_geometry[0]["same_size"] is (delta == 0.5)
    assert comparison.page_geometry[0]["same_margins"] is (delta == 0.5)


def test_element_geometry_changes_without_content_loss():
    source = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("text")], box=Box(0, 0, 10, 20))])])
    target = copy.deepcopy(source)
    target.sections[0].blocks[0].box = Box(3, 4, 10, 20, 90)
    comparison = compare_inspections(inspect_document_model(source), inspect_document_model(target))
    assert comparison.object_diff["changed"][0]["changes"] == ["geometry"]
    assert comparison.retention["characters"]["ratio"] == 1
    assert ObjectLossPolicy().evaluate(_report(), comparison)


def test_resource_and_package_hash_comparison_preserves_multiplicity():
    def inspect(count):
        return inspect_document_model(
            DocumentModel(
                resources={
                    str(index): Resource(str(index), ResourceKind.ATTACHMENT, "application/octet-stream", b"same")
                    for index in range(count)
                },
                package=PackageGraph(
                    "custom",
                    root="/",
                    parts={f"/{index}": PackagePart(f"/{index}", "application/octet-stream", b"") for index in range(count)},
                ),
            )
        )

    comparison = compare_inspections(inspect(3), inspect(2))
    for group in (comparison.resource_comparison, comparison.package_comparison):
        assert group["available"] is True
        assert group["exact_hash_matches"] == 2
        assert group["exact_hash_retention_ratio"] == 0.6667
        assert len(group["lost_resources"]) == 1
    assert comparison.package_comparison["exact_byte_retention_ratio"] == 1


def test_unhashed_external_resource_is_unknown_and_never_called_lost(tmp_path):
    path = tmp_path / "resource.bin"
    path.write_bytes(b"data")
    source = DocumentModel(
        resources={"asset": Resource("asset", ResourceKind.ATTACHMENT, "application/octet-stream", source=str(path))}
    )
    before, after = inspect_document_model(source), inspect_document_model(copy.deepcopy(source))
    assert before.valid and after.valid
    comparison = compare_inspections(before, after)
    group = comparison.resource_comparison
    assert group["available"] is False
    assert group["exact_hash_retention_ratio"] is None
    assert group["lost_resources"] == group["added_resources"] == []
    assert len(group["unmeasured_source_resources"]) == 1
    assert not any(issue.feature == "resource-loss" for issue in comparison.issues)


def test_fonts_normalize_aliases_and_account_for_run_substitutions():
    def inspect(names):
        return inspect_document_model(
            DocumentModel(
                sections=[Section(blocks=[Paragraph([TextRun("text", style=TextStyle(font_family=name)) for name in names])])]
            )
        )

    alias = compare_inspections(
        inspect(["ABCDEF+ArialMT", "arial", "TimesNewRomanPSMT"]), inspect(["Arial", "Arial", "Times New Roman"])
    )
    assert alias.font_comparison["exact_run_retention_ratio"] == 1
    comparison = compare_inspections(inspect(["Arial", "Arial", "Calibri"]), inspect(["Other", "Other", "Calibri"]))
    fonts = comparison.font_comparison
    assert fonts["preserved_runs"] == 1
    assert fonts["missing_families"] == {"Arial": 2}
    assert fonts["possible_substitutions"] == [{"source": "Arial", "target": "other", "runs": 2}]
    assert any(issue.feature == "font-substitution" and issue.severity is IssueSeverity.LOSS for issue in comparison.issues)
