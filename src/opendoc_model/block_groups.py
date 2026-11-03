"""Structural flow scopes and explicit references to existing list paragraphs."""

from opendoc_model.diagnostics import _DiagnosticError
from opendoc_model.document_model import BlockGroup, BlockGroupListOwner, Paragraph
from opendoc_model.limits import DocumentLimits
from opendoc_model.lists import get_list_item
from opendoc_model.references import _identifier, get_anchor
from opendoc_model.traversal import _ELEMENT_TYPES, ModelNode, NodeLocation, _walk_locations


def _validate_block_groups(root: ModelNode, limits: DocumentLimits) -> None:
    # Callers already check the input tree/wire budget. Recharging constructor
    # defaults here would break tight budgets for legacy, group-free JSON.
    locations = list(_walk_locations(root, limits))
    anchors: dict[str, list[NodeLocation[ModelNode]]] = {}
    groups = []
    for location in locations:
        if isinstance(location.node, _ELEMENT_TYPES):
            anchor = get_anchor(location.node, limits=limits)
            if anchor is not None:
                anchors.setdefault(anchor.id, []).append(location)
        if isinstance(location.node, BlockGroup) and location.node.list_owner is not None:
            groups.append(location)
    claimed: set[str] = set()
    for location in groups:
        group = location.node
        assert isinstance(group, BlockGroup) and group.list_owner is not None
        path = f"{location.path}.list_owner.paragraph_id"
        if not isinstance(group.list_owner, BlockGroupListOwner):
            raise _DiagnosticError(path, "expected BlockGroupListOwner", "flow.group.list-owner")
        identifier = _identifier(group.list_owner.paragraph_id, path)
        targets = anchors.get(identifier, [])
        if len(targets) != 1 or not isinstance(targets[0].node, Paragraph):
            raise _DiagnosticError(path, "expected a unique anchored primary Paragraph", "flow.group.list-owner")
        target = targets[0]
        assert isinstance(target.node, Paragraph)
        item = get_list_item(target.node, limits=limits)
        if item is None or item.continuation_of is not None:
            raise _DiagnosticError(path, "target must be a primary list paragraph", "flow.group.list-owner")
        parent = target.parent
        while parent is not None and parent is not location:
            # Locations from one walk have shared parents, so identity is occurrence-specific.
            if isinstance(parent.node, BlockGroup) and parent.node.list_owner is not None:
                raise _DiagnosticError(path, "target belongs to a nested compound group", "flow.group.list-owner")
            parent = parent.parent
        if parent is None or identifier in claimed:
            raise _DiagnosticError(path, "owner must occur inside exactly this compound group", "flow.group.list-owner")
        claimed.add(identifier)


__all__: list[str] = []
