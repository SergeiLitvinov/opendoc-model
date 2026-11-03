"""Streaming fingerprint of paragraph text in document traversal order."""

import hashlib
from typing import TypedDict


class TextFlowData(TypedDict):
    version: str
    sha256: str
    characters: int
    paragraphs: int
    tokenization: str
    token_count: int
    tokens: list[str] | None


TEXT_FLOW_VERSION = "paragraph-text-flow-v1"
MAX_TEXT_TOKENS = 10_000


class TextFlowFingerprint:
    """Collapse whitespace and paragraph boundaries, but preserve all other text."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self.characters = 0
        self.paragraphs = 0
        self.token_count = 0
        self._tokens: list[str] = []

    def add(self, text: str) -> None:
        normalized = " ".join(text.split())
        if not normalized:
            return
        if self.paragraphs:
            self._digest.update(b" ")
            self.characters += 1
        self._digest.update(normalized.encode("utf-8"))
        self.characters += len(normalized)
        self.paragraphs += 1
        self.token_count += normalized.count(" ") + 1
        if self.token_count <= MAX_TEXT_TOKENS:
            self._tokens.extend(hashlib.sha256(word.encode("utf-8")).hexdigest() for word in normalized.split(" "))
        else:
            self._tokens.clear()

    def to_dict(self) -> TextFlowData:
        return {
            "version": TEXT_FLOW_VERSION,
            "sha256": self._digest.hexdigest(),
            "characters": self.characters,
            "paragraphs": self.paragraphs,
            "tokenization": "whitespace-words-v1",
            "token_count": self.token_count,
            "tokens": list(self._tokens) if self.token_count <= MAX_TEXT_TOKENS else None,
        }
