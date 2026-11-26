"""Equipment-to-zone service topology and steady cooling allocations in kW."""

import math
from collections import defaultdict

from texsys.evidence import canonical_digest, file_digest

from .netlist import _netlist, _table, _text
from .usd_geometry import open_scene, world_box, world_polyline


def _version(document, kind):
  if type(document.get("schema_version")) is not int or document["schema_version"] != 1 or document.get("kind") != kind:
    raise ValueError(f"Expected version 1 {kind}.")


def cooling_service_netlist(scene, selection):
  from pxr import Usd, UsdGeom

  _version(selection, "cooling-service-layout")
  if selection.get("domain") != "hvac":
    raise ValueError("Cooling service layouts require the HVAC domain.")
  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  frame, digest = _text(root.GetCustomDataByKey("frame")), file_digest(scene)
  groups = [_table(selection[k]) for k in ("units", "rooms", "routes")]
  units, rooms, routes = groups
  ids = [key for group in groups for key in group]
  paths = [_text(path) for group in groups for path in group.values()]
  if len(set(ids)) != len(ids) or len(set(paths)) != len(paths):
    raise ValueError("Service objects require distinct IDs and distinct scene prims.")
  ports = {key: {"instance": key, "interface": "cooling-service"} for key in (*units, *rooms)}
  connections, unresolved, observations = {}, [], {}
  qualified = (frame, digest) == (selection.get("frame"), selection.get("scene_digest"))
  boxes, products = {}, {}
  if qualified:
    cache = UsdGeom.XformCache(Usd.TimeCode.Default())
    for group in (units, rooms, routes):
      for key, path in sorted(group.items()):
        prim = stage.GetPrimAtPath(path)
        if not prim or not prim.GetPath().HasPrefix(root.GetPath()):
          unresolved.append({"object": key, "evidence": path, "reason": "missing-scene-prim"})
          continue
        if group is not routes:
          boxes[key] = world_box(prim)
          if group is units:
            products[key] = prim.GetCustomDataByKey("productId")
          continue
        points = world_polyline(prim, cache)
        ends = []
        for end, targets in ((points[0], units), (points[-1], rooms)):
          candidates = sorted(t for t in targets if t in boxes and all(lo - 1e-6 <= x <= hi + 1e-6
                              for lo, x, hi in zip(boxes[t][0], end, boxes[t][1], strict=True)))
          ends.append({"xyz_m": list(end), "candidates": candidates})
        observations[key] = {"prim": path, "ends": ends, "length_m": math.fsum(math.dist(a, b) for a, b in zip(points, points[1:]))}
        for i, (end, inventory) in enumerate(zip(ends, (units, rooms), strict=True)):
          if len(end["candidates"]) != 1 or inventory.keys() - boxes.keys():
            unresolved.append({"route": key, "end": i, "candidates": end["candidates"], "evidence": path})
        if all(len(end["candidates"]) == 1 for end in ends) and not (units.keys() | rooms.keys()) - boxes.keys():
          connections[key] = {"ports": [end["candidates"][0] for end in ends], "evidence": path}
  else:
    unresolved.append({"reason": "incompatible-scene-or-frame"})
  netlist = _netlist(selection, "physical", {k: v for k, v in ports.items() if k in boxes}, connections, unresolved)
  return {**netlist, "method": "direct-unit-to-zone-centerline", "frame": frame, "scene_digest": digest,
          "inventory_complete": selection["complete"], "unit_prims": dict(units), "products": products, "units": sorted(units), "rooms": sorted(rooms), "observed_objects": sorted(boxes), "service_routes": observations}


def compare_service_routes(network, plan):
  _version(network, "domain-netlist")
  _version(plan, "cooling-service-plan")
  if network.get("origin") != "physical" or network.get("domain") != "hvac" or network.get("method") != "direct-unit-to-zone-centerline":
    raise ValueError("Expected an implementation-side direct cooling service network.")
  if any(network[k] != plan.get(k) for k in ("scope", "baseline")):
    return {}
  observed = set(network["observed_objects"])
  checks = {}
  for key, intended in sorted(_table(plan["routes"]).items()):
    unit, room = intended.get("unit"), intended.get("room")
    route = network["service_routes"].get(key)
    verified = None
    if route and unit in observed and room in observed and intended.get("source"):
      connection = network["connections"].get(key)
      if connection is not None:
        verified = connection["ports"] == [unit, room]
      elif any(endpoint not in end["candidates"] for endpoint, end in zip((unit, room), route["ends"], strict=True)):
        verified = False
    checks[key] = {"unit": unit, "room": room, "source": intended.get("source"), "connection": verified}
  return checks


def _unavailable(raw, inventory):
  if not isinstance(raw, list) or any(not isinstance(key, str) or key not in inventory for key in raw) or len(set(raw)) != len(raw):
    raise ValueError("Unavailable objects must be distinct members of the selected inventory.")
  return set(raw)


def case_paths(network, checks, stopped, lost):
  paths = {}
  for key in sorted(checks.keys() | network["service_routes"].keys()):
    row = checks.get(key, {})
    state = ("offline" if key in lost or row.get("unit") in stopped else "unverified" if row.get("connection") is None
             else "available" if row["connection"] else "wrong-endpoint")
    paths[key] = {"unit": row.get("unit"), "room": row.get("room"), "state": state}
  return paths


def _cooling_case(case, network, checks, pairs):
  units, rooms = network["units"], network["rooms"]
  dispatch = case.get("dispatch_kw")
  if not case.get("source") or dispatch is None or case.get("unavailable_units") is None:
    return {"issue": "缺少有出处的设备分配或停运清单"}
  if set(_table(dispatch)) != set(units):
    return {"issue": "设备分配清单与安装范围不一致"}
  stopped = _unavailable(case["unavailable_units"], units)
  lost = _unavailable(case.get("unavailable_routes", []), checks.keys() | network["service_routes"].keys())
  paths = case_paths(network, checks, stopped, lost)
  selections = _table(case.get("dispatch_routes", {}))
  if selections.keys() - dispatch.keys():
    raise ValueError("Feeder selections reference an unknown unit.")
  transfers, totals = [], {}
  balances = {room: {"routed_kw": [], "pending_kw": [], "withheld_kw": []} for room in rooms}
  for unit, assignments in sorted(dispatch.items()):
    if _table(assignments).keys() - set(rooms):
      raise ValueError("Cooling assignment references an unknown room.")
    selected = _table(selections.get(unit, {}))
    if selected.keys() - assignments.keys():
      raise ValueError("Route selected without a corresponding allocation.")
    for room, kw in sorted(assignments.items()):
      if type(kw) not in (int, float) or not math.isfinite(kw) or kw < 0:
        raise ValueError("Cooling allocations require finite nonnegative kW.")
      if not kw:
        continue
      candidates = pairs.get((unit, room), [])
      route = selected.get(room)
      if route is not None and _text(route) not in candidates:
        raise ValueError("Selected route does not serve the allocated unit and room in the plan.")
      if route is None and len(candidates) == 1:
        route = candidates[0]
      state = paths[route]["state"] if route is not None else "unverified"
      no_available_route = candidates and all(paths[k]["state"] in ("offline", "wrong-endpoint") for k in candidates)
      if unit in stopped or state in ("offline", "wrong-endpoint") or no_available_route:
        status = "withheld_kw"
      elif state == "unverified":
        status = "pending_kw"
      else:
        status = "routed_kw"
      balances[room][status].append(kw)
      transfers.append({"unit": unit, "room": room, "kw": kw, "route": route, "candidate_routes": candidates, "status": status})
    totals[unit] = math.fsum(assignments.values())
  return {"source": _text(case["source"]), "unit_dispatch_kw": totals, "rooms": {
    room: {k: math.fsum(v) for k, v in row.items()} for room, row in balances.items()}, "allocations": transfers,
    "paths": paths, "unavailable_units": sorted(stopped), "unavailable_routes": sorted(lost)}


def cooling_dispatch(network, plan, schedule):
  _version(schedule, "cooling-dispatch-cases")
  if type(plan.get("complete")) is not bool or type(schedule.get("complete")) is not bool:
    raise ValueError("Declare scope completeness for the service plan and case inventory.")
  checks = compare_service_routes(network, plan)
  pairs = defaultdict(list)
  for route, row in checks.items():
    pairs[row["unit"], row["room"]].append(route)
  cases, unresolved = {}, []
  if any(network[k] != doc.get(k) for doc in (plan, schedule) for k in ("scope", "baseline")):
    unresolved.append({"reason": "incompatible-issue"})
  elif any(issue.get("reason") == "incompatible-scene-or-frame" for issue in network["unresolved"]):
    unresolved.append({"reason": "incompatible-scene-or-frame"})
  else:
    for name, case in sorted(_table(schedule["cases"]).items()):
      row = _cooling_case(case, network, checks, pairs)
      cases[name] = row
      if "issue" in row:
        unresolved.append({"case": name, "reason": row["issue"]})
      else:
        unresolved.extend({"case": name, "unit": t["unit"], "room": t["room"], "reason": "unresolved-service-route"}
                          for t in row["allocations"] if t["status"] == "pending_kw")
  return {"schema_version": 1, "kind": "cooling-dispatch", "domain": "hvac", "frame": network["frame"],
          "scene_digest": network["scene_digest"], "scope": network["scope"], "baseline": network["baseline"],
          "network_digest": canonical_digest({k: v for k, v in network.items() if k != "sources"}),
          "plan_digest": canonical_digest(plan), "schedule_digest": canonical_digest(schedule),
          "unit_prims": network["unit_prims"], "network_inventory_complete": network["inventory_complete"],
          "plan_inventory_complete": plan["complete"], "case_inventory_complete": schedule["complete"],
          "complete": bool(cases) and network["complete"] and plan["complete"] and schedule["complete"] and not unresolved
                      and set(checks) == set(network["service_routes"]) and all(r["connection"] is True for r in checks.values()),
          "cases": cases, "unresolved": unresolved}
