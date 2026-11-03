"""Shared, bounded traversal of structural model occurrences and resource links."""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Generic, Literal, TypeAlias, TypeVar, cast

from opendoc_model.document_model import (
    Block,
    BlockGroup,
    DocumentModel,
    Footnote,
    Formula,
    Image,
    Inline,
    Paragraph,
    Section,
    Table,
    TableCell,
    TableRow,
    TextRun,
    VisualSurrogate,
)
from opendoc_model.limits import DocumentLimits, _guard_model, _quota, _resolve_limits

SECTION_CONTENT_FIELDS = (
    "headers",
    "first_page_headers",
    "even_page_headers",
    "blocks",
    "footers",
    "first_page_footers",
    "even_page_footers",
)
Element: TypeAlias = Block | TextRun
ModelNode: TypeAlias = DocumentModel | Section | TableRow | TableCell | Element | Footnote
NodeKind: TypeAlias = Literal["document", "section", "block", "inline", "row", "cell", "footnote"]
ResourceReferenceKind: TypeAlias = Literal["image", "fallback", "surrogate", "text"]
_NodeT = TypeVar("_NodeT", bound=ModelNode, covariant=True)
_ElementT = TypeVar("_ElementT", bound=Element)
_ErrorHandler: TypeAlias = Callable[[str, str], None]
_ChildSpec: TypeAlias = tuple[str, tuple[type[ModelNode], ...], NodeKind]
_ELEMENT_TYPES = (Paragraph, Table, TextRun, Formula, Image, BlockGroup)
_NODE_TYPES = (DocumentModel, Section, TableRow, TableCell, *_ELEMENT_TYPES, Footnote)


@dataclass(frozen=True, eq=False, slots=True)
class NodeLocation(Generic[_NodeT]):
    """One occurrence; paths and positions require a fresh walk after structural edits."""

    node: _NodeT = field(repr=False)
    path: str
    parent: NodeLocation[ModelNode] | None = field(repr=False)
    field: str | None
    index: int | None
    kind: NodeKind

    @property
    def section(self) -> Section | None:
        current: NodeLocation[ModelNode] | None = self
        while current is not None:
            if isinstance(current.node, Section):
                return current.node
            current = current.parent
        return None

    @property
    def section_index(self) -> int | None:
        current: NodeLocation[ModelNode] | None = self
        while current is not None:
            if isinstance(current.node, Section):
                return current.index
            current = current.parent
        return None


@dataclass(frozen=True, slots=True)
class ResourceReference:
    """An explicit model resource use, including its owner and exact field path."""

    owner: NodeLocation[Element]
    resource_id: str
    path: str
    field: str
    kind: ResourceReferenceKind


def _fail(path: str, message: str, on_error: _ErrorHandler | None) -> None:
    if on_error is None:
        raise ValueError(f"{path or 'root'}: {message}")
    on_error(path or "root", message)


def _join(path: str, name: str) -> str:
    return f"{path}.{name}" if path else name


def _child_fields(node: ModelNode) -> tuple[_ChildSpec, ...]:
    if isinstance(node, DocumentModel):
        return (("sections", (Section,), "section"), ("footnotes", (Footnote,), "footnote"))
    if isinstance(node, Footnote):
        return (("blocks", (Paragraph, Table, Image, Formula, BlockGroup), "block"),)
    if isinstance(node, Section):
        return tuple((name, (Paragraph, Table, Image, Formula, BlockGroup), "block") for name in SECTION_CONTENT_FIELDS)
    if isinstance(node, BlockGroup):
        return (("children", (Paragraph, Table, Image, Formula, BlockGroup), "block"),)
    if isinstance(node, Table):
        return (("rows", (TableRow,), "row"),)
    if isinstance(node, TableRow):
        return (("cells", (TableCell,), "cell"),)
    if isinstance(node, TableCell):
        return (("blocks", (Paragraph, Table, Image, Formula, BlockGroup), "block"),)
    if isinstance(node, Paragraph):
        return (("content", (TextRun, Image, Formula), "inline"),)
    return ()


def _children(reference: NodeLocation[ModelNode], on_error: _ErrorHandler | None) -> Iterator[NodeLocation[ModelNode]]:
    for name, expected, kind in _child_fields(reference.node):
        path = _join(reference.path, name)
        values = getattr(reference.node, name)
        if not isinstance(values, list):
            _fail(path, "expected list", on_error)
            continue
        for index, node in enumerate(values):
            location = f"{path}[{index}]"
            if not isinstance(node, expected):
                names = ", ".join(item.__name__ for item in expected)
                _fail(location, f"expected {names}", on_error)
                continue
            yield NodeLocation(node, location, reference, name, index, kind)


def _root_kind(root: ModelNode) -> NodeKind:
    if isinstance(root, DocumentModel):
        return "document"
    if isinstance(root, Footnote):
        return "footnote"
    if isinstance(root, Section):
        return "section"
    if isinstance(root, TableRow):
        return "row"
    if isinstance(root, TableCell):
        return "cell"
    return "inline" if isinstance(root, TextRun) else "block"


def _walk_locations(
    root: ModelNode,
    limits: DocumentLimits,
    *,
    path: str = "",
    on_error: _ErrorHandler | None = None,
) -> Iterator[NodeLocation[ModelNode]]:
    initial = NodeLocation(root, path, None, None, None, _root_kind(root))
    stack: list[tuple[Iterator[NodeLocation[ModelNode]], ModelNode | None]] = [(iter((initial,)), None)]
    active: set[int] = set()
    count = 0
    while stack:
        iterator, owner = stack[-1]
        reference = next(iterator, None)
        if reference is None:
            stack.pop()
            if owner is not None:
                active.remove(id(owner))
            continue
        if id(reference.node) in active:
            _fail(reference.path, "cyclic structural model", on_error)
            continue
        count += 1
        if count > limits.max_nodes:
            _quota(reference.path, "nodes", limits.max_nodes)
        if len(active) + 1 > limits.max_depth:
            _quota(reference.path, "depth", limits.max_depth)
        active.add(id(reference.node))
        yield reference
        stack.append((_children(reference, on_error), reference.node))


def walk_model(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[ModelNode]]:
    """Yield root and descendants in preorder; preserve repeated occurrences.

    The root path is empty, children use field names and list indices. Scalar
    edits are allowed during iteration; structural edits require a fresh walk.
    Shape violations raise ValueError, budget exhaustion ArtifactLimitError.
    This is a structural walk, not semantic validation of fields or references.
    """
    if not isinstance(root, _NODE_TYPES):
        raise ValueError("root: expected a supported structural model node")
    budget = _resolve_limits(limits)
    _guard_model(root, budget)
    yield from _walk_locations(root, budget)


def iter_sections(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Section]]:
    """Yield sections with their actual parent and document position."""
    for reference in walk_model(root, limits=limits):
        if isinstance(reference.node, Section):
            yield cast(NodeLocation[Section], reference)


def iter_blocks(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Block]]:
    """Yield block occurrences, including nested cells and every section collection."""
    for reference in walk_model(root, limits=limits):
        if reference.kind == "block":
            yield cast(NodeLocation[Block], reference)


def iter_inlines(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[NodeLocation[Inline]]:
    """Yield inline occurrences; standalone images/formulas are block roots."""
    for reference in walk_model(root, limits=limits):
        if reference.kind == "inline":
            yield cast(NodeLocation[Inline], reference)


def iter_elements(
    root: ModelNode,
    types: type[_ElementT] | tuple[type[_ElementT], ...],
    *,
    limits: DocumentLimits | None = None,
) -> Iterator[NodeLocation[_ElementT]]:
    """Find element types in both block and inline positions without user recursion."""
    choices = types if isinstance(types, tuple) else (types,)
    if any(not isinstance(item, type) or not issubclass(item, _ELEMENT_TYPES) for item in choices):
        raise ValueError("types: expected element classes")
    for reference in walk_model(root, limits=limits):
        if isinstance(reference.node, choices):
            yield cast(NodeLocation[_ElementT], reference)


def _resource_slots(node: Element) -> Iterator[tuple[str, object, ResourceReferenceKind]]:
    if isinstance(node, Image):
        yield "resource_id", node.resource_id, "image"
        if isinstance(node.properties, Mapping) and node.properties.get("fallback_resource_id") is not None:
            yield "properties.fallback_resource_id", node.properties["fallback_resource_id"], "fallback"
    if isinstance(node, TextRun) and isinstance(node.properties, Mapping) and node.properties.get("resource_id") is not None:
        yield "properties.resource_id", node.properties["resource_id"], "text"
    if isinstance(node.visual_surrogate, VisualSurrogate):
        yield "visual_surrogate.resource_id", node.visual_surrogate.resource_id, "surrogate"


def _references_at(reference: NodeLocation[Element]) -> Iterator[ResourceReference]:
    node = reference.node
    if isinstance(node, (Image, TextRun)) and not isinstance(node.properties, Mapping):
        raise ValueError(f"{_join(reference.path, 'properties')}: expected resource property mapping")
    if node.visual_surrogate is not None and not isinstance(node.visual_surrogate, VisualSurrogate):
        raise ValueError(f"{_join(reference.path, 'visual_surrogate')}: expected VisualSurrogate")
    for name, value, kind in _resource_slots(node):
        path = _join(reference.path, name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: expected nonempty resource identifier")
        yield ResourceReference(reference, value, path, name, kind)


def iter_resource_references(root: ModelNode, *, limits: DocumentLimits | None = None) -> Iterator[ResourceReference]:
    """Yield image, fallback, surrogate and standard TextRun resource links.

    Arbitrary user keys and opaque package relationships are not inferred.
    Missing resource identifiers are yielded; their resolution is validation.
    """
    for reference in walk_model(root, limits=limits):
        if isinstance(reference.node, _ELEMENT_TYPES):
            yield from _references_at(cast(NodeLocation[Element], reference))


def _set_resource_reference(reference: ResourceReference, identifier: str) -> None:
    """Write a previously validated reference using the shared slot grammar."""
    owner = reference.owner.node
    if reference.kind == "image" and isinstance(owner, Image):
        owner.resource_id = identifier
    elif reference.kind == "surrogate":
        if owner.visual_surrogate is None:
            raise ValueError(f"{reference.path}: resource owner changed")
        owner.visual_surrogate.resource_id = identifier
    else:
        owner.properties[reference.field.removeprefix("properties.")] = identifier


__all__ = [
    "SECTION_CONTENT_FIELDS",
    "Element",
    "ModelNode",
    "NodeKind",
    "NodeLocation",
    "ResourceReference",
    "ResourceReferenceKind",
    "iter_blocks",
    "iter_elements",
    "iter_inlines",
    "iter_resource_references",
    "iter_sections",
    "walk_model",
]
