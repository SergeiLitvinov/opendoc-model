"""Cross-format contracts: complete corpus, edits, reference closure and failure atomicity."""

from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

import pytest

from opendoc_model import (
    INTEGRATION_PROPERTY,
    Accessibility,
    AffineTransform,
    Anchor,
    Annotation,
    ArtifactLimitError,
    BibliographyEntry,
    CapabilityProfile,
    Chart,
    ChartAxis,
    ChartSeries,
    ColorValue,
    Comment,
    ContentControl,
    DiagnosticIssue,
    Diagram,
    DocumentLimits,
    DocumentModel,
    DocumentPage,
    ExtensionMigration,
    ExtensionSchema,
    FeatureCapability,
    Field,
    FormControl,
    Formula,
    FormulaFormat,
    FormulaTree,
    IntegrationModel,
    IssueSeverity,
    MathNode,
    MediaObject,
    Paint,
    Paragraph,
    PathCommand,
    PreservationRecord,
    PreservationState,
    Provenance,
    Resource,
    ResourceKind,
    Revision,
    SceneStyle,
    Section,
    Sheet,
    SheetCell,
    SourceFile,
    SourceMap,
    SourceMapping,
    SourceSpan,
    TextPosition,
    TextRange,
    TextRun,
    Timing,
    UnknownFragment,
    VectorGroup,
    VectorPath,
    VectorScene,
    Workbook,
    check_document,
    check_extensions,
    clone_model,
    document_from_json,
    document_to_json,
    edit_anchored_text,
    extract_document,
    get_extension,
    get_integration,
    integration_resource_uses,
    iter_elements,
    merge_documents,
    migrate_extension,
    negotiate_capabilities,
    preservation_result,
    remove_node,
    remove_resource,
    resolve_scene_style,
    set_anchor,
    set_extension,
    set_integration,
    transform_elements,
)


@pytest.fixture
def corpus():
    first, second = TextRun("A😀BC"), TextRun("second")
    formula = Formula("x/y", FormulaFormat.LATEX)
    paragraph = Paragraph([first, second, formula])
    for node, identifier in ((first, "t1"), (second, "t2"), (formula, "math"), (paragraph, "p")):
        set_anchor(node, Anchor(identifier))
    original = b"\\unknown{x}"
    document = DocumentModel(
        sections=[Section([paragraph])],
        resources={
            "source": Resource("source", ResourceKind.ATTACHMENT, "text/x-tex", data=original),
            "preview": Resource("preview", ResourceKind.RASTER_IMAGE, "image/png", data=b"preview"),
            "audio": Resource("audio", ResourceKind.ATTACHMENT, "audio/ogg", data=b"audio"),
        },
    )
    span = SourceSpan("tex", 0, len(original), line=1, column=1, expansion_id="macro")
    profile = CapabilityProfile("finite-input", 1, (FeatureCapability("text"), FeatureCapability("graphics")))
    model = IntegrationModel(
        profiles=(profile,),
        assessed_features=("text", "graphics"),
        assessment_complete=True,
        preservation=(
            PreservationRecord(DiagnosticIssue("text", IssueSeverity.INFO, "editable"), PreservationState.SEMANTIC, "p"),
            PreservationRecord(
                DiagnosticIssue("graphics", IssueSeverity.WARNING, "preview", reason="unsupported-paint"),
                PreservationState.VISUAL,
                "p",
                Provenance("tex", object_id="original"),
            ),
        ),
        source_map=SourceMap(
            sources=(
                SourceFile(
                    "tex",
                    "file:///inert.tex",
                    "byte",
                    resource_id="source",
                    sha256=sha256(original).hexdigest(),
                    size=len(original),
                ),
            ),
            mappings=(SourceMapping("p", (span,)),),
            expansions=(SourceSpan("tex", 0, len(original), object_id="macro"),),
        ),
        unknown_fragments=(UnknownFragment("unknown", "source", "text/x-tex", 100, node_id="p", source=span),),
        ranges=(
            TextRange("selection", TextPosition("t1", 0, "before"), TextPosition("t1", 4, "after")),
            TextRange("cross", TextPosition("t1", 1), TextPosition("t2", 2)),
        ),
        fields=(
            Field("reference", "reference", code="NEVER EXECUTE", target_id="p"),
            Field("citation", "citation", range_id="selection", bibliography_ids=("book",)),
        ),
        bibliography=(BibliographyEntry("book", "Title", ("Author",), "2026", {"doi": "inert"}),),
        comments=(Comment("comment", "selection", "hello"), Comment("reply", "cross", "reply", reply_to="comment")),
        revisions=(Revision("revision", "selection", "insert"),),
        content_controls=(ContentControl("control", "cross", "choice", ("one", "two")),),
        scenes=(
            VectorScene(
                "vector",
                100,
                100,
                paths=(
                    VectorPath(
                        "path",
                        (PathCommand("move", (0, 0)), PathCommand("line", (10, 10)), PathCommand("close")),
                        Paint(ColorValue.from_hex("#ff0000")),
                        transform=AffineTransform(e=3),
                    ),
                ),
                groups=(VectorGroup("group", ("path",), mask_resource_id="preview"),),
                roots=("group",),
                node_id="p",
            ),
        ),
        scene_styles=(SceneStyle("theme", {"fill": "red"}, layer="theme"), SceneStyle("local", {"stroke": "black"}, "theme")),
        charts=(
            Chart(
                "chart",
                "bar",
                (ChartSeries("series", (1, None, 3), ("a", "b", "c")),),
                (ChartAxis("x", "category"),),
                node_id="p",
                style_id="local",
                visual_resource_id="preview",
            ),
        ),
        diagrams=(Diagram("diagram", "vector", (("group", "path"),), node_id="p"),),
        pages=(DocumentPage("page", 595, 842, ("p", "t1", "t2", "math")),),
        accessibility=(Accessibility("p", "paragraph", language="ru"),),
        annotations=(Annotation("annotation", "page", "link", target="https://invalid", action={"script": "inert"}),),
        forms=(FormControl("form", "page", "button", action={"execute": "inert"}),),
        media=(MediaObject("sound", "audio", "audio", "p", 10, "preview"),),
        timing=(Timing("time", "sound", 0, 10),),
        workbooks=(
            Workbook(
                "workbook",
                (
                    Sheet(
                        "sheet",
                        "Sheet 1",
                        (
                            SheetCell(0, 0, True, row_span=2),
                            SheetCell(0, 1, 1, formula="=INERT()", style_id="local"),
                            SheetCell(2, 0, "text"),
                        ),
                    ),
                ),
            ),
        ),
        formula_trees=(
            FormulaTree(
                "math", MathNode("fraction", children=(MathNode("identifier", "x"), MathNode("identifier", "y"))), ("source",)
            ),
        ),
        extra={"future": {"preserved": True}},
    )
    set_integration(document, model)
    return document, model


def test_full_corpus_roundtrip_and_standalone_validation(corpus):
    document, model = corpus
    restored = document_from_json(document_to_json(document))
    assert restored.validate() == []
    assert check_document(restored).success
    assert check_extensions(restored, []).success
    assert get_integration(restored) == model
    assert get_integration(clone_model(document)) == model
    assert get_integration(restored).workbooks[0].sheets[0].cells[0].value is True
    assert get_integration(restored).forms[0].action == {"execute": "inert"}
    restored.metadata[INTEGRATION_PROPERTY]["data"]["future"]["preserved"] = False
    assert get_integration(document).extra["future"]["preserved"] is True


def test_unknown_envelope_and_nested_fields_survive(corpus):
    document, _ = corpus
    raw = document.metadata[INTEGRATION_PROPERTY]
    raw["vendor"] = {"keep": 1}
    raw["data"]["pages"][0]["future"] = ["opaque"]
    model = get_integration(document)
    set_integration(document, model)
    assert raw is not document.metadata[INTEGRATION_PROPERTY]
    assert document.metadata[INTEGRATION_PROPERTY]["vendor"] == {"keep": 1}
    assert get_integration(document).pages[0].extra == {"future": ["opaque"]}


@pytest.mark.parametrize("state", list(PreservationState))
def test_preservation_is_not_empty_issues_or_opaque_lossless(state):
    issue = DiagnosticIssue("text", IssueSeverity.INFO, "checked", reason="explicit")
    model = IntegrationModel(
        preservation=(PreservationRecord(issue, state),), assessed_features=("text",), assessment_complete=True
    )
    result = preservation_result(model)
    assert result.lossless is (state is PreservationState.SEMANTIC)
    assert result.success is (state is not PreservationState.REJECTED)
    assert not preservation_result(IntegrationModel()).lossless
    assert not preservation_result(replace(model, assessed_features=("text", "unreported"))).lossless


def test_negotiation_versions_states_and_absence():
    source = CapabilityProfile(
        "in",
        1,
        (FeatureCapability("text"), FeatureCapability("vector", (PreservationState.VISUAL,)), FeatureCapability("unknown")),
    )
    target = CapabilityProfile(
        "out",
        2,
        (
            FeatureCapability("text", schema_version=2),
            FeatureCapability("vector", (PreservationState.VISUAL, PreservationState.OPAQUE)),
        ),
    )
    assert negotiate_capabilities(source, target) == {"text": (), "vector": (PreservationState.VISUAL,), "unknown": ()}


def test_unicode_edit_remaps_cross_run_ranges_without_changing_source_snapshot(corpus):
    document, original = corpus
    edited = edit_anchored_text(document, "t1", 1, 3, "💠")
    assert next(iter_elements(edited, TextRun)).node.text == "A💠C"
    assert get_integration(edited).ranges[0].end.offset == 3
    assert get_integration(edited).ranges[1].start.offset == 2
    assert get_integration(edited).ranges[1].end.offset == 2
    assert get_integration(edited).source_map == original.source_map
    assert get_integration(document) == original
    assert next(iter_elements(document, TextRun)).node.text == "A😀BC"
    assert document_from_json(document_to_json(edited)).validate() == []


@pytest.mark.parametrize("affinity,expected", [("before", 1), ("after", 3)])
def test_zero_length_anchor_affinity_on_insert(corpus, affinity, expected):
    document, model = corpus
    point = TextPosition("t1", 1, affinity)
    set_integration(document, replace(model, ranges=(*model.ranges, TextRange("cursor", point, point))))
    edited = edit_anchored_text(document, "t1", 1, 1, "XX")
    cursor = get_integration(edited).ranges[-1]
    assert cursor.start.offset == cursor.end.offset == expected


def test_structural_edits_reject_dangling_ranges_atomically(corpus):
    document, _ = corpus
    before = document_to_json(document)
    with pytest.raises(ValueError, match="integration"):
        remove_node(document, next(iter_elements(document, TextRun)))
    assert document_to_json(document) == before

    def change(location):
        location.node.text = "same length but different"
        return location.node

    with pytest.raises(ValueError, match="edit_anchored_text"):
        transform_elements(document, TextRun, change)
    assert document_to_json(document) == before


def test_resource_retention_redirect_and_failed_digest_redirect(corpus):
    document, _ = corpus
    assert integration_resource_uses(document, "preview")
    before = document_to_json(document)
    with pytest.raises(ValueError, match="used"):
        remove_resource(document, "preview")
    with pytest.raises(ValueError):
        remove_resource(document, "source", replacement_id="preview")
    assert document_to_json(document) == before
    document.add_resource(Resource("new-preview", ResourceKind.RASTER_IMAGE, "image/png", data=b"new"))
    remove_resource(document, "preview", replacement_id="new-preview")
    assert integration_resource_uses(document, "new-preview")
    assert get_integration(document).charts[0].visual_resource_id == "new-preview"
    assert document.validate() == []


def test_extraction_closes_adapter_dependencies_and_merge_remaps(corpus):
    document, model = corpus
    selected = extract_document(document, next(iter_elements(document, TextRun)))
    assert get_integration(selected) == model
    assert set(selected.resources) == set(document.resources)
    other = deepcopy(document)
    other.metadata.pop(INTEGRATION_PROPERTY)
    merged = merge_documents([other, document], conflicts="rename")
    result = merged.document
    assert result.validate() == []
    assert get_integration(result).ranges[0].start.node_id == "t1~2"
    assert get_integration(result).media[0].resource_id == "audio~2"
    assert get_integration(result).source_map.sources[0].resource_id == "source~2"


def test_style_inheritance_and_independent_result(corpus):
    _, model = corpus
    assert resolve_scene_style(model, "local") == {"fill": "red", "stroke": "black"}
    model.scene_styles[0].properties["nested"] = {"value": 1}
    result = resolve_scene_style(model, "local")
    result["nested"]["value"] = 2
    assert model.scene_styles[0].properties["nested"] == {"value": 1}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: replace(m, ranges=(replace(m.ranges[0], start=TextPosition("missing", 0)),)),
        lambda m: replace(m, ranges=(replace(m.ranges[0], end=TextPosition("t1", 99)),)),
        lambda m: replace(m, ranges=(TextRange("bad", TextPosition("t2", 1), TextPosition("t1", 0)),)),
        lambda m: replace(
            m, preservation=(replace(m.preservation[1], issue=DiagnosticIssue("graphics", IssueSeverity.INFO, "x")),)
        ),
        lambda m: replace(m, source_map=replace(m.source_map, sources=(replace(m.source_map.sources[0], sha256="0" * 64),))),
        lambda m: replace(
            m, source_map=replace(m.source_map, expansions=(SourceSpan("tex", 0, 1, object_id="macro", expansion_id="macro"),))
        ),
        lambda m: replace(m, unknown_fragments=(replace(m.unknown_fragments[0], max_bytes=0),)),
        lambda m: replace(m, unknown_fragments=(replace(m.unknown_fragments[0], export_policy="visual"),)),
        lambda m: replace(m, fields=(Field("bad", "citation", bibliography_ids=("missing",)),)),
        lambda m: replace(m, comments=(Comment("bad", "selection", "x", reply_to="bad"),)),
        lambda m: replace(m, scenes=(replace(m.scenes[0], width=float("nan")),)),
        lambda m: replace(m, scenes=(replace(m.scenes[0], groups=(VectorGroup("group", ("group",)),)),)),
        lambda m: replace(m, scenes=(replace(m.scenes[0], paths=(VectorPath("path", (PathCommand("line", (0, 1)),)),)),)),
        lambda m: replace(m, scenes=(replace(m.scenes[0], paths=(VectorPath("path", (PathCommand("move", (0,)),)),)),)),
        lambda m: replace(m, scene_styles=(SceneStyle("cycle", {}, "cycle"),)),
        lambda m: replace(m, charts=(replace(m.charts[0], series=(ChartSeries("x", (1,), ("a", "b")),)),)),
        lambda m: replace(m, pages=(replace(m.pages[0], reading_order=("missing",)),)),
        lambda m: replace(m, forms=(replace(m.forms[0], page_id="missing"),)),
        lambda m: replace(m, timing=(replace(m.timing[0], after_id="time"),)),
        lambda m: replace(m, workbooks=(Workbook("w", (Sheet("s", "x", (SheetCell(0, 0, row_span=2), SheetCell(1, 0))),)),)),
        lambda m: replace(m, formula_trees=(FormulaTree("math", MathNode("fraction", children=(MathNode("text", "x"),))),)),
        lambda m: replace(m, extra={"pages": "shadow"}),
    ],
)
def test_invalid_semantics_and_quotas_do_not_mutate_document(corpus, mutation):
    document, model = corpus
    original_metadata = document.metadata
    before = document_to_json(document)
    with pytest.raises((ValueError, ArtifactLimitError)):
        set_integration(document, mutation(model))
    assert document.metadata is original_metadata
    assert document_to_json(document) == before


def test_typed_payload_rejects_bool_offsets_future_versions_and_nonfinite(corpus):
    document, _ = corpus
    raw = document.metadata[INTEGRATION_PROPERTY]
    raw["data"]["ranges"][0]["start"]["offset"] = True
    assert document.validate()
    with pytest.raises(ValueError):
        document_to_json(document)
    raw["version"] = 99
    with pytest.raises(ValueError, match="version"):
        get_integration(document)


def test_bounded_ast_cycles_depth_commands_and_opaque_collision(corpus):
    document, model = corpus
    with pytest.raises(ArtifactLimitError):
        set_integration(document, model, limits=DocumentLimits(max_nodes=50))
    node = MathNode("row")
    for _ in range(30):
        node = MathNode("row", children=(node,))
    with pytest.raises(ArtifactLimitError):
        set_integration(document, replace(model, formula_trees=(FormulaTree("math", node),)), limits=DocumentLimits(max_depth=20))
    model.extra["cycle"] = model.extra
    with pytest.raises(ValueError, match="cyclic"):
        set_integration(document, model)
    opaque = DocumentModel(metadata={INTEGRATION_PROPERTY: "old opaque value"})
    with pytest.raises(ValueError, match="opaque"):
        set_integration(opaque, IntegrationModel())
    assert opaque.metadata[INTEGRATION_PROPERTY] == "old opaque value"


def test_explicit_migration_chain_preserves_unknown_and_is_atomic():
    bag = {}
    set_extension(bag, "adapter.feature", {"old": 1})
    bag["adapter.feature"]["unknown"] = ["retain"]
    steps = [
        ExtensionMigration("adapter.feature", 1, 2, lambda value: {"new": value.data["old"]}),
        ExtensionMigration("adapter.feature", 2, 3, lambda value: {"new": value.data["new"], "flag": True}),
    ]
    result = migrate_extension(bag, "adapter.feature", 3, steps, schema=ExtensionSchema("adapter.feature", frozenset({3})))
    assert result.data == {"new": 1, "flag": True}
    assert result.extensions == {"unknown": ["retain"]}
    assert get_extension(bag, "adapter.feature").version == 3
    before = deepcopy(bag)

    def fail(value):
        value.data["new"] = 99
        raise RuntimeError("trusted callback failed")

    with pytest.raises(RuntimeError):
        migrate_extension(bag, "adapter.feature", 4, [ExtensionMigration("adapter.feature", 3, 4, fail)])
    assert bag == before
    with pytest.raises(ValueError, match="chain"):
        migrate_extension(bag, "adapter.feature", 5, steps)
    with pytest.raises(ValueError, match="ambiguous"):
        migrate_extension(bag, "adapter.feature", 3, [steps[0], steps[0]])
    assert bag == before


def test_opaque_source_does_not_fetch_external_resource_and_snapshot_ids_close_dependencies():
    first, target = TextRun("first"), Paragraph([TextRun("target")])
    set_anchor(first, Anchor("first"))
    set_anchor(target, Anchor("target"))
    document = DocumentModel(sections=[Section([Paragraph([first])]), Section([target])])
    model = IntegrationModel(fields=(Field("ref", "reference", target_id="target"),))
    set_integration(document, model)
    selected = extract_document(document, next(iter_elements(document, TextRun)))
    assert len(selected.sections) == 2
    assert get_integration(selected) == model
    document.add_resource(Resource("external", ResourceKind.ATTACHMENT, "text/plain", source="https://never-fetch.invalid"))
    with pytest.raises(ValueError, match="embedded bytes"):
        set_integration(document, replace(model, unknown_fragments=(UnknownFragment("raw", "external", "text/plain", 100),)))


@pytest.mark.parametrize(
    "node_id,start,end,text",
    [
        (None, 0, 1, "x"),
        ([], 0, 1, "x"),
        ("t1", True, 1, "x"),
        ("t1", -1, 1, "x"),
        ("t1", 2, 1, "x"),
        ("p", 0, 1, "x"),
        ("t1", 0, 1, "\ud800"),
    ],
)
def test_edit_invalid_inputs_raise_value_error_without_changes(corpus, node_id, start, end, text):
    document, _ = corpus
    before = document_to_json(document)
    with pytest.raises(ValueError):
        edit_anchored_text(document, node_id, start, end, text)
    assert document_to_json(document) == before


def test_migration_validator_and_output_limits_roll_back():
    bag = {}
    set_extension(bag, "org.data", {"value": 1})
    before = deepcopy(bag)
    step = ExtensionMigration("org.data", 1, 2, lambda value: {"value": 2})
    schema = ExtensionSchema(
        "org.data", frozenset({2}), lambda context: [DiagnosticIssue("invalid", IssueSeverity.ERROR, "reject")]
    )
    with pytest.raises(ValueError, match="schema validation"):
        migrate_extension(bag, "org.data", 2, [step], schema=schema)
    assert bag == before
    huge = ExtensionMigration("org.data", 1, 2, lambda value: {"value": "x" * 1000})
    with pytest.raises(ArtifactLimitError):
        migrate_extension(bag, "org.data", 2, [huge], limits=DocumentLimits(max_bytes=200))
    assert bag == before


def test_float_overflow_and_reserved_unknown_field_are_boundary_errors(corpus):
    document, model = corpus
    with pytest.raises(ValueError, match="floating point"):
        set_integration(document, replace(model, scenes=(replace(model.scenes[0], width=10**1000),)))
    document.metadata[INTEGRATION_PROPERTY]["data"]["pages"][0]["extra"] = {"injected": 1}
    assert document.validate()


def test_sheet_integer_precision_survives_json(corpus):
    document, model = corpus
    integer = 2**63 + 1
    book = Workbook("exact", (Sheet("s", "Numbers", (SheetCell(0, 0, integer),)),))
    set_integration(document, replace(model, workbooks=(book,)))
    cell = get_integration(document_from_json(document_to_json(document))).workbooks[0].sheets[0].cells[0]
    assert type(cell.value) is int
    assert cell.value == integer


@pytest.mark.parametrize(
    "changes",
    [
        {"assessed_features": ("text", "text")},
        {"assessed_features": ("different",)},
        {"preservation": (PreservationRecord(DiagnosticIssue("text", IssueSeverity.INFO, "x"), PreservationState.OPAQUE),)},
    ],
)
def test_standalone_preservation_rejects_invalid_assessment(changes):
    model = IntegrationModel(
        assessment_complete=True,
        assessed_features=("text",),
        preservation=(PreservationRecord(DiagnosticIssue("text", IssueSeverity.INFO, "x"), PreservationState.SEMANTIC),),
    )
    with pytest.raises(ValueError):
        preservation_result(replace(model, **changes))


def test_properties_only_schema_migration_scope():
    bag = {}
    set_extension(bag, "org.data", {"value": 1})
    schema = ExtensionSchema("org.data", frozenset({2}), scopes=frozenset({"properties"}))
    step = ExtensionMigration("org.data", 1, 2, lambda value: {"value": 2})
    with pytest.raises(ValueError, match="schema"):
        migrate_extension(bag, "org.data", 2, [step], schema=schema)
    assert get_extension(bag, "org.data").version == 1
    migrate_extension(bag, "org.data", 2, [step], schema=schema, scope="properties")
    assert get_extension(bag, "org.data").version == 2


@pytest.mark.parametrize(
    "changes",
    [
        lambda m: replace(m, media=(replace(m.media[0], resource_id="source"),)),
        lambda m: replace(m, charts=(replace(m.charts[0], visual_resource_id="audio"),)),
        lambda m: replace(m, scenes=(replace(m.scenes[0], groups=(VectorGroup("group", ("path",), mask_resource_id="audio"),)),)),
    ],
)
def test_visual_and_media_references_require_declared_resource_kinds(corpus, changes):
    document, model = corpus
    before = document_to_json(document)
    with pytest.raises(ValueError):
        set_integration(document, changes(model))
    assert document_to_json(document) == before
