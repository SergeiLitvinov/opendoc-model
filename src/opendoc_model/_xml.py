"""Bounded optional XML parsing without external resource resolution."""

from __future__ import annotations

from typing import Any, NoReturn

_MAX_XML_BYTES = 1024 * 1024
_MAX_XML_NODES = 4096
_MAX_XML_DEPTH = 64


def _xml_bytes(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("XML input must be a string")
    if len(value) > _MAX_XML_BYTES:
        raise ValueError("XML exceeds 1 MiB")
    try:
        data = value.encode("utf-8")
    except UnicodeError as error:
        raise ValueError("XML input must contain valid Unicode") from error
    if len(data) > _MAX_XML_BYTES:
        raise ValueError("XML exceeds 1 MiB")
    return data


def _parse_xml(value: str) -> Any:
    data = _xml_bytes(value)
    from lxml import etree

    class _NoExternalResources(etree.Resolver):
        def resolve(self, url: str | None, public_id: str | None, context: object) -> NoReturn:
            raise ValueError("External XML resources are not allowed")

    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        dtd_validation=False,
        attribute_defaults=False,
        no_network=True,
        recover=False,
        huge_tree=False,
        remove_comments=True,
        remove_pis=True,
    )
    parser.resolvers.add(_NoExternalResources())
    try:
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as error:
        raise ValueError("Invalid formula XML") from error
    information = root.getroottree().docinfo
    if information.doctype:
        raise ValueError("DTD in formula XML is not supported")
    if information.encoding.upper().replace("-", "") not in {"UTF8", "ASCII", "USASCII"}:
        raise ValueError("Formula XML string must declare UTF-8 or ASCII encoding")
    pending, count = [(root, 0)], 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if count > _MAX_XML_NODES or depth > _MAX_XML_DEPTH:
            raise ValueError("Formula XML complexity exceeded (4096 elements, depth 64)")
        pending.extend((child, depth + 1) for child in node)
    return root
