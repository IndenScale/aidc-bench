"""Capacity of a directed flow network, with an auditable minimum cut."""

import math
from collections import defaultdict, deque
from fractions import Fraction

from texsys.evidence import canonical_digest

from .netlist import _text


def flow_capacity(edges, source, sink):
  """Edmonds–Karp residual flow. Edge identities also distinguish parallel arcs."""
  graph = defaultdict(list)
  residual = []
  exact = any(isinstance(edge[2], Fraction) for edge in edges)
  for start, end, capacity in edges:
    if not isinstance(capacity, Fraction) and (type(capacity) not in (float, int) or not math.isfinite(capacity)):
      raise ValueError("Flow capacities must be finite and nonnegative.")
    if capacity < 0:
      raise ValueError("Flow capacities must be finite and nonnegative.")
    i = len(residual)
    graph[start].append((end, i))
    graph[end].append((start, i + 1))
    residual.extend((capacity, 0 if exact else 0.))
  if source == sink:
    raise ValueError("Supply and receiving nodes must be distinct.")
  while True:
    parent = {source: None}
    queue = deque([source])
    while queue and sink not in parent:
      node = queue.popleft()
      for other, i in graph[node]:
        if residual[i] > 0 and other not in parent:
          parent[other] = (node, i)
          queue.append(other)
    if sink not in parent:
      break
    path = []
    node = sink
    while node != source:
      node, i = parent[node]
      path.append(i)
    increment = min(residual[i] for i in path)
    for i in path:
      residual[i] -= increment
      residual[i ^ 1] += increment
  cut = [i for i, (a, b, _) in enumerate(edges) if a in parent and b not in parent]
  total = sum if exact else math.fsum
  return {"capacity": total(edges[i][2] for i in cut), "cut": cut,
          "edge_flows": residual[1::2]}

def airflow_capacity(network):
  """Replay a project-issued geometric capacity network with m³/s arc capacities."""
  if type(network.get("schema_version")) is not int or network["schema_version"] != 1 or network.get("kind") != "airflow-capacity-network":
    raise ValueError("Expected a version 1 airflow-capacity-network.")
  context = {key: _text(network[key]) for key in ("scene_digest", "frame", "zone", "case")}
  arcs = [(_text(row["from"]), _text(row["to"]), row["capacity_m3_s"]) for row in network["arcs"]]
  solution = flow_capacity(arcs, _text(network["inlet"]), _text(network["delivery"]))
  return {"schema_version": 1, "kind": "airflow-capacity", "domain": "hvac", **context,
          "network_digest": canonical_digest(network), "routable_m3_s": solution["capacity"],
          "cut_indices": solution["cut"], "arc_flows_m3_s": solution["edge_flows"], "unresolved": []}
