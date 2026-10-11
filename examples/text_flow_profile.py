"""Own measured declarations: no native extractor, PDF engine or full object inventory."""

import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

from opendoc_model import (
    ConversionReport,
    DocumentInspection,
    ObjectLossPolicy,
    TextFlowProfile,
    TextPreservationPolicy,
    compare_inspections,
    text_flow_profile_from_dict,
    text_flow_profile_to_dict,
)
from opendoc_model.text_flow import TextFlowFingerprint

profile = TextFlowProfile("own-text-extraction-v1", "own-selected-text-v1", measured=True, complete=True)
for _ in range(2):
    profile = text_flow_profile_from_dict(json.loads(json.dumps(text_flow_profile_to_dict(profile))))


def inspection(text, declared_profile=profile):
    flow = TextFlowFingerprint()
    flow.add(text)
    return DocumentInspection(
        None,
        "fixture",
        metadata={
            "text_flow": flow.to_dict(),
            "text_flow_profile": text_flow_profile_to_dict(declared_profile),
        },
    )


comparison = compare_inspections(inspection("one\t two"), inspection("one two"))
report = ConversionReport(Path("unused.fixture"))
assert TextPreservationPolicy("flow", 0).evaluate(report, comparison)
assert report.metrics["text_quality_gate"]["coverage"] == "declared-text-scope"
assert not ObjectLossPolicy().evaluate(ConversionReport(Path("unused.fixture")), comparison)
assert "object_inventory_scope" not in comparison.source.metadata
changed = compare_inspections(inspection("one two"), inspection("one new"))
assert not TextPreservationPolicy("flow", 0).evaluate(ConversionReport(Path("unused.fixture")), changed)
unknown = compare_inspections(inspection("one two"), inspection("one two", replace(profile, complete=False, reason="partial")))
unknown_report = ConversionReport(Path("unused.fixture"))
assert not TextPreservationPolicy("flow", 0).evaluate(unknown_report, unknown)
assert unknown_report.metrics["text_quality_gate"]["verified"] is False
contradictory = deepcopy(comparison.target)
contradictory.metadata["text_flow"]["sha256"] = "0" * 64
contradictory_report = ConversionReport(Path("unused.fixture"))
assert not TextPreservationPolicy("flow", 0).evaluate(contradictory_report, compare_inspections(comparison.source, contradictory))
assert contradictory_report.metrics["text_quality_gate"]["verified"] is False
print("Measured text profile: exact declared scope, unknown coverage and independent object gate OK")
