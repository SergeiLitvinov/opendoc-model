"""Explicit consumer namespaces and per-call validation of preserved JSON extensions."""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Mapping, MutableMapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias

from opendoc_model._json_validation import _json_tree
from opendoc_model.diagnostics import CheckResult, DiagnosticIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import DocumentModel, Footnote, Paragraph, Section, TextRun
from opendoc_model.limits import DocumentLimits, _quota, _resolve_limits
from opendoc_model.properties import ParagraphProperties
from opendoc_model.traversal import _walk_locations

ExtensionScope: TypeAlias = Literal["metadata", "properties"]
UnknownExtensionPolicy: TypeAlias = Literal["error", "preserve"]
_KEY = re.compile(r"[a-z][a-z0-9_-]*(?:\.[a-z][a-z0-9_-]*)+")
_BUILTINS = {
    "opendoc.table-borders",
    "opendoc.cell-borders",
    "opendoc.table-semantics",
    "opendoc.table-row-semantics",
    "opendoc.table-cell-semantics",
    "opendoc.integration",
    "opendoc.heading",
    "opendoc.list-item",
    "opendoc.anchor",
    "opendoc.internal-link",
    "opendoc.footnotes",
    "opendoc.footnote-reference",
}
_BUILTIN_OWNERS = {
    "opendoc.table-borders": {"Table"},
    "opendoc.cell-borders": {"TableCell"},
    "opendoc.table-semantics": {"Table"},
    "opendoc.table-row-semantics": {"TableRow"},
    "opendoc.table-cell-semantics": {"TableCell"},
    "opendoc.integration": {"DocumentModel"},
    "opendoc.heading": {"Paragraph"},
    "opendoc.list-item": {"Paragraph"},
    "opendoc.anchor": {"Paragraph", "Table", "TextRun", "Formula", "Image"},
    "opendoc.internal-link": {"TextRun"},
    "opendoc.footnote-reference": {"TextRun"},
    "opendoc.footnotes": {"DocumentModel"},
}


def _key(value: Any) -> str:
    if not isinstance(value, str) or _KEY.fullmatch(value) is None or value.startswith("opendoc."):
        raise ValueError("extension key must be a dotted consumer namespace outside opendoc_model.*")
    return value


@dataclass(frozen=True)
class ExtensionValue:
    """Independent JSON data and unknown envelope fields; reading is not semantic verification."""

    key: str
    version: int
    data: Any
    extensions: dict[str, Any]


@dataclass(frozen=True)
class ExtensionContext:
    """A validator receives independent data and a location ending in .data."""

    key: str
    version: int
    data: Any
    location: str
    scope: ExtensionScope
    owner_type: str


ExtensionCallback: TypeAlias = Callable[[ExtensionContext], Iterable[DiagnosticIssue] | None]
ExtensionMigrationCallback: TypeAlias = Callable[[ExtensionValue], Any]


@dataclass(frozen=True)
class ExtensionMigration:
    """Explicit trusted migration, never loaded by a name in stored JSON."""

    key: str
    source_version: int
    target_version: int
    migrate: ExtensionMigrationCallback

    def __post_init__(self) -> None:
        _key(self.key)
        if type(self.source_version) is not int or type(self.target_version) is not int:
            raise ValueError("migration versions must be integers")
        if not 1 <= self.source_version < self.target_version:
            raise ValueError("migration target must be newer than a positive source version")
        if not callable(self.migrate):
            raise ValueError("migration callback must be callable")


@dataclass(frozen=True)
class ExtensionSchema:
    """One consumer key, explicit supported versions and optional trusted validation code."""

    key: str
    versions: frozenset[int]
    validator: ExtensionCallback | None = None
    scopes: frozenset[ExtensionScope] = frozenset({"metadata", "properties"})

    def __post_init__(self) -> None:
        _key(self.key)
        if not isinstance(self.versions, frozenset) or not self.versions:
            raise ValueError("versions must be a nonempty frozenset of positive integers")
        if any(type(version) is not int or version < 1 for version in self.versions):
            raise ValueError("extension versions must be positive integers")
        if self.validator is not None and not callable(self.validator):
            raise ValueError("validator must be callable or None")
        if not isinstance(self.scopes, frozenset) or not self.scopes or not self.scopes <= {"metadata", "properties"}:
            raise ValueError("scopes must be a nonempty frozenset of metadata/properties")


def _value(raw: Any, key: str, path: str) -> ExtensionValue | None:
    if not isinstance(raw, dict) or raw.get("format") != key:
        return None
    if type(raw.get("version")) is not int or raw["version"] < 1:
        raise _DiagnosticError(f"{path}.version", "expected a positive integer extension version", "extension.version")
    if "data" not in raw:
        raise _DiagnosticError(f"{path}.data", "missing extension data", "extension.data")
    return ExtensionValue(
        key,
        raw["version"],
        deepcopy(raw["data"]),
        deepcopy({name: item for name, item in raw.items() if name not in {"format", "version", "data"}}),
    )


def get_extension(bag: Mapping[str, Any], key: str, *, limits: DocumentLimits | None = None) -> ExtensionValue | None:
    """Read a consumer envelope without inferring semantics or executing validation code."""
    _key(key)
    if not isinstance(bag, Mapping):
        raise ValueError("bag must be a mapping")
    resolved = _resolve_limits(limits)
    raw = bag.get(key)
    _json_tree(raw, f"[{key!r}]", resolved)
    return _value(raw, key, f"[{key!r}]")


def set_extension(
    bag: MutableMapping[str, Any], key: str, data: Any, *, version: int = 1, limits: DocumentLimits | None = None
) -> None:
    """Set independent JSON data atomically, retaining unknown tagged envelope fields."""
    existing = get_extension(bag, key, limits=limits)
    if not isinstance(bag, MutableMapping):
        raise ValueError("bag must be mutable")
    if key in bag and existing is None:
        raise ValueError("extension key is occupied by an opaque value")
    raw = deepcopy(bag[key]) if existing is not None else {}
    raw.update(format=key, version=version, data=data)
    _json_tree(raw, f"[{key!r}]", _resolve_limits(limits))
    _value(raw, key, f"[{key!r}]")
    bag[key] = deepcopy(raw)


def remove_extension(bag: MutableMapping[str, Any], key: str, *, limits: DocumentLimits | None = None) -> None:
    """Remove only a recognized envelope; opaque values are preserved by refusal."""
    existing = get_extension(bag, key, limits=limits)
    if not isinstance(bag, MutableMapping):
        raise ValueError("bag must be mutable")
    if key in bag and existing is None:
        raise ValueError("extension key is occupied by an opaque value")
    if existing is not None:
        del bag[key]


def migrate_extension(
    bag: MutableMapping[str, Any],
    key: str,
    target_version: int,
    migrations: Iterable[ExtensionMigration],
    *,
    schema: ExtensionSchema | None = None,
    scope: ExtensionScope = "metadata",
    limits: DocumentLimits | None = None,
) -> ExtensionValue:
    """Run a unique explicit forward chain atomically, preserving unknown envelope fields.

    Callbacks receive independent values; exceptions propagate without modifying
    the bag. Their runtime and external side effects remain the caller's responsibility.
    Unknown extensions are never automatically declared understood or migrated.
    """
    budget = _resolve_limits(limits)
    if scope not in ("metadata", "properties"):
        raise ValueError("scope must be metadata or properties")
    value = get_extension(bag, key, limits=budget)
    if not isinstance(bag, MutableMapping) or value is None:
        raise ValueError("migration requires a mutable bag with a recognized envelope")
    if type(target_version) is not int or target_version < value.version:
        raise ValueError("target version must be an integer >= the current version")
    selected: dict[int, ExtensionMigration] = {}
    for index, migration in enumerate(migrations):
        if index >= budget.max_nodes:
            _quota("migrations", "nodes", budget.max_nodes)
        if not isinstance(migration, ExtensionMigration) or migration.key != key:
            raise ValueError("migrations must belong to the requested extension key")
        if migration.source_version in selected:
            raise ValueError("ambiguous migration chain")
        selected[migration.source_version] = migration
    working = {key: deepcopy(bag[key])}
    while value.version != target_version:
        step = selected.get(value.version)
        if step is None or step.target_version > target_version:
            raise ValueError("no migration chain reaches the requested version")
        data = step.migrate(deepcopy(value))
        set_extension(working, key, data, version=step.target_version, limits=budget)
        value = get_extension(working, key, limits=budget)
        assert value is not None
    if schema is not None:
        if not isinstance(schema, ExtensionSchema) or schema.key != key:
            raise ValueError("schema must belong to the requested extension key")
        carrier = (
            DocumentModel(metadata=working)
            if scope == "metadata"
            else DocumentModel(sections=[Section(blocks=[Paragraph(properties=ParagraphProperties(working))])])
        )
        result = check_extensions(carrier, [schema], limits=budget)
        if not result.success:
            raise ValueError("migrated extension failed schema validation")
    bag[key] = working[key]
    return value


def _schemas(schemas: Iterable[ExtensionSchema], limits: DocumentLimits) -> dict[str, ExtensionSchema]:
    try:
        iterator = iter(schemas)
    except TypeError as error:
        raise ValueError("schemas must be an iterable of ExtensionSchema") from error
    result = {}
    for index, schema in enumerate(iterator):
        if index >= limits.max_nodes:
            _quota("schemas", "nodes", limits.max_nodes)
        if not isinstance(schema, ExtensionSchema):
            raise ValueError("schemas must contain ExtensionSchema")
        if schema.key in result:
            raise ValueError(f"duplicate extension schema {schema.key!r}")
        result[schema.key] = schema
    return result


def _bags(document: DocumentModel, limits: DocumentLimits) -> Iterator[tuple[Mapping[str, Any], str, ExtensionScope, str]]:
    yield document.metadata, "metadata", "metadata", "DocumentModel"
    yield document.footnote_properties, "footnote_properties", "metadata", "DocumentModel"
    yield document.footnote_extensions, "footnote_extensions", "metadata", "DocumentModel"
    for key, style in document.styles.items():
        yield style.properties, f"styles[{key!r}].properties", "properties", "TextStyle"
    for key, resource in document.resources.items():
        yield resource.properties, f"resources[{key!r}].properties", "properties", "Resource"
    for location in _walk_locations(document, limits):
        node = location.node
        if isinstance(node, DocumentModel):
            continue
        yield node.properties, f"{location.path}.properties", "properties", type(node).__name__
        if isinstance(node, Footnote):
            yield node.extensions, f"{location.path}.extensions", "properties", "Footnote"
        if isinstance(node, TextRun):
            yield node.style.properties, f"{location.path}.style.properties", "properties", "TextStyle"


def _check_extensions(
    document: DocumentModel, schemas: dict[str, ExtensionSchema], unknown: UnknownExtensionPolicy, limits: DocumentLimits
) -> CheckResult:
    if unknown not in ("error", "preserve"):
        raise ValueError("unknown must be error or preserve")
    issues: list[DiagnosticIssue] = []
    counts = {"checked": 0, "unknown": 0, "opaque": 0}

    def add(issue: DiagnosticIssue) -> None:
        if len(issues) >= limits.max_nodes:
            _quota("extension issues", "nodes", limits.max_nodes)
        _json_tree(
            {
                "code": issue.code,
                "severity": issue.severity.value,
                "message": issue.message,
                "location": issue.location,
                "measurement": issue.measurement,
                "reason": issue.reason,
            },
            "extension issue",
            limits,
        )
        issues.append(deepcopy(issue))

    for bag, path, scope, owner in _bags(document, limits):
        for key, raw in bag.items():
            schema = schemas.get(key)
            location = f"{path}[{key!r}]"
            builtin = key in _BUILTINS
            tagged = isinstance(raw, dict) and raw.get("format") == key
            if builtin:
                if tagged and (
                    owner not in _BUILTIN_OWNERS[key]
                    or key in {"opendoc.footnotes", "opendoc.integration"}
                    and path != "metadata"
                ):
                    add(
                        DiagnosticIssue(
                            "extension.builtin-scope",
                            IssueSeverity.ERROR,
                            "built-in extension is declared on an unsupported carrier",
                            location,
                        )
                    )
                continue
            if schema is None and (_KEY.fullmatch(key) is None or not tagged):
                continue
            if not tagged:
                counts["opaque"] += 1
                add(DiagnosticIssue("extension.opaque", IssueSeverity.ERROR, "registered extension is opaque", location))
                continue
            try:
                value = _value(raw, key, location)
            except _DiagnosticError as error:
                add(DiagnosticIssue(error.code, IssueSeverity.ERROR, error.message, error.location))
                continue
            assert value is not None
            if schema is None:
                counts["unknown"] += 1
                add(
                    DiagnosticIssue(
                        "extension.unknown",
                        IssueSeverity.ERROR if unknown == "error" else IssueSeverity.INFO,
                        "no schema is registered for this extension",
                        location,
                        {"key": key, "version": value.version},
                        "unknown-extension",
                    )
                )
                continue
            if value.version not in schema.versions:
                add(
                    DiagnosticIssue(
                        "extension.unsupported-version",
                        IssueSeverity.ERROR,
                        "unsupported extension version",
                        f"{location}.version",
                        {"version": value.version, "supported": sorted(schema.versions)},
                    )
                )
                continue
            if scope not in schema.scopes:
                add(DiagnosticIssue("extension.scope", IssueSeverity.ERROR, "extension is not allowed in this scope", location))
                continue
            counts["checked"] += 1
            if schema.validator is None:
                continue
            context = ExtensionContext(key, value.version, value.data, f"{location}.data", scope, owner)
            output = schema.validator(context)
            if output is None:
                continue
            try:
                iterator = iter(output)
            except TypeError as error:
                raise ValueError("extension validator must return diagnostics or None") from error
            for issue in iterator:
                if not isinstance(issue, DiagnosticIssue):
                    raise ValueError("extension validator must return DiagnosticIssue values")
                suffix = f".{issue.location}" if issue.location else ""
                add(
                    DiagnosticIssue(
                        issue.code, issue.severity, issue.message, context.location + suffix, issue.measurement, issue.reason
                    )
                )
    result = CheckResult(issues, {"extensions": counts})
    result.to_dict(limits=limits)
    return result


def check_extensions(
    document: DocumentModel,
    schemas: Iterable[ExtensionSchema],
    *,
    unknown: UnknownExtensionPolicy = "error",
    limits: DocumentLimits | None = None,
) -> CheckResult:
    """Check the whole model plus declared extension schemas, without global registration.

    Callback data/diagnostics are independent snapshots. Callback exceptions
    propagate; no executable names are loaded from JSON. Opaque bytes remain opaque.
    """
    from opendoc_model._validation import _model_issues

    resolved = _resolve_limits(limits)
    selected = _schemas(schemas, resolved)
    if unknown not in ("error", "preserve"):
        raise ValueError("unknown must be error or preserve")
    issues = _model_issues(document, resolved)
    if issues:
        return CheckResult(issues, {"extensions": {"checked": None, "unknown": None, "opaque": None}})
    return _check_extensions(document, selected, unknown, resolved)


__all__ = [
    "ExtensionCallback",
    "ExtensionContext",
    "ExtensionMigration",
    "ExtensionMigrationCallback",
    "ExtensionSchema",
    "ExtensionScope",
    "ExtensionValue",
    "UnknownExtensionPolicy",
    "check_extensions",
    "get_extension",
    "migrate_extension",
    "remove_extension",
    "set_extension",
]
