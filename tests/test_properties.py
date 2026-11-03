"""Strict property operations coexist with the saved permissive API."""

import pytest

from opendoc_model import ArtifactLimitError, DocumentLimits
from opendoc_model.properties import (
    ImageProperties,
    ParagraphProperties,
    SectionProperties,
    TableCellProperties,
    TableProperties,
    TableRowProperties,
    TextStyleProperties,
    VersionedProperties,
)


@pytest.mark.parametrize(
    "cls,key,input_,expected",
    [
        (SectionProperties, "gutter_pt", " 2.5 ", 2.5),
        (ParagraphProperties, "numbering_level", " +03 ", 3),
        (TextStyleProperties, "priority", "-2", -2),
        (TextStyleProperties, "base_style_id", "body", "body"),
        (TextStyleProperties, "left_indent_pt", 0, 0.0),
        (ImageProperties, "behind_doc", " OFF ", False),
        (ImageProperties, "layout_in_cell", 1, True),
        (ImageProperties, "blip_effects_xml", ["xml"], ["xml"]),
        (TableProperties, "grid_widths_twips", ["2", 3], [2, 3]),
        (TableRowProperties, "repeat_header", "yes", True),
        (TableCellProperties, "margins_twips", {"top": "0"}, {"top": 0}),
        (TableCellProperties, "fill", "", ""),
    ],
)
def test_normalized_writes_and_nonmutating_reads(cls, key, input_, expected):
    bag = cls({key: input_, "unknown": {"data": [1]}})
    assert bag.get_typed(key) == expected
    assert bag[key] == input_
    bag.set_typed(key, input_)
    assert bag[key] == expected
    assert bag["unknown"] == {"data": [1]}


@pytest.mark.parametrize(
    "cls",
    [
        SectionProperties,
        ParagraphProperties,
        TextStyleProperties,
        ImageProperties,
        TableProperties,
        TableRowProperties,
        TableCellProperties,
    ],
)
def test_all_declared_fields_have_a_typed_path_and_none_semantics(cls):
    bag = cls()
    for name in dir(cls):
        if isinstance(getattr(cls, name), property):
            assert bag.get_typed(name) is None
            bag.set_typed(name, None)
            assert name in bag and bag[name] is None
            del bag[name]
            assert bag.get_typed(name) is None


@pytest.mark.parametrize(
    "cls,key,value",
    [
        (ImageProperties, "behind_doc", "perhaps"),
        (ImageProperties, "behind_doc", 2),
        (ImageProperties, "behind_doc", []),
        (ParagraphProperties, "numbering_id", True),
        (ParagraphProperties, "numbering_id", 2.0),
        (ParagraphProperties, "numbering_id", "2.0"),
        (ParagraphProperties, "numbering_id", "٣"),
        (ParagraphProperties, "left_indent_pt", True),
        (ParagraphProperties, "left_indent_pt", "nan"),
        (ParagraphProperties, "left_indent_pt", float("inf")),
        (ParagraphProperties, "style_name", 12),
        (TableProperties, "grid_widths_twips", (1, 2)),
        (TableProperties, "grid_widths_twips", [True]),
        (TableCellProperties, "margins_twips", {1: 2}),
        (ImageProperties, "blip_effects_xml", [1]),
        (ImageProperties, "wrap_polygon", {}),
        (ImageProperties, "wrap_polygon", {"edited": False, "points": [{"x": True, "y": 2}]}),
    ],
)
def test_conversion_errors_are_located_and_assignment_is_atomic(cls, key, value):
    bag = cls({key: None, "unknown": "retained"})
    with pytest.raises(ValueError, match=key):
        bag.set_typed(key, value)
    assert bag.to_dict() == {key: None, "unknown": "retained"}
    bag[key] = value
    with pytest.raises(ValueError, match=key):
        bag.get_typed(key)


def test_container_outputs_and_polygon_extensions_are_independent():
    polygon = {"edited": False, "points": [{"x": 1, "y": 2, "custom": [3]}], "custom": {"a": [1]}}
    bag = ImageProperties()
    bag.set_typed("wrap_polygon", polygon)
    polygon["points"][0]["custom"].append(4)
    returned = bag.get_typed("wrap_polygon")
    returned["custom"]["a"].append(2)
    assert bag["wrap_polygon"] == {"edited": False, "points": [{"x": 1, "y": 2, "custom": [3]}], "custom": {"a": [1]}}


def test_unknown_fields_remain_mapping_values():
    bag = VersionedProperties({"custom": [1]})
    for key in ("custom", "missing", 1, [], None):
        with pytest.raises(ValueError):
            bag.get_typed(key)
        with pytest.raises(ValueError):
            bag.set_typed(key, 2)
    assert bag.to_dict() == {"custom": [1]}


def test_legacy_getters_and_mapping_writes_keep_their_contract():
    image = ImageProperties(behind_doc="perhaps", name=12, wrap_polygon={})
    assert image.behind_doc is True and image.name == "12" and image.wrap_polygon == {}
    table = TableProperties(grid_widths_twips=[1.9])
    assert table.grid_widths_twips == [1]
    assert TableProperties().grid_widths_twips == []
    with pytest.raises(TypeError):
        _ = ParagraphProperties(numbering_id={}).numbering_id
    with pytest.raises(AttributeError):
        image.behind_doc = False


def test_property_budgets_and_cycles_fail_before_mutation():
    bag = TableProperties(grid_widths_twips=[1])
    with pytest.raises(ArtifactLimitError):
        bag.set_typed("grid_widths_twips", [1, 2], limits=DocumentLimits(max_nodes=2))
    assert bag["grid_widths_twips"] == [1]
    with pytest.raises(ValueError, match="limits"):
        bag.get_typed("grid_widths_twips", limits=3)
    cyclic = []
    cyclic.append(cyclic)
    with pytest.raises(ValueError, match="cyclic"):
        bag.set_typed("grid_widths_twips", cyclic)
