"""Строгое преобразование базового Presentation MathML в Office Math без потерь структуры."""

from __future__ import annotations

from typing import Any

from opendoc_model._xml import _parse_xml

MATHML = "http://www.w3.org/1998/Math/MathML"
OMML = "http://schemas.openxmlformats.org/officeDocument/2006/math"
TOKENS = {"mi", "mn", "mo", "mtext"}
VARIANTS = {"normal": "p", "italic": "i", "bold": "b", "bold-italic": "bi"}
SCRIPTS = {
    "msub": ("sSub", ("e", "sub")),
    "msup": ("sSup", ("e", "sup")),
    "msubsup": ("sSubSup", ("e", "sub", "sup")),
    "mfrac": ("f", ("num", "den")),
}
ACCENTS = {"^": "\u0302", "ˆ": "\u0302", "~": "\u0303", "˜": "\u0303", "→": "\u20d7", ".": "\u0307", "˙": "\u0307", "¨": "\u0308"}
ACCENTS.update({value: value for value in tuple(ACCENTS.values())})


def mathml_to_omml(value: str) -> str:
    """Вернуть oMath; отклонить неизвестные конструкции, атрибуты и чрезмерный XML."""
    from lxml import etree

    return etree.tostring(_mathml_to_omml_tree(value), encoding="unicode")


def _mathml_to_omml_tree(value: str) -> Any:
    root = _parse_xml(value)
    if _tag(root) != "math":
        raise ValueError("Ожидается корневой элемент math")
    result = _element("oMath")
    result.extend(_convert(root))
    return result


def _element(tag: str, value: str | None = None) -> Any:
    from lxml import etree

    node = etree.Element(f"{{{OMML}}}{tag}", nsmap={"m": OMML})
    if value is not None:
        node.set(f"{{{OMML}}}val", value)
    return node


def _tag(node: Any) -> str:
    from lxml import etree

    name = etree.QName(node)
    if name.namespace not in (None, MATHML):
        raise ValueError("Чужое пространство имён в MathML")
    return name.localname


def _attributes(node: Any, allowed: set[str]) -> None:
    unknown = set(node.attrib) - allowed - {"id"}
    if unknown:
        raise ValueError("Неподдержанные атрибуты MathML: " + ", ".join(sorted(unknown)))


def _run(text: str, variant: str) -> Any:
    run = _element("r")
    props = _element("rPr")
    props.append(_element("sty", VARIANTS[variant]))
    run.append(props)
    token = _element("t")
    token.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    token.text = text
    run.append(token)
    return run


def _convert(node: Any, variant: str | None = None) -> list[Any]:
    tag = _tag(node)
    allowed = {"mathvariant"} if tag in TOKENS | {"mstyle"} else set()
    if tag == "math":
        allowed |= {"display"}
    if tag == "mfenced":
        allowed |= {"open", "close", "separators"}
    if tag in {"mover", "munderover"}:
        allowed.add("accent")
    if tag in {"munder", "munderover"}:
        allowed.add("accentunder")
    _attributes(node, allowed)
    if tag == "math" and node.get("display") not in {None, "block", "inline"}:
        raise ValueError("Некорректный display MathML")
    variant = node.get("mathvariant", variant)
    if variant is not None and variant not in VARIANTS:
        raise ValueError("Неподдержанный mathvariant")
    if tag in TOKENS:
        if len(node):
            raise ValueError("Вложенная разметка внутри токена MathML")
        text = node.text or ""
        default = "italic" if tag == "mi" and len(text) == 1 else "normal"
        return [_run(text, variant or default)]
    if (node.text or "").strip() or any((child.tail or "").strip() for child in node):
        raise ValueError("Текст вне токенов MathML")
    if tag in {"math", "mrow", "mstyle"}:
        return [item for child in node for item in _convert(child, variant)]
    if tag == "semantics":
        if not len(node) or any(_tag(child) not in {"annotation", "annotation-xml"} for child in list(node)[1:]):
            raise ValueError("Некорректный semantics")
        return _convert(node[0], variant)
    if tag in SCRIPTS:
        target, slots = SCRIPTS[tag]
        if len(node) != len(slots):
            raise ValueError(f"Неверное число аргументов {tag}")
        result = _element(target)
        for slot, child in zip(slots, node):
            argument = _element(slot)
            argument.extend(_convert(child, variant))
            result.append(argument)
        return [result]
    if tag in {"msqrt", "mroot"}:
        if tag == "mroot" and len(node) != 2:
            raise ValueError("Неверное число аргументов mroot")
        result, props, degree, body = _element("rad"), _element("radPr"), _element("deg"), _element("e")
        props.append(_element("degHide", "1" if tag == "msqrt" else "0"))
        if tag == "mroot":
            degree.extend(_convert(node[1], variant))
        children = list(node) if tag == "msqrt" else [node[0]]
        for child in children:
            body.extend(_convert(child, variant))
        result.extend([props, degree, body])
        return [result]
    if tag == "mfenced":
        return [_fenced(node, variant)]
    if tag == "mtable":
        return [_matrix(node, variant)]
    if tag in {"munder", "mover", "munderover"}:
        return [_limits(node, variant)]
    raise ValueError(f"Неподдержанная конструкция MathML: {tag}")


def _limits(node: Any, variant: str | None) -> Any:
    tag = _tag(node)
    if len(node) != (3 if tag == "munderover" else 2):
        raise ValueError(f"Неверное число аргументов {tag}")
    body = _convert(node[0], variant)
    slots = [("accentunder", "limLow", node[1])] if tag != "mover" else []
    if tag != "munder":
        slots.append(("accent", "limUpp", node[-1]))
    for attribute, target, script in slots:
        accent = node.get(attribute)
        if accent is None:
            if any(_tag(child) == "mo" for child in script.iter()):
                raise ValueError(f"Укажите явно {attribute} для оператора в пределе MathML")
            accent = "false"
        if accent not in {"true", "false"}:
            raise ValueError(f"Некорректный {attribute}")
        if accent == "true":
            result = _accent(script, above=attribute == "accent")
        else:
            result = _element(target)
        base = _element("e")
        base.extend(body)
        result.append(base)
        if accent == "false":
            limit = _element("lim")
            limit.extend(_convert(script, variant))
            result.append(limit)
        body = [result]
    return body[0]


def _accent(script: Any, *, above: bool) -> Any:
    if _tag(script) != "mo" or len(script):
        raise ValueError("Поддерживается только простой акцент mo")
    _attributes(script, {"stretchy"})
    if script.get("stretchy", "true") != "true":
        raise ValueError("Поддерживаются только растягиваемые акценты")
    symbol = script.text or ""
    position = "top" if above else "bot"
    bars = {"¯", "‾", "\u0305"} if above else {"_", "\u0332"}
    if symbol in bars:
        result, props = _element("bar"), _element("barPr")
        props.append(_element("pos", position))
    elif symbol == ("⏞" if above else "⏟"):
        result, props = _element("groupChr"), _element("groupChrPr")
        props.extend([_element("chr", symbol), _element("pos", position), _element("vertJc", "bot" if above else "top")])
    elif above and symbol in ACCENTS:
        result, props = _element("acc"), _element("accPr")
        props.append(_element("chr", ACCENTS[symbol]))
    else:
        raise ValueError("Неподдержанный знак над или под выражением MathML")
    result.append(props)
    return result


def _fenced(node: Any, variant: str | None) -> Any:
    result, props, body = _element("d"), _element("dPr"), _element("e")
    for attribute, tag, default in (("open", "begChr", "("), ("close", "endChr", ")")):
        value = node.get(attribute, default)
        if len(value) > 1:
            raise ValueError("Многосимвольные ограничители MathML не поддерживаются")
        props.append(_element(tag, value))
    separators = "".join(node.get("separators", ",").split())
    for index, child in enumerate(node):
        if index and separators:
            body.append(_run(separators[min(index - 1, len(separators) - 1)], "normal"))
        body.extend(_convert(child, variant))
    result.extend([props, body])
    return result


def _matrix(node: Any, variant: str | None) -> Any:
    result = _element("m")
    widths = set()
    for row in node:
        if _tag(row) != "mtr" or (row.text or "").strip():
            raise ValueError("Неподдержанная строка матрицы MathML")
        _attributes(row, set())
        widths.add(len(row))
        target = _element("mr")
        for cell in row:
            if _tag(cell) != "mtd" or (cell.text or "").strip() or (cell.tail or "").strip():
                raise ValueError("Неподдержанная ячейка матрицы MathML")
            _attributes(cell, set())
            body = _element("e")
            for child in cell:
                if (child.tail or "").strip():
                    raise ValueError("Текст вне токенов MathML")
                body.extend(_convert(child, variant))
            target.append(body)
        result.append(target)
    if len(widths) != 1 or 0 in widths:
        raise ValueError("Матрица MathML должна быть непустой и прямоугольной")
    return result
