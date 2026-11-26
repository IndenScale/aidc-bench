"""Supply quality metrics across measured phases or poles."""

import math
from collections import defaultdict, deque
from graphlib import TopologicalSorter

from .service_intervals import continuous_service_bounds


def voltage_deviation_pct(interval_v, nominal_v):
  if nominal_v <= 0:
    raise ValueError("Nominal voltage must be positive.")
  return [None if value is None else (value / nominal_v - 1) * 100 for value in interval_v]


def interval_envelope(intervals):
  values = list(intervals)
  return [min((low for low, _ in values if low is not None), default=None),
          max((high for _, high in values if high is not None), default=None)]


def interruption_bounds(window_ms, segments, edge_error_ms):
  """Bound the longest terminal interruption using continuous recorder state intervals."""
  def finite(value):
    return type(value) in (int, float) and math.isfinite(value)

  if (len(window_ms) != 2 or not all(finite(v) for v in window_ms) or window_ms[0] >= window_ms[1]
      or not finite(edge_error_ms) or edge_error_ms < 0):
    raise ValueError("Invalid observation window or edge timing error.")
  states = []
  for begin, end, state in segments:
    if not all(finite(v) for v in (begin, end)) or state not in ("powered", "interrupted"):
      raise ValueError("Expected terminal state intervals.")
    states.append((begin, end, state == "powered"))
  lower, upper, powered, interrupted, bracketed = continuous_service_bounds(window_ms, states, edge_error_ms)
  return {"longest_bounds_ms": [lower, upper], "confirmed_outages_ms": interrupted,
          "confirmed_powered_ms": powered, "bracketed": bracketed}


def spectrum_coverage(scans, required):
  """Union of scan intervals inside each requested band, with any missing ranges in MHz."""
  gaps = []
  for low, high in required:
    if low >= high:
      raise ValueError("Frequency bands must have increasing bounds.")
    cursor = low
    missing = []
    for start, end in sorted((a, b) for a, b in scans if low <= a < b <= high):
      if start > cursor:
        missing.append([cursor, start])
      cursor = max(cursor, end)
    if cursor < high:
      missing.append([cursor, high])
    gaps.append(missing)
  return gaps


def distribution_paths(parents, sources, memberships, busways):
  """Track UPS groups and any unprotected or undistributed path to energized nodes."""
  groups, no_ups, no_distribution, energized = {}, set(), set(), set()
  for node in TopologicalSorter(parents).static_order():
    upstream = parents[node] & energized
    if node not in sources and not upstream:
      continue
    energized.add(node)
    groups[node] = set().union(*(groups[parent] for parent in upstream))
    if node in memberships:
      groups[node].add(memberships[node])
    elif node in sources or upstream & no_ups:
      no_ups.add(node)
    if node not in busways and (node in sources or upstream & no_distribution):
      no_distribution.add(node)
  return groups, no_ups, no_distribution


def supplying_ups(parents, electrical):
  """Return reachable last UPS identities, retaining None for a direct supply path."""
  states = {}
  for key in TopologicalSorter(parents).static_order():
    inherited = {value for parent in parents[key] for value in states[parent]}
    kind = electrical[key]
    states[key] = {None} if kind == "source" else {key} if kind == "ups" and inherited else inherited
  return states


def reachable_paths(starts, graph, skip=()):
  """Record a path predecessor for every reachable node, optionally excluding equipment."""
  previous = dict.fromkeys(starts)
  queue = deque(starts)
  while queue:
    at = queue.popleft()
    for name in sorted(graph.get(at, ())):
      if name not in previous and name not in skip:
        previous[name] = at
        queue.append(name)
  return previous


def energized_feeder_network(load, edges, enabled, incoming, sources):
  """Topology reachable upstream in one switching position, with inactive and unrelated routes."""
  upstream = defaultdict(set)
  for key in enabled:
    start, end = edges[key]
    upstream[end].add(start)
  ancestors = reachable_paths([load], upstream)
  return {"ancestors": sorted(ancestors), "roots": sorted(ancestors.keys() & sources),
          "multiple_upstream": {key: sorted(upstream[key]) for key in sorted(ancestors) if len(upstream[key]) > 1},
          "unrelated_routes": [key for key in enabled if edges[key][1] not in ancestors],
          "inactive_upstream_routes": sorted({route for key in ancestors for route in incoming.get(key, {}).values()}
                                           - set(enabled))}


def terminal_transfer_paths(routes, hops, load, transfer, incoming, outgoing, is_switch, allowed_loads):
  """Observe the two sources, common upstream equipment and the physical last transfer point."""
  first, second = hops
  sources = [first[0], second[0]]
  shared = sorted(set(first[:-2]).intersection(second[:-2]))
  at_terminal = is_switch and first[-2] == second[-2] == transfer
  if at_terminal:
    entries = {route[-2] for route in routes}
    at_terminal = (len(entries) == 2 and entries == set(incoming[transfer].values())
                   and set(incoming[load]) == {transfer} and outgoing[transfer].keys() <= allowed_loads)
  return sources, shared, at_terminal


def protective_path(path, feeders):
  """Observe conductor functions along an ordered feeder path without assuming internal bonds."""
  missing, nonseparate, no_neutral, recombined, conflicts, unknown = [], [], [], [], [], []
  previous = set()
  for key in path:
    row = feeders.get(key, {})
    roles = set(row.get("conductors", ()))
    complete = row.get("complete") is True
    if not complete:
      unknown.append(key)
    if complete and not roles & {"PE", "PEN"}:
      missing.append(key)
    if "PEN" in roles or (complete and "PE" not in roles):
      nonseparate.append(key)
    if complete and "N" not in roles:
      no_neutral.append(key)
    if "PE" in previous and "PEN" in roles:
      recombined.append(key)
    conflicts.extend(row.get("conflicts", ()))
    previous = roles
  return {"missing_protection": missing, "non_separate_conductor_routes": nonseparate,
          "routes_without_neutral": no_neutral, "recombined_routes": recombined,
          "terminal_role_conflicts": conflicts, "unresolved_routes": unknown}
