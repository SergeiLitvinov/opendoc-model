"""Memory checks expose codes, exact paths and policy reasons without I/O."""

import json
from itertools import repeat
from pathlib import Path

import pytest

from opendoc_model import (
    ArtifactLimitError,
    CheckResult,
    ConversionReport,
    DiagnosticIssue,
    DocumentLimits,
    DocumentModel,
    EmphasisLossPolicy,
    Formula,
    FormulaFormat,
    FormulaLossPolicy,
    Image,
    IssueSeverity,
    ObjectLossPolicy,
    Paragraph,
    QualityPolicy,
    Resource,
    ResourceKind,
    Section,
    TextPreservationPolicy,
    TextRun,
    TextStyle,
    check_document,
    compare_documents,
    compare_inspections,
    inspect_document_model,
)


def _document(text="text", bold=False):
    return DocumentModel(sections=[Section(blocks=[Paragraph([TextRun(text, TextStyle(bold=bold))])])])


def test_structural_check_and_json_snapshot_have_no_destination():
    document = _document()
    document.metadata = {"custom": {"values": [1]}}
    result = check_document(document)
    assert result.success and result.lossless
    payload = result.to_dict()
    assert payload["format"] == "opendoc.check" and payload["version"] == 1
    assert "output_path" not in payload
    assert json.loads(json.dumps(payload, ensure_ascii=False)) == payload
    assert payload["metrics"]["inspection"]["metrics"]["characters"] == 4
    document.metadata["custom"]["values"].append(2)
    assert result.metrics["inspection"]["metadata"]["custom"]["values"] == [1]
    payload["metrics"]["inspection"]["metadata"]["custom"]["values"].append(3)
    assert result.metrics["inspection"]["metadata"]["custom"]["values"] == [1]


def test_missing_reference_has_code_exact_field_and_identifier():
    document = DocumentModel(sections=[Section(blocks=[Image("missing")])])
    result = check_document(document)
    assert not result.success and not result.lossless
    assert result.metrics["inspection"]["metrics"] == {}
    issue = result.issues[0]
    assert issue.code == "model.reference.missing"
    assert issue.location == "sections[0].blocks[0].resource_id"
    assert issue.measurement == {"kind": "resource", "identifier": "missing"}
    assert issue.reason == "invalid-input"
    assert "resource_id" in inspect_document_model(document).issues[0].location


def test_extension_key_containing_colon_does_not_corrupt_location():
    document = _document()
    document.metadata["custom: data"] = [object()]
    issue = check_document(document).issues[0]
    assert issue.code == "json.invalid"
    assert issue.location == "metadata['custom: data'][0]"
    assert inspect_document_model(document).issues[0].location == issue.location
    assert "custom: data" in document.validate()[0]


@pytest.mark.parametrize(
    "mutation,code,path",
    [
        ("cycle", "model.cycle", "$.metadata['self']"),
        ("mapping-key", "model.mapping-key", "$.metadata"),
        ("style-cycle", "model.style.cycle", "styles['a'].properties.base_style_id"),
        ("utf8", "json.utf8", "sections[0].blocks[0].content[0].text"),
        ("wrong-sections", "model.invalid", "sections"),
    ],
)
def test_structured_failures_are_not_message_parsing(mutation, code, path):
    document = _document()
    if mutation == "cycle":
        document.metadata["self"] = document.metadata
    elif mutation == "mapping-key":
        document.metadata[1] = "value"
    elif mutation == "style-cycle":
        document.styles["a"] = TextStyle(properties={"base_style_id": "a"})
    elif mutation == "utf8":
        document.sections[0].blocks[0].content[0].text = "\ud800"
    else:
        document.sections = None
    result = check_document(document)
    assert not result.success
    assert any(issue.code == code and issue.location == path for issue in result.issues)


def test_wrong_model_and_budget_errors_are_distinct():
    result = check_document(None)
    assert result.issues[0].code == "model.type" and result.issues[0].location == "document"
    with pytest.raises(ArtifactLimitError):
        check_document(_document(), limits=DocumentLimits(max_nodes=1))
    with pytest.raises(ValueError, match="limits"):
        check_document(_document(), limits=3)


def test_memory_checks_do_not_stat_or_open_external_sources(monkeypatch):
    document = DocumentModel(
        resources={"external": Resource("external", ResourceKind.ATTACHMENT, "type", source="https://invalid.test/file")}
    )
    for name in ("open", "stat", "is_file"):
        monkeypatch.setattr(Path, name, lambda *args, **kwargs: pytest.fail("Unexpected filesystem lookup"))
    result = check_document(document)
    assert result.success
    resource = result.metrics["inspection"]["resources"][0]
    assert resource["size_bytes"] is None and resource["sha256"] is None and resource["source_exists"] is None
    comparison = compare_documents(document, document)
    assert comparison.success
    measurement = comparison.metrics["comparison"]["resource_comparison"]
    assert measurement["source_bytes"] is None and measurement["exact_byte_retention_ratio"] is None
    issue = next(issue for issue in comparison.issues if issue.location == "comparison.resources")
    assert issue.code == "measurement.unavailable" and issue.reason == "external-data-not-loaded"


def test_legacy_inspection_filesystem_behavior_remains_opt_in_default(tmp_path):
    document = DocumentModel(resources={"r": Resource("r", ResourceKind.ATTACHMENT, "type", source=str(tmp_path / "missing"))})
    assert not inspect_document_model(document).valid
    assert inspect_document_model(document, check_external_sources=False).valid
    with pytest.raises(ValueError):
        inspect_document_model(document, check_external_sources=None)


@pytest.mark.parametrize(
    "policy,key",
    [
        (TextPreservationPolicy(), "text_quality_gate"),
        (TextPreservationPolicy("flow"), "text_quality_gate"),
        (TextPreservationPolicy("flow", 1), "text_quality_gate"),
        (ObjectLossPolicy(), "object_quality_gate"),
        (FormulaLossPolicy(), "formula_quality_gate"),
        (EmphasisLossPolicy(), "emphasis_quality_gate"),
        (QualityPolicy(), "quality_gate"),
    ],
)
def test_every_policy_accepts_memory_result_and_retains_legacy_outcome(policy, key):
    document = _document()
    before = inspect_document_model(document)
    comparison = compare_inspections(before, before)
    legacy, memory = ConversionReport(Path("result.json")), CheckResult()
    if isinstance(policy, QualityPolicy):
        assert policy.evaluate(legacy) is policy.evaluate(memory)
    else:
        assert policy.evaluate(legacy, comparison) is policy.evaluate(memory, comparison)
    assert legacy.metrics[key] == memory.metrics[key]
    result = compare_documents(document, document, policies=[policy])
    assert result.success and result.metrics[key]["accepted"]


def test_loss_is_not_error_until_explicit_policy_rejects():
    source, target = _document("long text"), DocumentModel()
    result = compare_documents(source, target)
    assert result.success and not result.lossless
    assert any(issue.code == "retention-characters" and issue.measurement["source"] == 9 for issue in result.issues)
    strict = compare_documents(source, target, policies=[TextPreservationPolicy(), QualityPolicy()])
    assert not strict.success
    issue = next(issue for issue in strict.issues if issue.code == "text-quality")
    assert issue.reason == "text-changed-or-removed"
    assert issue.measurement["unmatched_source_paragraphs"] == 1
    assert next(issue for issue in strict.issues if issue.code == "quality-budget").reason == "budget-exceeded"


def test_policy_unavailability_and_measurement_snapshot_are_machine_readable():
    source = _document()
    source.sections[0].blocks.append(Formula("x", FormulaFormat.MATHML))
    result = compare_documents(source, source, policies=[FormulaLossPolicy()])
    issue = next(issue for issue in result.issues if issue.code == "formula-quality")
    assert issue.reason == "unavailable" and issue.measurement["changed_formulas"] is None
    result.metrics["formula_quality_gate"]["reason"] = "changed-after-evaluation"
    assert issue.reason == "unavailable" and issue.measurement["reason"] == "unavailable"


def test_comparison_retains_both_sides_of_invalid_model_and_rejects_strict_unknown():
    source = _document()
    source.sections[0].blocks[0].style_id = "missing"
    target = _document()
    target.sections[0].blocks[0].content[0].text = False
    result = compare_documents(source, target, policies=[TextPreservationPolicy()])
    assert not result.success
    assert any(issue.location == "source.sections[0].blocks[0].style_id" for issue in result.issues)
    assert any(issue.location == "target.sections[0].blocks[0].content[0].text" for issue in result.issues)
    assert result.metrics["comparison"]["retention"]["characters"]["ratio"] is None
    assert next(issue for issue in result.issues if issue.code == "text-quality").reason == "unavailable"
    assert any(issue.reason == "invalid-model" for issue in result.issues)


def test_policy_iterables_are_validated_bounded_and_do_not_guess_defaults():
    document = _document()
    for policies in ("policy", 1, [object()]):
        with pytest.raises(ValueError):
            compare_documents(document, document, policies=policies)
    with pytest.raises(ArtifactLimitError, match="policies"):
        compare_documents(document, document, policies=repeat(QualityPolicy()), limits=DocumentLimits(max_nodes=100))
    assert not any(key.endswith("_gate") for key in compare_documents(document, document).metrics)


def test_result_serialization_validates_json_and_does_not_alias_values():
    result = CheckResult([DiagnosticIssue("test", IssueSeverity.INFO, "detail", measurement={"values": [1]})])
    payload = result.to_dict()
    payload["issues"][0]["measurement"]["values"].append(2)
    assert result.issues[0].measurement == {"values": [1]}
    result.metrics["cycle"] = result.metrics
    with pytest.raises(ValueError, match="cyclic"):
        result.to_dict()
    result.metrics = {"invalid": object()}
    with pytest.raises(ValueError):
        result.to_dict()
    with pytest.raises(ArtifactLimitError):
        CheckResult().to_dict(limits=DocumentLimits(max_nodes=1))


@pytest.mark.parametrize("kwargs", [{"code": ""}, {"severity": "error"}, {"location": 1}, {"measurement": []}, {"reason": ""}])
def test_invalid_issue_fields(kwargs):
    values = {"code": "test", "severity": IssueSeverity.ERROR, "message": "detail", **kwargs}
    with pytest.raises(ValueError):
        DiagnosticIssue(**values)
