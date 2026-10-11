"""Structured quota errors without parsing their backward-compatible text."""

from opendoc_model import ArtifactLimitError, DocumentLimits, document_from_json


def main():
    try:
        document_from_json("{}", limits=DocumentLimits(max_bytes=1))
    except ArtifactLimitError as error:
        assert (error.path, error.quota, error.maximum) == ("$", "bytes", 1)
        assert str(error) == "$: bytes quota exceeded (1)"
    else:
        raise AssertionError("Expected explicit input quota failure")
    legacy = ArtifactLimitError("legacy message")
    assert legacy.args == ("legacy message",)
    assert (legacy.path, legacy.quota, legacy.maximum) == (None, None, None)
    print("Structured limits: known fields and legacy errors verified")


if __name__ == "__main__":
    main()
