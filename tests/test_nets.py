"""Tests for ODB++ EDA netlist parsing (parse_eda_nets)."""

import os
import sys

# Make the package importable when run directly or via pytest (no conftest here).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from odb_image_generator.parsing.nets import parse_eda_nets  # noqa: E402


def test_parses_net_records_in_index_order():
    eda = "\n".join([
        "# 09-01-26 14:35:39",
        "HDR Altium Designer file",
        "UNITS=MM",
        "#NET 0",
        "NET $NONE$",
        "SNT TOP T 16 6",
        "FID C 19 2975",
        "#NET 1",
        "NET NetD16_A",
        "#NET 2",
        "NET +LOW_28V",
    ])
    nets = parse_eda_nets(eda)
    assert nets == ["$NONE$", "NetD16_A", "+LOW_28V"]
    assert nets[0] == "$NONE$"           # net 0 is the unconnected pseudo-net


def test_ignores_comment_and_feature_lines():
    # '#NET n' markers are comments; SNT/FID are per-net feature records.
    eda = "# NET 5\n#NET 6\nSNT TOP T 1 2\nFID C 1 2"
    assert parse_eda_nets(eda) == []


def test_empty_or_missing_eda_is_graceful():
    assert parse_eda_nets("") == []
    assert parse_eda_nets("\n\n   \n") == []


if __name__ == "__main__":  # allow `python tests/test_nets.py`
    test_parses_net_records_in_index_order()
    test_ignores_comment_and_feature_lines()
    test_empty_or_missing_eda_is_graceful()
    print("all net-parse tests passed")
