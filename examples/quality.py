"""Independent quality decisions: text, objects, emphasis, formulas and losses."""

from opendoc_model import (
    CheckResult,
    DocumentModel,
    EmphasisLossPolicy,
    Formula,
    FormulaFormat,
    FormulaLossPolicy,
    IssueSeverity,
    ObjectLossPolicy,
    Paragraph,
    Provenance,
    QualityPolicy,
    Section,
    TextPreservationPolicy,
    TextRun,
    TextStyle,
    clone_model,
    compare_documents,
)

run = TextRun("one two", provenance=Provenance("example", object_id="run"))
paragraph = Paragraph([run], provenance=Provenance("example", object_id="paragraph"))
source = DocumentModel(sections=[Section(blocks=[paragraph])])
same = compare_documents(
    source, clone_model(source), policies=[ObjectLossPolicy(), TextPreservationPolicy(), EmphasisLossPolicy()]
)
assert same.success
edited = clone_model(source)
edited.sections[0].blocks[0].content[0].text = "one three"
# The origin proves the object exists; a separate policy decides text preservation.
assert compare_documents(source, edited, policies=[ObjectLossPolicy()]).success
assert not compare_documents(source, edited, policies=[TextPreservationPolicy()]).success
accepted = compare_documents(source, edited, policies=[TextPreservationPolicy(mode="flow", max_text_edits=1)])
assert accepted.success and accepted.metrics["text_quality_gate"]["text_edits"] == 1
styled = clone_model(source)
styled.sections[0].blocks[0].content[0].style = TextStyle(bold=True)
strict = compare_documents(source, styled, policies=[EmphasisLossPolicy()])
assert not strict.success and strict.metrics["emphasis_quality_gate"]["changed_characters"] == 6
assert compare_documents(source, styled, policies=[EmphasisLossPolicy(6)]).success
formulas = DocumentModel(sections=[Section(blocks=[Formula("x", FormulaFormat.LATEX)])])
changed = clone_model(formulas)
changed.sections[0].blocks[0].value = "y"
assert not compare_documents(formulas, changed, policies=[FormulaLossPolicy()]).success
assert compare_documents(formulas, changed, policies=[FormulaLossPolicy(1)]).success
reported = CheckResult()
reported.add(IssueSeverity.LOSS, "consumer.loss", "Explicitly reported loss")
assert QualityPolicy(1).evaluate(reported)
assert reported.metrics["quality_gate"]["visual_score"] is None
assert not QualityPolicy().evaluate(reported)
print("Quality decisions: independent objects/text, bounded edits, emphasis, formulas and reported losses OK")
