"""Standalone ledger transport uses the same integration envelope without an owner."""

import json

from opendoc_model import (
    DiagnosticIssue,
    IntegrationModel,
    IssueSeverity,
    PreservationRecord,
    PreservationState,
    Provenance,
    integration_from_dict,
    integration_to_dict,
)

original = IntegrationModel(
    preservation=(
        PreservationRecord(
            DiagnosticIssue(
                "own.feature",
                IssueSeverity.WARNING,
                "Original retained",
                "items[0]",
                reason="No semantic projection",
                measurement={"own": [1]},
            ),
            PreservationState.OPAQUE,
            provenance=Provenance("own", object_id="item"),
            extra={"future_record": {"values": [1]}},
        ),
    ),
    assessed_features=("own.feature",),
    extra={"future_model": [1]},
)
payload = integration_to_dict(original)
assert payload["format"] == "opendoc.integration" and payload["version"] == 1
decoded = integration_from_dict(payload)
payload["data"]["future_model"].append(2)
assert decoded == original
for _ in range(2):
    decoded = integration_from_dict(json.loads(json.dumps(integration_to_dict(decoded), ensure_ascii=False)))
assert decoded == original
assert decoded.preservation[0].state is PreservationState.OPAQUE
print("Standalone integration codec: independent data and two JSON cycles verified")
