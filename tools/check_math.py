"""Verify the same installed core with and without its optional math backend."""

import argparse
import subprocess
import tempfile
from pathlib import Path

PROBE = """
import importlib
import importlib.abc
import pkgutil
import sys
from importlib.metadata import distributions
from pathlib import Path

enabled = sys.argv[1] == 'math'
assert {dist.metadata['Name'].lower() for dist in distributions()} == (
    {'opendoc-model', 'lxml'} if enabled else {'opendoc-model'})

class NoEagerMath(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'lxml' or fullname.startswith('lxml.'):
            raise AssertionError('Core operation attempted optional import: ' + fullname)

guard = NoEagerMath()
sys.meta_path.insert(0, guard)
import opendoc_model as core
assert Path(core.__file__).resolve().is_relative_to(Path(sys.prefix).resolve())
for module in pkgutil.walk_packages(core.__path__, core.__name__ + '.'):
    importlib.import_module(module.name)
from opendoc_model.formula_quality_policy import formula_fingerprint
from opendoc_model.mathml import mathml_to_omml

# Even when lxml is installed, model operations and LaTeX must not attempt it.
latex = core.Formula('x^2', core.FormulaFormat.LATEX, fallback_text='x^2')
document = core.DocumentModel(sections=[core.Section(blocks=[core.Paragraph([
    core.TextRun('core'), latex])])], metadata={'consumer': {'data': [1, None]}})
serialized = core.document_to_json(document)
restored = core.document_from_json(serialized)
assert restored == document
assert core.document_to_json(restored) == serialized
edited = core.clone_model(document)
next(core.iter_elements(edited, core.TextRun)).node.text = 'edited'
assert core.extract_text(document) == 'corex^2'
assert core.extract_text(edited) == 'editedx^2'
assert core.check_document(restored).success
assert formula_fingerprint(latex)
assert core.compare_documents(document, restored, policies=[core.FormulaLossPolicy()]).success
assert not any(name == 'lxml' or name.startswith('lxml.') for name in sys.modules)
sys.meta_path.remove(guard)

mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'
omml = ('<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
        '<m:r><m:rPr><m:sty m:val="i"/></m:rPr><m:t xml:space="preserve">x</m:t></m:r></m:oMath>')
formulas = [core.Formula(mathml, core.FormulaFormat.MATHML), core.Formula(omml, core.FormulaFormat.OMML)]
xml_document = core.DocumentModel(sections=[core.Section(blocks=formulas)])
payload = core.document_to_json(xml_document)
xml_restored = core.document_from_json(payload)
assert xml_restored == xml_document
assert core.document_to_json(xml_restored) == payload
fingerprints = [formula_fingerprint(formula) for formula in formulas]
result = core.compare_documents(xml_document, xml_restored, policies=[core.FormulaLossPolicy(999)])
assert result.success == enabled
assert result.metrics['formula_quality_gate']['verified'] == enabled
if enabled:
    assert fingerprints[0] and fingerprints[0] == fingerprints[1]
    assert formula_fingerprint(core.Formula(mathml.replace('>x<', '>y<'), core.FormulaFormat.MATHML)) != fingerprints[0]
    assert formula_fingerprint(core.Formula('<math><unknown/></math>', core.FormulaFormat.MATHML)) is None
    assert formula_fingerprint(core.Formula('<!DOCTYPE math><math/>', core.FormulaFormat.MATHML)) is None
    assert formula_fingerprint(core.Formula(mathml_to_omml(mathml), core.FormulaFormat.OMML)) == fingerprints[0]
    assert 'lxml.etree' in sys.modules
else:
    assert fingerprints == [None, None]
    assert result.metrics['formula_quality_gate']['reason'] == 'unavailable'
    assert result.metrics['formula_quality_gate']['changed_formulas'] is None
    try:
        mathml_to_omml(mathml)
    except ImportError:
        pass
    else:
        raise AssertionError('XML conversion did not require math')
    assert not any(name == 'lxml' or name.startswith('lxml.') for name in sys.modules)
print('Installed math boundary: lazy imports, core operations and ' + ('XML enabled' if enabled else 'XML unavailable') + ' OK')
"""


def verify(python, with_math=False):
    with tempfile.TemporaryDirectory(prefix="opendoc_model-math-probe-") as directory:
        subprocess.run(
            [str(Path(python).absolute()), "-I", "-c", PROBE, "math" if with_math else "core"], cwd=directory, check=True
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="Installed wheel environment")
    parser.add_argument("--with-math", action="store_true", help="Require only opendoc_model and lxml distributions")
    args = parser.parse_args()
    verify(args.python, args.with_math)
