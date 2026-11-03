"""Consumer schemas never run implicitly, mutate model data or claim unknown versions."""

import json
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType

import pytest

from opendoc_model import (
    SECTION_CONTENT_FIELDS,
    ArtifactLimitError,
    DiagnosticIssue,
    DocumentLimits,
    DocumentModel,
    ExtensionSchema,
    Footnote,
    IssueSeverity,
    PackageGraph,
    Paragraph,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    check_document,
    check_extensions,
    clone_model,
    compare_documents,
    document_from_json,
    document_to_json,
    get_extension,
    remove_extension,
    set_extension,
)

KEY = "org.example.review"


def _document():
    document = DocumentModel(sections=[Section(blocks=[Paragraph([TextRun("text")])])])
    set_extension(document.metadata, KEY, {"rating": 3})
    return document


def test_extension_set_get_remove_are_independent_atomic_and_preserve_unknown_fields():
    bag = {}
    incoming = {"items": [1]}
    set_extension(bag, KEY, incoming, version=2)
    incoming["items"].append(2)
    assert get_extension(bag, KEY).data == {"items": [1]}
    bag[KEY]["vendor-extra"] = {"values": [3]}
    old = bag[KEY]
    value = get_extension(bag, KEY)
    value.data["items"].append(4)
    value.extensions["vendor-extra"]["values"].append(5)
    assert old["data"] == {"items": [1]} and old["vendor-extra"] == {"values": [3]}
    set_extension(bag, KEY, False, version=3)
    assert bag[KEY]["vendor-extra"] == {"values": [3]}
    assert old["version"] == 2
    before = deepcopy(bag)
    for data in (float("nan"), object(), (1,), {"cycle": None}):
        if isinstance(data, dict):
            data["cycle"] = data
        with pytest.raises(ValueError):
            set_extension(bag, KEY, data)
        assert bag == before
    with pytest.raises(ArtifactLimitError):
        set_extension(bag, KEY, "large", limits=DocumentLimits(max_nodes=1))
    assert bag == before
    remove_extension(bag, KEY)
    assert bag == {} and get_extension(bag, KEY) is None


@pytest.mark.parametrize(
    "key", ["review", "opendoc.heading", "opendoc.future", "Org.example", "org..example", "org.example/feature", "", 1]
)
def test_new_keys_must_use_owned_dotted_consumer_namespace(key):
    with pytest.raises(ValueError):
        set_extension({}, key, {})
    with pytest.raises(ValueError):
        ExtensionSchema(key, frozenset({1}))


@pytest.mark.parametrize(
    "versions", [set(), {1}, frozenset(), frozenset({True}), frozenset({0}), frozenset({1.0}), frozenset({"1"})]
)
def test_schemas_declare_strict_versions(versions):
    with pytest.raises(ValueError):
        ExtensionSchema(KEY, versions)


@pytest.mark.parametrize("version", [True, 0, -1, "1", None])
def test_envelope_versions_are_not_coerced(version):
    with pytest.raises(ValueError):
        set_extension({}, KEY, {}, version=version)
    document = _document()
    document.metadata[KEY]["version"] = version
    assert not check_extensions(document, [ExtensionSchema(KEY, frozenset({1}))]).success


@pytest.mark.parametrize("opaque", [None, 7, "legacy", {}, {"format": "other", "version": 1}])
def test_opaque_values_are_preserved_and_cannot_be_overwritten(opaque):
    document = DocumentModel(metadata={KEY: opaque})
    assert get_extension(document.metadata, KEY) is None
    for action in (lambda: set_extension(document.metadata, KEY, {}), lambda: remove_extension(document.metadata, KEY)):
        with pytest.raises(ValueError, match="opaque"):
            action()
    assert document_from_json(document_to_json(document)) == document
    result = check_extensions(document, [ExtensionSchema(KEY, frozenset({1}))])
    assert not result.success and result.issues[0].code == "extension.opaque"


def test_versions_scope_unknown_policy_and_explicit_no_hook_default():
    document = _document()
    assert check_document(document).success
    unknown = check_extensions(document, [])
    assert not unknown.success and unknown.issues[0].code == "extension.unknown"
    preserved = check_extensions(document, [], unknown="preserve")
    assert preserved.success and preserved.issues[0].severity is IssueSeverity.INFO
    assert preserved.issues[0].reason == "unknown-extension"
    unsupported = check_extensions(document, [ExtensionSchema(KEY, frozenset({2}))])
    assert not unsupported.success and unsupported.issues[0].code == "extension.unsupported-version"
    wrong_scope = check_extensions(document, [ExtensionSchema(KEY, frozenset({1}), scopes=frozenset({"properties"}))])
    assert not wrong_scope.success and wrong_scope.issues[0].code == "extension.scope"
    schema = ExtensionSchema(KEY, frozenset({1}))
    assert check_extensions(document, [schema]).success
    assert check_document(document, extensions=[schema]).success
    assert check_document(document, extensions=[]).success is False
    assert check_document(document, extensions=[], unknown_extensions="preserve").success
    assert document_from_json(document_to_json(document)) == document


def test_callbacks_receive_detached_data_and_return_bounded_independent_relative_diagnostics():
    document = _document()
    measurement = {"rating": [3]}
    contexts = []

    def validator(context):
        contexts.append(context)
        context.data["rating"] = 9
        return [DiagnosticIssue("org.example.rating", IssueSeverity.ERROR, "unsupported rating", "rating", measurement)]

    result = check_extensions(document, [ExtensionSchema(KEY, frozenset({1}), validator)])
    assert document.metadata[KEY]["data"] == {"rating": 3}
    assert contexts[0].location == f"metadata[{KEY!r}].data"
    assert contexts[0].scope == "metadata" and contexts[0].owner_type == "DocumentModel"
    assert result.issues[0].location == f"metadata[{KEY!r}].data.rating"
    measurement["rating"].append(4)
    assert result.issues[0].measurement == {"rating": [3]}
    assert not result.to_dict()["success"]


def test_every_property_and_metadata_carrier_is_visited_including_aliases_and_note_bodies():
    document = _document()
    for field in SECTION_CONTENT_FIELDS:
        run = TextRun("text")
        set_extension(run.properties, KEY, "run")
        set_extension(run.style.properties, KEY, "inline-style")
        paragraph = Paragraph([run, run])
        cell = TableCell([paragraph])
        row = TableRow([cell])
        table = Table([row])
        for owner in (paragraph, cell, row, table):
            set_extension(owner.properties, KEY, type(owner).__name__)
        getattr(document.sections[0], field).append(table)
    set_extension(document.sections[0].properties, KEY, "section")
    document.styles["named"] = TextStyle()
    set_extension(document.styles["named"].properties, KEY, "named-style")
    document.resources["asset"] = Resource("asset", ResourceKind.ATTACHMENT, "type", b"")
    set_extension(document.resources["asset"].properties, KEY, "resource")
    document.footnotes = [Footnote("note", [Paragraph([TextRun("body")])])]
    set_extension(document.footnotes[0].properties, KEY, "note-properties")
    set_extension(document.footnotes[0].extensions, KEY, "note-extra")
    set_extension(document.footnote_properties, KEY, "registry-properties")
    set_extension(document.footnote_extensions, KEY, "registry-extra")
    contexts = []
    result = check_extensions(document, [ExtensionSchema(KEY, frozenset({1}), lambda item: contexts.append(item))])
    assert result.success and result.metrics["extensions"]["checked"] == 64
    assert len(contexts) == 64
    assert len({context.location for context in contexts}) == 64
    assert any(context.location.startswith("footnotes[0].extensions") for context in contexts)
    assert any(context.location.startswith("resources['asset']") for context in contexts)
    assert document_from_json(document_to_json(document)) == document


def test_compare_document_callbacks_are_side_specific_and_schema_generator_is_consumed_once():
    document = _document()
    target = clone_model(document)
    set_extension(target.metadata, KEY, {"rating": 9})
    calls = []

    def validator(context):
        calls.append(context.data["rating"])
        if context.data["rating"] > 5:
            return [DiagnosticIssue("org.example.rating", IssueSeverity.ERROR, "too high")]
        return None

    result = compare_documents(document, target, extensions=(item for item in [ExtensionSchema(KEY, frozenset({1}), validator)]))
    assert calls == [3, 9]
    assert not result.success
    issue = next(item for item in result.issues if item.code == "org.example.rating")
    assert issue.location == f"target.metadata[{KEY!r}].data"
    assert result.metrics["extensions"]["source"]["checked"] == 1
    assert result.metrics["extensions"]["target"]["checked"] == 1


@pytest.mark.parametrize(
    "callback",
    [
        lambda context: 7,
        lambda context: ["not an issue"],
        lambda context: [DiagnosticIssue("bad", IssueSeverity.ERROR, "bad", measurement={"x": float("nan")})],
    ],
)
def test_invalid_callback_result_is_a_contract_error(callback):
    with pytest.raises(ValueError):
        check_extensions(_document(), [ExtensionSchema(KEY, frozenset({1}), callback)])


def test_callback_defects_propagate_and_never_become_success():
    document = _document()
    before = document_to_json(document)

    def validator(context):
        context.data.clear()
        raise RuntimeError("consumer defect")

    with pytest.raises(RuntimeError, match="consumer defect"):
        check_document(document, extensions=[ExtensionSchema(KEY, frozenset({1}), validator)])
    assert document_to_json(document) == before


def test_callbacks_and_schema_streams_are_bounded_and_invalid_models_skip_callbacks():
    document = _document()
    consumed = []

    def endless(context):
        while True:
            consumed.append(1)
            yield DiagnosticIssue("issue", IssueSeverity.INFO, "info")

    with pytest.raises(ArtifactLimitError):
        check_extensions(document, [ExtensionSchema(KEY, frozenset({1}), endless)], limits=DocumentLimits(max_nodes=30))
    assert len(consumed) <= 31

    def schemas():
        for index in range(1000):
            yield ExtensionSchema(f"org.example.key{index}", frozenset({1}))

    with pytest.raises(ArtifactLimitError):
        check_extensions(document, schemas(), limits=DocumentLimits(max_nodes=30))
    document.sections = None
    result = check_extensions(
        document, [ExtensionSchema(KEY, frozenset({1}), lambda context: pytest.fail("must skip invalid model"))]
    )
    assert not result.success and result.metrics["extensions"]["checked"] is None


def test_bad_manifest_and_readonly_mappings_are_rejected_without_mutation():
    schema = ExtensionSchema(KEY, frozenset({1}))
    for schemas in (None, [None], [schema, schema]):
        with pytest.raises(ValueError):
            check_extensions(_document(), schemas)
    with pytest.raises(ValueError):
        ExtensionSchema(KEY, frozenset({1}), validator="import.module")
    for scopes in (frozenset(), frozenset({"resource"}), {"metadata"}):
        with pytest.raises(ValueError):
            ExtensionSchema(KEY, frozenset({1}), scopes=scopes)
    for checker in (
        lambda: check_extensions(_document(), [], unknown="ignore"),
        lambda: check_document(_document(), unknown_extensions="ignore"),
        lambda: compare_documents(_document(), _document(), unknown_extensions="ignore"),
    ):
        with pytest.raises(ValueError):
            checker()
    bag = MappingProxyType({})
    with pytest.raises(ValueError):
        set_extension(bag, KEY, 1)
    with pytest.raises(ValueError):
        remove_extension(bag, KEY)


def test_json_roundtrip_keeps_legacy_unknowns_without_running_any_callback(monkeypatch):
    document = _document()
    document.metadata["legacy"] = {"arbitrary": [None, True, 0, "UTF-8 привет"]}
    document.metadata[KEY]["unknown"] = {"future": [1]}
    document.sections[0].blocks[0].properties["legacy"] = {"x": [2]}
    document.resources["remote"] = Resource("remote", ResourceKind.ATTACHMENT, "type", source="https://invalid.test")

    def fail(*args, **kwargs):
        raise AssertionError("unexpected external lookup")

    monkeypatch.setattr("pathlib.Path.stat", fail)
    monkeypatch.setattr("pathlib.Path.open", fail)
    assert document_from_json(document_to_json(document)) == document
    assert check_extensions(document, [ExtensionSchema(KEY, frozenset({1}))]).success
    assert check_document(document, extensions=[ExtensionSchema(KEY, frozenset({1}))]).success


def test_unknown_json_nodes_and_versions_and_runtime_types_cannot_silently_lose_state():
    payload = json.loads(document_to_json(_document()))
    payload["document"]["sections"][0]["blocks"][0]["type"] = "org.example.new-node"
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))
    payload["version"] = 999
    with pytest.raises(ValueError):
        document_from_json(json.dumps(payload))

    @dataclass
    class CustomParagraph(Paragraph):
        value: str = "state"

    document = DocumentModel(sections=[Section(blocks=[CustomParagraph()])])
    issue = next(item for item in check_document(document).issues if item.code == "model.type.unsupported")
    assert issue.location == "sections[0].blocks[0]"
    with pytest.raises(ValueError, match="unsupported serialized model type"):
        document_to_json(document)
    document.sections[0].blocks = [Paragraph()]
    document.sections[0].blocks[0].custom = "state"
    assert any(item.code == "model.state.unsupported" for item in check_document(document).issues)
    with pytest.raises(ValueError, match="extra model state"):
        document_to_json(document)
    graph = PackageGraph("custom", root="/")
    graph.custom = "state"
    assert graph.validate() and not check_document(DocumentModel(package=graph)).success


def test_builtin_namespace_is_reserved_and_wrong_carrier_declarations_are_explicit_errors():
    document = DocumentModel(metadata={"opendoc.heading": {"format": "opendoc.heading", "version": 1, "level": 1}})
    result = check_extensions(document, [])
    assert not result.success and result.issues[0].code == "extension.builtin-scope"
    document.metadata = {"opendoc.future": {"format": "opendoc.future", "version": 99, "data": {}}}
    result = check_extensions(document, [])
    assert not result.success and result.issues[0].code == "extension.unknown"
    assert check_extensions(document, [], unknown="preserve").issues[0].reason == "unknown-extension"
