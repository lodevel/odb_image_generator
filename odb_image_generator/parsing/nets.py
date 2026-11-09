"""ODB++ EDA netlist parsing."""

from typing import List


def parse_eda_nets(eda_txt: str) -> List[str]:
    """Return net names from an ODB++ ``eda/data`` file, indexed by net number.

    The EDA netlist lists one ``NET <name>`` record per net in net-number
    order (net 0 first, conventionally ``$NONE$``). A pin's ``net_num`` in a
    ``components`` file indexes directly into this list. Comment lines
    (``# ...``, including ``#NET <n>`` markers) and the per-net feature/attribute
    records (``SNT``, ``FID``, ``FTR``, …) are ignored — only the ``NET``
    records advance the index, which is what the components ``net_num``
    references.
    """
    names: List[str] = []
    for raw in eda_txt.splitlines():
        line = raw.strip()
        if line.startswith("NET "):          # leading '#' (comments) excluded
            names.append(line[4:].strip())
    return names
