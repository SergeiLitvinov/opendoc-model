"""Explicit source certainty for section page settings, without choosing defaults."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, NoReturn, TypeAlias, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import Length, PageSettings, Section
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits
from opendoc_model.properties import SectionProperties

PAGE_SETTINGS_STATE_PROPERTY = "opendoc.page-settings-state"
PageSettingName: TypeAlias = Literal["width", "height", "margin_top", "margin_right", "margin_bottom", "margin_left"]
_FIELDS = ("width", "height", "margin_top", "margin_right", "margin_bottom", "margin_left")


def _error(path: str, message: str, code: str = "page.settings.invalid") -> NoReturn:
    raise _DiagnosticError(path, message, code)


def _length(value: Any, path: str) -> None:
    if not isinstance(value, Length) or type(value.pt) not in (int, float):
        _error(path, "expected Length with finite point value")
    try:
        finite = math.isfinite(value.pt)
    except OverflowError:
        finite = False
    if not finite or value.pt < 0:
        _error(path, "expected nonnegative finite point value")


@dataclass(frozen=True)
class PageSettingValue(IntegrationRecord):
    """Source fact, unresolved value, based estimate or explicit user setting.

    Unknown never carries a numeric value; PageSettings may still need a caller's
    placeholder. A stale estimate retains its historical value and basis.
    """

    state: Literal["source", "unknown", "computed", "explicit"]
    value: Length | None = None
    basis: str | None = None
    freshness: Literal["current", "stale"] = "current"

    def __post_init__(self) -> None:
        if self.state not in ("source", "unknown", "computed", "explicit"):
            _error("page_setting.state", "unsupported certainty state")
        if self.freshness not in ("current", "stale"):
            _error("page_setting.freshness", "unsupported freshness")
        if self.state == "unknown":
            if self.value is not None:
                _error("page_setting.value", "unknown geometry cannot carry a known value")
        else:
            _length(self.value, "page_setting.value")
        if self.basis is not None and (not isinstance(self.basis, str) or not self.basis.strip()):
            _error("page_setting.basis", "expected a nonempty basis or None")
        if self.state == "computed" and self.basis is None:
            _error("page_setting.basis", "computed geometry requires an explicit basis")


def _unknown() -> PageSettingValue:
    return PageSettingValue("unknown")


@dataclass(frozen=True)
class PageSettingsState(IntegrationRecord):
    """All six source-certainty declarations; unspecified fields remain unknown."""

    width: PageSettingValue = field(default_factory=_unknown)
    height: PageSettingValue = field(default_factory=_unknown)
    margin_top: PageSettingValue = field(default_factory=_unknown)
    margin_right: PageSettingValue = field(default_factory=_unknown)
    margin_bottom: PageSettingValue = field(default_factory=_unknown)
    margin_left: PageSettingValue = field(default_factory=_unknown)

    def __post_init__(self) -> None:
        for name in _FIELDS:
            item = getattr(self, name)
            if type(item) is not PageSettingValue:
                _error(f"page_settings_state.{name}", "expected PageSettingValue")
            item.__post_init__()
            if name in {"width", "height"} and item.value is not None and item.value.pt <= 0:
                _error(f"page_settings_state.{name}.value", "page dimensions must be positive")
        for size, first, second in (("width", "margin_left", "margin_right"), ("height", "margin_top", "margin_bottom")):
            items = [getattr(self, name) for name in (size, first, second)]
            if all(item.value is not None and item.freshness == "current" for item in items):
                if items[1].value.pt + items[2].value.pt >= items[0].value.pt:
                    _error("page_settings_state." + size, "current known margins consume the declared page dimension")

    def to_dict(self, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
        """Encode detached states, Length values and unknown JSON fields."""
        budget = _resolve_limits(limits)
        _guard_model(self, budget)
        self.__post_init__()
        raw: dict[str, Any] = _convert(self, PageSettingsState, "page_settings_state", encode=True)
        _json_tree(raw, "page_settings_state", budget)
        return raw

    @classmethod
    def from_dict(cls, value: dict[str, Any], *, limits: DocumentLimits | None = None) -> PageSettingsState:
        """Missing declarations become unknown, never numeric factory defaults."""
        budget = _resolve_limits(limits)
        _json_tree(value, "page_settings_state", budget)
        return cast(PageSettingsState, _convert(value, cls, "page_settings_state", encode=False))


def _page(value: Any, budget: DocumentLimits, path: str) -> None:
    from opendoc_model._validation import _Validator

    if not isinstance(value, PageSettings):
        _error(path, "expected PageSettings")
    validator = _Validator(budget)
    validator.page(value, path)
    if validator.errors:
        _error(path, "; ".join(validator.errors))


def _read(section: Section, budget: DocumentLimits, path: str) -> tuple[PageSettingsState, dict[str, Any]] | None:
    if not isinstance(section.properties, Mapping):
        _error(path + ".properties", "expected a property mapping")
    raw = section.properties.get(PAGE_SETTINGS_STATE_PROPERTY)
    here = f"{path}.properties[{PAGE_SETTINGS_STATE_PROPERTY!r}]"
    _json_tree(raw, here, budget)
    if not isinstance(raw, dict) or raw.get("format") != PAGE_SETTINGS_STATE_PROPERTY:
        return None
    if type(raw.get("version")) is not int or raw["version"] != 1:
        _error(here + ".version", "unsupported page settings state version")
    if "state" not in raw or not isinstance(raw.get("projection"), dict):
        _error(here, "expected state and a complete numeric projection snapshot")
    try:
        state = PageSettingsState.from_dict(raw["state"], limits=budget)
    except _DiagnosticError as error:
        _error(here + ".state" + error.location.removeprefix("page_settings_state"), error.message)
    snapshot = {}
    for name in _FIELDS:
        if name not in raw["projection"]:
            _error(here + ".projection." + name, "missing projection field; defaults are never inferred")
        projected = _convert(raw["projection"][name], Length, here + ".projection." + name, encode=False)
        _length(projected, here + ".projection." + name)
        snapshot[name] = projected
        item = getattr(state, name)
        if item.freshness == "current" and item.value is not None and item.value.pt != projected.pt:
            _error(here + ".state." + name, "current declared value conflicts with the projection snapshot")
    _page(PageSettings(**snapshot), budget, here + ".projection")
    return state, raw


def _effective(
    section: Section, state: PageSettingsState, raw: dict[str, Any], budget: DocumentLimits, path: str
) -> PageSettingsState:
    _page(section.page, budget, path + ".page")
    updates = {}
    for name in _FIELDS:
        item = getattr(state, name)
        if getattr(section.page, name).pt != raw["projection"][name]["pt"]:
            item = replace(item, freshness="stale")
        updates[name] = item
    return replace(state, **updates)


def _validate_page_settings_state(section: Section, budget: DocumentLimits, path: str) -> None:
    parsed = _read(section, budget, path)
    if parsed is None:
        return
    state, raw = parsed
    effective = _effective(section, state, raw, budget, path)
    for name in _FIELDS:
        if getattr(state, name).freshness == "current" and getattr(effective, name).freshness == "stale":
            _error(
                path + ".page." + name,
                "page setting changed; explicitly accept, replace or invalidate its state",
                "page.settings.stale",
            )


def get_page_settings_state(section: Section, *, limits: DocumentLimits | None = None) -> PageSettingsState | None:
    """Return detached effective states; absent/opaque preserves legacy semantics.

    Direct numeric edits report stale without mutating or accepting assumptions.
    Same-number acceptance must use an explicit helper, never number comparison.
    """
    if not isinstance(section, Section):
        _error("section", "expected Section")
    budget = _resolve_limits(limits)
    _guard_model(section, budget)
    parsed = _read(section, budget, "section")
    return _effective(section, *parsed, budget, "section") if parsed is not None else None


def set_page_settings_state(section: Section, state: PageSettingsState | None, *, limits: DocumentLimits | None = None) -> None:
    """Atomically declare certainty and apply only current known point values.

    Unknown/stale fields keep the caller's existing operational numbers. Removing
    tracking is allowed only for current source/explicit fields, never unresolved
    estimates. Old envelope/record unknown fields survive replacement.
    """
    if not isinstance(section, Section) or state is not None and type(state) is not PageSettingsState:
        _error("page_settings_state", "expected Section and PageSettingsState or None")
    budget = _resolve_limits(limits)
    _guard_model(section, budget)
    _page(section.page, budget, "section.page")
    previous = _read(section, budget, "section")
    if PAGE_SETTINGS_STATE_PROPERTY in section.properties and previous is None:
        _error("section.properties", "page settings state property is occupied by opaque data")
    properties = dict(section.properties)
    page = _convert(_convert(section.page, PageSettings, "section.page", encode=True), PageSettings, "section.page", encode=False)
    if state is None:
        if previous is not None:
            effective = _effective(section, *previous, budget, "section")
            if any(
                getattr(effective, name).state not in {"source", "explicit"} or getattr(effective, name).freshness != "current"
                for name in _FIELDS
            ):
                _error("page_settings_state", "accept unresolved/stale fields before removing tracking")
        properties.pop(PAGE_SETTINGS_STATE_PROPERTY, None)
    else:
        state = PageSettingsState.from_dict(state.to_dict(limits=budget), limits=budget)
        raw = dict(previous[1]) if previous is not None else {}
        projection = dict(raw.get("projection", {}))
        if previous is not None:
            state = replace(
                state,
                extra={**previous[0].extra, **state.extra},
                **{
                    name: replace(getattr(state, name), extra={**getattr(previous[0], name).extra, **getattr(state, name).extra})
                    for name in _FIELDS
                },
            )
        for name in _FIELDS:
            item = getattr(state, name)
            if item.freshness == "current" and item.value is not None:
                setattr(page, name, Length(float(item.value.pt)))
            projection[name] = _convert(getattr(page, name), Length, "projection." + name, encode=True)
        raw.update(format=PAGE_SETTINGS_STATE_PROPERTY, version=1, state=state.to_dict(limits=budget), projection=projection)
        properties[PAGE_SETTINGS_STATE_PROPERTY] = raw
    _page(page, budget, "section.page")
    _json_tree(properties, "section.properties", budget)
    independent = _convert(properties, dict[str, Any], "section.properties", encode=True)
    candidate = replace(section, page=page, properties=SectionProperties(independent))
    _guard_model(candidate, budget)
    _validate_page_settings_state(candidate, budget, "section")
    section.page, section.properties = candidate.page, candidate.properties


def _selected(fields: Iterable[PageSettingName] | None, budget: DocumentLimits) -> set[str]:
    if fields is None:
        return set(_FIELDS)
    if isinstance(fields, (str, bytes)):
        _error("page_settings_state.fields", "expected an iterable of field names, not a string")
    try:
        iterator = iter(fields)
    except TypeError:
        _error("page_settings_state.fields", "expected field names")
    selected: set[str] = set()
    for index, name in enumerate(iterator):
        if index >= budget.max_nodes:
            _quota("page_settings_state.fields", "nodes", budget.max_nodes)
        if type(name) is not str or name not in _FIELDS or name in selected:
            _error(f"page_settings_state.fields[{index}]", "unknown or duplicate field")
        selected.add(name)
    return selected


def _change(section: Section, fields: Iterable[PageSettingName] | None, budget: DocumentLimits, accept: bool) -> None:
    effective = get_page_settings_state(section, limits=budget)
    if effective is None:
        _error("page_settings_state", "explicit tracking is required before acceptance or invalidation")
    selected = _selected(fields, budget)
    if not selected:
        _validate_page_settings_state(section, budget, "section")
        return
    parsed = _read(section, budget, "section")
    assert parsed is not None
    declared = parsed[0]
    updates = {}
    for name in _FIELDS:
        item = getattr(effective, name)
        if name not in selected:
            if getattr(declared, name).freshness == "current" and item.freshness == "stale":
                _error("page_settings_state.fields", "include every directly changed field in the batch")
        elif accept:
            item = PageSettingValue("explicit", Length(float(getattr(section.page, name).pt)), extra=item.extra)
        else:
            item = replace(item, freshness="stale")
        updates[name] = item
    set_page_settings_state(section, replace(effective, **updates), limits=budget)


def accept_page_settings(
    section: Section, fields: Iterable[PageSettingName] | None = None, *, limits: DocumentLimits | None = None
) -> None:
    """Explicitly accept current operational numbers, even unchanged placeholders."""
    _change(section, fields, _resolve_limits(limits), True)


def invalidate_page_settings(
    section: Section, fields: Iterable[PageSettingName] | None = None, *, limits: DocumentLimits | None = None
) -> None:
    """Persist stale fields without changing numbers, source certainty or basis."""
    _change(section, fields, _resolve_limits(limits), False)


__all__ = [
    "PAGE_SETTINGS_STATE_PROPERTY",
    "PageSettingName",
    "PageSettingValue",
    "PageSettingsState",
    "get_page_settings_state",
    "set_page_settings_state",
    "accept_page_settings",
    "invalidate_page_settings",
]
