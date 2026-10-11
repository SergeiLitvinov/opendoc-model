"""Caller-measured text scope, independent of recursive model object inventory."""

from dataclasses import dataclass
from typing import Any, NoReturn, cast

from opendoc_model._integration_codec import _convert
from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.integration_types import IntegrationRecord
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.text_flow import MAX_TEXT_TOKENS, TEXT_FLOW_VERSION

TEXT_FLOW_PROFILE_FORMAT = "opendoc.text-flow-profile"
TEXT_FLOW_PROFILE_KEY = "text_flow_profile"
_EMPTY_TEXT_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


@dataclass(frozen=True)
class TextFlowProfile(IntegrationRecord):
    """Measured completeness applies only to the named scope and extraction profile.

    Profile and scope identifiers are opaque, versioned caller declarations.
    Neither measurement nor document completeness is inferred by the library.
    """

    profile: str
    scope: str
    recipe: str = TEXT_FLOW_VERSION
    measured: bool = False
    complete: bool = False
    reason: str | None = None


def _error(path: str, message: str) -> NoReturn:
    raise _DiagnosticError(path, message, "text-flow-profile.invalid")


def _validate(profile: TextFlowProfile) -> None:
    for name in ("profile", "scope", "recipe"):
        if not getattr(profile, name):
            _error(name, "expected nonempty identifier")
    if profile.reason is not None and not profile.reason:
        _error("reason", "expected nonempty machine reason or unknown")
    if profile.complete and not profile.measured:
        _error("complete", "unmeasured scope cannot claim completeness")
    if profile.complete and profile.reason is not None:
        _error("reason", "complete scope cannot carry an unavailability reason")


def text_flow_profile_to_dict(profile: TextFlowProfile, *, limits: DocumentLimits | None = None) -> dict[str, Any]:
    """Copy a bounded v1 profile envelope, preserving inert unknown fields."""
    budget = _resolve_limits(limits)
    _guard_model(profile, budget)
    try:
        raw: dict[str, Any] = _convert(profile, TextFlowProfile, "profile", encode=True)
        checked: TextFlowProfile = _convert(raw, TextFlowProfile, "profile", encode=False)
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _validate(checked)
    if {"format", "version"}.intersection(raw):
        _error("extra", "unknown fields cannot shadow the envelope")
    raw.update(format=TEXT_FLOW_PROFILE_FORMAT, version=1)
    _json_tree(raw, "profile", budget)
    return raw


def text_flow_profile_from_dict(data: Any, *, limits: DocumentLimits | None = None) -> TextFlowProfile:
    """Read the closed v1 schema. Unknown recipes remain data, not available evidence."""
    _json_tree(data, "profile", _resolve_limits(limits))
    if type(data) is not dict or data.get("format") != TEXT_FLOW_PROFILE_FORMAT:
        _error("format", "expected opendoc.text-flow-profile")
    if type(data.get("version")) is not int or data["version"] != 1:
        _error("version", "unsupported text flow profile version")
    try:
        result = cast(
            TextFlowProfile,
            _convert(
                {key: value for key, value in data.items() if key not in {"format", "version"}},
                TextFlowProfile,
                "profile",
                encode=False,
            ),
        )
    except _DiagnosticError as error:
        _error(error.location, error.message)
    _validate(result)
    return result


def _digest(value: Any) -> bool:
    return type(value) is str and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _measured_flow(flow: Any) -> bool:
    _json_tree(flow, "text_flow", _resolve_limits(None))
    if type(flow) is not dict or flow.get("version") != TEXT_FLOW_VERSION or not _digest(flow.get("sha256")):
        return False
    if any(type(flow.get(key)) is not int or flow[key] < 0 for key in ("characters", "paragraphs", "token_count")):
        return False
    count = flow["token_count"]
    if flow.get("tokenization") != "whitespace-words-v1" or not 0 <= flow["paragraphs"] <= count <= flow["characters"]:
        return False
    tokens = flow.get("tokens")
    if count <= MAX_TEXT_TOKENS:
        if (
            type(tokens) is not list
            or len(tokens) != count
            or not all(_digest(token) and token != _EMPTY_TEXT_HASH for token in tokens)
        ):
            return False
    elif tokens is not None or "tokens" not in flow:
        return False
    if count == 0:
        return bool(flow["characters"] == flow["paragraphs"] == 0 and flow["sha256"] == _EMPTY_TEXT_HASH)
    return bool(flow["paragraphs"] > 0 and flow["characters"] >= 2 * count - 1 and flow["sha256"] != _EMPTY_TEXT_HASH)


def _flows_consistent(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Reject contradictory known declarations, without inferring missing measurements."""
    if source["sha256"] == target["sha256"]:
        return not any(
            source.get(key) is not None and target.get(key) is not None and source[key] != target[key]
            for key in ("characters", "token_count", "tokens")
        )
    return not (
        type(source.get("tokens")) is list and type(target.get("tokens")) is list and source["tokens"] == target["tokens"]
    )


def _profiles_compatible(source: dict[str, Any], target: dict[str, Any]) -> bool:
    try:
        profiles = [text_flow_profile_from_dict(side.get(TEXT_FLOW_PROFILE_KEY)) for side in (source, target)]
        flows = [cast(dict[str, Any], side.get("text_flow")) for side in (source, target)]
        if not all(_measured_flow(flow) for flow in flows):
            return False
        return all(item.measured and item.complete and item.recipe == TEXT_FLOW_VERSION for item in profiles) and (
            profiles[0].profile,
            profiles[0].scope,
            profiles[0].recipe,
        ) == (profiles[1].profile, profiles[1].scope, profiles[1].recipe)
    except ValueError:
        return False


__all__ = [
    "TEXT_FLOW_PROFILE_FORMAT",
    "TEXT_FLOW_PROFILE_KEY",
    "TextFlowProfile",
    "text_flow_profile_to_dict",
    "text_flow_profile_from_dict",
]
