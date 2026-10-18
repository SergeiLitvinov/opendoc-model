"""Mixed paint scopes in the existing VectorScene; no native interpreter or renderer."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any, TypeVar

from opendoc_model.document_model import DocumentModel, Resource, ResourceKind
from opendoc_model.integration_types import (
    GroupColorSpace,
    GroupCompositing,
    PathCommand,
    SceneOccurrence,
    VectorClip,
    VectorGroup,
    VectorScene,
)
from opendoc_model.limits import DocumentLimits, _guard_model, _resolve_limits


def _commands(commands: tuple[PathCommand, ...], location: str) -> None:
    from opendoc_model.integration import _error

    arities = {"move": 2, "line": 2, "quadratic": 4, "cubic": 6, "close": 0}
    opened = False
    for index, command in enumerate(commands):
        path = f"{location}[{index}]"
        if len(command.values) != arities[command.operation]:
            _error(path, "wrong command arity")
        if command.operation == "move":
            opened = True
        elif not opened:
            _error(path, "a subpath must begin with move")
        elif command.operation == "close":
            opened = False


def _compositing(value: GroupCompositing | None, path: str, resources: dict[str, Resource]) -> None:
    from opendoc_model.integration import _error, _reference

    if value is not None and value.opacity is not None and not 0 <= value.opacity <= 1:
        _error(path + ".opacity", "expected opacity between 0 and 1 or unknown")
    color = value.color_space if value is not None else None
    if color is not None:
        location = path + ".color_space"
        _reference(color.profile_resource_id, resources, location + ".profile_resource_id")
        if color.profile_resource_id is not None and resources[color.profile_resource_id].kind != ResourceKind.ATTACHMENT:
            _error(location + ".profile_resource_id", "profile requires an ATTACHMENT resource")
        if color.space == "icc" and color.profile_resource_id is None:
            _error(location + ".profile_resource_id", "ICC space requires an explicit profile resource")
        if color.space == "srgb" and color.profile_resource_id is not None:
            _error(location, "fixed sRGB cannot carry a profile override")


def _validate_scene(
    scene: VectorScene, nodes: dict[str, Any], resources: dict[str, Resource], limits: DocumentLimits, path: str
) -> None:
    from opendoc_model.integration import _acyclic, _error, _index, _reference, _visual_reference

    _reference(scene.node_id, nodes, path + ".node_id")
    if scene.width <= 0 or scene.height <= 0:
        _error(path, "scene dimensions must be positive points")
    # One local namespace, with clip geometry separate from paintable children.
    _index((*scene.paths, *scene.groups, *scene.occurrences, *scene.clips), path + ".ids")
    shapes = _index((*scene.paths, *scene.groups, *scene.occurrences), path + ".shapes")
    clips = _index(scene.clips, path + ".clips")
    common = scene.scope_version == 1
    if not common and (scene.occurrences or scene.clips or any(group.compositing is not None for group in scene.groups)):
        _error(path + ".scope_version", "mixed scopes require explicit scope_version=1")
    for index, key in enumerate(scene.roots):
        _reference(key, shapes, f"{path}.roots[{index}]")
    for index, clip in enumerate(scene.clips):
        _commands(clip.commands, f"{path}.clips[{index}].commands")
    for index, value in enumerate(scene.paths):
        location = f"{path}.paths[{index}]"
        _commands(value.commands, location + ".commands")
        if value.stroke_width < 0:
            _error(location + ".stroke_width", "expected nonnegative points")
        for name in ("fill", "stroke"):
            paint = getattr(value, name)
            if paint is not None and not 0 <= paint.opacity <= 1:
                _error(location + "." + name + ".opacity", "invalid opacity")
    edges: dict[str, tuple[str, ...]] = {}
    counts = {key: 0 for key in shapes}
    for key in scene.roots:
        counts[key] += 1
    for index, group in enumerate(scene.groups):
        location = f"{path}.groups[{index}]"
        if not 0 <= group.opacity <= 1 or len(set(group.children)) != len(group.children):
            _error(location, "invalid legacy opacity or duplicate children")
        _compositing(group.compositing, location + ".compositing", resources)
        for child_index, key in enumerate(group.children):
            _reference(key, shapes, f"{location}.children[{child_index}]")
            counts[key] += 1
    for index, occurrence in enumerate(scene.occurrences):
        _reference(occurrence.node_id, nodes, f"{path}.occurrences[{index}].node_id")
        _compositing(occurrence.compositing, f"{path}.occurrences[{index}].compositing", resources)
    for name in ("paths", "groups", "occurrences"):
        for index, item in enumerate(getattr(scene, name)):
            location = f"{path}.{name}[{index}]"
            _reference(item.clip_id, clips if common else shapes, location + ".clip_id")
            _visual_reference(item.mask_resource_id, resources, location + ".mask_resource_id")
            edges[item.id] = (*getattr(item, "children", ()), *((item.clip_id,) if item.clip_id else ()))
    edges.update({key: () for key in clips})
    _acyclic(edges, path, limits)
    if common:
        if any(count > 1 for count in counts.values()):
            _error(path, "mixed paint occurrences/scopes must have one parent or root use")
        reachable: set[str] = set()
        pending = list(scene.roots)
        while pending:
            key = pending.pop()
            if key not in reachable:
                reachable.add(key)
                pending.extend(getattr(shapes[key], "children", ()))
        if any(item.id not in reachable for item in scene.occurrences):
            _error(path + ".occurrences", "paint occurrence is unreachable from explicit roots")


def _scene_unknowns(scene: VectorScene, path: str) -> Iterator[tuple[str, str]]:
    if scene.scope_version != 1:
        return
    for index, clip in enumerate(scene.clips):
        if clip.fill_rule is None:
            yield f"{path}.clips[{index}].fill_rule", "Clip winding is unknown; rendering is not established"
    for name in ("groups", "occurrences"):
        for index, item in enumerate(getattr(scene, name)):
            value = item.compositing
            unknown = [
                key for key in ("opacity", "isolated", "knockout", "blend_mode") if value is None or getattr(value, key) is None
            ]
            if unknown:
                yield f"{path}.{name}[{index}].compositing", "Unknown scope composition: " + ", ".join(unknown)


def _color_space_unknowns(scene: VectorScene, path: str) -> Iterator[tuple[str, str]]:
    if scene.scope_version != 1:
        return
    for name in ("groups", "occurrences"):
        for index, item in enumerate(getattr(scene, name)):
            color = item.compositing.color_space if item.compositing is not None else None
            if color is None or color.space is None:
                yield (
                    f"{path}.{name}[{index}].compositing.color_space",
                    "Group blending space is unknown; no colorimetry inferred",
                )


def get_vector_scene(document: DocumentModel, scene_id: str, *, limits: DocumentLimits | None = None) -> VectorScene | None:
    """Read an independent scene; no fallback to opaque/native properties."""
    from opendoc_model.integration import _nonempty, get_integration

    _nonempty(scene_id, "scene_id")
    model = get_integration(document, limits=limits)
    return next((scene for scene in model.scenes if scene.id == scene_id), None) if model is not None else None


_Record = TypeVar("_Record", VectorScene, VectorClip, VectorGroup)


def _extensions(previous: _Record | None, value: _Record) -> _Record:
    if type(value.extra) is not dict:
        raise ValueError("scene record extra must be a dictionary")
    return replace(value, extra={**(previous.extra if previous else {}), **value.extra})


def set_vector_scene(document: DocumentModel, scene: VectorScene, *, limits: DocumentLimits | None = None) -> None:
    """Atomically add/replace one scene, retaining its unknown envelope fields."""
    from opendoc_model.integration import get_integration, set_integration
    from opendoc_model.integration_types import IntegrationModel

    budget = _resolve_limits(limits)
    if type(scene) is not VectorScene:
        raise ValueError("expected VectorScene")
    _guard_model(scene, budget)
    if type(scene.groups) is not tuple or any(type(group) is not VectorGroup for group in scene.groups):
        raise ValueError("scene.groups must be a tuple of VectorGroup")
    model = get_integration(document, limits=budget) or IntegrationModel()
    previous = next((item for item in model.scenes if item.id == scene.id), None)
    if scene.scope_version is None and (
        scene.clips
        or scene.occurrences
        or any(group.compositing is not None for group in scene.groups)
        or previous is not None
        and previous.scope_version == 1
    ):
        scene = replace(scene, scope_version=1)
    scene = _extensions(previous, scene)
    scenes = tuple(scene if item.id == scene.id else item for item in model.scenes)
    set_integration(document, replace(model, scenes=scenes if previous else (*scenes, scene)), limits=budget)


def remove_vector_scene(document: DocumentModel, scene_id: str, *, limits: DocumentLimits | None = None) -> None:
    """Remove a scene atomically; references from other integration records must remain valid."""
    from opendoc_model.integration import get_integration, set_integration

    if get_vector_scene(document, scene_id, limits=limits) is None:
        return
    model = get_integration(document, limits=limits)
    assert model is not None
    set_integration(document, replace(model, scenes=tuple(item for item in model.scenes if item.id != scene_id)), limits=limits)


def _scene(document: DocumentModel, scene_id: str, limits: DocumentLimits | None) -> VectorScene:
    scene = get_vector_scene(document, scene_id, limits=limits)
    if scene is None:
        raise ValueError("unknown scene_id")
    return scene


def set_scene_clip(
    document: DocumentModel, scene_id: str, clip_id: str, clip: VectorClip | None, *, limits: DocumentLimits | None = None
) -> None:
    """Replace geometry, or remove a typed clip and detach its local uses; keep content intact."""
    from opendoc_model.integration import _nonempty

    _nonempty(clip_id, "clip_id")
    scene = _scene(document, scene_id, limits)
    previous = next((item for item in scene.clips if item.id == clip_id), None)
    if clip is not None and (type(clip) is not VectorClip or clip.id != clip_id):
        raise ValueError("expected VectorClip at requested ID")
    if previous is None and clip is None:
        return
    if clip is not None:
        _guard_model(clip, _resolve_limits(limits))
        clip = _extensions(previous, clip)
        clips = tuple(clip if item.id == clip_id else item for item in scene.clips)
        changed = replace(scene, clips=clips if previous else (*clips, clip))
    else:
        changed = replace(
            scene,
            clips=tuple(item for item in scene.clips if item.id != clip_id),
            paths=tuple(replace(item, clip_id=None) if item.clip_id == clip_id else item for item in scene.paths),
            groups=tuple(replace(item, clip_id=None) if item.clip_id == clip_id else item for item in scene.groups),
            occurrences=tuple(replace(item, clip_id=None) if item.clip_id == clip_id else item for item in scene.occurrences),
        )
    set_vector_scene(document, changed, limits=limits)


def set_scene_group(
    document: DocumentModel, scene_id: str, group_id: str, group: VectorGroup | None, *, limits: DocumentLimits | None = None
) -> None:
    """Replace a scope; removal unwraps its children in place without distributing effects."""
    from opendoc_model.integration import _nonempty

    _nonempty(group_id, "group_id")
    scene = _scene(document, scene_id, limits)
    previous = next((item for item in scene.groups if item.id == group_id), None)
    if group is not None and (type(group) is not VectorGroup or group.id != group_id):
        raise ValueError("expected VectorGroup at requested ID")
    if previous is None and group is None:
        return
    if group is not None:
        _guard_model(group, _resolve_limits(limits))
        group = _extensions(previous, group)
        groups = tuple(group if item.id == group_id else item for item in scene.groups)
        changed = replace(scene, groups=groups if previous else (*groups, group))
    else:
        assert previous is not None

        def unwrap(items: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(child for key in items for child in (previous.children if key == group_id else (key,)))

        changed = replace(
            scene,
            roots=unwrap(scene.roots),
            groups=tuple(replace(item, children=unwrap(item.children)) for item in scene.groups if item.id != group_id),
        )
    set_vector_scene(document, changed, limits=limits)


def get_scope_color_space(
    document: DocumentModel, scene_id: str, scope_id: str, *, limits: DocumentLimits | None = None
) -> GroupColorSpace | None:
    """Read a detached group/occurrence color-space declaration; no legacy/default lookup."""
    from opendoc_model.integration import _nonempty

    _nonempty(scope_id, "scope_id")
    scene = _scene(document, scene_id, limits)
    items: tuple[VectorGroup | SceneOccurrence, ...] = (*scene.groups, *scene.occurrences)
    for item in items:
        if item.id == scope_id:
            return item.compositing.color_space if item.compositing is not None else None
    raise ValueError("unknown group/occurrence scope_id")


def set_scope_color_space(
    document: DocumentModel, scene_id: str, scope_id: str, value: GroupColorSpace | None, *, limits: DocumentLimits | None = None
) -> None:
    """Atomically replace/remove a common scope's color space, preserving other parameters.

    Removal means unknown, not parent/sRGB/native fallback. Profile bytes remain
    opaque and unused resources are retained. Old vector scopes require explicit
    migration to scope_version=1 before edits through this API.
    """
    budget = _resolve_limits(limits)
    if value is not None:
        if type(value) is not GroupColorSpace or type(value.extra) is not dict:
            raise ValueError("expected GroupColorSpace with dictionary extra or None")
        _guard_model(value, budget)
    previous = get_scope_color_space(document, scene_id, scope_id, limits=budget)
    scene = _scene(document, scene_id, budget)
    if scene.scope_version != 1:
        raise ValueError("color-space editing requires common scope_version=1")
    if value is not None:
        value = replace(value, extra={**(previous.extra if previous else {}), **value.extra})
    items: tuple[VectorGroup | SceneOccurrence, ...] = (*scene.groups, *scene.occurrences)
    item = next(item for item in items if item.id == scope_id)
    compositing = replace(item.compositing or GroupCompositing(), color_space=value)
    changed = replace(
        scene,
        groups=tuple(replace(group, compositing=compositing) if group.id == scope_id else group for group in scene.groups),
        occurrences=tuple(
            replace(occurrence, compositing=compositing) if occurrence.id == scope_id else occurrence
            for occurrence in scene.occurrences
        ),
    )
    set_vector_scene(document, changed, limits=budget)


__all__ = [
    "get_vector_scene",
    "set_vector_scene",
    "remove_vector_scene",
    "set_scene_clip",
    "set_scene_group",
    "get_scope_color_space",
    "set_scope_color_space",
]
