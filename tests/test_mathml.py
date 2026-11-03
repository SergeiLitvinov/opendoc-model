"""Independent native trees verify supported MathML and its strict boundary."""

from xml.sax.saxutils import escape

import pytest

from opendoc_model import Formula, FormulaFormat
from opendoc_model.formula_quality_policy import formula_fingerprint
from opendoc_model.mathml import mathml_to_omml

etree = pytest.importorskip("lxml.etree")
MATHML = "http://www.w3.org/1998/Math/MathML"
OMML = "http://schemas.openxmlformats.org/officeDocument/2006/math"


def _math(body):
    return f'<math xmlns="{MATHML}">{body}</math>'


def _omml(body):
    return f'<m:oMath xmlns:m="{OMML}">{body}</m:oMath>'


def _run(text, style="p"):
    return f'<m:r><m:rPr><m:sty m:val="{style}"/></m:rPr><m:t xml:space="preserve">{escape(text)}</m:t></m:r>'


X = _run("x", "i")
ONE, TWO = _run("1"), _run("2")


@pytest.mark.parametrize(
    ("body", "native"),
    [
        ("<mi>x</mi>", X),
        ("<mi>name</mi>", _run("name")),
        ("<mn>2</mn><mo>+</mo>", TWO + _run("+")),
        ("<mtext>текст &amp; 😀</mtext>", _run("текст & 😀")),
        ("<mrow><mi>x</mi><mn>1</mn></mrow>", X + ONE),
        ('<mstyle mathvariant="bold"><mi>x</mi><mn>2</mn></mstyle>', _run("x", "b") + _run("2", "b")),
        ('<mstyle mathvariant="bold"><mi mathvariant="normal">x</mi></mstyle>', _run("x")),
        ("<msub><mi>x</mi><mn>1</mn></msub>", f"<m:sSub><m:e>{X}</m:e><m:sub>{ONE}</m:sub></m:sSub>"),
        ("<msup><mi>x</mi><mn>2</mn></msup>", f"<m:sSup><m:e>{X}</m:e><m:sup>{TWO}</m:sup></m:sSup>"),
        (
            "<msubsup><mi>x</mi><mn>1</mn><mn>2</mn></msubsup>",
            f"<m:sSubSup><m:e>{X}</m:e><m:sub>{ONE}</m:sub><m:sup>{TWO}</m:sup></m:sSubSup>",
        ),
        ("<mfrac><mi>x</mi><mn>2</mn></mfrac>", f"<m:f><m:num>{X}</m:num><m:den>{TWO}</m:den></m:f>"),
        ("<msqrt><mi>x</mi></msqrt>", f'<m:rad><m:radPr><m:degHide m:val="1"/></m:radPr><m:deg/><m:e>{X}</m:e></m:rad>'),
        (
            "<mroot><mi>x</mi><mn>2</mn></mroot>",
            f'<m:rad><m:radPr><m:degHide m:val="0"/></m:radPr><m:deg>{TWO}</m:deg><m:e>{X}</m:e></m:rad>',
        ),
        (
            "<mfenced><mi>x</mi><mn>2</mn></mfenced>",
            f'<m:d><m:dPr><m:begChr m:val="("/><m:endChr m:val=")"/></m:dPr><m:e>{X}{_run(",")}{TWO}</m:e></m:d>',
        ),
        (
            '<mfenced open="" close="" separators=""><mi>x</mi><mn>2</mn></mfenced>',
            f'<m:d><m:dPr><m:begChr m:val=""/><m:endChr m:val=""/></m:dPr><m:e>{X}{TWO}</m:e></m:d>',
        ),
        (
            "<mtable><mtr><mtd><mi>x</mi></mtd><mtd><mn>2</mn></mtd></mtr></mtable>",
            f"<m:m><m:mr><m:e>{X}</m:e><m:e>{TWO}</m:e></m:mr></m:m>",
        ),
        ("<munder><mi>x</mi><mn>1</mn></munder>", f"<m:limLow><m:e>{X}</m:e><m:lim>{ONE}</m:lim></m:limLow>"),
        ("<mover><mi>x</mi><mn>2</mn></mover>", f"<m:limUpp><m:e>{X}</m:e><m:lim>{TWO}</m:lim></m:limUpp>"),
        (
            "<munderover><mi>x</mi><mn>1</mn><mn>2</mn></munderover>",
            f"<m:limUpp><m:e><m:limLow><m:e>{X}</m:e><m:lim>{ONE}</m:lim></m:limLow></m:e><m:lim>{TWO}</m:lim></m:limUpp>",
        ),
        (
            '<mover accent="true"><mi>x</mi><mo>^</mo></mover>',
            f'<m:acc><m:accPr><m:chr m:val="̂"/></m:accPr><m:e>{X}</m:e></m:acc>',
        ),
        (
            '<mover accent="true"><mi>x</mi><mo>¯</mo></mover>',
            f'<m:bar><m:barPr><m:pos m:val="top"/></m:barPr><m:e>{X}</m:e></m:bar>',
        ),
        (
            '<munder accentunder="true"><mi>x</mi><mo>_</mo></munder>',
            f'<m:bar><m:barPr><m:pos m:val="bot"/></m:barPr><m:e>{X}</m:e></m:bar>',
        ),
        (
            '<mover accent="true"><mi>x</mi><mo>⏞</mo></mover>',
            '<m:groupChr><m:groupChrPr><m:chr m:val="⏞"/><m:pos m:val="top"/><m:vertJc m:val="bot"/></m:groupChrPr>'
            f"<m:e>{X}</m:e></m:groupChr>",
        ),
        (
            '<munder accentunder="true"><mi>x</mi><mo>⏟</mo></munder>',
            '<m:groupChr><m:groupChrPr><m:chr m:val="⏟"/><m:pos m:val="bot"/><m:vertJc m:val="top"/></m:groupChrPr>'
            f"<m:e>{X}</m:e></m:groupChr>",
        ),
        (
            '<semantics><mi>x</mi><annotation encoding="application/x-tex">x</annotation>'
            '<annotation-xml encoding="vendor"><v:data xmlns:v="urn:vendor"/></annotation-xml></semantics>',
            X,
        ),
        ("<math><mi>x</mi></math>", X),
    ],
)
def test_supported_constructs_match_independent_native_omml(body, native):
    source = _math(body)
    converted = mathml_to_omml(source)
    expected = _omml(native)
    assert formula_fingerprint(Formula(source, FormulaFormat.MATHML)) == formula_fingerprint(
        Formula(expected, FormulaFormat.OMML)
    )
    assert formula_fingerprint(Formula(converted, FormulaFormat.OMML)) == formula_fingerprint(
        Formula(expected, FormulaFormat.OMML)
    )
    assert etree.tostring(etree.fromstring(converted.encode()), method="c14n") == etree.tostring(
        etree.fromstring(expected.encode()), method="c14n"
    )


@pytest.mark.parametrize(("variant", "style"), [("normal", "p"), ("italic", "i"), ("bold", "b"), ("bold-italic", "bi")])
def test_all_supported_token_variants(variant, style):
    source = _math(f'<mi mathvariant="{variant}">x</mi>')
    assert formula_fingerprint(Formula(source, FormulaFormat.MATHML)) == formula_fingerprint(
        Formula(_omml(_run("x", style)), FormulaFormat.OMML)
    )


@pytest.mark.parametrize(
    "body",
    [
        "<unknown/>",
        "<apply><ci>x</ci></apply>",
        '<mi href="https://example.invalid">x</mi>',
        '<mi mathvariant="double-struck">x</mi>',
        '<mstyle color="red"><mi>x</mi></mstyle>',
        "<mi><mn>1</mn></mi>",
        "text<mi>x</mi>",
        "<mi>x</mi>tail",
        "<mfrac><mi>x</mi></mfrac>",
        "<msub><mi>x</mi></msub>",
        "<msup><mi>x</mi><mn>1</mn><mn>2</mn></msup>",
        "<mroot><mi>x</mi></mroot>",
        "<msubsup><mi>x</mi><mn>2</mn></msubsup>",
        "<semantics/>",
        "<semantics><mi>x</mi><mi>y</mi></semantics>",
        "<annotation>x</annotation>",
        '<mfenced open="[["><mi>x</mi></mfenced>',
        '<mfenced close="]]"/>',
        "<mtable/>",
        "<mtable><mtr/></mtable>",
        "<mtable><mtr><mtd/></mtr><mtr><mtd/><mtd/></mtr></mtable>",
        "<mtable><wrong/></mtable>",
        "<mtable><mtr><wrong/></mtr></mtable>",
        "<mtable><mtr>text<mtd/></mtr></mtable>",
        "<mtable><mtr><mtd>text</mtd></mtr></mtable>",
        "<mtable><mtr><mtd><mi>x</mi>tail</mtd></mtr></mtable>",
        '<mtable><mtr columnalign="left"><mtd/></mtr></mtable>',
        '<mtable><mtr><mtd rowspan="2"/></mtr></mtable>',
        "<mover><mi>x</mi><mo>^</mo></mover>",
        '<mover accent="1"><mi>x</mi><mn>2</mn></mover>',
        '<mover accent="true"><mi>x</mi><mo stretchy="false">^</mo></mover>',
        '<mover accent="true"><mi>x</mi><mi>y</mi></mover>',
        '<mover accent="true"><mi>x</mi><mo>?</mo></mover>',
        '<munder accentunder="true"><mi>x</mi><mo>^</mo></munder>',
        '<mover accent="true"><mi>x</mi><mo custom="x">^</mo></mover>',
        '<mover accent="true"><mi>x</mi><mo><mi>y</mi></mo></mover>',
        "<munderover><mi>x</mi><mn>1</mn></munderover>",
        '<f:mi xmlns:f="urn:foreign">x</f:mi>',
        '<mi xmlns:f="urn:foreign" f:id="x">x</mi>',
    ],
)
def test_unsupported_mathml_has_an_explicit_error_and_no_fingerprint(body):
    source = _math(body)
    with pytest.raises(ValueError):
        mathml_to_omml(source)
    assert formula_fingerprint(Formula(source, FormulaFormat.MATHML)) is None


@pytest.mark.parametrize(
    "source",
    [
        "<mi>x</mi>",
        '<math xmlns="urn:foreign"><mi>x</mi></math>',
        '<math display="invalid"><mi>x</mi></math>',
        '<math mathvariant="bold"><mi>x</mi></math>',
        '<math xmlns:f="urn:foreign" f:display="block"><mi>x</mi></math>',
    ],
)
def test_root_namespace_and_attributes_are_explicit(source):
    with pytest.raises(ValueError):
        mathml_to_omml(source)
    assert formula_fingerprint(Formula(source, FormulaFormat.MATHML)) is None


def test_namespaces_ids_and_presentation_annotations_are_normalized():
    plain = "<math><mi>x</mi></math>"
    prefixed = f'<q:math xmlns:q="{MATHML}" id="formula" display="block"><q:mi id="token">x</q:mi></q:math>'
    assert mathml_to_omml(plain) == mathml_to_omml(prefixed)


def test_repeated_separators_and_combined_accents_preserve_native_structure():
    source = _math('<mfenced open="[" close="]" separators="|; "><mn>1</mn><mn>2</mn><mn>3</mn><mn>4</mn></mfenced>')
    result = etree.fromstring(mathml_to_omml(source).encode())
    assert result.xpath("//m:t/text()", namespaces={"m": OMML}) == ["1", "|", "2", ";", "3", ";", "4"]
    source = _math('<munderover accentunder="true" accent="true"><mi>x</mi><mo>_</mo><mo>¯</mo></munderover>')
    result = etree.fromstring(mathml_to_omml(source).encode())
    assert result.xpath("//m:pos/@m:val", namespaces={"m": OMML}) == ["top", "bot"]
