"""Verify an installed document wheel with no application or format backends."""

import argparse
import subprocess
import tempfile
from pathlib import Path

from tools.check_math import verify as verify_math

PROBE = """
import importlib.util
from importlib.metadata import distribution, distributions
from pathlib import Path
import opendoc_model as core
from opendoc_model.formula_quality_policy import formula_fingerprint
from opendoc_model.mathml import mathml_to_omml

for name in ('fastapi', 'docx', 'pptx', 'fitz', 'lxml'):
    assert importlib.util.find_spec(name) is None, name
assert {dist.metadata['Name'].lower() for dist in distributions()} == {'opendoc-model'}
dist = distribution('opendoc_model')
assert dist.version == core.__version__, (dist.version, core.__version__)
assert all('extra ==' in requirement for requirement in dist.requires or []), dist.requires
assert Path(core.__file__).is_relative_to(Path(__import__('sys').prefix)), core.__file__
paragraph = core.Paragraph(content=[core.TextRun('Independent document')],
                           properties={'custom': {'revision': 7}})
document = core.DocumentModel(sections=[core.Section(blocks=[paragraph])], metadata={'custom': {'category': 'draft'}})
document.add_resource(core.Resource(id='asset', kind=core.ResourceKind.ATTACHMENT,
                                  media_type='application/octet-stream', data=b'embedded'))
before = core.inspect_document_model(document)
path = core.save_document(document, 'document.json')
restored = core.load_document(path)
assert restored.validate() == []
assert restored.sections[0].blocks[0].properties['custom'] == {'revision': 7}
assert restored.metadata == document.metadata
assert restored.resources['asset'].data == b'embedded'
after = core.inspect_document_model(restored)
comparison = core.compare_inspections(before, after)
assert before.metrics['paragraphs'] == 1
assert comparison.retention['characters']['ratio'] == 1
report = core.ConversionReport(Path('result.json'))
core.ObjectLossPolicy(max_lost_objects=0).evaluate(report, comparison)
assert report.success, report.to_dict()
try:
    core.document_from_json('{}', limits=core.DocumentLimits(max_bytes=1))
except core.ArtifactLimitError:
    pass
else:
    raise AssertionError('Installed wheel must enforce the explicit input budget')
latex = core.Formula('x^2', core.FormulaFormat.LATEX)
assert formula_fingerprint(latex)
formula_document = core.DocumentModel(sections=[core.Section(blocks=[latex])])
formula_restored = core.document_from_json(core.document_to_json(formula_document))
comparison = core.compare_inspections(core.inspect_document_model(formula_document),
                                     core.inspect_document_model(formula_restored))
assert core.FormulaLossPolicy().evaluate(core.ConversionReport(Path('latex.json')), comparison)
for format_, value in (
    (core.FormulaFormat.MATHML, '<math><mi>x</mi></math>'),
    (core.FormulaFormat.OMML,
     '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"/>'),
):
    formula = core.Formula(value, format_)
    assert formula_fingerprint(formula) is None
    inspection = core.inspect_document_model(core.DocumentModel(sections=[core.Section(blocks=[formula])]))
    assert inspection.valid
    comparison = core.compare_inspections(inspection, inspection)
    report = core.ConversionReport(Path('unavailable.json'))
    assert not core.FormulaLossPolicy(999).evaluate(report, comparison)
    assert report.metrics['formula_quality_gate']['reason'] == 'unavailable'
    assert report.metrics['formula_quality_gate']['changed_formulas'] is None
try:
    mathml_to_omml('<math><mi>x</mi></math>')
except ImportError:
    pass
else:
    raise AssertionError('XML conversion must require the optional math backend')
assert not any(name == 'lxml' or name.startswith('lxml.') for name in __import__('sys').modules)
nested = core.DocumentModel(sections=[core.Section(blocks=[
    core.Table([core.TableRow([core.TableCell([core.Paragraph([
        core.TextRun('nested'), core.Image('asset', 'asset')
    ])])])])
])], resources={'asset': core.Resource('asset', core.ResourceKind.RASTER_IMAGE, 'image/png', b'bytes')})
images = list(core.iter_elements(nested, core.Image))
assert len(images) == 1
assert images[0].path == 'sections[0].blocks[0].rows[0].cells[0].blocks[0].content[1]'
assert isinstance(images[0].parent.node, core.Paragraph)
assert next(core.iter_resource_references(nested)).resource_id == 'asset'
for reference in core.iter_elements(nested, core.TextRun):
    reference.node.text = 'updated'
restored = core.document_from_json(core.document_to_json(nested))
assert next(core.iter_elements(restored, core.TextRun)).node.text == 'updated'
original_json = core.document_to_json(nested)
copied = core.clone_model(nested)
def edit_run(reference):
    reference.node.text = 'final'
    return reference.node
changed = core.transform_elements(copied, core.TextRun, edit_run)
assert core.extract_text(changed) == 'finalasset'
assert core.document_to_json(nested) == original_json
assert core.document_to_json(copied) == original_json
section = next(core.iter_sections(changed))
added = core.insert_node(changed, section, 'blocks', 1, core.Paragraph([core.TextRun('appendix')]))
replaced = core.replace_node(changed, added, core.Paragraph([core.TextRun('temporary')]))
assert core.remove_node(changed, replaced).plain_text == 'temporary'
assert changed.validate() == []
assert core.extract_text(core.load_document(core.save_document(changed, 'changed.json'))) == 'finalasset'
assert not any(name == 'lxml' or name.startswith('lxml.') for name in __import__('sys').modules)
merge_source = core.clone_model(nested)
merge_source.styles['base'] = core.TextStyle(bold=True)
merge_source.styles['body'] = core.TextStyle(properties={'base_style_id': 'base'})
next(core.iter_elements(merge_source, core.Paragraph)).node.style_id = 'body'
merged = core.merge_documents([merge_source, merge_source], conflicts='rename')
assert merged.id_maps[1].resources == {'asset': 'asset~2'}
assert merged.id_maps[1].styles == {'base': 'base~2', 'body': 'body~2'}
selected = list(core.iter_elements(merged.document, core.Paragraph))[1]
extracted = core.extract_document(merged.document, selected)
assert set(extracted.styles) == {'body~2', 'base~2'}
assert set(extracted.resources) == {'asset~2'}
assert extracted.validate() == []
assert core.load_document(core.save_document(extracted, 'extracted.json')) == extracted
assert merge_source.styles['body'].properties['base_style_id'] == 'base'
resolved_style = core.resolve_style(extracted, 'body~2')
assert resolved_style.bold is True
assert 'base_style_id' not in resolved_style.properties
extracted_paragraph = next(core.iter_elements(extracted, core.Paragraph)).node
extracted_paragraph.properties.set_typed('left_indent_pt', '0')
extracted_run = next(item for item in extracted_paragraph.content if isinstance(item, core.TextRun))
extracted_run.style.bold = False
effective = core.effective_text_style(extracted, extracted_paragraph, extracted_run)
assert effective.bold is False and effective.properties.get_typed('left_indent_pt') == 0.0
assert extracted.styles['base~2'].bold is True
try:
    extracted_paragraph.properties.set_typed('numbering_level', '1.5')
except ValueError:
    pass
else:
    raise AssertionError('Typed properties must not truncate fractional values')
assert core.load_document(core.save_document(extracted, 'styled.json')) == extracted
external_path = Path('external.bin')
external_path.write_bytes(b'portable')
portable_source = core.DocumentModel()
asset_id = core.add_resource(portable_source, core.Resource('local', core.ResourceKind.RASTER_IMAGE,
                                                           'image/png', source='external.bin'))
portable_source.sections = [core.Section(blocks=[core.Image(asset_id, 'portable')])]
assert len(core.find_resource_uses(portable_source, asset_id)) == 1
portable = core.embed_resources(portable_source, base_dir=Path.cwd())
assert portable.resources[asset_id].data == b'portable'
assert portable.resources[asset_id].source is None and portable_source.resources[asset_id].data is None
copy_id = core.add_resource(portable, portable.resources[asset_id], conflicts='rename')
assert core.find_duplicate_resources(portable) == ((asset_id, copy_id),)
core.remove_resource(portable, asset_id, replacement_id=copy_id)
assert len(core.find_resource_uses(portable, copy_id)) == 1
core.replace_resource(portable, copy_id, core.Resource('updated', core.ResourceKind.RASTER_IMAGE, 'image/png', b'new'))
assert core.load_document(core.save_document(portable, 'portable.json')) == portable
memory_check = core.check_document(portable)
assert memory_check.success and 'output_path' not in memory_check.to_dict()
memory_comparison = core.compare_documents(portable, portable, policies=[core.TextPreservationPolicy(),
                                                                       core.FormulaLossPolicy()])
assert memory_comparison.success, memory_comparison.to_dict()
assert memory_comparison.to_dict()['format'] == 'opendoc.check'
invalid_memory = core.DocumentModel(sections=[core.Section(blocks=[core.Image('missing')])])
failure = core.check_document(invalid_memory)
assert not failure.success and failure.issues[0].code == 'model.reference.missing'
assert failure.issues[0].location == 'sections[0].blocks[0].resource_id'
external_memory = core.DocumentModel(resources={'remote': core.Resource('remote', core.ResourceKind.ATTACHMENT,
                                                                       'type', source='https://invalid.test/data')})
assert core.check_document(external_memory).success
assert core.check_document(external_memory).metrics['inspection']['resources'][0]['size_bytes'] is None
heading_paragraph = core.Paragraph([core.TextRun('Chapter')])
core.set_heading(heading_paragraph, core.Heading(1))
heading_document = core.DocumentModel(sections=[core.Section(blocks=[heading_paragraph])])
heading_restored = core.document_from_json(core.document_to_json(heading_document))
assert core.get_heading(next(core.iter_headings(heading_restored)).node) == core.Heading(1)
core.set_heading(heading_restored.sections[0].blocks[0], core.Heading(2))
assert core.compare_documents(heading_document, heading_restored).metrics['comparison']['object_diff']['changed_headings'] == 1
list_paragraph = core.Paragraph([core.TextRun('Item')])
core.set_list_item(list_paragraph, core.ListItem('items', start=3))
list_document = core.DocumentModel(sections=[core.Section(blocks=[list_paragraph])])
list_restored = core.document_from_json(core.document_to_json(list_document))
assert [item.number for item in core.iter_list_numbers(list_restored)] == [3]
list_merged = core.merge_documents([list_document, list_restored], conflicts='rename')
assert list_merged.id_maps[1].lists == {'items': 'items~2'}
assert [item.number for item in core.iter_list_numbers(list_merged.document)] == [3, 3]
target_paragraph = core.Paragraph([core.TextRun('Target')])
core.set_anchor(target_paragraph, core.Anchor('target'))
link_run = core.TextRun('Go')
core.set_internal_link(link_run, core.InternalLink('target'))
reference_document = core.DocumentModel(sections=[core.Section(blocks=[core.Paragraph([link_run]), target_paragraph])])
reference_restored = core.document_from_json(core.document_to_json(reference_document))
assert core.resolve_anchor(reference_restored, 'target').node is reference_restored.sections[0].blocks[1]
reference_merged = core.merge_documents([reference_document, reference_restored], conflicts='rename')
assert reference_merged.id_maps[1].anchors == {'target': 'target~2'}
assert [core.get_internal_link(item.node).target_id for item in core.iter_internal_links(reference_merged.document)] == [
    'target', 'target~2']
reference_selected = core.extract_document(reference_document, next(core.iter_internal_links(reference_document)))
assert core.resolve_anchor(reference_selected, 'target') is not None
reference_comparison = core.compare_documents(reference_document, reference_restored)
assert reference_comparison.metrics['comparison']['object_diff']['references']['available']
note_reference = core.TextRun('1')
core.set_footnote_reference(note_reference, core.FootnoteReference('note'))
note_document = core.DocumentModel(sections=[core.Section(blocks=[core.Paragraph([note_reference])])],
                                   footnotes=[core.Footnote('note', [core.Paragraph([core.TextRun('Note body')])])])
note_restored = core.document_from_json(core.document_to_json(note_document))
assert note_restored == note_document
assert [item.number for item in core.iter_footnote_numbers(note_restored)] == [1]
assert next(core.iter_footnotes(note_restored)).node is note_restored.footnotes[0]
note_selected = core.extract_document(note_restored, next(core.iter_footnote_references(note_restored)))
assert core.get_footnote(note_selected, 'note').blocks[0].plain_text == 'Note body'
note_merged = core.merge_documents([note_document, note_restored], conflicts='rename')
assert note_merged.id_maps[1].footnotes == {'note': 'note~2'}
assert [item.number for item in core.iter_footnote_numbers(note_merged.document)] == [1, 2]
assert core.compare_documents(note_document, note_restored).metrics['comparison']['object_diff']['footnotes']['available']
def review_extension(context):
    if context.data.get('approved') is not True:
        return [core.DiagnosticIssue('review.approved', core.IssueSeverity.ERROR, 'approval required', 'approved')]
    return None

extended = core.DocumentModel()
core.set_extension(extended.metadata, 'org.example.review', {'approved': True})
extended.metadata['org.example.review']['retained'] = 'unknown envelope field'
schemas = [core.ExtensionSchema('org.example.review', frozenset({1}), review_extension)]
extended.package = core.PackageGraph.create('example.archive',
    parts=[core.PackagePart('/content', 'application/octet-stream', b'opaque')],
    relationships=[core.PackageRelationship('main', 'example.main', '/', '/content')])
extended_restored = core.document_from_json(core.document_to_json(extended))
assert extended_restored == extended
assert extended_restored.package.root == '/'
assert core.PackageGraph('example.archive').root == '/word/document.xml'
assert core.get_extension(extended_restored.metadata, 'org.example.review').extensions == {
    'retained': 'unknown envelope field'}
assert core.check_extensions(extended_restored, schemas).success
assert core.check_document(extended_restored, extensions=schemas).success
assert core.compare_documents(extended, extended_restored, extensions=iter(schemas)).success
assert not core.check_extensions(extended_restored, []).success
assert core.check_extensions(extended_restored, [], unknown='preserve').metrics['extensions']['unknown'] == 1
core.set_extension(extended_restored.metadata, 'org.example.review', {'approved': False})
extension_issue = core.check_extensions(extended_restored, schemas).issues[0]
assert extension_issue.location == "metadata['org.example.review'].data.approved"
assert extension_issue.code == 'review.approved'
budget_document = core.DocumentModel(sections=[core.Section(blocks=[core.Paragraph([core.TextRun('kept')])])])
budget_result = core.compare_documents(budget_document, budget_document,
    matching_limits=core.MatchingLimits(0), policies=[core.ObjectLossPolicy()])
assert not budget_result.success
assert budget_result.metrics['comparison']['object_diff']['reason'] == 'matching-budget-exceeded'
assert budget_result.metrics['comparison']['object_diff']['lost'] == []
assert budget_result.metrics['object_quality_gate']['lost_objects'] is None
assert core.compare_documents(budget_document, budget_document,
    matching_limits=core.MatchingLimits(100), policies=[core.ObjectLossPolicy()]).success
print('Independent wheel: extensions, packages, model, traversal, operations, composition, lists, references, '
      'footnotes, resources, styles, typed properties, memory checks, persistence, comparison and optional math behavior OK')
"""

PROBE += (
    "\nimport runpy\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/integration_model.py"))
    + ", run_name='__main__')\n"
)
PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/table_widths.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/table_semantics.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/page_geometry.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path(" + repr(str(Path(__file__).resolve().parent.parent / "examples/outline.py")) + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/table_borders.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/object_mapping.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/text_flow_profile.py"))
    + ", run_name='__main__')\n"
)

PROBE += (
    "\nrunpy.run_path(" + repr(str(Path(__file__).resolve().parent.parent / "examples/spacing.py")) + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/text_colors.py"))
    + ", run_name='__main__')\n"
)


PROBE += (
    "\nrunpy.run_path("
    + repr(str(Path(__file__).resolve().parent.parent / "examples/fixed_layout.py"))
    + ", run_name='__main__')\n"
)


def verify(python: str) -> None:
    with tempfile.TemporaryDirectory(prefix="document-core-probe-") as directory:
        subprocess.run([str(Path(python).absolute()), "-I", "-c", PROBE], cwd=directory, check=True)
    verify_math(python)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", required=True, help="Python in an empty environment with only the core wheel installed")
    verify(parser.parse_args().python)
