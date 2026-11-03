"""Rich document-local notes, explicit references and derived numbering."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass, replace
from typing import Any, cast

from opendoc_model.diagnostics import ConversionIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import DocumentModel, Footnote, TextRun
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.object_matching import _match_objects, _MatchingBudget, _MatchingLimitError
from opendoc_model.references import _identifier
from opendoc_model.traversal import ModelNode, NodeLocation, iter_elements, walk_model

FOOTNOTES_PROPERTY = "opendoc.footnotes"
FOOTNOTE_REFERENCE_PROPERTY = "opendoc.footnote-reference"


@dataclass(frozen=True)
class FootnoteReference:
    """A reference to a definition ID; the run retains its own display text."""

    note_id: str

    def __post_init__(self) -> None:
        _identifier(self.note_id, "footnote_reference.note_id")


@dataclass(frozen=True)
class FootnoteNumber:
    """A reference occurrence and its first-use number in common traversal order."""

    location: NodeLocation[TextRun]
    note_id: str
    number: int


def _reference_payload(value: Any, path: str) -> FootnoteReference | None:
    if not isinstance(value, dict) or value.get("format") != FOOTNOTE_REFERENCE_PROPERTY:
        return None
    if type(value.get("version")) is not int or value["version"] != 1:
        raise _DiagnosticError(f"{path}.version", "unsupported footnote reference version", "semantic.version")
    return FootnoteReference(_identifier(value.get("note_id"), f"{path}.note_id"))


def get_footnote_reference(run: TextRun, *, limits: DocumentLimits | None = None) -> FootnoteReference | None:
    """Read only explicitly tagged note references."""
    from opendoc_model._json_validation import _json_tree

    if not isinstance(run, TextRun) or not isinstance(run.properties, Mapping):
        raise ValueError("expected TextRun with property mapping")
    resolved = _resolve_limits(limits)
    value = run.properties.get(FOOTNOTE_REFERENCE_PROPERTY)
    _json_tree(value, f"properties[{FOOTNOTE_REFERENCE_PROPERTY!r}]", resolved)
    return _reference_payload(value, f"properties[{FOOTNOTE_REFERENCE_PROPERTY!r}]")


def set_footnote_reference(run: TextRun, reference: FootnoteReference | None, *, limits: DocumentLimits | None = None) -> None:
    """Assign/remove a role atomically, preserving unknown tagged fields."""
    from opendoc_model._json_validation import _json_tree
    from opendoc_model.references import get_internal_link

    existing = get_footnote_reference(run, limits=limits)
    if not isinstance(run.properties, MutableMapping):
        raise ValueError("expected mutable properties")
    if reference is not None and not isinstance(reference, FootnoteReference):
        raise ValueError("reference must be FootnoteReference or None")
    if FOOTNOTE_REFERENCE_PROPERTY in run.properties and existing is None:
        raise ValueError("footnote property is occupied by an opaque extension")
    if reference is None:
        if existing is not None:
            del run.properties[FOOTNOTE_REFERENCE_PROPERTY]
        return
    if run.link is not None or get_internal_link(run, limits=limits) is not None:
        raise ValueError("a footnote reference cannot coexist with another link role")
    value = deepcopy(run.properties[FOOTNOTE_REFERENCE_PROPERTY]) if existing is not None else {}
    value.update(format=FOOTNOTE_REFERENCE_PROPERTY, version=1, note_id=reference.note_id)
    _json_tree(value, f"properties[{FOOTNOTE_REFERENCE_PROPERTY!r}]", _resolve_limits(limits))
    _reference_payload(value, f"properties[{FOOTNOTE_REFERENCE_PROPERTY!r}]")
    run.properties[FOOTNOTE_REFERENCE_PROPERTY] = value


def iter_footnotes(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Footnote]]:
    """Yield live definitions after ordinary sections, with normal rich-block descendants."""
    for location in walk_model(root, limits=limits):
        if isinstance(location.node, Footnote):
            yield cast(NodeLocation[Footnote], location)


def iter_footnote_references(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[TextRun]]:
    """Yield every reference occurrence, including references in note bodies."""
    for location in iter_elements(root, TextRun, limits=limits):
        if get_footnote_reference(location.node, limits=limits) is not None:
            yield location


def iter_footnote_numbers(document: DocumentModel, *, limits: DocumentLimits | None = None) -> Iterator[FootnoteNumber]:
    """Validate before yielding; number distinct IDs by first reference, starting at one."""
    from opendoc_model._validation import _validate_model

    errors = _validate_model(document, limits)
    if errors:
        raise ValueError("; ".join(errors))
    numbers: dict[str, int] = {}
    for location in iter_footnote_references(document, limits=limits):
        reference = get_footnote_reference(location.node, limits=limits)
        assert reference is not None
        if reference.note_id not in numbers:
            numbers[reference.note_id] = len(numbers) + 1
        yield FootnoteNumber(location, reference.note_id, numbers[reference.note_id])


def get_footnote(document: DocumentModel, identifier: str, *, limits: DocumentLimits | None = None) -> Footnote | None:
    """Find a live unique definition; other model semantics are checked separately."""
    if not isinstance(document, DocumentModel):
        raise ValueError("expected DocumentModel")
    _identifier(identifier, "identifier")
    found = None
    for location in iter_footnotes(document, limits=limits):
        if location.node.id == identifier:
            if found is not None:
                raise ValueError(f"duplicate footnote {identifier!r}")
            found = location.node
    return found


def set_footnote(document: DocumentModel, note: Footnote, *, limits: DocumentLimits | None = None) -> None:
    """Insert/replace an independent note at its existing position, committing a valid model only."""
    from opendoc_model._validation import _validate_model

    if not isinstance(document, DocumentModel) or not isinstance(note, Footnote):
        raise ValueError("expected DocumentModel and Footnote")
    resolved = _resolve_limits(limits)
    _guard_model(document, resolved)
    _guard_model(note, resolved)
    _identifier(note.id, "footnote.id")
    if not isinstance(document.footnotes, list):
        raise ValueError("footnotes must be a list")
    notes = list(document.footnotes)
    indexes = [index for index, existing in enumerate(notes) if isinstance(existing, Footnote) and existing.id == note.id]
    if len(indexes) > 1:
        raise ValueError(f"duplicate footnote {note.id!r}")
    copied = deepcopy(note)
    if indexes:
        notes[indexes[0]] = copied
    else:
        notes.append(copied)
    candidate = replace(document, footnotes=notes)
    errors = _validate_model(candidate, resolved)
    if errors:
        raise ValueError("; ".join(errors))
    document.footnotes = notes


def remove_footnote(document: DocumentModel, identifier: str, *, limits: DocumentLimits | None = None) -> Footnote:
    """Remove an unreferenced definition atomically, returning an independent snapshot."""
    from opendoc_model._validation import _validate_model

    note = get_footnote(document, identifier, limits=limits)
    if note is None:
        raise ValueError(f"unknown footnote {identifier!r}")
    notes = [item for item in document.footnotes if item is not note]
    errors = _validate_model(replace(document, footnotes=notes), limits)
    if errors:
        raise ValueError("; ".join(errors))
    snapshot = deepcopy(note)
    document.footnotes = notes
    return snapshot


def _decode_notes(value: Any, path: str) -> tuple[list[Footnote], dict[str, Any], dict[str, Any]] | None:
    """Decode only a tagged, already JSON-bounded registry; validate shape before construction."""
    if not isinstance(value, dict) or value.get("format") != FOOTNOTES_PROPERTY:
        return None
    from opendoc_model._json_validation import _array, _bag, _block, _record, _string
    from opendoc_model.document_codec import _block_from_dict

    if type(value.get("version")) is not int or value["version"] != 1:
        raise _DiagnosticError(f"{path}.version", "unsupported footnotes version", "semantic.version")
    _record(value, path, {"notes": _array(_bag)}, {"properties": _bag})
    notes = []
    for index, raw in enumerate(value["notes"]):
        location = f"{path}.notes[{index}]"
        _record(raw, location, {"id": _string}, {"blocks": _array(_block), "properties": _bag})
        _identifier(raw["id"], f"{location}.id")
        notes.append(
            Footnote(
                raw["id"],
                [_block_from_dict(block) for block in raw.get("blocks", [])],
                dict(raw.get("properties", {})),
                {key: item for key, item in raw.items() if key not in {"id", "blocks", "properties"}},
            )
        )
    return (
        notes,
        dict(value.get("properties", {})),
        {key: item for key, item in value.items() if key not in {"format", "version", "notes", "properties"}},
    )


def _encode_notes(document: DocumentModel) -> dict[str, Any]:
    from opendoc_model.document_codec import _block_to_dict, _properties_to_dict

    return {
        **_properties_to_dict(document.footnote_extensions),
        "format": FOOTNOTES_PROPERTY,
        "version": 1,
        "notes": [
            {
                **_properties_to_dict(note.extensions),
                "id": note.id,
                "blocks": [_block_to_dict(block) for block in note.blocks],
                "properties": _properties_to_dict(note.properties),
            }
            for note in document.footnotes
        ],
        "properties": _properties_to_dict(document.footnote_properties),
    }


def _note_inventory(document: DocumentModel, limits: DocumentLimits) -> dict[str, Any]:
    from opendoc_model._json_validation import _json_tree

    encoded = _encode_notes(document)
    _json_tree(encoded, "footnotes", limits)
    notes = []
    for index, raw in enumerate(encoded["notes"]):
        body = json.dumps({key: value for key, value in raw.items() if key != "id"}, sort_keys=True, ensure_ascii=False)
        notes.append(
            {"id": raw["id"], "location": f"footnotes[{index}]", "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest()}
        )
    references = []
    for number in iter_footnote_numbers(document, limits=limits):
        run = number.location.node
        references.append(
            {
                "type": "footnote-reference",
                "location": number.location.path,
                "note_id": number.note_id,
                "number": number.number,
                "text": run.text,
                "content_hash": hashlib.sha256(run.text.encode("utf-8")).hexdigest(),
            }
        )
    properties = json.dumps(
        {key: value for key, value in encoded.items() if key not in {"format", "version", "notes"}},
        sort_keys=True,
        ensure_ascii=False,
    )
    return {
        "format": "opendoc.footnotes-inventory",
        "version": 1,
        "notes": notes,
        "references": references,
        "properties_hash": hashlib.sha256(properties.encode("utf-8")).hexdigest(),
    }


def _note_inventory_valid(value: Any) -> bool:
    if not isinstance(value, dict) or value.get("format") != "opendoc.footnotes-inventory":
        return False
    if type(value.get("version")) is not int or value["version"] != 1:
        return False
    if not isinstance(value.get("notes"), list) or not isinstance(value.get("references"), list):
        return False
    digest = value.get("properties_hash")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        return False
    identifiers = set()
    paths = set()
    numbers: dict[str, int] = {}
    try:
        for item in value["notes"]:
            if not isinstance(item, dict):
                return False
            _identifier(item.get("id"), "id")
            _identifier(item.get("location"), "location")
            digest = item.get("body_hash")
            if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
                return False
            if item["id"] in identifiers or item["location"] in paths:
                return False
            identifiers.add(item["id"])
            paths.add(item["location"])
        paths.clear()
        for item in value["references"]:
            if not isinstance(item, dict) or item.get("type") != "footnote-reference":
                return False
            _identifier(item.get("location"), "location")
            _identifier(item.get("note_id"), "note_id")
            if item["note_id"] not in identifiers or item["location"] in paths or not isinstance(item.get("text"), str):
                return False
            if item["note_id"] not in numbers:
                numbers[item["note_id"]] = len(numbers) + 1
            if type(item.get("number")) is not int or item["number"] != numbers[item["note_id"]]:
                return False
            if item.get("content_hash") != hashlib.sha256(item["text"].encode("utf-8")).hexdigest():
                return False
            paths.add(item["location"])
    except (ValueError, UnicodeEncodeError):
        return False
    return True


def _compare_notes(
    source: Any, target: Any, available: bool, *, matching_budget: _MatchingBudget | None = None
) -> tuple[dict[str, Any], list[ConversionIssue]]:
    if not available or not _note_inventory_valid(source) or not _note_inventory_valid(target):
        return {
            "available": False,
            "lost_notes": None,
            "changed_notes": None,
            "lost_references": None,
            "changed_references": None,
            "changes": [],
            "reference_matches": [],
            "added_notes": None,
            "added_references": None,
        }, []
    budget = matching_budget or _MatchingBudget()
    try:
        budget.charge(len(source["notes"]) + len(target["notes"]))
    except _MatchingLimitError as error:
        result, _ = _compare_notes(source, target, False)
        result.update(reason="matching-budget-exceeded", matching_budget=error.measurement)
        return result, [ConversionIssue(IssueSeverity.INFO, "footnote-matching-unavailable", str(error), "footnotes")]
    before = {item["id"]: item for item in source["notes"]}
    after = {item["id"]: item for item in target["notes"]}
    changes = []
    issues = []

    def record(code: str, left: dict[str, Any], right: dict[str, Any] | None, loss: bool) -> None:
        changes.append({"code": code, "source": left, "target": right})
        issues.append(
            ConversionIssue(IssueSeverity.LOSS if loss else IssueSeverity.WARNING, code, code.replace("-", " "), left["location"])
        )

    if source["properties_hash"] != target["properties_hash"]:
        record(
            "footnote-collection-change",
            {"location": "footnote_properties", "properties_hash": source["properties_hash"]},
            {"location": "footnote_properties", "properties_hash": target["properties_hash"]},
            False,
        )
    for identifier, item in before.items():
        if identifier not in after:
            record("footnote-loss", item, None, True)
        elif item["body_hash"] != after[identifier]["body_hash"]:
            record("footnote-change", item, after[identifier], False)
    try:
        matches, lost, added = _match_objects(source["references"], target["references"], budget)
    except _MatchingLimitError as error:
        result, _ = _compare_notes(source, target, False)
        result.update(reason="matching-budget-exceeded", matching_budget=error.measurement)
        return result, [ConversionIssue(IssueSeverity.INFO, "footnote-matching-unavailable", str(error), "footnotes")]
    for item in lost:
        record("footnote-reference-loss", item, None, True)
    changed = []
    for match in matches:
        if match["source"] != match["target"]:
            changed.append(match)
            record("footnote-reference-change", match["source"], match["target"], False)
    return {
        "available": True,
        "lost_notes": sum(identifier not in after for identifier in before),
        "changed_notes": sum(item["code"] == "footnote-change" for item in changes),
        "added_notes": [item for identifier, item in after.items() if identifier not in before],
        "lost_references": len(lost),
        "changed_references": len(changed),
        "added_references": added,
        "reference_matches": matches,
        "changes": changes,
    }, issues


def _note_content_available(source: dict[str, Any], target: dict[str, Any]) -> bool:
    """Old aggregates do not prove retention of newly interpreted note bodies."""
    involved = False
    for metadata in (source, target):
        involved |= metadata.get("footnote_content_included") is True
        for key, format_name in (("semantic_footnotes", "opendoc.footnotes-inventory"), (FOOTNOTES_PROPERTY, FOOTNOTES_PROPERTY)):
            registry = metadata.get(key)
            if isinstance(registry, dict) and registry.get("format") == format_name and registry.get("notes"):
                involved = True
    return not involved or all(_note_inventory_valid(metadata.get("semantic_footnotes")) for metadata in (source, target))


__all__ = [
    "FOOTNOTES_PROPERTY",
    "FOOTNOTE_REFERENCE_PROPERTY",
    "FootnoteNumber",
    "FootnoteReference",
    "get_footnote",
    "get_footnote_reference",
    "iter_footnote_numbers",
    "iter_footnote_references",
    "iter_footnotes",
    "remove_footnote",
    "set_footnote",
    "set_footnote_reference",
]
