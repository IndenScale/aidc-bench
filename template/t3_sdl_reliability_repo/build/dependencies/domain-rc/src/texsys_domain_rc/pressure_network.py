"""Steady power-law pressure network using Pa and m³/h throughout."""

import math

from .hvac import room_pressure


class PressureUnresolved(ValueError):
  """A pressure result requires additional case or boundary evidence."""


def solve_pressures(edges, nets, references, *, absolute_flow_tolerance=1e-6, relative_flow_tolerance=1e-9):
  """Iterate local mass balances. A converged solution must satisfy every nodal residual."""
  incident = {key: {} for key in nets}
  for key, edge in edges.items():
    a, b = edge["ends"]
    for zone, neighbor in ((a, b), (b, a)):
      if zone in nets and edge["coefficient_m3_h_pa_n"] > 0:
        incident[zone][key] = neighbor
  anchored = set(references)
  while reached := {zone for zone in nets.keys() - anchored if anchored.intersection(incident[zone].values())}:
    anchored.update(reached)
  if missing := nets.keys() - anchored:
    raise PressureUnresolved(f"节点没有连至定压边界的开放通路：{sorted(missing)}")
  # A zero-demand branch with one remaining neighbor is exactly isobaric with that neighbor.
  # Peel it before iteration, then restore each node's pressure for the full-network residual check.
  pending = [zone for zone, duty in nets.items() if duty == 0]
  dead_ends = []
  while pending:
    zone = pending.pop()
    if zone not in incident:
      continue
    neighbors = set(incident[zone].values())
    if len(neighbors) != 1:
      continue
    neighbor = neighbors.pop()
    dead_ends.append((zone, neighbor))
    for key in incident.pop(zone):
      if neighbor in incident:
        del incident[neighbor][key]
    if neighbor in incident and nets[neighbor] == 0:
      pending.append(neighbor)
  active = sorted(incident)
  pressures = {**references, **dict.fromkeys(nets, next(iter(references.values())))}
  for _ in range(2000):
    for zone in active:
      local = {key: {**edges[key], "pressure_pa": pressures[other]} for key, other in incident[zone].items()}
      pressures[zone], _, _ = room_pressure(nets[zone], local)
    for zone, neighbor in reversed(dead_ends):
      pressures[zone] = pressures[neighbor]
    flows = {}
    exchange = {zone: [] for zone in pressures}
    for key, edge in edges.items():
      a, b = edge["ends"]
      delta = pressures[a]-pressures[b]
      flows[key] = math.copysign(edge["coefficient_m3_h_pa_n"] * abs(delta)**edge["exponent"], delta)
      exchange[a].append(flows[key])
      exchange[b].append(-flows[key])
    outgoing = {zone: math.fsum(parts) for zone, parts in exchange.items()}
    residuals = {zone: outgoing[zone]-duty for zone, duty in nets.items()}
    if all(abs(value) <= max(absolute_flow_tolerance, abs(nets[zone])*relative_flow_tolerance) for zone, value in residuals.items()):
      return pressures, flows, outgoing, residuals
  raise PressureUnresolved("压力迭代未达到逐节点流量守恒容差")
