"""A missing measurement cannot satisfy a selected strict object policy."""

from opendoc_model import DocumentModel, MatchingLimits, ObjectLossPolicy, Paragraph, Section, TextRun, compare_documents

document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("kept")])])])
unknown = compare_documents(document, document, matching_limits=MatchingLimits(max_work=0))
diff = unknown.metrics["comparison"]["object_diff"]
assert not diff["available"] and diff["retention_ratio"] is None
assert diff["lost"] == [] and diff["retained"] == []
assert diff["reason"] == "matching-budget-exceeded"
strict = compare_documents(document, document, matching_limits=MatchingLimits(0), policies=[ObjectLossPolicy()])
assert not strict.success and strict.metrics["object_quality_gate"]["reason"] == "unavailable"
complete = compare_documents(document, document, matching_limits=MatchingLimits(100), policies=[ObjectLossPolicy()])
assert complete.success and complete.metrics["object_quality_gate"]["verified"]
print("OpenDoc Model bounded matching and unavailable evidence example: OK")
