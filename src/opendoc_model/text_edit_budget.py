"""Bounded word edit distance; never misreport a lower bound as an exact count."""

from typing import Any

from opendoc_model.diagnostics import CheckResult, ConversionReport, IssueSeverity

MAX_DISTANCE_CELLS = 2_000_000


def bounded_word_distance(source: list[str], target: list[str], limit: int) -> tuple[int | None, bool]:
    """Return exact distance within budget, or (None, True) when proven above it.

    (None, False) means the work limit prevents a decision. Insertions,
    deletions and substitutions cost one; swaps have no special discount.
    """
    if type(limit) is not int or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    start = 0
    while start < min(len(source), len(target)) and source[start] == target[start]:
        start += 1
    end_source, end_target = len(source), len(target)
    while end_source > start and end_target > start and source[end_source - 1] == target[end_target - 1]:
        end_source -= 1
        end_target -= 1
    left, right = source[start:end_source], target[start:end_target]
    if abs(len(left) - len(right)) > limit:
        return None, True
    if not left or not right:
        distance = max(len(left), len(right))
        return (distance, True) if distance <= limit else (None, True)
    if len(left) * min(len(right) + 1, 2 * limit + 1) > MAX_DISTANCE_CELLS:
        return None, False
    infinity = limit + 1
    previous = {column: column for column in range(min(len(right), limit) + 1)}
    for row, token in enumerate(left, 1):
        current = {0: row} if row <= limit else {}
        for column in range(max(1, row - limit), min(len(right), row + limit) + 1):
            current[column] = min(
                previous.get(column, infinity) + 1,
                current.get(column - 1, infinity) + 1,
                previous.get(column - 1, infinity) + (token != right[column - 1]),
            )
        if min(current.values(), default=infinity) > limit:
            return None, True
        previous = current
    distance = previous.get(len(right), infinity)
    return (distance, True) if distance <= limit else (None, True)


def evaluate_text_edit_budget(
    report: ConversionReport | CheckResult, source: dict[str, Any], target: dict[str, Any], available: bool, limit: int
) -> bool:
    exact, verified = None, False
    if available and source["sha256"] == target["sha256"]:
        exact, verified = 0, True
    elif available and all(
        flow.get("tokenization") == "whitespace-words-v1"
        and isinstance(flow.get("tokens"), list)
        and all(isinstance(token, str) for token in flow["tokens"])
        and type(flow.get("token_count")) is int
        and len(flow["tokens"]) == flow.get("token_count")
        for flow in (source, target)
    ):
        exact, verified = bounded_word_distance(source["tokens"], target["tokens"], limit)
    accepted = verified and exact is not None
    report.metrics["text_quality_gate"] = {
        "mode": "flow",
        "basis": "word_levenshtein_v1",
        "verified": verified,
        "accepted": accepted,
        "max_text_edits": limit,
        "text_edits": exact,
        "text_edits_lower_bound": limit + 1 if verified and exact is None else exact,
        "reason": "accepted" if accepted else "budget-exceeded" if verified else "unavailable",
    }
    if not accepted:
        message = (
            f"Число правок слов превышает допустимое: не менее {limit + 1} при лимите {limit}."
            if verified
            else ("Бюджет правок текста не удалось проверить: недостаточно данных или превышен лимит вычислений.")
        )
        report.add(IssueSeverity.ERROR, "text-quality", message)
    elif exact:
        report.add(IssueSeverity.WARNING, "text-edits", f"Результат принят с изменениями текста: {exact} правок слов.")
    return accepted
