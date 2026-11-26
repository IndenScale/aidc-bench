"""Coverage of a rectangle by disks with independent radii (metres)."""

import math


def _clip_cell(polygon, site, radius, other, other_radius):
  """Clip to points whose squared distance minus squared radius favours site."""
  dx, dy = other[0] - site[0], other[1] - site[1]
  if dx == dy == 0:
    return polygon if radius >= other_radius else []
  offset = (dx * dx + dy * dy + (radius - other_radius) * (radius + other_radius)) / 2

  def side(point):
    return offset - dx * (point[0] - site[0]) - dy * (point[1] - site[1])

  result = []
  previous = polygon[-1]
  u = side(previous)
  for point in polygon:
    v = side(point)
    if (u < 0 < v) or (v < 0 < u):
      t = u / (u - v)
      result.append(tuple(a + t * (b - a) for a, b in zip(previous, point, strict=True)))
    if v >= 0:
      result.append(point)
    previous, u = point, v
  return result


def disk_coverage(low, high, sites, tolerance_m=0.0):
  """Return the controlling vertex of each nonempty power cell and for the whole rectangle.

  The power function on each convex cell is a squared distance minus a constant,
  so its maximum is attained at a vertex. The largest cell maximum decides union
  coverage. Different radii need not select the Euclidean-nearest site.
  """
  width, height = (b - a for a, b in zip(low, high, strict=True))
  if not (math.isfinite(width) and width > 0 and math.isfinite(height) and height > 0
          and math.isfinite(tolerance_m) and tolerance_m >= 0):
    raise ValueError("Expected a finite rectangle of positive area and nonnegative distance tolerance.")
  rectangle = [(0., 0.), (width, 0.), (width, height), (0., height)]
  local = {}
  for key, (center, radius) in sorted(sites.items()):
    if len(center) != 2 or not all(map(math.isfinite, center)) or not math.isfinite(radius) or radius < 0:
      raise ValueError("Expected a finite disk center and nonnegative radius.")
    local[key] = ((center[0] - low[0], center[1] - low[1]), radius + tolerance_m)

  cells = {}
  for key, (site, radius) in local.items():
    polygon = rectangle
    for other, (center, other_radius) in local.items():
      if other != key:
        polygon = _clip_cell(polygon, site, radius, center, other_radius)
        if not polygon:
          break
    if polygon:
      vertex = max(polygon, key=lambda point: math.dist(site, point))
      distance = math.dist(site, vertex)
      cells[key] = {"point_xy_m": [a + b for a, b in zip(low, vertex, strict=True)],
                    "distance_m": distance, "maximum_m": sites[key][1],
                    "power_m2": (distance - radius) * (distance + radius)}
  controlling = max(cells, key=lambda key: cells[key]["power_m2"], default=None)
  return {"controlling_site": controlling, "cells": cells}
