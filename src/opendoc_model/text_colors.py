"""Declared text-color comparison; no automatic RGB, theme or native cascade."""

from __future__ import annotations

from typing import Any

from opendoc_model._json_validation import _color
from opendoc_model.color import ColorLike, ColorValue
from opendoc_model.document_model import DocumentModel, Paragraph, TextRun
from opendoc_model.limits import DocumentLimits
from opendoc_model.styles import _resolved


def _value(color: ColorLike | None) -> str | dict[str, object] | None:
    return color.to_dict() if isinstance(color, ColorValue) else color


class _TextColors:
    """Cache named styles only after model validation, using the existing cascade."""

    def __init__(self, document: DocumentModel, limits: DocumentLimits) -> None:
        self.document = document
        self.limits = limits
        self.cache: dict[str | None, dict[str, Any]] = {None: {"color": None, "background": None}}

    def named(self, identifier: str | None) -> dict[str, Any]:
        if identifier not in self.cache:
            style = _resolved(self.document, identifier, self.limits)
            self.cache[identifier] = {name: _value(getattr(style, name)) for name in ("color", "background")}
        return self.cache[identifier]

    def paragraph(self, paragraph: Paragraph) -> dict[str, Any] | None:
        identifiers = [
            paragraph.style_id,
            *(run.style.properties.get("base_style_id") for run in paragraph.content if isinstance(run, TextRun)),
        ]
        if any(identifier is not None and identifier not in self.document.styles for identifier in identifiers):
            return None
        inherited = self.named(paragraph.style_id)
        style = self.document.styles.get(paragraph.style_id) if paragraph.style_id is not None else None
        paragraph_direct = {name: _value(getattr(style, name)) if style is not None else None for name in ("color", "background")}
        spans: list[dict[str, Any]] = []
        offset = 0
        for run in paragraph.content:
            if not isinstance(run, TextRun) or not run.text:
                continue
            base = self.named(run.style.properties.get("base_style_id"))
            direct = {name: _value(getattr(run.style, name)) for name in ("color", "background")}
            resolved = {
                name: direct[name] if direct[name] is not None else base[name] if base[name] is not None else inherited[name]
                for name in direct
            }
            state = {"direct": direct, "resolved": resolved}
            end = offset + len(run.text)
            if spans and all(spans[-1][name] == value for name, value in state.items()):
                spans[-1]["end"] = end
            else:
                spans.append({"start": offset, "end": end, **state})
            offset = end
        return {"paragraph": dict(inherited), "paragraph_direct": paragraph_direct, "spans": spans}


def _text_colors_valid(value: Any) -> bool:
    def palette(raw: Any) -> bool:
        if not isinstance(raw, dict) or not {"color", "background"} <= raw.keys():
            return False
        for name in ("color", "background"):
            item = raw[name]
            if item is None or isinstance(item, str):
                continue
            try:
                _color(item, name)
            except ValueError:
                return False
        return True

    if not isinstance(value, dict) or not all(palette(value.get(scope)) for scope in ("paragraph", "paragraph_direct")):
        return False
    if not isinstance(value.get("spans"), list):
        return False
    offset = 0
    for span in value["spans"]:
        if not isinstance(span, dict) or type(span.get("start")) is not int or type(span.get("end")) is not int:
            return False
        if (
            span["start"] != offset
            or span["end"] <= offset
            or not all(palette(span.get(name)) for name in ("direct", "resolved"))
        ):
            return False
        offset = span["end"]
    return True


def _color_loss(source: Any, target: Any) -> bool:
    if source is None:
        return False
    return target is None or source == "auto" and target != "auto"


def _text_colors_removed(source: dict[str, Any], target: dict[str, Any]) -> bool:
    if any(
        _color_loss(source[scope][name], target[scope][name])
        for scope in ("paragraph", "paragraph_direct")
        for name in ("color", "background")
    ):
        return True
    target_spans = target["spans"]
    index = 0
    for before in source["spans"]:
        while index < len(target_spans) and target_spans[index]["end"] <= before["start"]:
            index += 1
        cursor = before["start"]
        current = index
        while current < len(target_spans) and target_spans[current]["start"] < before["end"]:
            after = target_spans[current]
            if after["start"] > cursor:
                return True
            for scope in ("direct", "resolved"):
                if any(_color_loss(before[scope][name], after[scope][name]) for name in ("color", "background")):
                    return True
            cursor = min(before["end"], after["end"])
            current += 1
        if cursor < before["end"] and any(
            value is not None for scope in ("direct", "resolved") for value in before[scope].values()
        ):
            return True
    return False
