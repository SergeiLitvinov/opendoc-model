"""Source certainty and explicit user acceptance; the caller chooses placeholders."""

from dataclasses import replace

from opendoc_model import (
    DocumentModel,
    Length,
    PageSettingsState,
    PageSettingValue,
    Section,
    accept_page_settings,
    document_from_json,
    document_to_json,
    get_page_settings_state,
    invalidate_page_settings,
    set_page_settings_state,
)

section = Section()
document = DocumentModel(sections=[section])
# These facts/estimates belong to the producer. Model does not choose defaults.
state = PageSettingsState(
    width=PageSettingValue("source", Length(612)),
    margin_left=PageSettingValue("source", Length(0)),
    margin_top=PageSettingValue("computed", Length(36), "caller profile v1"),
)
set_page_settings_state(section, state)
assert section.page.width == Length(612)
assert get_page_settings_state(section).height.value is None
placeholder = section.page.height.pt
accept_page_settings(section, ["height"])
assert section.page.height.pt == placeholder
assert get_page_settings_state(section).height == PageSettingValue("explicit", Length(placeholder))
section.page.margin_top = Length(40)
assert get_page_settings_state(section).margin_top.freshness == "stale"
invalidate_page_settings(section, ["margin_top"])
for _ in range(2):
    document = document_from_json(document_to_json(document))
    section = document.sections[0]
    assert get_page_settings_state(section).margin_top == PageSettingValue("computed", Length(36), "caller profile v1", "stale")
set_page_settings_state(section, replace(get_page_settings_state(section), margin_top=PageSettingValue("unknown")))
assert section.page.margin_top == Length(40)
assert get_page_settings_state(section).margin_top.value is None
print("Page settings certainty: unknown/source/computed/explicit, same-number acceptance and stale JSON verified")
