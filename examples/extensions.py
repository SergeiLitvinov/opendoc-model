"""Persist consumer data and explicitly validate its version and semantics."""

from opendoc_model import (
    DiagnosticIssue,
    DocumentModel,
    ExtensionContext,
    ExtensionSchema,
    IssueSeverity,
    check_document,
    check_extensions,
    compare_documents,
    document_from_json,
    document_to_json,
    get_extension,
    set_extension,
)


def review(context: ExtensionContext):
    if not isinstance(context.data, dict) or type(context.data.get("approved")) is not bool:
        return [DiagnosticIssue("review.approved", IssueSeverity.ERROR, "expected a boolean", "approved")]
    return None


document = DocumentModel()
set_extension(document.metadata, "org.example.review", {"approved": True})
document.metadata["org.example.review"]["retained"] = "future envelope field"
schemas = [ExtensionSchema("org.example.review", frozenset({1}), review, frozenset({"metadata"}))]
restored = document_from_json(document_to_json(document))
assert restored == document
assert get_extension(restored.metadata, "org.example.review").extensions == {"retained": "future envelope field"}
assert check_extensions(restored, schemas).success
assert check_document(restored, extensions=schemas).success
assert compare_documents(document, restored, extensions=iter(schemas)).success
set_extension(restored.metadata, "org.example.review", {"approved": "yes"})
issue = check_extensions(restored, schemas).issues[0]
assert issue.code == "review.approved"
assert issue.location == "metadata['org.example.review'].data.approved"
assert not check_extensions(document, []).success
unverified = check_extensions(document, [], unknown="preserve")
assert unverified.success and unverified.metrics["extensions"]["unknown"] == 1
print("OpenDoc Model explicit extension validation example: OK")
