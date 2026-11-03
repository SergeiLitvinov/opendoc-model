"""Source certainty is independent of operational page numbers and format defaults."""

import json
from copy import deepcopy
from dataclasses import replace

import pytest

from opendoc_model import (
    PAGE_SETTINGS_STATE_PROPERTY,
    ArtifactLimitError,
    DocumentLimits,
    DocumentModel,
    Length,
    PageSettings,
    PageSettingsState,
    PageSettingValue,
    Section,
    accept_page_settings,
    check_document,
    clone_model,
    document_from_dict,
    document_from_json,
    document_to_dict,
    document_to_json,
    extract_document,
    get_page_settings_state,
    invalidate_page_settings,
    merge_documents,
    set_page_settings_state,
    walk_model,
)


def source():
    return PageSettingsState(
        width=PageSettingValue("source", Length(612), extra={"field_future": [1]}),
        height=PageSettingValue("source", Length(792)),
        margin_top=PageSettingValue("computed", Length(36), "caller-selected profile"),
        margin_left=PageSettingValue("source", Length(0)),
        extra={"future": {"values": [2]}},
    )


def owner():
    section = Section(properties={"own": {"values": [1]}})
    document = DocumentModel(sections=[section])
    set_page_settings_state(section, source())
    return document, section


def test_partial_source_unknown_computed_zero_and_length_survive_two_independent_cycles():
    document, section = owner()
    expected = source()
    for _ in range(2):
        expected = PageSettingsState.from_dict(json.loads(json.dumps(expected.to_dict())))
        document = document_from_json(document_to_json(document))
        section = document.sections[0]
        assert get_page_settings_state(section) == expected
        assert section.page.width == Length(612) and section.page.margin_left == Length(0)
        assert section.page.margin_right == Length(72)
        assert expected.margin_right.state == "unknown" and expected.margin_right.value is None
        assert expected.margin_top.state == "computed" and expected.margin_top.basis == "caller-selected profile"
    detached = get_page_settings_state(section)
    detached.width.value.pt = 10
    detached.extra["future"]["values"].append(999)
    detached.width.extra["field_future"].append(999)
    assert get_page_settings_state(section) == expected


def test_explicit_acceptance_of_same_placeholder_is_distinct_from_direct_assignment():
    section = Section()
    page = deepcopy(section.page)
    set_page_settings_state(section, PageSettingsState())
    section.page.width = Length(page.width.pt)
    before = get_page_settings_state(section)
    assert before.width.state == "unknown" and before.width.value is None
    accept_page_settings(section, ["width"])
    after = get_page_settings_state(section)
    assert section.page == page
    assert after.width == PageSettingValue("explicit", Length(page.width.pt))
    assert after.height.state == "unknown" and after.height.value is None


def test_unknown_placeholder_changes_stay_unknown_and_empty_selection_never_repairs_stale_data():
    section = Section()
    set_page_settings_state(section, PageSettingsState())
    before = deepcopy(section)
    properties = section.properties
    accept_page_settings(section, [])
    invalidate_page_settings(section, [])
    assert section == before and section.properties is properties
    section.page.width = Length(700)
    observed = get_page_settings_state(section)
    assert observed.width == PageSettingValue("unknown", freshness="stale")
    before = deepcopy(section)
    for operation in (accept_page_settings, invalidate_page_settings):
        with pytest.raises(ValueError, match="explicitly accept"):
            operation(section, [])
        assert section == before
    invalidate_page_settings(section, ["width"])
    assert get_page_settings_state(section).width == observed.width


def test_direct_numeric_edits_report_stale_refuse_json_and_require_complete_explicit_batch():
    document, section = owner()
    section.page.width = Length(700)
    section.page.margin_left = Length(1)
    effective = get_page_settings_state(section)
    assert effective.width.state == "source" and effective.width.value == Length(612)
    assert effective.width.freshness == effective.margin_left.freshness == "stale"
    assert effective.height.freshness == "current"
    before = deepcopy(document)
    properties = section.properties
    with pytest.raises(ValueError, match="explicitly accept"):
        document_to_json(document)
    result = check_document(document)
    assert not result.success and any(issue.code == "page.settings.stale" for issue in result.issues)
    for operation in (
        lambda: accept_page_settings(section, ["width"]),
        lambda: invalidate_page_settings(section, ["width"]),
    ):
        with pytest.raises(ValueError, match="every directly changed"):
            operation()
        assert document == before and section.properties is properties
    accept_page_settings(section, ["width", "margin_left"])
    accepted = get_page_settings_state(section)
    assert accepted.width == PageSettingValue("explicit", Length(700), extra={"field_future": [1]})
    assert accepted.margin_left == PageSettingValue("explicit", Length(1))
    assert accepted.margin_top.state == "computed" and accepted.margin_right.state == "unknown"
    assert document.validate() == []


def test_invalidation_retains_estimate_and_basis_and_does_not_reset_numeric_edit():
    document, section = owner()
    section.page.margin_top = Length(40)
    invalidate_page_settings(section, ["margin_top"])
    expected = get_page_settings_state(section)
    assert section.page.margin_top == Length(40)
    assert expected.margin_top == PageSettingValue("computed", Length(36), "caller-selected profile", "stale")
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_page_settings_state(document.sections[0]) == expected


def test_deleting_estimate_keeps_placeholder_unknown_and_cannot_silently_erase_tracking():
    _, section = owner()
    state = get_page_settings_state(section)
    set_page_settings_state(section, replace(state, margin_top=PageSettingValue("unknown", basis="estimate discarded")))
    assert section.page.margin_top == Length(36)
    assert get_page_settings_state(section).margin_top.value is None
    before = deepcopy(section)
    with pytest.raises(ValueError, match="accept unresolved"):
        set_page_settings_state(section, None)
    assert section == before
    accept_page_settings(section)
    accepted = deepcopy(section.page)
    set_page_settings_state(section, None)
    assert get_page_settings_state(section) is None
    assert PAGE_SETTINGS_STATE_PROPERTY not in section.properties and section.page == accepted
    assert section.properties["own"] == {"values": [1]}


def test_plain_and_legacy_documents_do_not_gain_unknownness_or_new_keys():
    section = Section()
    document = DocumentModel(sections=[section])
    before = document_to_json(document)
    assert get_page_settings_state(section) is None
    assert document_to_json(document) == before and PAGE_SETTINGS_STATE_PROPERTY not in before
    assert Section([], PageSettings()).page == PageSettings()
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        assert get_page_settings_state(document.sections[0]) is None
    with pytest.raises(ValueError, match="explicit tracking"):
        accept_page_settings(section)
    assert PageSettingsState.from_dict({}) == PageSettingsState()


@pytest.mark.parametrize(
    "arguments",
    [
        {"state": "unknown", "value": Length(1)},
        {"state": "source"},
        {"state": "computed", "value": Length(1)},
        {"state": "computed", "value": Length(1), "basis": " "},
        {"state": "explicit", "value": Length(-1)},
        {"state": "bad", "value": Length(1)},
        {"state": "explicit", "value": Length(1), "freshness": "bad"},
        {"state": "explicit", "value": Length(1), "basis": False},
    ],
)
def test_incompatible_states_are_refused(arguments):
    with pytest.raises(ValueError):
        PageSettingValue(**arguments)


@pytest.mark.parametrize("bad", [True, "12", float("nan"), float("inf"), -float("inf"), pytest.param(10**400, id="overflow")])
def test_lengths_require_finite_points_not_bool_or_strings(bad):
    with pytest.raises(ValueError):
        PageSettingValue("source", Length(bad))
    with pytest.raises(ValueError):
        PageSettingsState.from_dict({"width": {"state": "source", "value": {"pt": bad}}})


def test_positive_page_dimensions_and_current_known_margins_are_checked():
    with pytest.raises(ValueError, match="positive"):
        PageSettingsState(width=PageSettingValue("source", Length(0)))
    with pytest.raises(ValueError, match="margins consume"):
        PageSettingsState(
            width=PageSettingValue("source", Length(100)),
            margin_left=PageSettingValue("explicit", Length(60)),
            margin_right=PageSettingValue("computed", Length(60), "own profile"),
        )
    _, section = owner()
    before = deepcopy(section)
    with pytest.raises(ValueError, match="margins consume"):
        set_page_settings_state(section, PageSettingsState(width=PageSettingValue("source", Length(10))))
    assert section == before


@pytest.mark.parametrize("mode", ["version", "projection_missing", "projection_bad", "projection_conflict", "state"])
def test_raw_json_checks_version_complete_projection_and_consistency_with_locations(mode):
    document, _ = owner()
    raw = document_to_dict(document)
    carrier = raw["document"]["sections"][0]["properties"][PAGE_SETTINGS_STATE_PROPERTY]
    if mode == "version":
        carrier["version"] = True
    elif mode == "projection_missing":
        del carrier["projection"]["height"]
    elif mode == "projection_bad":
        carrier["projection"]["height"]["pt"] = 0
    elif mode == "projection_conflict":
        carrier["projection"]["width"]["pt"] = 613
    else:
        carrier["state"]["margin_right"]["value"] = {"pt": 72}
    before = deepcopy(raw)
    with pytest.raises(ValueError, match=r"sections\[0\]"):
        document_from_dict(raw)
    assert raw == before


@pytest.mark.parametrize("opaque", [None, "native", {"format": "future", "values": [1]}])
def test_opaque_carriers_are_not_reinterpreted_or_overwritten(opaque):
    section = Section(properties={PAGE_SETTINGS_STATE_PROPERTY: opaque})
    before = deepcopy(section)
    assert get_page_settings_state(section) is None
    assert DocumentModel(sections=[section]).validate() == []
    for value in (source(), None):
        with pytest.raises(ValueError, match="opaque"):
            set_page_settings_state(section, value)
        assert section == before


def test_all_levels_of_unknown_fields_survive_replacement_and_are_independent():
    document, section = owner()
    carrier = section.properties[PAGE_SETTINGS_STATE_PROPERTY]
    carrier["wrapper_future"] = {"values": [3]}
    carrier["projection"]["projection_future"] = [4]
    new = PageSettingsState(width=PageSettingValue("explicit", Length(650), extra={"new": [5]}))
    set_page_settings_state(section, new)
    new.width.extra["new"].append(999)
    state = get_page_settings_state(section)
    assert state.width.extra == {"field_future": [1], "new": [5]}
    assert state.extra == {"future": {"values": [2]}}
    for _ in range(2):
        document = document_from_json(document_to_json(document))
        raw = document.sections[0].properties[PAGE_SETTINGS_STATE_PROPERTY]
        assert raw["wrapper_future"] == {"values": [3]} and raw["projection"]["projection_future"] == [4]


@pytest.mark.parametrize("fields", ["width", ["bad"], [True], ["width", "width"], 12])
def test_invalid_selections_are_atomic(fields):
    _, section = owner()
    before = deepcopy(section)
    properties = section.properties
    for operation in (accept_page_settings, invalidate_page_settings):
        with pytest.raises(ValueError):
            operation(section, fields)
        assert section == before and section.properties is properties


@pytest.mark.parametrize("limits", [DocumentLimits(max_nodes=10), DocumentLimits(max_bytes=1), DocumentLimits(max_depth=1)])
def test_quota_errors_remain_structured_and_operations_atomic(limits):
    _, section = owner()
    before = deepcopy(section)
    properties = section.properties
    for operation in (
        lambda: get_page_settings_state(section, limits=limits),
        lambda: set_page_settings_state(section, source(), limits=limits),
        lambda: accept_page_settings(section, limits=limits),
        lambda: invalidate_page_settings(section, limits=limits),
    ):
        with pytest.raises(ArtifactLimitError) as caught:
            operation()
        assert caught.value.path and caught.value.quota and caught.value.maximum is not None
        assert section == before and section.properties is properties


def test_explicit_large_budget_reaches_all_codec_and_state_steps():
    section = Section()
    state = PageSettingsState(extra={"future": [None] * 100_001})
    with pytest.raises(ArtifactLimitError):
        set_page_settings_state(section, state)
    assert get_page_settings_state(section) is None
    budget = DocumentLimits(max_nodes=500_000)
    set_page_settings_state(section, state, limits=budget)
    for _ in range(2):
        data = get_page_settings_state(section, limits=budget).to_dict(limits=budget)
        assert len(PageSettingsState.from_dict(data, limits=budget).extra["future"]) == 100_001


def test_clone_merge_extract_keep_states_without_aliases_or_implicit_reacceptance():
    document, section = owner()
    clone = clone_model(document)
    accept_page_settings(clone.sections[0], ["width"])
    assert get_page_settings_state(section).width.state == "source"
    merged = merge_documents([document, clone]).document
    location = next(item for item in walk_model(merged) if item.node is merged.sections[1])
    extracted = extract_document(merged, location)
    assert get_page_settings_state(extracted.sections[0]).width.state == "explicit"
    assert get_page_settings_state(merged.sections[0]).width.state == "source"
    assert merged.sections[0].properties is not merged.sections[1].properties
