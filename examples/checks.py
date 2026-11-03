"""Check and compare models in memory with machine-readable diagnostics."""

import json

from opendoc_model import (
    DocumentModel,
    Paragraph,
    Section,
    TextPreservationPolicy,
    TextRun,
    check_document,
    clone_model,
    compare_documents,
)

source = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("Original text")])])])
assert check_document(source).success
target = clone_model(source)
target.sections[0].blocks[0].content[0].text = "Changed text"
result = compare_documents(source, target, policies=[TextPreservationPolicy()])
assert not result.success
issue = next(issue for issue in result.issues if issue.code == "text-quality")
assert issue.reason == "text-changed-or-removed"
assert issue.measurement["unmatched_source_paragraphs"] == 1
payload = json.loads(json.dumps(result.to_dict(), ensure_ascii=False))
assert "output_path" not in payload
assert payload["format"] == "opendoc.check" and payload["version"] == 1
target.sections[0].blocks[0].style_id = "missing"
invalid = check_document(target)
issue = next(issue for issue in invalid.issues if issue.code == "model.reference.missing")
assert issue.location == "sections[0].blocks[0].style_id"
assert issue.measurement["identifier"] == "missing"
print("OpenDoc Model memory checks example: OK")
