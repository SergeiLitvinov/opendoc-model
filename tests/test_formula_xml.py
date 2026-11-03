"""XML fingerprints stay bounded, reproducible and independent of external I/O."""

import builtins
import copy
from pathlib import Path

import pytest

from opendoc_model import (
    ConversionReport,
    DocumentModel,
    Formula,
    FormulaFormat,
    FormulaLossPolicy,
    Section,
    compare_inspections,
    inspect_document_model,
)
from opendoc_model.formula_quality_policy import formula_fingerprint
from opendoc_model.mathml import mathml_to_omml

MATHML = "http://www.w3.org/1998/Math/MathML"
OMML = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MAX_BYTES = 1024 * 1024
XML_FORMATS = [FormulaFormat.MATHML, FormulaFormat.OMML]


@pytest.fixture
def etree():
    return pytest.importorskip("lxml.etree")


def _source(format_, text="x"):
    if format_ is FormulaFormat.MATHML:
        return f'<math xmlns="{MATHML}"><mtext>{text}</mtext></math>'
    return f'<m:oMath xmlns:m="{OMML}"><m:r><m:t>{text}</m:t></m:r></m:oMath>'


def _block_lxml(monkeypatch):
    import_function = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "lxml" or name.startswith("lxml."):
            raise ImportError("Optional math backend deliberately unavailable")
        return import_function(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)


def test_latex_and_strict_formula_policy_work_without_optional_backend(monkeypatch):
    _block_lxml(monkeypatch)
    source = DocumentModel(sections=[Section(blocks=[Formula(r"x^2", FormulaFormat.LATEX)])])
    before = inspect_document_model(source)
    assert before.objects[0]["formula_hash"]
    after = inspect_document_model(copy.deepcopy(source))
    assert FormulaLossPolicy().evaluate(ConversionReport(Path("result.json")), compare_inspections(before, after))


@pytest.mark.parametrize("format_", XML_FORMATS)
def test_xml_has_no_fingerprint_without_extra_and_strict_policy_does_not_pass(monkeypatch, format_):
    _block_lxml(monkeypatch)
    value = _source(format_)
    assert formula_fingerprint(Formula(value, format_)) is None
    source = inspect_document_model(DocumentModel(sections=[Section(blocks=[Formula(value, format_)])]))
    assert source.valid
    report = ConversionReport(Path("result.json"))
    assert not FormulaLossPolicy(999).evaluate(report, compare_inspections(source, copy.deepcopy(source)))
    assert report.metrics["formula_quality_gate"]["reason"] == "unavailable"
    assert report.metrics["formula_quality_gate"]["changed_formulas"] is None
    with pytest.raises(ImportError):
        mathml_to_omml(_source(FormulaFormat.MATHML))


@pytest.mark.parametrize("format_", [FormulaFormat.LATEX, *XML_FORMATS])
@pytest.mark.parametrize("character", ["x", "α"])
def test_utf8_byte_limit_is_inclusive_and_applies_to_input(etree, format_, character):
    empty = "" if format_ is FormulaFormat.LATEX else _source(format_, "")
    remaining = MAX_BYTES - len(empty.encode("utf-8"))
    text = character * (remaining // len(character.encode("utf-8")))
    text += "x" * (remaining - len(text.encode("utf-8")))
    value = text if format_ is FormulaFormat.LATEX else _source(format_, text)
    assert len(value.encode("utf-8")) == MAX_BYTES
    assert formula_fingerprint(Formula(value, format_)) is not None
    if format_ is FormulaFormat.MATHML:
        assert mathml_to_omml(value)
    value = text + "x" if format_ is FormulaFormat.LATEX else _source(format_, text + "x")
    assert formula_fingerprint(Formula(value, format_)) is None
    if format_ is FormulaFormat.MATHML:
        with pytest.raises(ValueError, match="1 MiB"):
            mathml_to_omml(value)


@pytest.mark.parametrize("format_", XML_FORMATS)
@pytest.mark.parametrize("count", [4096, 4097])
def test_xml_element_count_exact_boundary(etree, format_, count):
    if format_ is FormulaFormat.MATHML:
        source = f'<math xmlns="{MATHML}">' + "<mi>x</mi>" * (count - 1) + "</math>"
    else:
        source = f'<m:oMath xmlns:m="{OMML}">' + "<m:r/>" * (count - 1) + "</m:oMath>"
    assert (formula_fingerprint(Formula(source, format_)) is not None) is (count == 4096)
    if format_ is FormulaFormat.MATHML:
        if count == 4096:
            assert mathml_to_omml(source)
        else:
            with pytest.raises(ValueError, match="complexity"):
                mathml_to_omml(source)


@pytest.mark.parametrize("format_", XML_FORMATS)
@pytest.mark.parametrize("depth", [64, 65])
def test_xml_depth_root_zero_exact_boundary(etree, format_, depth):
    if format_ is FormulaFormat.MATHML:
        source = f'<math xmlns="{MATHML}">' + "<mrow>" * (depth - 1) + "<mi>x</mi>" + "</mrow>" * (depth - 1) + "</math>"
    else:
        source = f'<m:oMath xmlns:m="{OMML}">' + "<m:e>" * (depth - 1) + "<m:t>x</m:t>" + "</m:e>" * (depth - 1) + "</m:oMath>"
    assert (formula_fingerprint(Formula(source, format_)) is not None) is (depth == 64)
    if format_ is FormulaFormat.MATHML:
        if depth == 64:
            assert mathml_to_omml(source)
        else:
            with pytest.raises(ValueError, match="complexity"):
                mathml_to_omml(source)


@pytest.mark.parametrize(
    "source", ["", "<math>", "<math/><extra/>", "<math>&unknown;</math>", "<math>\x00</math>", "<math>\ud800</math>"]
)
def test_malformed_xml_and_unicode_are_not_random_parser_exceptions(etree, source):
    with pytest.raises(ValueError):
        mathml_to_omml(source)
    for format_ in XML_FORMATS:
        assert formula_fingerprint(Formula(source, format_)) is None


@pytest.mark.parametrize("format_", XML_FORMATS)
def test_dtd_and_external_entities_do_not_resolve_resources(etree, monkeypatch, tmp_path, format_):
    secret = tmp_path / "secret.txt"
    secret.write_text("EXTERNAL_CONTENT_MUST_NOT_BE_READ", encoding="utf-8")
    calls = []

    class Trap(etree.Resolver):
        def resolve(self, url, public_id, context):
            calls.append(url)
            raise AssertionError("XML must not resolve external resources")

    factory = etree.XMLParser

    def parser(*args, **kwargs):
        value = factory(*args, **kwargs)
        value.resolvers.add(Trap())
        return value

    monkeypatch.setattr(etree, "XMLParser", parser)
    root_name = "math" if format_ is FormulaFormat.MATHML else "m:oMath"
    for declaration, content in [
        (f'<!DOCTYPE {root_name} SYSTEM "{secret.as_uri()}">', "x"),
        (f'<!DOCTYPE {root_name} SYSTEM "http://127.0.0.1:1/never-request.dtd">', "x"),
        (f'<!DOCTYPE {root_name} [<!ENTITY external SYSTEM "{secret.as_uri()}">]>', "&external;"),
        (f'<!DOCTYPE {root_name} [<!ENTITY local "expanded">]>', "&local;"),
        (f'<!DOCTYPE {root_name} [<!ENTITY % external SYSTEM "{secret.as_uri()}">%external;]>', "x"),
    ]:
        source = declaration + _source(format_, content)
        assert formula_fingerprint(Formula(source, format_)) is None
        if format_ is FormulaFormat.MATHML:
            with pytest.raises(ValueError, match="DTD"):
                mathml_to_omml(source)
    assert calls == []


def test_cdata_literal_dtd_and_predefined_entities_are_plain_text(etree):
    literal = '<!DOCTYPE math SYSTEM "file:///never-open"> & value'
    source = _source(FormulaFormat.MATHML, f"<![CDATA[{literal}]]>")
    converted = mathml_to_omml(source)
    assert etree.fromstring(converted.encode()).xpath("//m:t/text()", namespaces={"m": OMML}) == [literal]
    assert formula_fingerprint(Formula(source, FormulaFormat.MATHML)) is not None
    assert formula_fingerprint(Formula(_source(FormulaFormat.MATHML, "&lt;&amp;&gt;"), FormulaFormat.MATHML)) is not None


def test_omml_prefixes_attribute_order_comments_and_indentation_are_reproducible(etree):
    plain = (
        f'<m:oMath xmlns:m="{OMML}"><m:r><m:rPr><m:sty m:val="i" m:vendor="retained"/></m:rPr>'
        '<m:t xml:space="preserve"> x </m:t></m:r></m:oMath>'
    )
    variant = (
        f'<q:oMath xmlns:q="{OMML}">\n<!-- comment --><?ignored local?><q:r>\n'
        '<q:rPr><q:sty q:vendor="retained" q:val="i"/></q:rPr><q:t xml:space="preserve"> x </q:t>\n</q:r>\n</q:oMath>'
    )
    fingerprint = formula_fingerprint(Formula(plain, FormulaFormat.OMML))
    assert fingerprint
    assert formula_fingerprint(Formula(variant, FormulaFormat.OMML)) == fingerprint
    assert formula_fingerprint(Formula(plain.replace("retained", "changed"), FormulaFormat.OMML)) != fingerprint
    assert formula_fingerprint(Formula(plain.replace(" x ", "x"), FormulaFormat.OMML)) != fingerprint


@pytest.mark.parametrize(
    "body",
    [
        "text<m:r/>",
        "<m:r/>tail",
        '<foreign xmlns="urn:foreign"/>',
        '<m:r xmlns:w="urn:foreign" w:style="x"/>',
        '<m:r plain="unqualified"/>',
    ],
)
def test_unsupported_omml_content_is_not_silently_discarded(etree, body):
    value = f'<m:oMath xmlns:m="{OMML}">{body}</m:oMath>'
    assert formula_fingerprint(Formula(value, FormulaFormat.OMML)) is None


def test_omml_paragraph_wrapper_only_normalizes_if_it_carries_no_extra_content(etree):
    native = _source(FormulaFormat.OMML)
    wrapped = f'<m:oMathPara xmlns:m="{OMML}">{native}</m:oMathPara>'
    assert formula_fingerprint(Formula(wrapped, FormulaFormat.OMML)) == formula_fingerprint(Formula(native, FormulaFormat.OMML))
    for value in (
        wrapped.replace("<m:oMathPara ", '<m:oMathPara m:vendor="ignored-before" '),
        wrapped.replace("><m:oMath ", ">ignored-before<m:oMath "),
        wrapped.replace("</m:oMathPara>", native + "</m:oMathPara>"),
    ):
        assert formula_fingerprint(Formula(value, FormulaFormat.OMML)) is None


@pytest.mark.parametrize("encoding", ["UTF-8", "ASCII", "ISO-8859-1", "UTF-16"])
def test_string_encoding_declaration_cannot_silently_change_unicode(etree, encoding):
    source = f'<?xml version="1.0" encoding="{encoding}"?>' + _source(FormulaFormat.MATHML)
    assert (formula_fingerprint(Formula(source, FormulaFormat.MATHML)) is not None) is (encoding in {"UTF-8", "ASCII"})
