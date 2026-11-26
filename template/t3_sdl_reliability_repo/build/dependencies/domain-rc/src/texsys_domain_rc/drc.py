"""Measure obstacle-limited orthogonal clearances in metres."""

import math
from itertools import pairwise


def section_coordinates(elevation_m, axis, station, left, right):
  point = [station, station, elevation_m]
  point[1 - axis] = left
  end = point.copy()
  end[1 - axis] = right
  return [point, end]


def clear_sections(elevation_m, route, direction, obstacles, extra_cuts=()):
  """Find the connected clear interval containing the declared corridor centerline."""
  across = 1 - direction
  start, end = route.span(direction)
  left, right = route.span(across)
  center = left + (right - left) / 2
  obstacles = {key: box for key, box in obstacles.items() if route.overlaps(box)}
  edges = (*extra_cuts, *(edge for box in obstacles.values() for edge in box.span(direction)))
  cuts = sorted({start, end, *(edge for edge in edges if start < edge < end)})
  for low, high in pairwise(cuts):
    active = {key: box.span(across) for key, box in obstacles.items()
              if box.low[direction] < high and low < box.high[direction]}
    blocking = sorted(key for key, (a, b) in active.items() if a <= center <= b)
    if blocking:
      width, clear_left, clear_right = 0.0, center, center
    else:
      clear_left = max([left, *(b for _, b in active.values() if b < center)])
      clear_right = min([right, *(a for a, _ in active.values() if a > center)])
      width = clear_right - clear_left
      blocking = sorted(key for key, (a, b) in active.items() if b == clear_left or a == clear_right)
    yield {
      "observed_m": width,
      "station_range_m": [low, high],
      "section_xyz_m": section_coordinates(elevation_m, direction, low + (high - low) / 2, clear_left, clear_right),
      "limiting_objects": blocking,
    }


def centerline_width_sections(legs, start_crossing, end_crossing, spaces, obstacles, tolerance_m):
  """Floor section widths along a prescribed orthogonal centerline between two surveyed crossings."""
  sections, gaps = [], []
  first, first_distance = start_crossing
  last, last_distance = end_crossing
  for index in range(first, last + 1):
    a, b, axis = legs[index]
    cross = 1 - axis
    sign = math.copysign(1, b[axis] - a[axis])
    start = a[axis] + sign * first_distance if index == first else a[axis]
    end = a[axis] + sign * last_distance if index == last else b[axis]
    low, high = sorted((start, end))
    pos, floor = a[cross], a[2]
    intervals = {key: box for key, box in spaces.items() if box[0][2] - tolerance_m <= floor < box[1][2] - tolerance_m}
    # The net width is measured in the floor-adjacent walkable band. Upper
    # obstructions and doors are evaluated independently for the equipment body.
    exclusions = {key: box for key, box in obstacles.items() if box[0][2] <= floor + tolerance_m < box[1][2]}
    cuts = sorted({low, high, *(coord[axis] for bounds in (intervals | exclusions).values() for coord in bounds
                                if low < coord[axis] < high)})
    for left, right in pairwise(cuts):
      if right - left <= tolerance_m:
        continue
      mid = (left + right) / 2
      clear = sorted((lo[cross], hi[cross]) for lo, hi in intervals.values() if lo[axis] < mid < hi[axis])
      merged = []
      for lo, hi in clear:
        if merged and lo <= merged[-1][1] + tolerance_m:
          merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
          merged.append((lo, hi))
      corridor = next((part for part in merged if part[0] - tolerance_m <= pos <= part[1] + tolerance_m), None)
      if corridor is None:
        gaps.append({"leg": index, "station_range_m": [left, right]})
        continue
      lo, hi = corridor
      active_obstacles = []
      for identity, (blocker_lo, blocker_hi) in exclusions.items():
        if not blocker_lo[axis] < mid < blocker_hi[axis]:
          continue
        p, q = blocker_lo[cross], blocker_hi[cross]
        if p < corridor[1] and corridor[0] < q:
          active_obstacles.append(identity)
        if p < pos < q:
          lo = hi = pos
        elif q <= pos:
          lo = max(lo, q)
        elif p >= pos:
          hi = min(hi, p)
      sections.append({"leg": index, "station_range_m": [left, right], "width_m": max(0, hi - lo),
                       "floor_obstacles": sorted(active_obstacles), "lateral_interval_m": [lo, hi]})
  return sections, gaps
