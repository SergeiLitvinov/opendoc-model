"""Atomic JSON model persistence, independent of application filesystem helpers."""

import codecs
import os
import uuid
from collections.abc import Iterable
from pathlib import Path


class ArtifactLimitError(ValueError):
    """Budget exhaustion with optional path, quota name and configured maximum.

    Positional args and their string representation retain ValueError semantics.
    Legacy caller-created errors have unknown fields; no message parsing occurs.
    """

    def __init__(self, *args: object, path: str | None = None, quota: str | None = None, maximum: int | None = None) -> None:
        super().__init__(*args)
        self.path = path
        self.quota = quota
        self.maximum = maximum


def atomic_write_text(path: str | Path, content: str, encoding: str = "utf-8", *, max_bytes: int = 100 * 1024 * 1024) -> Path:
    if len(content.encode(encoding)) > max_bytes:
        raise ArtifactLimitError(f"artifact quota exceeded ({max_bytes} bytes)", path=str(path), quota="bytes", maximum=max_bytes)
    return _atomic_write_chunks(path, [content], encoding=encoding, max_bytes=max_bytes)


def _atomic_write_chunks(path: str | Path, chunks: Iterable[str], *, encoding: str, max_bytes: int) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    try:
        encoder = codecs.getincrementalencoder(encoding)()
        size = 0
        with partial.open("wb") as stream:
            for chunk in chunks:
                data = encoder.encode(chunk)
                size += len(data)
                if size > max_bytes:
                    raise ArtifactLimitError(
                        f"artifact quota exceeded ({max_bytes} bytes)", path=str(target), quota="bytes", maximum=max_bytes
                    )
                stream.write(data)
            final = encoder.encode("", final=True)
            if size + len(final) > max_bytes:
                raise ArtifactLimitError(
                    f"artifact quota exceeded ({max_bytes} bytes)", path=str(target), quota="bytes", maximum=max_bytes
                )
            stream.write(final)
        os.replace(partial, target)
    finally:
        partial.unlink(missing_ok=True)
    return target
