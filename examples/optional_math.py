"""Optional XML support is a measured capability, never an implicit requirement."""

from opendoc_model import DocumentModel, Formula, FormulaFormat, FormulaLossPolicy, Section, clone_model, compare_documents
from opendoc_model.formula_quality_policy import formula_fingerprint
from opendoc_model.mathml import mathml_to_omml

latex = Formula("x^2", FormulaFormat.LATEX)
assert formula_fingerprint(latex)
mathml = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'
formula = Formula(mathml, FormulaFormat.MATHML)
source = DocumentModel(sections=[Section(blocks=[formula])])
result = compare_documents(source, clone_model(source), policies=[FormulaLossPolicy()])
try:
    native = mathml_to_omml(mathml)
except ImportError:
    assert formula_fingerprint(formula) is None
    assert not result.success
    assert result.metrics["formula_quality_gate"]["reason"] == "unavailable"
    assert result.metrics["formula_quality_gate"]["changed_formulas"] is None
    print("Optional math example: core and LaTeX work; XML evidence unavailable")
else:
    assert formula_fingerprint(formula) == formula_fingerprint(Formula(native, FormulaFormat.OMML))
    assert result.success and result.metrics["formula_quality_gate"]["verified"]
    assert formula_fingerprint(Formula("<math><unsupported/></math>", FormulaFormat.MATHML)) is None
    print("Optional math example: supported XML measured; unsupported XML unavailable")
