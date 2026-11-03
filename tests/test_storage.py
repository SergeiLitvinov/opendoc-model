"""Quota rejection and failed publication preserve an existing document."""

import pytest

from opendoc_model import ArtifactLimitError, storage


def test_quota_rejection_keeps_previous_file(tmp_path):
    target = tmp_path / "document.json"
    target.write_text("previous", encoding="utf-8")
    with pytest.raises(ArtifactLimitError):
        storage.atomic_write_text(target, "too large", max_bytes=3)
    assert target.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.iterdir()) == [target]


def test_publication_failure_cleans_partial_and_preserves_previous(tmp_path, monkeypatch):
    target = tmp_path / "document.json"
    target.write_text("previous", encoding="utf-8")

    def fail(*args):
        raise OSError("locked file")

    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError, match="locked file"):
        storage.atomic_write_text(target, "replacement")
    assert target.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.iterdir()) == [target]
