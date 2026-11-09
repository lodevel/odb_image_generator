"""Tests for the LLM-pull schema-discovery / projection / filter CLI helpers.

Covers the additive --list-property-fields, --fields (column projection) and
--filter (row selection) behaviour built on top of --list. Field names are only
EXAMPLES here (Type, Package, Manufacturer_Reference, ...) — the code never
hardcodes which field means what; discovery + projection is the whole point.
"""

import os
import sys

# Make the package importable when run directly or via pytest (no conftest here).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odb_image_generator.models import Board, Pin, Placement  # noqa: E402
from cli import (  # noqa: E402
    _build_component_list,
    _build_property_fields,
    _parse_fields_spec,
    _parse_filter_spec,
    _parse_refdes_prefix_spec,
    _refdes_matches_prefix,
)


def _board() -> Board:
    """A tiny mixed board: an IC (full props), a resistor, and a test point."""
    return Board(
        outline_pts=[],
        bbox_mm=(0.0, 0.0, 10.0, 10.0),
        placements=[
            Placement(
                refdes="U1", x_mm=1.0, y_mm=1.0, rot_deg=0.0, side="TOP",
                pins=[Pin("2", 0, 0), Pin("1", 0, 0), Pin("10", 0, 0)],
                properties={
                    "Manufacturer_Reference": "TPS62840",
                    "Type": "IC",
                    "Package": "SOT-23",
                    "PLM_Number": "PLM-9921",
                },
            ),
            Placement(
                refdes="R1", x_mm=2.0, y_mm=2.0, rot_deg=0.0, side="BOTTOM",
                pins=[Pin("1", 0, 0), Pin("2", 0, 0)],
                properties={"Type": "Resistor", "Value": "10k"},
            ),
            Placement(
                refdes="TP_AUX_5V0", x_mm=3.0, y_mm=3.0, rot_deg=0.0, side="TOP",
                pins=[Pin("1", 0, 0)],
                properties={"Type": "Pad", "Package": "TP_PAD"},
            ),
        ],
    )


# --- --list-property-fields ------------------------------------------------

def test_list_property_fields_is_sorted_union_of_all_keys():
    fields = _build_property_fields(_board())
    # Union across the three components, sorted, no duplicates.
    assert fields == [
        "Manufacturer_Reference",
        "PLM_Number",
        "Package",
        "Type",
        "Value",
    ]


def test_list_property_fields_empty_board_is_empty_list():
    empty = Board(outline_pts=[], bbox_mm=(0, 0, 1, 1), placements=[])
    assert _build_property_fields(empty) == []


# --- default --list is unchanged (backward-compat) -------------------------

def test_list_components_default_emits_all_properties_unchanged():
    comps = _build_component_list(_board())
    by_ref = {c["refdes"]: c for c in comps}
    # Every property still present (full dict), no projection applied.
    assert by_ref["U1"]["properties"] == {
        "Manufacturer_Reference": "TPS62840",
        "Type": "IC",
        "Package": "SOT-23",
        "PLM_Number": "PLM-9921",
    }
    # Existing shape intact: refdes/side/pins(natural-sorted)/properties.
    assert by_ref["U1"]["side"] == "TOP"
    assert by_ref["U1"]["pins"] == ["1", "2", "10"]
    assert set(by_ref["U1"]) == {"refdes", "side", "pins", "properties"}
    # All three components returned, natural-sorted by refdes.
    assert [c["refdes"] for c in comps] == ["R1", "TP_AUX_5V0", "U1"]


# --- --fields projection ---------------------------------------------------

def test_fields_projects_only_requested_columns_in_order():
    comps = _build_component_list(
        _board(), fields=["Package", "Type"])
    by_ref = {c["refdes"]: c for c in comps}
    # Only the two requested keys, in the requested order.
    assert list(by_ref["U1"]["properties"].keys()) == ["Package", "Type"]
    assert by_ref["U1"]["properties"] == {"Package": "SOT-23", "Type": "IC"}


def test_fields_omits_missing_columns_no_null_padding():
    # R1 has no 'Package'; projecting it must drop the key, not insert null.
    comps = _build_component_list(_board(), fields=["Package"])
    by_ref = {c["refdes"]: c for c in comps}
    assert by_ref["R1"]["properties"] == {}
    assert by_ref["U1"]["properties"] == {"Package": "SOT-23"}


def test_fields_none_keeps_full_properties():
    comps = _build_component_list(_board(), fields=None)
    by_ref = {c["refdes"]: c for c in comps}
    assert "PLM_Number" in by_ref["U1"]["properties"]


# --- --filter row selection ------------------------------------------------

def test_filter_selects_only_matching_rows():
    comps = _build_component_list(_board(), filter_kv=("Type", "Pad"))
    assert [c["refdes"] for c in comps] == ["TP_AUX_5V0"]


def test_filter_value_match_is_case_insensitive():
    comps = _build_component_list(_board(), filter_kv=("Type", "pAd"))
    assert [c["refdes"] for c in comps] == ["TP_AUX_5V0"]


def test_filter_missing_key_excludes_component():
    # 'Value' only exists on R1, so only R1 can match.
    comps = _build_component_list(_board(), filter_kv=("Value", "10k"))
    assert [c["refdes"] for c in comps] == ["R1"]


def test_filter_and_fields_compose():
    comps = _build_component_list(
        _board(), fields=["Package"], filter_kv=("Type", "Pad"))
    assert len(comps) == 1
    assert comps[0]["refdes"] == "TP_AUX_5V0"
    assert comps[0]["properties"] == {"Package": "TP_PAD"}


# --- --refdes-prefix row selection (IC family pre-filter) ------------------

def test_refdes_prefix_keeps_only_ics():
    # U1 is the only U#/IC# refdes; R1 (resistor) and TP_AUX_5V0 (a "U"-less
    # test point) are excluded.
    comps = _build_component_list(_board(), refdes_prefixes=("u", "ic"))
    assert [c["refdes"] for c in comps] == ["U1"]


def test_refdes_prefix_requires_digit_after_prefix():
    # 'U' must be followed by a digit: U1 matches, a hypothetical 'UART_X' does
    # NOT (mirrors the push path's ^(?:U|IC)\d). _refdes_matches_prefix unit:
    assert _refdes_matches_prefix("U1", ("u", "ic")) is True
    assert _refdes_matches_prefix("U11.2", ("u",)) is True
    assert _refdes_matches_prefix("IC3", ("u", "ic")) is True
    assert _refdes_matches_prefix("UART_DE", ("u",)) is False
    assert _refdes_matches_prefix("R1", ("u", "ic")) is False
    # None / empty prefixes -> no filter (always True).
    assert _refdes_matches_prefix("R1", None) is True
    assert _refdes_matches_prefix("R1", ()) is True


def test_refdes_prefix_is_case_insensitive():
    comps = _build_component_list(_board(), refdes_prefixes=("U",))
    # _build_component_list receives already-lowercased prefixes from the spec
    # parser; the matcher itself lowercases the refdes too.
    assert [c["refdes"] for c in comps] == []
    comps = _build_component_list(_board(), refdes_prefixes=("u",))
    assert [c["refdes"] for c in comps] == ["U1"]


def test_refdes_prefix_composes_with_fields_and_filter():
    comps = _build_component_list(
        _board(), fields=["Manufacturer_Reference"],
        filter_kv=("Type", "IC"), refdes_prefixes=("u", "ic"))
    assert len(comps) == 1
    assert comps[0]["refdes"] == "U1"
    assert comps[0]["properties"] == {"Manufacturer_Reference": "TPS62840"}


def test_parse_refdes_prefix_spec_trims_lowercases_dedupes():
    assert _parse_refdes_prefix_spec(" U , IC ,u ") == ("u", "ic")
    assert _parse_refdes_prefix_spec("U,IC") == ("u", "ic")
    assert _parse_refdes_prefix_spec(None) is None
    assert _parse_refdes_prefix_spec("") is None
    assert _parse_refdes_prefix_spec("  ,  ") is None


# --- spec parsers ----------------------------------------------------------

def test_parse_fields_spec_trims_dedupes_preserves_order():
    assert _parse_fields_spec(" a , b ,a, c ") == ["a", "b", "c"]
    assert _parse_fields_spec(None) is None
    assert _parse_fields_spec("") is None
    assert _parse_fields_spec("  ,  ") is None


def test_parse_filter_spec_splits_on_first_equals():
    assert _parse_filter_spec("Type=Pad") == ("Type", "Pad")
    # VALUE may itself contain '='.
    assert _parse_filter_spec("K=a=b") == ("K", "a=b")
    assert _parse_filter_spec(None) is None
    # No '=' -> empty KEY signals malformed to the validator.
    assert _parse_filter_spec("bogus") == ("", "")


if __name__ == "__main__":  # allow `python tests/test_property_discovery.py`
    test_list_property_fields_is_sorted_union_of_all_keys()
    test_list_property_fields_empty_board_is_empty_list()
    test_list_components_default_emits_all_properties_unchanged()
    test_fields_projects_only_requested_columns_in_order()
    test_fields_omits_missing_columns_no_null_padding()
    test_fields_none_keeps_full_properties()
    test_filter_selects_only_matching_rows()
    test_filter_value_match_is_case_insensitive()
    test_filter_missing_key_excludes_component()
    test_filter_and_fields_compose()
    test_parse_fields_spec_trims_dedupes_preserves_order()
    test_parse_filter_spec_splits_on_first_equals()
    print("all property-discovery tests passed")
