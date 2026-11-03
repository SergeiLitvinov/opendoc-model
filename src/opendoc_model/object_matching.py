"""One-to-one matching of inspected objects without collapsing duplicates."""

from collections import defaultdict
from collections.abc import Callable, Hashable
from dataclasses import dataclass
from typing import Any, TypedDict

from opendoc_model.storage import ArtifactLimitError

Object = dict[str, Any]


class ObjectMatch(TypedDict):
    source: Object
    target: Object
    match_basis: str
    ambiguous: bool
    source_index: int
    target_index: int


@dataclass(frozen=True)
class MatchingLimits:
    """Deterministic record/candidate work units, shared by comparison domains."""

    max_work: int = 1_000_000

    def __post_init__(self) -> None:
        if type(self.max_work) is not int or self.max_work < 0:
            raise ValueError("max_work must be a non-negative integer")


class _MatchingLimitError(ArtifactLimitError):
    def __init__(self, maximum: int, used: int, requested: int) -> None:
        super().__init__(
            f"matching work quota exceeded ({maximum}); used {used}, next charge {requested}", quota="work", maximum=maximum
        )
        self.measurement = {"max_work": maximum, "used_work": used, "requested_work": requested}


class _MatchingBudget:
    def __init__(self, limits: MatchingLimits | None = None) -> None:
        if limits is not None and not isinstance(limits, MatchingLimits):
            raise ValueError("matching limits must be MatchingLimits or None")
        self.maximum = limits.max_work if limits is not None else MatchingLimits().max_work
        self.used = 0

    def charge(self, count: int = 1) -> None:
        if count > self.maximum - self.used:
            raise _MatchingLimitError(self.maximum, self.used, count)
        self.used += count


class _CandidatePool:
    """Stable indices with lazy deletion, including an index for equal locations."""

    def __init__(self, indices: list[int], objects: list[Object]) -> None:
        self.indices = indices
        self.position = 0
        self.locations: dict[Hashable, list[int]] = defaultdict(list)
        self.offsets: dict[Hashable, int] = {}
        for index in indices:
            self.locations[objects[index].get("location")].append(index)

    def first(self, location: Hashable, remaining: set[int], budget: _MatchingBudget) -> int | None:
        budget.charge()
        selected = self.locations.get(location)
        if selected is not None:
            offset = self.offsets.get(location, 0)
            while offset < len(selected) and selected[offset] not in remaining:
                budget.charge()
                offset += 1
            if offset:
                self.offsets[location] = offset
            if offset < len(selected):
                return selected[offset]
        while self.position < len(self.indices) and self.indices[self.position] not in remaining:
            budget.charge()
            self.position += 1
        return self.indices[self.position] if self.position < len(self.indices) else None


def match_objects(
    source: list[Object], target: list[Object], *, limits: MatchingLimits | None = None
) -> tuple[list[ObjectMatch], list[Object], list[Object]]:
    """Prefer provenance, then content, and use location only as a heuristic.

    Equal content cannot override conflicting explicit origins. Duplicate
    fingerprints remain separate occurrences; their pairing is marked ambiguous.
    Exhaustion raises ArtifactLimitError without returning partial matches.
    """
    return _match_objects(source, target, _MatchingBudget(limits))


def _match_objects(
    source: list[Object], target: list[Object], budget: _MatchingBudget
) -> tuple[list[ObjectMatch], list[Object], list[Object]]:
    budget.charge(len(source) + len(target))
    remaining_source, remaining_target = set(range(len(source))), set(range(len(target)))
    matches: list[ObjectMatch] = []

    def origin(item: Object) -> str | None:
        return (item.get("provenance") or {}).get("identity") or None

    def compatible(before: Object, after: Object) -> bool:
        before_origin, after_origin = before.get("provenance") or {}, after.get("provenance") or {}
        if before_origin.get("source_format") and after_origin.get("source_format"):
            before_scope = (before_origin["source_format"], before_origin.get("source_path"))
            after_scope = (after_origin["source_format"], after_origin.get("source_path"))
            if before_scope != after_scope:
                return True  # Re-imported files have independent origin identifiers.
        return not (origin(before) and origin(after) and origin(before) != origin(after))

    def scope(item: Object) -> tuple[Hashable, Hashable] | None:
        provenance = item.get("provenance") or {}
        if provenance.get("source_format"):
            return provenance["source_format"], provenance.get("source_path")
        return None

    def pair(left: int, right: int, basis: str, ambiguous: bool) -> None:
        budget.charge()
        matches.append(
            {
                "source": source[left],
                "target": target[right],
                "match_basis": basis,
                "ambiguous": ambiguous,
                "source_index": left,
                "target_index": right,
            }
        )
        remaining_source.remove(left)
        remaining_target.remove(right)

    def match_groups(key: Callable[[Object], Hashable], basis: str, *, unique: bool = False) -> None:
        budget.charge(len(remaining_source) + len(remaining_target))
        left_groups, right_groups = defaultdict(list), defaultdict(list)
        for index in sorted(remaining_source):
            if (value := key(source[index])) is not None:
                left_groups[value].append(index)
        for index in sorted(remaining_target):
            if (value := key(target[index])) is not None:
                right_groups[value].append(index)
        for value, left in left_groups.items():
            right = right_groups.get(value, [])
            budget.charge(len(left) + len(right))
            ambiguous = len(left) > 1 or len(right) > 1
            if unique and ambiguous:
                continue
            # Within one import scope, only equal or absent identities can match.
            # Provenance groups already share an identity across import scopes.
            indexed = (
                basis.startswith("provenance")
                or len({scope(source[index]) for index in left} | {scope(target[index]) for index in right}) <= 1
            )
            if indexed:
                budget.charge(3 * len(right))
                all_candidates = _CandidatePool(right, target)
                origins: dict[Hashable, list[int]] = defaultdict(list)
                for index in right:
                    origins[origin(target[index])].append(index)
                pools = {identity: _CandidatePool(indices, target) for identity, indices in origins.items()}
                for index in left:
                    budget.charge()
                    identity = origin(source[index])
                    available = (
                        [all_candidates]
                        if identity is None or basis.startswith("provenance")
                        else [pools[item] for item in (None, identity) if item in pools]
                    )
                    candidates = [
                        candidate
                        for pool in available
                        if (candidate := pool.first(source[index].get("location"), remaining_target, budget)) is not None
                    ]
                    if candidates:
                        other = min(
                            candidates,
                            key=lambda candidate: (source[index].get("location") != target[candidate].get("location"), candidate),
                        )
                        pair(index, other, basis, ambiguous)
                continue
            active_right = dict.fromkeys(right)
            for index in left:
                budget.charge()
                candidates = []
                for other in active_right:
                    budget.charge()
                    if compatible(source[index], target[other]):
                        candidates.append(other)
                if not candidates:
                    continue
                # Stable locations disambiguate equal fingerprints where possible.
                other = candidates[0]
                for candidate in candidates:
                    budget.charge()
                    if source[index].get("location") == target[candidate].get("location"):
                        other = candidate
                        break
                pair(index, other, basis, ambiguous)
                del active_right[other]

    match_groups(lambda item: (item.get("type"), origin(item)) if origin(item) else None, "provenance", unique=True)
    match_groups(
        lambda item: (
            (item.get("type"), origin(item), item["content_hash"]) if origin(item) and item.get("content_hash") else None
        ),
        "provenance-content",
    )
    match_groups(lambda item: (item.get("type"), item["content_hash"]) if item.get("content_hash") else None, "content")
    match_groups(lambda item: (item.get("type"), origin(item)) if origin(item) else None, "provenance", unique=True)
    match_groups(lambda item: (item.get("type"), item["location"]) if item.get("location") else None, "location")
    budget.charge(len(matches) + len(remaining_source) + len(remaining_target))
    matches.sort(key=lambda item: item["source_index"])
    return matches, [source[index] for index in sorted(remaining_source)], [target[index] for index in sorted(remaining_target)]
