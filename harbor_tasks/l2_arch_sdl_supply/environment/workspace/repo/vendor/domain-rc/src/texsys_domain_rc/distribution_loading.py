"""Coincident apparent loads on the selected radial paths of an AC distribution system."""

import math
from collections import defaultdict
from itertools import pairwise

from texsys.evidence import canonical_digest

from .netlist import _table, _text

PHASES = ("A", "B", "C")


def _header(record, kind):
  if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record.get("kind") != kind:
    raise ValueError(f"Expected version 1 {kind}.")
  return {key: _text(record.get(key)) for key in ("frame", "scene_digest")}


def _kva(value):
  if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
    raise ValueError("Expected finite nonnegative apparent power in kVA.")
  return value


def _routes(network, nodes, *, expansion):
  routes = {}
  for key, row in _table(network["routes"]).items():
    pair = (row["from"], row["to"])
    if (expansion and pair in routes) or pair[0] == pair[1] or any(k not in nodes for k in pair):
      raise ValueError(f"Invalid or parallel equipment endpoints on {key}.")
    if nodes[pair[0]] in ("it-load", "other-load") or nodes[pair[1]] == "source":
      raise ValueError(f"Invalid source or load direction on {key}.")
    if type(row.get("endpoints_verified")) is not bool:
      raise ValueError(f"Missing endpoint qualification on {key}.")
    phases = row.get("phases")
    if phases is not None and (not isinstance(phases, list) or not phases or set(phases) - set(PHASES)
                               or len(phases) != len(set(phases)) or type(row.get("has_neutral")) is not bool):
      raise ValueError(f"Invalid phase inventory on {key}.")
    routes[pair] = key, row
  return routes


def routed_totals(allocations, quantities):
  """Sum coincident power shares on each load and its traversed upstream equipment and feeders."""
  entries = {"loads": defaultdict(list), "nodes": defaultdict(list), "routes": defaultdict(list)}
  for allocation in allocations:
    nodes, routes = allocation["nodes"], allocation["routes"]
    if (not routes or len(nodes) != len(routes) + 1 or len(set(nodes)) != len(nodes)
        or len(set(routes)) != len(routes)):
      raise ValueError("Each power allocation needs one simple ordered path.")
    if any(type(allocation[k]) not in (int, float) or not math.isfinite(allocation[k]) or allocation[k] < 0 for k in quantities):
      raise ValueError("Invalid routed power quantity.")
    for scope, keys in (("loads", [nodes[-1]]), ("nodes", nodes[:-1]), ("routes", routes)):
      for key in keys:
        entries[scope][key].append(allocation)
  return {scope: {key: {"contributors": sorted({e["nodes"][-1] for e in rows}),
                        **{q: math.fsum(e[q] for e in rows) for q in quantities}} for key, rows in sorted(assets.items())}
          for scope, assets in entries.items()}


def _case(case, nodes, routes, loads):
  source = case.get("source")
  rows = _table(case.get("loads", {}))
  if rows.keys() - loads:
    raise ValueError("Load schedule references an unknown load.")
  if not source or case.get("complete") is not True or loads - rows.keys():
    return {"issue": "工况出处或负荷清单不完整", "missing_loads": sorted(loads - rows.keys())}
  _text(source)
  allocations, contributors = [], defaultdict(list)
  incoming, growth = {}, []
  unknown, mismatch, neutral_required = set(), set(), set()
  for load, row in sorted(rows.items()):
    path = row.get("path")
    if path is None or row.get("existing_kva") is None or row.get("growth_kva") is None:
      return {"issue": f"{load} 缺少供电路径或工况负荷"}
    if (not isinstance(path, list) or len(path) < 2 or any(k not in nodes for k in path)
        or len(set(path)) != len(path) or nodes[path[0]] != "source" or path[-1] != load):
      raise ValueError(f"{load} requires a simple source-to-load path.")
    base, added = (_kva(row[k]) for k in ("existing_kva", "growth_kva"))
    phase = row.get("phase")
    if phase is not None and phase not in (*PHASES, "ABC"):
      raise ValueError(f"{load} has an invalid phase.")
    if added and nodes[load] == "it-load":
      growth.append(load)
    feeders = []
    for start, end in pairwise(path):
      edge = routes.get((start, end))
      if edge is None or not edge[1]["endpoints_verified"]:
        return {"issue": f"{load} 缺少端点已核实的供电路径", "endpoints": [start, end]}
      if not (base or added):
        continue
      if incoming.setdefault(end, start) != start:
        return {"issue": f"{end} 同时经不同上游供电，需要分流依据"}
      key, wire = edge
      feeders.append(key)
      available = wire.get("phases")
      if available is None or phase is None:
        unknown.add(key)
        continue
      if (phase == "ABC" and set(available) != set(PHASES)) or (phase != "ABC" and phase not in available):
        mismatch.add(key)
      if phase != "ABC":
        if not wire["has_neutral"]:
          neutral_required.add(key)
        if set(available) == set(PHASES):
          contributors[key].append((phase, base, added))
    if base or added:
      allocations.append({"nodes": path, "routes": feeders, "existing_kva": base, "growth_kva": added})
  totals = routed_totals(allocations, ("existing_kva", "growth_kva"))
  assets = [{"type": kind, "id": key, "loads": row["contributors"], "existing_kva": row["existing_kva"], "growth_kva": row["growth_kva"]}
            for kind, scope in (("node", "nodes"), ("route", "routes")) for key, row in totals[scope].items()]
  stages = {}
  for key in sorted(contributors.keys() - unknown - mismatch):
    amounts = contributors[key]
    base = {p: math.fsum(v for phase, v, _ in amounts if phase == p) for p in PHASES}
    expanded = {p: base[p] + math.fsum(v for phase, _, v in amounts if phase == p) for p in PHASES}
    stages[key] = {}
    for stage, values in (("existing", base), ("expanded", expanded)):
      mean = math.fsum(values.values()) / 3
      if mean:
        stages[key][stage] = {"single_phase_kva": values, "mean_kva": mean,
                              "deviation_ratio": max(abs(v - mean) / mean for v in values.values())}
  return {"source": source, "assets": assets, "it_growth_loads": growth, "phase_loading": stages,
          "consistent_phase_labels": case.get("consistent_phase_labels") is True,
          "phase_mismatches": sorted(mismatch), "unknown_phases": sorted(unknown), "neutral_required": sorted(neutral_required)}


def _dispatch(case, nodes, routes):
  if case.get("complete") is not True or not case.get("source"):
    return {"issue": "缺少有出处的完整分流工况"}
  source = _text(case["source"])
  unavailable = case["unavailable"]
  if not isinstance(unavailable, list) or len(set(unavailable)) != len(unavailable) or set(unavailable) - nodes.keys():
    raise ValueError("Unknown or duplicate unavailable equipment.")
  lost_routes = case.get("unavailable_routes", [])
  if not isinstance(lost_routes, list) or len(set(lost_routes)) != len(lost_routes) or set(lost_routes) - routes.keys():
    raise ValueError("Unknown or duplicate unavailable feeder.")
  transfers, withheld, active_parents = [], [], defaultdict(set)
  loads = _table(case["loads"])
  parallel = False
  for load, shares in sorted(loads.items()):
    if nodes.get(load) not in ("it-load", "other-load") or not isinstance(shares, list):
      raise ValueError(f"{load} requires an array of declared power shares at an installed load.")
    for share in shares:
      path = share["path"]
      if not isinstance(path, list) or not path or len(set(path)) != len(path):
        raise ValueError(f"{load} requires an ordered simple feeder path.")
      if any(key not in routes or not routes[key]["endpoints_verified"] for key in path):
        return {"issue": f"{load} 缺少已核实的线路", "path": path}
      hops = [routes[path[0]]["from"]]
      for key in path:
        if hops[-1] != routes[key]["from"]:
          raise ValueError(f"Discontinuous path for {load}.")
        hops.append(routes[key]["to"])
      if hops[-1] != load or nodes[hops[0]] != "source" or len(set(hops)) != len(hops):
        raise ValueError(f"{load} requires a simple source-to-load path.")
      kw, kva = (_kva(share[q]) for q in ("kw", "kva"))
      if not 0 < kw <= kva:
        raise ValueError("Each dispatch share requires 0 < kW ≤ kVA.")
      allocation = {"kw": kw, "kva": kva, "nodes": hops, "routes": path}
      stopped = sorted(set(hops) & set(unavailable))
      stopped_routes = sorted(set(path) & set(lost_routes))
      if stopped or stopped_routes:
        withheld.append({**allocation, "unavailable": stopped, "unavailable_routes": stopped_routes})
      else:
        transfers.append(allocation)
        for a, b in pairwise(hops):
          active_parents[b].add(a)
    parallel |= len(shares) > 1
  sharing = case.get("parallel_source")
  if (parallel or any(len(v) > 1 for v in active_parents.values())) and not sharing:
    return {"issue": "多路同时供电缺少分流依据", "withheld": withheld}
  if sharing is not None:
    _text(sharing)
  return {"source": source, "parallel_source": sharing, "scope_loads": sorted(loads),
          "transfers": transfers, "withheld": withheld, "routed_totals": routed_totals(transfers, ("kw", "kva"))}


def _study(network, schedule, *, expansion):
  header = _header(network, "distribution-network")
  selected = _header(schedule, "distribution-load-cases" if expansion else "power-dispatch-cases")
  if type(network.get("complete")) is not bool or type(schedule.get("complete")) is not bool:
    raise ValueError("Network and case inventories require explicit completeness.")
  _text(network["source"])
  nodes = _table(network["nodes"])
  if any(v not in ("source", "it-load", "other-load", "equipment") for v in nodes.values()):
    raise ValueError("Unknown distribution node role.")
  routes = _routes(network, nodes, expansion=expansion)
  loads = {k for k, role in nodes.items() if role in ("it-load", "other-load")}
  cases, unresolved = {}, []
  if selected != header:
    unresolved.append({"reason": "incompatible-installation-or-frame"})
  else:
    for name, case in sorted(_table(schedule["cases"]).items()):
      if not isinstance(case, dict):
        raise ValueError("Each load case requires a record.")
      if expansion:
        result = _case(case, nodes, routes, loads)
      else:
        result = _dispatch(case, nodes, network["routes"])
      cases[name] = result
      if "issue" in result:
        unresolved.append({"case": name, "reason": result["issue"]})
      elif expansion:
        unresolved.extend({"case": name, "route": route, "reason": "unknown-phase"} for route in result["unknown_phases"])
        if not result["consistent_phase_labels"]:
          unresolved.append({"case": name, "reason": "unconfirmed-phase-labels"})
  return {"schema_version": 1, "kind": "distribution-loading" if expansion else "power-dispatch", "domain": "electrical", **header,
          "network_digest": canonical_digest({k: v for k, v in network.items() if k != "sources"}),
          "schedule_digest": canonical_digest(schedule), "case_inventory_complete": schedule["complete"],
          "cases": cases, "unresolved": unresolved, "complete": bool(cases) and network["complete"] and schedule["complete"] and not unresolved}


def distribution_loading(network, schedule):
  """Deliver upstream kVA and the allocation of single-phase loads before and after expansion."""
  return _study(network, schedule, expansion=True)


def power_dispatch(network, schedule):
  """Replay simultaneous kW/kVA shares, excluding paths through unavailable equipment."""
  return _study(network, schedule, expansion=False)
