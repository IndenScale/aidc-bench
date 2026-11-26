"""Continuous collision intervals for a rectangular load rotating about its centre."""

import math
from itertools import pairwise


def _boundary_angles(constant, cosine, sine):
  # tan(theta / 2) maps the quarter turn to [0,1]. Each separating-axis
  # inequality can change sign only at a real root of this quadratic.
  a, b, c = constant - cosine, 2 * sine, constant + cosine
  scale = max(abs(a), abs(b), abs(c))
  if not scale:
    return []
  a, b, c = a / scale, b / scale, c / scale
  if not a:
    roots = [-c / b] if b else []
  else:
    disc = b * b - 4 * a * c
    if disc < 0:
      return []
    q = -.5 * (b + math.copysign(math.sqrt(disc), b))
    roots = [q / a, c / q] if q else [0.]
  return [2 * math.atan(root) for root in roots if 0 < root < 1]


def overlap_angles(length, width, local_bounds, tolerance):
  """Angles in degrees from the incoming heading towards the outgoing heading.

  The fixed rectangle is expressed on the incoming and outgoing unit axes,
  relative to the pivot. Returns interior witnesses and limiting angles.
  """
  lo, hi = local_bounds
  if (not all(math.isfinite(v) for v in (length, width, tolerance, *lo, *hi)) or min(length, width) <= 0
      or tolerance < 0 or len(lo) != 2 or len(hi) != 2 or any(a >= b for a, b in zip(lo, hi, strict=True))):
    raise ValueError("Expected positive rectangles, finite coordinates and nonnegative tolerance.")
  dx, dy = [(a + b) / 2 for a, b in zip(lo, hi, strict=True)]
  h, k = [(b - a) / 2 for a, b in zip(lo, hi, strict=True)]
  a, b = length / 2, width / 2
  axes = [(h - abs(dx) - tolerance, a, b), (k - abs(dy) - tolerance, b, a)]
  for sign in (-1, 1):
    axes.append((a - tolerance, h + sign * dx, k + sign * dy))
    axes.append((b - tolerance, k + sign * dy, h - sign * dx))
  cuts = {0., math.pi / 2}
  for terms in axes:
    cuts.update(_boundary_angles(*terms))
  hits = []
  for start, end in pairwise(sorted(cuts)):
    mid = (start + end) / 2
    co, si = math.cos(mid), math.sin(mid)
    if all(math.fsum((constant, cosine * co, sine * si)) > 0 for constant, cosine, sine in axes):
      hits.append({"angle_bounds_deg": [math.degrees(start), math.degrees(end)], "witness_deg": math.degrees(mid)})
  return hits
