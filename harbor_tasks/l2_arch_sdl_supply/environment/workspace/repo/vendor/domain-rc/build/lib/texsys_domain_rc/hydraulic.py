"""Hydraulic paths and volume balance under declared operating conditions."""

import math
from collections import defaultdict, deque
from itertools import pairwise


def pipe_stations(point, points, tolerance_m):
  """Project a point onto an oriented centreline and coalesce coincident vertex stations."""
  offset = 0.
  stations = []
  for start, end in pairwise(points):
    direction = tuple(b - a for a, b in zip(start, end, strict=True))
    length = math.hypot(*direction)
    if length == 0:
      continue
    unit = tuple(delta / length for delta in direction)
    along = math.fsum((value - origin) * component for value, origin, component in zip(point, start, unit, strict=True))
    along = min(length, max(0., along))
    nearest = tuple(origin + along * component for origin, component in zip(start, unit, strict=True))
    if math.dist(point, nearest) <= tolerance_m:
      station = offset + along
      if not stations or station - stations[-1] > tolerance_m:
        stations.append(station)
    offset += length
  return stations


def pipe_station(point, points, tolerance_m):
  stations = pipe_stations(point, points, tolerance_m)
  return stations[0] if len(stations) == 1 else None


def terminal_network(topology, origins, terminal, junctions):
  upstream = origins | junctions
  downstream = junctions | {terminal}
  return {
    "supply": {key: (a, b) for key, (a, b) in topology["supply"].items() if a in upstream and b in downstream},
    "return": {key: (a, b) for key, (a, b) in topology["return"].items() if a in downstream and b in upstream},
  }


def find_path(links, starts, ends, removed=None):
  adjacent = defaultdict(list)
  for key, (a, b) in links.items():
    if key != removed:
      adjacent[a].append((b, key))
  pending = deque(sorted(starts))
  paths = {name: [] for name in starts}
  while pending:
    name = pending.popleft()
    if name in ends:
      return paths[name]
    for neighbor, key in adjacent[name]:
      if neighbor not in paths:
        paths[neighbor] = [*paths[name], key]
        pending.append(neighbor)
  return None


def round_trip(topology, sources, terminal, removed=None):
  for source in sorted(sources):
    supply = find_path(topology["supply"], {source}, {terminal}, removed)
    returned = find_path(topology["return"], {terminal}, {source}, removed)
    if supply is not None and returned is not None:
      return source, supply, returned
  return None, None, None


VOLUME_TOLERANCE_M3 = 1e-9


def replay_storage(capacity, initial, intervals):
  """Integrate storage in m³ with piecewise constant inflow and discharge in m³/s over seconds."""
  stored, peak = min(initial, capacity), min(initial, capacity)
  excess = max(0., initial - capacity)
  first_overflow = 0. if excess > 0 else None
  time = 0.
  history = []
  for duration, inflow, discharge in intervals:
    rate = inflow - discharge
    change = rate * duration
    candidate = stored + change
    after = min(capacity, max(0., candidate))
    overflow = max(0., candidate - capacity)
    # When the tray runs dry, actual discharge is capped by the water available.
    actual_discharge = min(discharge * duration, stored + inflow * duration)
    if first_overflow is None and overflow > 0:
      first_overflow = time + max(0., (capacity - stored) / rate)
    history.append({"start_s": time, "end_s": time + duration,
                    "inflow_lps": inflow * 1000, "available_discharge_lps": discharge * 1000,
                    "storage_start_m3": stored, "storage_end_m3": after,
                    "inflow_m3": inflow * duration, "discharged_m3": actual_discharge, "overflow_m3": overflow})
    stored, peak = after, max(peak, after)
    excess += overflow
    time += duration
  residual = math.fsum((initial, *(row["inflow_m3"] for row in history),
                        *(-row["discharged_m3"] for row in history), -excess, -stored))
  return {"peak_storage_m3": peak, "final_storage_m3": stored, "overflow_m3": excess,
          "first_overflow_s": first_overflow if excess > VOLUME_TOLERANCE_M3 else None,
          "mass_balance_residual_m3": residual, "intervals": history}
