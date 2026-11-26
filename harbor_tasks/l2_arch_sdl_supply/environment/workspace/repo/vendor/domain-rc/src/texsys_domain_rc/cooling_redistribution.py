"""Concurrent, divisible cooling service over independent capacity-limited direct routes."""

import math
from collections import defaultdict, deque

from texsys.evidence import canonical_digest

from .cooling_service import _unavailable, _version, case_paths, compare_service_routes
from .netlist import _table, _text


def _kw(value):
  if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
    raise ValueError("Cooling service requires finite nonnegative kW.")
  return value


def _maximum_service(capacities, loads, routes):
  source, sink = ("boundary", "source"), ("boundary", "sink")
  residual, edges = defaultdict(dict), []

  def edge(a, b, cap):
    residual[a][b], residual[b][a] = cap, 0.
    edges.append((a, b, cap))

  for unit, capacity in sorted(capacities.items()):
    edge(source, ("unit", unit), capacity)
  for room, demand in sorted(loads.items()):
    edge(("room", room), sink, demand)
  for route, (unit, room, cap) in sorted(routes.items()):
    edge(("unit", unit), ("route", route), cap)
    edge(("route", route), ("room", room), cap)
  while True:
    parent = {source: None}
    queue = deque([source])
    while queue and sink not in parent:
      a = queue.popleft()
      for b, free in residual[a].items():
        if free > 0 and b not in parent:
          parent[b] = a
          queue.append(b)
    if sink not in parent:
      break
    path, b = [], sink
    while b != source:
      a = parent[b]
      path.append((a, b))
      b = a
    step = min(residual[a][b] for a, b in path)
    for a, b in path:
      residual[a][b] -= step
      residual[b][a] += step
  by_room = {r: residual[sink].get(("room", r), 0.) for r in sorted(loads)}
  by_route = {r: residual["room", room]["route", r] for r, (_, room, _) in sorted(routes.items())}
  flow = math.fsum(by_room.values())
  cut = [{"from": list(a), "to": list(b), "capacity_kw": cap} for a, b, cap in edges if a in parent and b not in parent]
  cut_capacity = math.fsum(e["capacity_kw"] for e in cut)
  if not math.isclose(cut_capacity, flow, abs_tol=1e-8, rel_tol=1e-10) or not math.isclose(math.fsum(by_route.values()), flow, abs_tol=1e-8, rel_tol=1e-10):
    raise ValueError("Cooling reallocation failed its flow or cut balance.")
  return {"maximum_kw": flow, "cut_capacity_kw": cut_capacity, "cut_edges": cut, "room_kw": by_room, "route_kw": by_route}


def _scenario(case, network, checks, performance):
  units, rooms = network["units"], network["rooms"]
  if not case.get("source") or case.get("independent_routes") is not True:
    return {"issue": "缺少同工况、独立路径和可调分配依据"}
  temperature = case.get("ambient_c")
  if type(temperature) not in (int, float) or not math.isfinite(temperature) or performance.get("ambient_c") != temperature:
    return {"issue": "设备性能与分配研究的室外温度不匹配"}
  if any(case.get(k) is None for k in ("room_loads_kw", "unavailable_units", "routes")):
    return {"issue": "缺少分区负荷、停运清单或路线输送依据"}
  demand = _table(case["room_loads_kw"])
  if set(demand) != set(rooms):
    return {"issue": "分区负荷范围与布置不一致"}
  demand = {r: _kw(q) for r, q in demand.items()}
  stopped = _unavailable(case["unavailable_units"], units)
  lost = _unavailable(case.get("unavailable_routes", []), checks.keys() | network["service_routes"].keys())
  capacities = {}
  for key in sorted(set(units) - stopped):
    point = performance.get("units", {}).get(key, {})
    if (not point.get("source") or not network["products"].get(key) or point.get("product") != network["products"][key]
        or "capacity_kw" not in point):
      return {"issue": f"{key} 缺少对应本机型号的同工况性能"}
    capacities[key] = _kw(point["capacity_kw"])
  firm, possible = {}, {}
  limits = _table(case["routes"])
  if limits.keys() - checks.keys():
    raise ValueError("An independent service limit requires a planned route.")
  for route, row in case_paths(network, checks, stopped, lost).items():
    unit, room = row["unit"], row["room"]
    if row["state"] in ("offline", "wrong-endpoint") or unit not in capacities or room not in demand:
      continue
    bound = limits.get(route, {})
    if not bound.get("source") or ("maximum_kw" not in bound and bound.get("nonlimiting") is not True):
      return {"issue": f"{route} 缺少同工况可输送冷量或无额外限制的依据"}
    if "maximum_kw" in bound and bound.get("nonlimiting") is True:
      raise ValueError("Use one transfer limit per route.")
    maximum = _kw(bound["maximum_kw"]) if "maximum_kw" in bound else min(capacities[unit], demand[room])
    possible[route] = unit, room, maximum
    if row["state"] == "available":
      firm[route] = possible[route]
  confirmed = _maximum_service(capacities, demand, firm)
  potential = _maximum_service(capacities, demand, possible) if possible != firm else confirmed
  return {"source": _text(case["source"]), "ambient_c": temperature, "demand_kw": math.fsum(demand.values()),
          "unit_capacity_kw": capacities, "room_loads_kw": demand, "confirmed_routes": confirmed,
          "including_unverified_routes": potential, "unverified_routes": sorted(possible.keys() - firm.keys())}


def cooling_redistribution(network, plan, performance, study):
  _version(performance, "cooling-performance")
  _version(study, "cooling-redistribution-cases")
  checks = compare_service_routes(network, plan)
  cases, unresolved = {}, []
  if (any(network[k] != d.get(k) for k in ("scope", "baseline") for d in (plan, study))
      or any(row.get("reason") == "incompatible-scene-or-frame" for row in network["unresolved"])
      or not study.get("catalog_digest") or performance.get("catalog_digest") != study["catalog_digest"]
      or not study.get("conditions_digest") or performance.get("conditions_digest") != study["conditions_digest"]):
    unresolved.append({"reason": "incompatible-network-or-product-study"})
  else:
    for key, case in sorted(_table(study["cases"]).items()):
      result = _scenario(case, network, checks, performance.get("cases", {}).get(key, {}))
      cases[key] = result
      if "issue" in result:
        unresolved.append({"case": key, "reason": result["issue"]})
      elif result["unverified_routes"]:
        unresolved.append({"case": key, "reason": "unverified-routes", "routes": result["unverified_routes"]})
  return {"schema_version": 1, "kind": "cooling-redistribution", "domain": "hvac", "frame": network["frame"],
          "scene_digest": network["scene_digest"], "scope": network["scope"], "baseline": network["baseline"],
          "network_digest": canonical_digest({k: v for k, v in network.items() if k != "sources"}),
          "plan_digest": canonical_digest(plan), "performance_digest": canonical_digest({k: v for k, v in performance.items() if k != "sources"}),
          "study_digest": canonical_digest(study), "network_inventory_complete": network["inventory_complete"],
          "plan_inventory_complete": plan.get("complete") is True, "cases": cases, "unresolved": unresolved}
