"""Reproducible library costs; timing and traced allocation peaks are separate runs."""

from __future__ import annotations

import argparse
import gc
import importlib
import json
import platform
import statistics
import sys
import time
import tracemalloc
from pathlib import Path


def _cases(size):
    core = importlib.import_module("opendoc_model")
    matching = importlib.import_module("opendoc_model.object_matching")
    paragraphs = [core.Paragraph([core.TextRun(f"Paragraph {index}: UTF-8 привет")]) for index in range(size)]
    flat = core.DocumentModel(sections=[core.Section(blocks=paragraphs)])
    nested = core.Table(rows=[core.TableRow(cells=[core.TableCell(blocks=paragraphs)])])
    for _ in range(7):
        nested = core.Table(rows=[core.TableRow(cells=[core.TableCell(blocks=[nested])])])
    nested_document = core.DocumentModel(sections=[core.Section(blocks=[nested])])
    binary = core.DocumentModel(
        resources={
            "blob": core.Resource("blob", core.ResourceKind.ATTACHMENT, "application/octet-stream", data=b"x" * (size * 1024))
        }
    )
    encoded = core.document_to_json(binary)
    duplicates = [{"type": "paragraph", "content_hash": "same", "location": str(index)} for index in range(size)]
    reversed_duplicates = list(reversed(duplicates))
    conflicts = [
        {**item, "provenance": {"identity": f"id-{index}", "source_format": "custom", "source_path": "one"}}
        for index, item in enumerate(duplicates)
    ]
    other_origins = [
        {**item, "provenance": {"identity": f"other-{index}", "source_format": "custom", "source_path": "one"}}
        for index, item in enumerate(duplicates)
    ]
    mixed_origins = [
        {**item, "provenance": {**item["provenance"], "source_format": "custom" if index % 2 else "other"}}
        for index, item in enumerate(other_origins)
    ]

    def mixed_matching():
        try:
            matches, lost, added = matching.match_objects(conflicts, mixed_origins)
        except core.ArtifactLimitError as error:
            return {"available": False, "reason": "matching-budget-exceeded", "detail": str(error)}
        return {
            "available": True,
            "matches": len(matches),
            "lost": len(lost),
            "added": len(added),
            "ambiguous_matches": sum(item["ambiguous"] for item in matches),
        }

    yield "walk-flat", lambda: sum(1 for _ in core.walk_model(flat)), {"paragraphs": size}
    yield "json-base64-write", lambda: core.document_to_json(binary), {"embedded_bytes": size * 1024}
    yield "json-base64-read", lambda: core.document_from_json(encoded), {"json_utf8_bytes": len(encoded.encode("utf-8"))}
    yield "inspect-nested-tables", lambda: core.inspect_document_model(nested_document), {"paragraphs": size, "table_depth": 8}
    yield "match-duplicates", lambda: matching.match_objects(duplicates, reversed_duplicates), {"source": size, "target": size}
    yield "match-origin-conflicts", lambda: matching.match_objects(conflicts, other_origins), {"source": size, "target": size}
    yield "match-mixed-sources", mixed_matching, {"source": size, "target": size}


def measure(sizes, repeats):
    rows = []
    for size in sizes:
        for name, operation, inputs in _cases(size):
            operation()  # Warm imports/caches outside measurement.
            samples = []
            for _ in range(repeats):
                gc.collect()
                start = time.perf_counter()
                result = operation()
                samples.append(time.perf_counter() - start)
                del result
            gc.collect()
            tracemalloc.start()
            result = operation()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            result_metadata = result if isinstance(result, dict) and "available" in result else None
            del result
            row = {
                "case": name,
                "inputs": inputs,
                "median_seconds": statistics.median(samples),
                "samples_seconds": samples,
                "peak_traced_bytes": peak,
            }
            if result_metadata is not None:
                row["result"] = result_metadata
            rows.append(row)
            print(f"{name} {size}: {row['median_seconds']:.6f} s, {peak} traced bytes", flush=True)
    core = importlib.import_module("opendoc_model")
    return {
        "format": "opendoc.performance",
        "version": 1,
        "environment": {"python": sys.version, "platform": platform.platform(), "library": core.__version__},
        "method": {
            "repeats": repeats,
            "warmup": 1,
            "timing_includes_gc": False,
            "peak_run_separate": True,
            "matching_max_work": core.MatchingLimits().max_work if hasattr(core, "MatchingLimits") else None,
        },
        "results": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", type=int, nargs="+", default=[128, 512, 2048])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path(".opendoc/performance.json"))
    parser.add_argument("--source-root", type=Path, help="Optional src directory of a previous checkout for comparison")
    arguments = parser.parse_args()
    if arguments.repeats < 1 or any(size < 1 for size in arguments.sizes):
        parser.error("sizes and repeats must be positive")
    if arguments.source_root is not None:
        sys.path.insert(0, str(arguments.source_root.resolve()))
    report = measure(arguments.sizes, arguments.repeats)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
