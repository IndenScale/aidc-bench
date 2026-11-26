"""Parallel-beam shadows of orthogonal solid boxes on a vertical rectangular opening."""

import math
from itertools import product


def _cross(a, b, p):
  return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def _hull(points):
  points = sorted(set(points))

  def chain(ordered):
    result = []
    for p in ordered:
      while len(result) >= 2 and _cross(result[-2], result[-1], p) <= 0:
        result.pop()
      result.append(p)
    return result[:-1]

  return chain(points) + chain(reversed(points))


def _clip(poly, a, b, inside):
  result = []
  for i, end in enumerate(poly):
    start = poly[i - 1]
    u, v = _cross(a, b, start), _cross(a, b, end)
    if (u < 0 < v) or (v < 0 < u):
      t = u / (u - v)
      result.append(tuple(x + t * (y - x) for x, y in zip(start, end, strict=True)))
    if (inside and v >= 0) or (not inside and v <= 0):
      result.append(end)
  return result


def _area(poly):
  return abs(math.fsum(_cross(poly[0], poly[i - 1], poly[i]) for i in range(2, len(poly)))) / 2


def _subtract(poly, shadow):
  """Keep disjoint convex pieces outside the shadow, clipping one half-plane at a time."""
  pieces = []
  for i, end in enumerate(shadow):
    start = shadow[i - 1]
    if start == end:
      continue
    outside = _clip(poly, start, end, False)
    if _area(outside) > 0:
      pieces.append(outside)
    poly = _clip(poly, start, end, True)
    if _area(poly) == 0:
      break
  return pieces


def _shadow(box, axis, face, sign, direction, origin, opening):
  lo, hi = box
  near, far = sorted(sign * (point[axis] - face) for point in (lo, hi))
  if far <= 0:
    return []
  transverse = 1 - axis
  normal = sign * direction[axis]
  points = [(y - origin[0] - depth * direction[transverse] / normal,
             z - origin[1] - depth * direction[2] / normal)
            for depth, y, z in product((max(0, near), far), (lo[transverse], hi[transverse]), (lo[2], hi[2]))]
  poly = _hull(points)
  for i, end in enumerate(opening):
    poly = _clip(poly, opening[i - 1], end, True)
  return poly if _area(poly) > 0 else []


def opening_exposure(axis, face, sign, extent, toward_sun, obstacles):
  """Return beam-visible area bounds for the listed objects, before glazing.

  Axis and sign specify the outward normal in world coordinates. Each obstacle
  supplies two world bounds and opaque=True, False or None. Polygons in the
  result use the opening's lower transverse/elevation corner as their origin.
  """
  if len(toward_sun) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in toward_sun):
    raise ValueError("Sun direction requires three finite world coordinates.")
  norm = math.hypot(*toward_sun)
  if not norm or not math.isfinite(norm):
    raise ValueError("Sun direction has an invalid magnitude.")
  direction = tuple(v / norm for v in toward_sun)
  (u, v), (z, top) = extent
  width, height = v - u, top - z
  if axis not in (0, 1) or sign not in (-1, 1) or min(height, width) <= 0:
    raise ValueError("Expected a vertical rectangular opening with a signed horizontal normal.")
  opening = [(0, 0), (width, 0), (width, height), (0, height)]
  area = width * height
  normal = sign * direction[axis]
  result = {"aperture_area_m2": area, "origin_m": [u, z], "toward_sun_unit": direction, "shadows": {}}
  if normal <= 0 or direction[2] < 0:
    return {**result, "incidence": "no-direct-beam", "visible_lower_m2": 0., "visible_upper_m2": 0.}
  if normal < 1e-10:
    return {**result, "incidence": "grazing", "visible_lower_m2": 0., "visible_upper_m2": area}
  certain, possible = [opening], [opening]
  for key, (bounds, opaque) in sorted(obstacles.items()):
    if opaque is False:
      continue
    shadow = _shadow(bounds, axis, face, sign, direction, (u, z), opening)
    if shadow:
      result["shadows"][key] = {"polygon_m": shadow, "opaque": opaque}
      possible = [piece for poly in possible for piece in _subtract(poly, shadow)]
      if opaque is True:
        certain = [piece for poly in certain for piece in _subtract(poly, shadow)]
  return {**result, "incidence": "front", "visible_lower_m2": min(area, math.fsum(map(_area, possible))),
          "visible_upper_m2": min(area, math.fsum(map(_area, certain)))}
