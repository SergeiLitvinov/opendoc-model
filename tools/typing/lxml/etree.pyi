"""Local typing contract for the XML API used by OpenDoc Model, under MIT."""

from collections.abc import Iterator, Mapping
from typing import Literal

class XMLSyntaxError(SyntaxError): ...

class Resolver:
    def resolve(self, url: str | None, public_id: str | None, context: object) -> object: ...

class _Resolvers:
    def add(self, resolver: Resolver) -> None: ...

class XMLParser:
    resolvers: _Resolvers
    def __init__(
        self,
        *,
        resolve_entities: bool = ...,
        load_dtd: bool = ...,
        dtd_validation: bool = ...,
        attribute_defaults: bool = ...,
        no_network: bool = ...,
        recover: bool = ...,
        huge_tree: bool = ...,
        remove_comments: bool = ...,
        remove_pis: bool = ...,
    ) -> None: ...

class _DocInfo:
    doctype: str
    encoding: str

class _ElementTree:
    docinfo: _DocInfo

class _Element:
    def __iter__(self) -> Iterator[_Element]: ...
    def getroottree(self) -> _ElementTree: ...
    def set(self, key: str, value: str) -> None: ...

class QName:
    namespace: str | None
    localname: str
    def __init__(self, value: _Element | str) -> None: ...

def Element(tag: str, *, nsmap: Mapping[str | None, str] | None = None) -> _Element: ...  # noqa: N802 - external API name
def fromstring(text: bytes | str, parser: XMLParser) -> _Element: ...
def tostring(element: _Element, *, encoding: Literal["unicode"]) -> str: ...
