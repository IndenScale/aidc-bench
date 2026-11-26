"""Minimum of a bilinear temperature field clipped to a rectangular surface patch."""

import math
from bisect import bisect_left


def _number(value):
  if type(value) not in (float, int) or not math.isfinite(value):
    raise ValueError("Expected a finite surface-field coordinate or temperature.")
  return value


def _axis(values):
  if not isinstance(values, list) or len(values) < 2:
    raise ValueError("A rectilinear field needs at least two nodes on each axis.")
  coords = [_number(v) for v in values]
  if any(b <= a for a, b in zip(coords, coords[1:])):
    raise ValueError("Surface-field coordinates must be strictly increasing.")
  return coords


def _weights(nodes, x):
  index = bisect_left(nodes, x)
  if nodes[index] == x:
    return [(index, 1.)]
  t = (x - nodes[index - 1]) / (nodes[index] - nodes[index - 1])
  return [(index - 1, 1 - t), (index, t)]


def _cuts(nodes, interval):
  start, end = interval
  if not _number(start) < _number(end):
    raise ValueError("Invalid surface patch extent.")
  low, high = max(nodes[0], start), min(nodes[-1], end)
  return sorted({low, high, *(v for v in nodes if low < v < high)}) if low <= high else []


def surface_minimum(field, extent):
  """Return the lowest known candidate and whether the full patch minimum was resolved."""
  if field.get("interpolation") != "bilinear":
    raise ValueError("Expected a rectilinear bilinear nodal surface field.")
  u, v = _axis(field["u_m"]), _axis(field["v_m"])
  values = field["temperatures_c"]
  if not isinstance(values, list) or len(values) != len(v):
    raise ValueError("Temperature rows must correspond to the v coordinates.")
  for row in values:
    if not isinstance(row, list) or len(row) != len(u):
      raise ValueError("Temperature columns must correspond to the u coordinates.")
    for value in row:
      if value is not None:
        _number(value)
  complete = all(nodes[0] <= lo < hi <= nodes[-1] for nodes, (lo, hi) in zip((u, v), extent, strict=True))
  # On each clipped cell a bilinear field attains its minimum at a corner.
  u_weights = [(x, _weights(u, x)) for x in _cuts(u, extent[0])]
  v_weights = [(y, _weights(v, y)) for y in _cuts(v, extent[1])]
  minimum = point = None
  known = missing = 0
  for x, columns in u_weights:
    for y, rows in v_weights:
      if any(values[j][i] is None for i, _ in columns for j, _ in rows):
        missing += 1
        continue
      value = math.fsum(values[j][i] * wx * wy for i, wx in columns for j, wy in rows)
      known += 1
      if minimum is None or value < minimum:
        minimum, point = value, [x, y]
  return {"lowest_known_c": minimum, "controlling_uv_m": point, "full_grid_extent": complete,
          "complete": complete and missing == 0, "known_corners": known, "unresolved_corners": missing}
