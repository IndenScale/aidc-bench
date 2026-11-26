"""Constant simultaneous make-up demand supported by finite tanks and directed flow limits."""

from fractions import Fraction

from .flow_capacity import flow_capacity


def _quantity(value):
  if type(value) not in (int, float):
    raise ValueError("Reserve quantities must be finite nonnegative numbers.")
  result = Fraction(str(value))
  if result < 0:
    raise ValueError("Reserve quantities must be finite nonnegative numbers.")
  return result


def _reserve_network(volumes, demands, links):
  source, sink = object(), object()
  # Every arc has a fixed volume and a volume per hour. At any time horizon the
  # cut volume must cover the full simultaneous demand times that horizon.
  arcs, labels = [], []
  for tank, volume in sorted(volumes.items()):
    arcs.append((source, tank, _quantity(volume), 0))
    labels.append({"tank": tank})
  demand = sum(_quantity(q) for q in demands.values())
  if demand <= 0:
    raise ValueError("At least one plant must have positive make-up demand.")
  for start, end, rate in links:
    arcs.append((start, end, 0, demand if rate is None else _quantity(rate)))
    labels.append({"from": start, "to": end})
  for plant, rate in sorted(demands.items()):
    arcs.append((plant, sink, 0, _quantity(rate)))
    labels.append({"plant": plant})
  return source, sink, arcs, labels, demand


def makeup_endurance(volumes, demands, links):
  """Return maximum hours, an allocation and the limiting cut for a no-inflow emergency."""
  source, sink, arcs, labels, demand = _reserve_network(volumes, demands, links)
  volume = sum(a[2] for a in arcs)
  hours = volume / demand
  limiting = list(range(len(volumes)))
  while True:
    result = flow_capacity([(a, b, fixed + rate * hours) for a, b, fixed, rate in arcs], source, sink)
    if result["capacity"] >= demand * hours:
      break
    limiting = result["cut"]
    fixed = sum(arcs[i][2] for i in limiting)
    rate = sum(arcs[i][3] for i in limiting)
    # A deficient cut gives a strictly smaller rational horizon. There are finitely many cuts.
    hours = fixed / (demand - rate)
  return {"hours": float(hours), "limiting_cut": [labels[i] for i in limiting],
          "allocation": [{**label, "volume_m3": float(flow)} for label, flow in zip(labels, result["edge_flows"], strict=True)]}


def makeup_shortfall(volumes, demands, links, hours):
  """Unserved volumes at a fixed horizon, among allocations maximizing total delivery."""
  horizon = _quantity(hours)
  source, sink, arcs, labels, rate = _reserve_network(volumes, demands, links)
  edges = [(a, b, fixed + q * horizon) for a, b, fixed, q in arcs]
  delivery = flow_capacity(edges, source, sink)
  served = delivery["capacity"]
  shortfall = rate * horizon - served
  bounds = {}
  supply_edges = [edge for edge in edges if edge[1] is not sink]
  outlets = [edge for edge in edges if edge[1] is sink]
  for plant, _, required in outlets:
    least = most = 0
    if shortfall and required:
      # An optimal flow to a subset can be augmented to full throughput without
      # reducing any flow already entering the sink. Prioritize this outlet,
      # then all other outlets, to obtain its two attainable endpoints.
      preferred = flow_capacity([*supply_edges, (plant, sink, required)], source, sink)["capacity"]
      others = [edge for edge in outlets if edge[0] != plant]
      other_delivery = flow_capacity(supply_edges + others, source, sink)["capacity"]
      least = required - preferred
      most = required - (served - other_delivery)
    bounds[plant] = [float(least), float(most)]
  return {"hours": float(horizon), "required_m3": float(rate * horizon), "max_delivered_m3": float(served),
          "shortfall_m3": float(shortfall), "plant_shortfall_bounds_m3": bounds,
          "limiting_cut": [labels[i] for i in delivery["cut"]] if shortfall else []}
