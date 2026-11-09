"""Tests for ODB++ component-property capture (CMP attrs + PRP records).

Properties are dumped raw (name->value) so the LLM can identify ICs; the parser
never interprets which field is a part number.
"""

import os
import sys

# Make the package importable when run directly or via pytest (no conftest here).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odb_image_generator.parsing.components import parse_components_file  # noqa: E402


def test_prp_records_captured_with_refdes_and_pins_intact():
    txt = "\n".join([
        "# components file",
        "UNITS=MM",
        "CMP 5 95.2394209 42.46449724 270 N U1",
        "PRP Comment 'TPS62840'",
        "PRP Value '10uF'",
        "PRP Description 'Step-Down Converter'",
        "TOP 0 95.0 42.0 270 N 118 283 1",
        "TOP 1 96.0 43.0 270 N 119 284 5",
    ])
    placements = parse_components_file(txt, "TOP")
    assert len(placements) == 1
    pl = placements[0]

    # Existing behaviour intact: refdes, position, side, pins.
    assert pl.refdes == "U1"
    assert pl.side == "TOP"
    assert pl.x_mm == 95.2394209
    assert pl.rot_deg == 270.0
    assert sorted(p.name for p in pl.pins) == ["1", "5"]
    assert pl.pins[0].net_num == 118

    # PRP name/value pairs captured raw (values may contain spaces).
    assert pl.properties["Comment"] == "TPS62840"
    assert pl.properties["Value"] == "10uF"
    assert pl.properties["Description"] == "Step-Down Converter"


def test_cmp_trailing_attrs_captured():
    txt = "CMP 5 1.0 2.0 0 N R1 ATTR1 ATTR2 ;trailing"
    pl = parse_components_file(txt, "BOTTOM")[0]
    assert pl.refdes == "R1"
    assert pl.properties["_cmp_attrs"] == "ATTR1 ATTR2"


def test_no_properties_means_empty_dict():
    txt = "CMP 5 1.0 2.0 0 N R2"
    pl = parse_components_file(txt, "TOP")[0]
    assert pl.properties == {}


def test_properties_bind_to_current_component_only():
    txt = "\n".join([
        "CMP 5 1.0 2.0 0 N U1",
        "PRP Value 'first'",
        "CMP 5 3.0 4.0 0 N U2",
        "PRP Value 'second'",
    ])
    placements = parse_components_file(txt, "TOP")
    by_ref = {p.refdes: p for p in placements}
    assert by_ref["U1"].properties["Value"] == "first"
    assert by_ref["U2"].properties["Value"] == "second"


def test_malformed_prp_lines_are_skipped_not_raised():
    txt = "\n".join([
        "CMP 5 1.0 2.0 0 N U1",
        "PRP",                       # no name, no value
        "PRP NoQuotes bareword",     # value not single-quoted
        "PRP Good 'kept'",
    ])
    pl = parse_components_file(txt, "TOP")[0]
    assert pl.properties == {"Good": "kept"}


def test_prp_before_any_cmp_is_ignored():
    txt = "\n".join([
        "PRP Orphan 'nope'",
        "CMP 5 1.0 2.0 0 N U1",
    ])
    pl = parse_components_file(txt, "TOP")[0]
    assert pl.properties == {}


if __name__ == "__main__":  # allow `python tests/test_component_properties.py`
    test_prp_records_captured_with_refdes_and_pins_intact()
    test_cmp_trailing_attrs_captured()
    test_no_properties_means_empty_dict()
    test_properties_bind_to_current_component_only()
    test_malformed_prp_lines_are_skipped_not_raised()
    test_prp_before_any_cmp_is_ignored()
    print("all component-property tests passed")
