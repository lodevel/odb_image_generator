"""Rout layer parsing: board cutouts milled inside the outline.

Many exporters write the board's outline to the profile but its internal
cutouts only to the rout layer (matrix ``TYPE=ROUT``), as a chain of ``L``
(and ``A``) features the router follows. A chain that closes on itself and
lies inside the board outline is a cutout; the chain that follows the
outline itself is not.
"""

from typing import List

from .profile import Point, arc_points

_TOL_MM = 1e-3


def _same(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) <= _TOL_MM and abs(a[1] - b[1]) <= _TOL_MM


def parse_rout_chains(feature_txt: str) -> List[List[Point]]:
    """Connected paths of the rout layer's ``L``/``A`` features, in file
    order: a feature that starts where the previous one ended continues the
    path, any other starts a new one."""
    chains: List[List[Point]] = []
    cur: List[Point] = []
    for line in feature_txt.splitlines():
        parts = line.split(";", 1)[0].split()
        if not parts or parts[0] not in ("L", "A"):
            continue
        try:
            start = (float(parts[1]), float(parts[2]))
            end = (float(parts[3]), float(parts[4]))
            if parts[0] == "A":
                if len(parts) < 7:
                    continue
                center = (float(parts[5]), float(parts[6]))
                clockwise = len(parts) < 11 or parts[10].upper() == "Y"
                seg = arc_points(start, end, center, clockwise)
            else:
                seg = [start, end]
        except (ValueError, IndexError):
            continue
        if cur and _same(cur[-1], seg[0]):
            cur.extend(p for p in seg[1:] if not _same(p, cur[-1]))
        else:
            if cur:
                chains.append(cur)
            cur = [seg[0]] + [p for p in seg[1:] if not _same(p, seg[0])]
    if cur:
        chains.append(cur)
    return chains


def _inside(pt: Point, poly: List[Point]) -> bool:
    """Even-odd point-in-polygon test."""
    x, y = pt
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def rout_cutouts(
    chains: List[List[Point]], outline: List[Point]
) -> List[List[Point]]:
    """The closed chains that lie strictly inside *outline*: the cutouts.

    The chain tracing the outline itself fails the bounding-box test (it
    reaches the outline's extremes) and is dropped, as are open chains."""
    if len(outline) < 3:
        return []
    oxs = [p[0] for p in outline]
    oys = [p[1] for p in outline]
    oxmin, oxmax, oymin, oymax = min(oxs), max(oxs), min(oys), max(oys)
    cutouts: List[List[Point]] = []
    for chain in chains:
        if len(chain) < 4 or not _same(chain[0], chain[-1]):
            continue
        xs = [p[0] for p in chain]
        ys = [p[1] for p in chain]
        if not (min(xs) > oxmin + _TOL_MM and max(xs) < oxmax - _TOL_MM
                and min(ys) > oymin + _TOL_MM and max(ys) < oymax - _TOL_MM):
            continue
        if all(_inside(p, outline) for p in chain):
            cutouts.append(chain)
    return cutouts
