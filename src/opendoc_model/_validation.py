"""Structural model checks shared by persistence and inspection."""

from __future__ import annotations

import math
from collections import deque
from dataclasses import fields
from typing import Any, cast

from opendoc_model._json_validation import _color, _json_tree
from opendoc_model.color import ColorValue
from opendoc_model.diagnostics import DiagnosticIssue, IssueSeverity, _DiagnosticError
from opendoc_model.document_model import (
    Box,
    ConversionMode,
    DocumentModel,
    Footnote,
    Formula,
    FormulaFormat,
    Image,
    ImageCrop,
    Length,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    PageSettings,
    Paragraph,
    Provenance,
    ProvenanceEvent,
    Resource,
    ResourceKind,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    TextStyle,
    VisualSurrogate,
)
from opendoc_model.footnotes import FOOTNOTE_REFERENCE_PROPERTY, FOOTNOTES_PROPERTY, _reference_payload
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits
from opendoc_model.lists import LIST_PROPERTY, _list_payload
from opendoc_model.properties import VersionedProperties
from opendoc_model.references import ANCHOR_PROPERTY, INTERNAL_LINK_PROPERTY, Anchor, InternalLink, _payload
from opendoc_model.semantics import HEADING_PROPERTY, _heading_payload
from opendoc_model.storage import ArtifactLimitError
from opendoc_model.traversal import _resource_slots, _walk_locations

_SERIALIZED_TYPES = (
    DocumentModel,
    Section,
    Footnote,
    Paragraph,
    Table,
    TableRow,
    TableCell,
    TextRun,
    Formula,
    Image,
    TextStyle,
    Resource,
    PackageGraph,
    PackagePart,
    PackageRelationship,
    Box,
    ImageCrop,
    Length,
    PageSettings,
    Provenance,
    ProvenanceEvent,
    VisualSurrogate,
    ColorValue,
)
_STATE_FIELDS = {kind: frozenset(item.name for item in fields(kind)) for kind in _SERIALIZED_TYPES}


class _Validator:
    def __init__(
        self,
        limits: DocumentLimits,
        resources: dict[str, Resource] | None = None,
        styles: dict[str, TextStyle] | None = None,
        issues: list[DiagnosticIssue] | None = None,
    ) -> None:
        self.errors: list[str] = []
        self.issues = issues if issues is not None else []
        self.limits = limits
        self.resources = resources or {}
        self.styles = styles or {}
        self.pending: deque[tuple[str, Any, str]] = deque()
        self.list_configs: dict[tuple[str, int], tuple[str, int]] = {}
        self.anchors: dict[str, str] = {}
        self.internal_links: list[tuple[str, str]] = []
        self.footnotes: dict[str, str] = {}
        self.footnote_references: list[tuple[str, str]] = []

    def error(
        self,
        path: str,
        message: str,
        *,
        code: str = "model.invalid",
        measurement: dict[str, Any] | None = None,
        diagnostic_path: str | None = None,
    ) -> None:
        self.errors.append(f"{path}: {message}" if path else message)
        self.issues.append(
            DiagnosticIssue(
                code,
                IssueSeverity.ERROR,
                message,
                diagnostic_path if diagnostic_path is not None else path,
                measurement,
                "invalid-input",
            )
        )

    def capture(self, error: ValueError, path: str) -> None:
        self.errors.append(str(error))
        if isinstance(error, _DiagnosticError):
            self.issues.append(
                DiagnosticIssue(error.code, IssueSeverity.ERROR, error.message, error.location, reason="invalid-input")
            )
        else:
            self.issues.append(DiagnosticIssue("model.invalid", IssueSeverity.ERROR, str(error), path, reason="invalid-input"))

    def instance(self, value: Any, expected: type[Any] | tuple[type[Any], ...], path: str) -> bool:
        if isinstance(value, expected):
            if not self.serialized_state(value, path):
                return False
            return True
        names = ", ".join(item.__name__ for item in expected) if isinstance(expected, tuple) else expected.__name__
        self.error(path, f"expected {names}", code="model.type", measurement={"expected": names})
        return False

    def serialized_state(self, value: Any, path: str) -> bool:
        known = _STATE_FIELDS.get(type(value))
        if known is None:
            base = next((kind for kind in _SERIALIZED_TYPES if isinstance(value, kind)), None)
            if base is None:
                return True
            self.error(
                path,
                "unsupported serialized model type",
                code="model.type.unsupported",
                measurement={"type": type(value).__name__, "supported": base.__name__},
            )
            return False
        extra = {name for name in getattr(value, "__dict__", {}) if name not in known and not name.startswith("_")}
        if extra:
            self.error(
                path,
                "extra model state must be stored in properties/metadata",
                code="model.state.unsupported",
                measurement={"fields": sorted(extra)},
            )
            return False
        return True

    def string(self, value: Any, path: str, *, nullable: bool = False, nonempty: bool = False) -> bool:
        if value is None and nullable:
            return True
        if not isinstance(value, str):
            self.error(path, "expected a string", code="model.type", measurement={"expected": "str"})
            return False
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            self.error(path, "string cannot be encoded as UTF-8", code="json.utf8")
            return False
        if nonempty and not value:
            self.error(path, "string must not be empty", code="model.empty-string")
            return False
        return True

    def number(self, value: Any, path: str, *, minimum: float | None = None, positive: bool = False) -> bool:
        try:
            valid = type(value) in (int, float) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid:
            self.error(path, "expected a finite number", code="model.number.invalid")
            return False
        if positive and value <= 0:
            self.error(path, "number must be positive", code="model.number.range", measurement={"minimum_exclusive": 0})
            return False
        if minimum is not None and value < minimum:
            self.error(path, f"number must be at least {minimum:g}", code="model.number.range", measurement={"minimum": minimum})
            return False
        return True

    def properties(self, value: Any, path: str) -> dict[str, Any]:
        if isinstance(value, VersionedProperties):
            value = value.to_dict()
        if not self.instance(value, dict, path):
            return {}
        try:
            _json_tree(value, path, self.limits)
        except ArtifactLimitError:
            raise
        except ValueError as error:
            self.capture(error, path)
        return cast(dict[str, Any], value)

    def reference(self, value: Any, path: str, kind: str, *, legacy_path: str | None = None, nullable: bool = True) -> None:
        if not self.string(value, path, nullable=nullable):
            return
        if value is None:
            return
        values = self.styles if kind == "style" else self.resources
        if value not in values:
            self.error(
                legacy_path or path,
                f"unknown {kind} {value!r}",
                code="model.reference.missing",
                measurement={"kind": kind, "identifier": value},
                diagnostic_path=path,
            )

    def run(self) -> None:
        # A bounded preflight has already rejected cycles. No recursive calls
        # are needed to check every occurrence in the semantic tree.
        while self.pending:
            category, item, path = self.pending.popleft()
            getattr(self, category)(item, path)

    def provenance(self, value: Any, path: str) -> None:
        if value is None or not self.instance(value, Provenance, path):
            return
        self.string(value.source_format, f"{path}.source_format")
        for name in ("source_path", "object_id", "package_part"):
            self.string(getattr(value, name), f"{path}.{name}", nullable=True)
        if value.page is not None and (type(value.page) is not int or value.page < 0):
            self.error(f"{path}.page", "page must be a non-negative integer")
        if self.instance(value.events, list, f"{path}.events"):
            for index, event in enumerate(value.events):
                location = f"{path}.events[{index}]"
                if self.instance(event, ProvenanceEvent, location):
                    self.string(event.operation, f"{location}.operation")
                    self.string(event.detail, f"{location}.detail")
                    self.string(event.fallback_reason, f"{location}.fallback_reason", nullable=True)

    def surrogate(self, value: Any, path: str) -> None:
        if value is None or not self.instance(value, VisualSurrogate, path):
            return
        self.string(value.reason, f"{path}.reason", nonempty=True)
        self.string(value.media_type, f"{path}.media_type", nullable=True)
        if value.fidelity is not None and self.number(value.fidelity, f"{path}.fidelity", minimum=0) and value.fidelity > 1:
            self.error(f"{path}.fidelity", "fidelity must be between 0 and 1")

    def box(self, value: Any, path: str) -> None:
        if value is None or not self.instance(value, Box, path):
            return
        for name in ("x", "y", "rotation"):
            self.number(getattr(value, name), f"{path}.{name}")
        for name in ("width", "height"):
            self.number(getattr(value, name), f"{path}.{name}", minimum=0)

    def style(self, value: TextStyle, path: str) -> None:
        for name in ("font_family", "language"):
            self.string(getattr(value, name), f"{path}.{name}", nullable=True)
        for name in ("bold", "italic", "underline", "superscript", "subscript"):
            item = getattr(value, name)
            if item is not None and type(item) is not bool:
                self.error(f"{path}.{name}", "expected a boolean or None")
        if value.font_size is not None and self.instance(value.font_size, Length, f"{path}.font_size"):
            self.number(value.font_size.pt, f"{path}.font_size.pt", positive=True)
        for name in ("color", "background"):
            item = getattr(value, name)
            if item is not None and not isinstance(item, (str, ColorValue)):
                self.error(f"{path}.{name}", "expected a color or string")
            elif isinstance(item, ColorValue):
                try:
                    _color(item.to_dict(), f"{path}.{name}")
                except ValueError as error:
                    self.capture(error, f"{path}.{name}")
        properties = self.properties(value.properties, f"{path}.properties")
        self.reference(properties.get("base_style_id"), f"{path}.properties.base_style_id", "style")

    def page(self, value: PageSettings, path: str) -> None:
        valid = True
        for name in ("width", "height", "margin_top", "margin_right", "margin_bottom", "margin_left"):
            length = getattr(value, name)
            if not self.instance(length, Length, f"{path}.{name}"):
                valid = False
            elif not self.number(length.pt, f"{path}.{name}.pt", minimum=0, positive=name in {"width", "height"}):
                valid = False
        if valid:
            if value.margin_left.pt + value.margin_right.pt >= value.width.pt:
                self.error(path, "horizontal margins consume the page width")
            if value.margin_top.pt + value.margin_bottom.pt >= value.height.pt:
                self.error(path, "vertical margins consume the page height")

    def section(self, value: Section, path: str) -> None:
        if self.instance(value.page, PageSettings, f"{path}.page"):
            self.page(value.page, f"{path}.page")
        self.properties(value.properties, f"{path}.properties")
        self.provenance(value.provenance, f"{path}.provenance")

    def element(self, value: Any, path: str) -> None:
        properties = self.properties(value.properties, f"{path}.properties")
        if isinstance(value, Table):
            self.preferred_width(value, path)
        for key in (ANCHOR_PROPERTY, INTERNAL_LINK_PROPERTY):
            if key == INTERNAL_LINK_PROPERTY and not isinstance(value, TextRun):
                continue
            location = f"{path}.properties[{key!r}]"
            try:
                item = _payload(properties.get(key), location, key)
                if isinstance(item, Anchor):
                    if item.id in self.anchors:
                        self.error(
                            f"{location}.id",
                            f"duplicate anchor {item.id!r}",
                            code="semantic.anchor.duplicate",
                            measurement={"first_location": self.anchors[item.id]},
                        )
                    else:
                        self.anchors[item.id] = path
                elif isinstance(item, InternalLink):
                    self.internal_links.append((item.target_id, f"{location}.target_id"))
                    if value.link is not None:
                        self.error(location, "internal link conflicts with TextRun.link", code="semantic.link.conflict")
            except ValueError as error:
                self.capture(error, location)
        self.provenance(value.provenance, f"{path}.provenance")
        self.surrogate(value.visual_surrogate, f"{path}.visual_surrogate")
        for name, resource_id, kind in _resource_slots(value):
            label = {
                "image": "resource",
                "fallback": "fallback resource",
                "surrogate": "visual surrogate resource",
                "text": "resource",
            }[kind]
            self.reference(resource_id, f"{path}.{name}", label, legacy_path=None if kind == "text" else path, nullable=False)
        if isinstance(value, TextRun):
            note_path = f"{path}.properties[{FOOTNOTE_REFERENCE_PROPERTY!r}]"
            try:
                note_reference = _reference_payload(properties.get(FOOTNOTE_REFERENCE_PROPERTY), note_path)
                if note_reference is not None:
                    self.footnote_references.append((note_reference.note_id, f"{note_path}.note_id"))
                    internal = _payload(properties.get(INTERNAL_LINK_PROPERTY), note_path, INTERNAL_LINK_PROPERTY)
                    if value.link is not None or internal is not None:
                        self.error(
                            note_path, "footnote reference conflicts with another link role", code="semantic.footnote.conflict"
                        )
            except ValueError as error:
                self.capture(error, note_path)
            self.string(value.text, f"{path}.text")
            self.string(value.link, f"{path}.link", nullable=True)
            if self.instance(value.style, TextStyle, f"{path}.style"):
                self.style(value.style, f"{path}.style")
            return
        self.box(value.box, f"{path}.box")
        if isinstance(value, Paragraph):
            list_path = f"{path}.properties[{LIST_PROPERTY!r}]"
            try:
                list_item = _list_payload(properties.get(LIST_PROPERTY), list_path)
                if list_item is not None:
                    list_key, config = (list_item.list_id, list_item.level), (list_item.kind, list_item.start)
                    if list_key in self.list_configs and self.list_configs[list_key] != config:
                        self.error(list_path, "conflicting list kind/start for the same level", code="semantic.list.config")
                    self.list_configs[list_key] = config
            except ValueError as error:
                self.capture(error, list_path)
            try:
                _heading_payload(properties.get(HEADING_PROPERTY), f"{path}.properties[{HEADING_PROPERTY!r}]")
            except ValueError as error:
                self.capture(error, f"{path}.properties")
            self.reference(value.style_id, f"{path}.style_id", "style")
            self.string(value.alignment, f"{path}.alignment", nullable=True)
        elif isinstance(value, Table):
            self.reference(value.style_id, f"{path}.style_id", "style")
        elif isinstance(value, Image):
            self.string(value.alt_text, f"{path}.alt_text")
            self.crop(value.crop, f"{path}.crop")
        elif isinstance(value, Formula):
            self.string(value.value, f"{path}.value", nonempty=True)
            self.instance(value.format, FormulaFormat, f"{path}.format")
            self.string(value.fallback_text, f"{path}.fallback_text")
            if type(value.display) is not bool:
                self.error(f"{path}.display", "expected a boolean")

    def crop(self, value: Any, path: str) -> None:
        if value is None or not self.instance(value, ImageCrop, path):
            return
        valid = True
        for name in ("left", "top", "right", "bottom"):
            item = getattr(value, name)
            if not self.number(item, f"{path}.{name}", minimum=0):
                valid = False
            elif item > 1:
                self.error(f"{path}.{name}", "crop fraction must be at most 1")
                valid = False
        if valid and (value.left + value.right >= 1 or value.top + value.bottom >= 1):
            self.error(path, "crop removes the entire image")

    def row(self, value: TableRow, path: str) -> None:
        self.properties(value.properties, f"{path}.properties")

    def footnote(self, value: Footnote, path: str) -> None:
        if self.string(value.id, f"{path}.id", nonempty=True):
            if value.id in self.footnotes:
                self.error(
                    f"{path}.id",
                    f"duplicate footnote {value.id!r}",
                    code="semantic.footnote.duplicate",
                    measurement={"first_location": self.footnotes[value.id]},
                )
            else:
                self.footnotes[value.id] = path
        self.properties(value.properties, f"{path}.properties")
        extensions = self.properties(value.extensions, f"{path}.extensions")
        if {"id", "blocks", "properties"}.intersection(extensions):
            self.error(
                f"{path}.extensions", "reserved footnote fields in extensions", code="semantic.footnote.extension-conflict"
            )

    def cell(self, value: TableCell, path: str) -> None:
        for name in ("row_span", "column_span"):
            item = getattr(value, name)
            if type(item) is not int or item < 1:
                self.error(f"{path}.{name}", "span must be a positive integer")
        self.properties(value.properties, f"{path}.properties")
        self.preferred_width(value, path)

    def preferred_width(self, value: Table | TableCell, path: str) -> None:
        from opendoc_model.widths import get_preferred_width

        # Old bags retain their existing permissive semantics until a new
        # preference is explicitly present.
        if isinstance(value.properties, (dict, VersionedProperties)) and value.properties.get("preferred_width") is not None:
            try:
                get_preferred_width(value, limits=self.limits)
            except ArtifactLimitError:
                raise
            except ValueError as error:
                self.error(f"{path}.properties.preferred_width", str(error), code="model.width.invalid")

    def resource(self, value: Resource, path: str) -> None:
        self.string(value.id, f"{path}.id", nonempty=True)
        self.instance(value.kind, ResourceKind, f"{path}.kind")
        self.string(value.media_type, f"{path}.media_type")
        self.string(value.source, f"{path}.source", nullable=True)
        self.string(value.filename, f"{path}.filename", nullable=True)
        if value.data is not None:
            self.instance(value.data, bytes, f"{path}.data")
        if value.data is None and value.source is None:
            self.error(path, "resource requires either data or source")
        self.properties(value.properties, f"{path}.properties")
        self.provenance(value.provenance, f"{path}.provenance")

    def mapping(self, value: Any, expected: type[Any], path: str, category: str) -> dict[str, Any]:
        if not self.instance(value, dict, path):
            return {}
        for key, item in value.items():
            if not self.string(key, path, nonempty=True):
                continue
            location = f"{path}[{key!r}]"
            if self.instance(item, expected, location):
                self.pending.append((category, item, location))
                if isinstance(item, Resource) and item.id != key:
                    self.error(f"{location}.id", f"must match object key {key!r}")
        return cast(dict[str, Any], value)

    def package_name(self, value: Any, path: str, *, root: bool = False) -> bool:
        if not self.string(value, path, nonempty=True):
            return False
        if root and value == "/":
            return True
        if not value.startswith("/") or any(part in {"", ".", ".."} for part in value.split("/")[1:]):
            self.error(path, "package name must be an absolute normalized path")
            return False
        return True

    def package(self, value: PackageGraph, path: str) -> None:
        if not self.serialized_state(value, path):
            return
        self.string(value.format, f"{path}.format")
        self.package_name(value.root, f"{path}.root", root=True)
        parts = value.parts if self.instance(value.parts, dict, f"{path}.parts") else {}
        for name, part in parts.items():
            if not self.package_name(name, f"{path}.parts"):
                continue
            location = f"{path}.parts[{name!r}]"
            if not self.instance(part, PackagePart, location):
                continue
            self.package_name(part.name, f"{location}.name")
            if part.name != name:
                self.error(f"{location}.name", f"must match object key {name!r}")
            self.string(part.media_type, f"{location}.media_type")
            self.instance(part.data, bytes, f"{location}.data")
        seen: set[tuple[str, str]] = set()
        if not self.instance(value.relationships, list, f"{path}.relationships"):
            return
        for index, item in enumerate(value.relationships):
            location = f"{path}.relationships[{index}]"
            if not self.instance(item, PackageRelationship, location):
                continue
            identifier = self.string(item.id, f"{location}.id", nonempty=True)
            source = self.package_name(item.source, f"{location}.source", root=True)
            self.string(item.relationship_type, f"{location}.relationship_type", nonempty=True)
            target = self.string(item.target, f"{location}.target", nonempty=True)
            if type(item.external) is not bool:
                self.error(f"{location}.external", "expected a boolean")
                continue
            if identifier and source:
                key = (item.source, item.id)
                if key in seen:
                    self.error(f"{location}.id", f"duplicate relationship {item.source}:{item.id}")
                seen.add(key)
                if item.source not in parts and item.source not in {"/", value.root}:
                    self.error(f"{location}.source", f"unknown relationship source {item.source!r}")
            if target and not item.external:
                self.package_name(item.target, f"{location}.target")
                if item.target not in parts:
                    self.error(f"{location}.target", f"unknown relationship target {item.target!r}")

    def style_cycles(self) -> None:
        checked: set[str] = set()
        for start in self.styles:
            visited: set[str] = set()
            current = start
            while current not in checked and current in self.styles:
                if current in visited:
                    self.error(
                        f"styles[{current!r}].properties.base_style_id", "cyclic style inheritance", code="model.style.cycle"
                    )
                    break
                visited.add(current)
                style = self.styles[current]
                if not isinstance(style, TextStyle) or not isinstance(style.properties, (dict, VersionedProperties)):
                    break
                parent = style.properties.get("base_style_id")
                if not isinstance(parent, str):
                    break
                current = parent
            checked.update(visited)


def _preflight(value: Any, validator: _Validator) -> bool:
    try:
        _guard_model(value, validator.limits)
    except ArtifactLimitError:
        raise
    except ValueError as error:
        validator.capture(error, "$")
        return False
    return True


def _validate_model(
    document: DocumentModel,
    limits: DocumentLimits | None = None,
    *,
    preflight: bool = True,
    issues: list[DiagnosticIssue] | None = None,
) -> list[str]:
    validator = _Validator(_resolve_limits(limits), issues=issues)
    if preflight and not _preflight(document, validator):
        return validator.errors
    if not validator.instance(document, DocumentModel, "document"):
        return validator.errors
    validator.instance(document.mode, ConversionMode, "mode")
    validator.string(document.source_format, "source_format", nullable=True)
    if type(document.version) is not int or document.version not in {1, 2}:
        validator.error("version", "unsupported model version")
    validator.properties(document.metadata, "metadata")
    validator.properties(document.footnote_properties, "footnote_properties")
    extensions = validator.properties(document.footnote_extensions, "footnote_extensions")
    if {"format", "version", "notes", "properties"}.intersection(extensions):
        validator.error(
            "footnote_extensions", "reserved registry fields in extensions", code="semantic.footnote.extension-conflict"
        )
    if isinstance(document.metadata, dict) and FOOTNOTES_PROPERTY in document.metadata:
        raw_notes = document.metadata[FOOTNOTES_PROPERTY]
        tagged = isinstance(raw_notes, dict) and raw_notes.get("format") == FOOTNOTES_PROPERTY
        if tagged or document.footnotes or document.footnote_properties or document.footnote_extensions:
            validator.error(
                f"metadata[{FOOTNOTES_PROPERTY!r}]",
                "serialized footnotes metadata is reserved; use the model footnotes collection",
                code="semantic.footnote.metadata-conflict",
            )
    validator.resources = validator.mapping(document.resources, Resource, "resources", "resource")
    validator.styles = validator.mapping(document.styles, TextStyle, "styles", "style")
    if document.package is not None and validator.instance(document.package, PackageGraph, "package"):
        validator.package(document.package, "package")
    validator.run()
    for reference in _walk_locations(document, validator.limits, on_error=validator.error):
        node, path = reference.node, reference.path
        if node is not document and not validator.serialized_state(node, path):
            continue
        if isinstance(node, Section):
            validator.section(node, path)
        elif isinstance(node, Footnote):
            validator.footnote(node, path)
        elif isinstance(node, TableRow):
            validator.row(node, path)
        elif isinstance(node, TableCell):
            validator.cell(node, path)
        elif isinstance(node, (Paragraph, Table, TextRun, Image, Formula)):
            validator.element(node, path)
    validator.style_cycles()
    for identifier, path in validator.internal_links:
        if identifier not in validator.anchors:
            validator.error(
                path,
                f"unknown anchor {identifier!r}",
                code="semantic.anchor.missing",
                measurement={"identifier": identifier},
            )
    for identifier, path in validator.footnote_references:
        if identifier not in validator.footnotes:
            validator.error(
                path,
                f"unknown footnote {identifier!r}",
                code="semantic.footnote.missing",
                measurement={"identifier": identifier},
            )
    if not validator.errors:
        from opendoc_model.table_borders import _validate_borders
        from opendoc_model.table_semantics import _validate_tables

        try:
            _validate_tables(document, validator.limits)
            _validate_borders(document, validator.limits)
        except ArtifactLimitError:
            raise
        except ValueError as error:
            validator.capture(error, "table semantics")
    if not validator.errors:
        from opendoc_model.integration import _integration_issue

        issue = _integration_issue(document, validator.limits)
        if issue is not None:
            validator.error(issue.location, issue.message, code=issue.code)
    return validator.errors


def _model_issues(document: DocumentModel, limits: DocumentLimits | None = None) -> list[DiagnosticIssue]:
    issues: list[DiagnosticIssue] = []
    _validate_model(document, limits, issues=issues)
    return issues


def _validate_package(package: PackageGraph, limits: DocumentLimits | None = None) -> list[str]:
    validator = _Validator(_resolve_limits(limits))
    if _preflight(package, validator):
        validator.package(package, "package")
    return validator.errors
