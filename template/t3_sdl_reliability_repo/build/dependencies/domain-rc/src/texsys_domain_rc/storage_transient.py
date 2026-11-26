"""Sensible chilled-water storage, physical transfer paths and time-bounded dispatch."""

import math
from fractions import Fraction

from texsys.evidence import canonical_digest

from .hydraulic import round_trip, terminal_network
from .thermal import stored_energy_kwh
from .water_network import chilled_water_network


class MissingStorageEvidence(ValueError):
  """A valid observation cannot be made with the supplied evidence."""


def _field(row, key):
  if key not in row or row[key] is None:
    raise MissingStorageEvidence(f"缺少蓄冷依据 {key}")
  return row[key]


def _text(value):
  if not isinstance(value, str) or not value.strip():
    raise ValueError("需要非空标识或来源")
  return value


def _value(value, *, positive=False):
  if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (positive and value == 0):
    raise ValueError("蓄冷参数应为有限的非负数，容量特性须为正")
  return value


def tank_observation(key, prim, bounds, levels, capacity):
  low = _field(levels, "minimum_level_m")
  high = _field(levels, "initial_level_m")
  a, b = bounds
  if (any(type(x) not in (int, float) or not math.isfinite(x) for x in (low, high))
      or low < a[2] - 1e-6 or high > b[2] + 1e-6 or high < low):
    raise ValueError(f"{key} 的有效水位与内净包络不符")
  delta = _value(_field(levels, "usable_delta_k"), positive=True)
  fraction = _value(_field(levels, "usable_fraction"), positive=True)
  if fraction > 1:
    raise ValueError("蓄冷可用系数不得超过 1")
  volume = (b[0] - a[0]) * (b[1] - a[1]) * max(0., min(high, b[2]) - max(low, a[2]))
  return {"object": key, "prim": prim, "volume_m3": volume, "usable_delta_k": delta, "usable_fraction": fraction,
          "energy_kwh": stored_energy_kwh(volume, delta, fraction, _value(capacity, positive=True)),
          "source": _text(_field(levels, "source"))}


def storage_network(scene, hydraulic):
  """One possible sensible-cooling transfer per tank/terminal with an installed round trip."""
  network = chilled_water_network(scene, hydraulic)
  nodes, topology, issues = network["nodes"], network["topology"], network["unresolved"]
  stores = {k: n for k, n in nodes.items() if n["kind"] == "storage"}
  loads = {k: n for k, n in nodes.items() if n["kind"] == "terminal"}
  junctions = {k for k, n in nodes.items() if n["kind"] == "junction"}
  ports = {k: {"instance": k, "interface": "sensible-cooling"} for k in stores.keys() | loads.keys()}
  links = {}
  if not issues:
    for store in sorted(stores):
      for load in sorted(loads):
        local = terminal_network(topology, {store}, load, junctions)
        _, supply, returned = round_trip(local, {store}, load)
        if supply is not None and returned is not None:
          links[str(len(links)+1)] = {"ports": [store, load], "evidence": stores[store]["prim"],
                                      "supply": supply, "return": returned}
  return {"kind": "domain-netlist", "schema_version": 1, "origin": "physical", "granularity": "port", "domain": "thermal",
          **{k: network[k] for k in ("scope", "baseline", "frame", "scene_digest")}, "source_digest": network["water_netlist_digest"], "complete": not issues,
          "unresolved": [{"reason": msg} for msg in issues], "ports": ports, "connections": links, "stores": stores, "terminals": loads,
          "hydraulic_topology": topology, "junctions": sorted(junctions)}


def _interval(network, tanks, allowed, row, start, end, storage_only, energy, losses):
  """Check installed routes and kW independently of inventory, then balance kWh if available."""
  source = _text(_field(row, "source"))
  demands, limits = _field(row, "terminals"), row.get("available_discharge_kw")
  if limits is None:
    limits = {}
  if not isinstance(demands, dict) or not isinstance(limits, dict):
    raise ValueError("末端和水箱能力应为带设备 ID 的映射")
  if demands.keys() - network["terminals"].keys() or limits.keys() - tanks.keys():
    raise MissingStorageEvidence("区间记录的末端或水箱与实施清单不一致")
  issues = []
  disabled = _field(row, "unavailable_segments")
  topology = network["hydraulic_topology"]
  segments = topology["supply"].keys() | topology["return"].keys()
  if not isinstance(disabled, list) or any(not isinstance(k, str) or k not in segments for k in disabled) or len(set(disabled)) != len(disabled):
    raise ValueError("工况必须按唯一的已安装管段 ID 声明不可用管段")
  active = {kind: {key: ends for key, ends in paths.items() if key not in disabled} for kind, paths in topology.items()}
  requested = {k: {} for k in tanks}
  routes = {}
  deficit, delivered, gross = {}, {}, {}
  for load in sorted(network["terminals"]):
    try:
      demand = _field(demands, load)
      duty = _value(_field(demand, "load_kw"))
      restored = 0. if storage_only else _value(_field(demand, "other_delivered_kw"))
      shares = _field(demand, "dispatch_fraction")
    except MissingStorageEvidence as exc:
      issues.append(f"{load}：{exc}")
      continue
    gross[load] = duty
    deficit[load] = max(0, Fraction(str(duty)) - Fraction(str(restored)))
    delivered[load] = min(duty, restored)
    if not isinstance(shares, dict) or shares.keys() - tanks.keys():
      raise ValueError(f"{load} 的调度引用未知水箱")
    fractions = {tank: Fraction(str(_value(x))) for tank, x in shares.items()}
    if any(x > 1 for x in fractions.values()) or abs(math.fsum(fractions.values())-1.) > 1e-9:
      raise ValueError(f"{load} 的调度比例之和须为 1")
    total_share = sum(fractions.values())
    for tank, share in fractions.items():
      if not share:
        continue
      local = terminal_network(active, {tank}, load, set(network["junctions"]))
      _, supply, returned = round_trip(local, {tank}, load)
      connected = (tank, load) in allowed and supply is not None and returned is not None
      routes.setdefault(tank, {})[load] = {"supply": supply, "return": returned, "available": connected}
      if connected:
        requested[tank][load] = deficit[load]*share/total_share
      elif deficit[load] > 0:
        losses.append({"by_min": start, "reason": "no-round-trip", "tank": tank, "terminal": load,
                       "unavailable_segments": disabled, "missing_kw": float(deficit[load]*share/total_share)})
  before = {k: float(v) for k, v in energy.items()} if energy is not None else None
  steps, supplied = {}, dict.fromkeys(demands, 0)
  duration_h = (Fraction(str(end)) - Fraction(str(start))) / 60
  for tank, allocations in requested.items():
    demand_kw = sum(allocations.values())
    assigned_kw = {load: float(kw) for load, kw in allocations.items()}
    if limits.get(tank) is None:
      issues.append(f"{tank} 缺少工况可用放冷功率")
      limit_kw = tanks[tank]["max_discharge_kw"]
    else:
      limit_kw = _value(limits[tank])
    if limit_kw > tanks[tank]["max_discharge_kw"]:
      raise ValueError(f"{tank} 的工况放冷功率超出选型能力")
    kw = min(demand_kw, Fraction(str(limit_kw)))
    if demand_kw > kw:
      losses.append({"by_min": start, "reason": "discharge-power", "tank": tank,
                     "requested_kw": float(demand_kw), "capacity_upper_kw": limit_kw, "assigned_kw": assigned_kw})
    if energy is None:
      continue
    spent = min(energy[tank], kw*duration_h)
    exhaustion = float(Fraction(str(start)) + 60*energy[tank]/kw) if kw and energy[tank] < kw*duration_h else None
    if exhaustion is not None:
      losses.append({"by_min": exhaustion, "reason": "stored-energy", "tank": tank, "initial_kwh_upper_bound": before[tank],
                     "discharge_kw": float(kw), "assigned_kw": assigned_kw})
    energy[tank] -= spent
    for load, duty in allocations.items():
      if demand_kw:
        supplied[load] += spent*duty/demand_kw
    steps[tank] = {"requested_kw": float(demand_kw), "available_kw": limit_kw, "discharged_kwh": float(spent),
                   "depleted_at_min": exhaustion, "assigned_kw": assigned_kw}
  if issues:
    raise MissingStorageEvidence("；".join(issues))
  if energy is None:
    return None
  unserved = {k: float(max(0, duration_h*q-supplied[k])) for k, q in deficit.items()}
  consumed = math.fsum(step["discharged_kwh"] for step in steps.values())
  demand_energy = math.fsum(gross.values())*duration_h
  residual = math.fsum((demand_energy, -math.fsum(delivered.values())*duration_h, -consumed, -math.fsum(unserved.values())))
  if not math.isfinite(residual) or abs(residual) > max(1e-9, 1e-10*demand_energy):
    raise ValueError("时序区间能量收支残差超限")
  return {"gross_load_kw": gross, "energy_balance_residual_kwh": residual, "start_min": start, "end_min": end, "source": source, "storage_demand_kw": {k: float(v) for k, v in deficit.items()},
          "other_delivered_kw": delivered, "initial_kwh": before, "final_kwh": {k: float(v) for k, v in energy.items()},
          "stores": steps, "unserved_kwh": unserved, "transfer_paths": routes, "unavailable_segments": disabled}


def _integrate(network, tanks, case, *, storage_only):
  # Preserve decimal input boundaries across shared dispatch and accumulated discharges.
  energy = {key: Fraction(str(data["energy_kwh"])) for key, data in tanks.items()}
  allowed = {tuple(connection["ports"]) for connection in network["connections"].values()}
  no_charge = case.get("no_charge_source")
  if no_charge is not None:
    _text(no_charge)
  horizon, previous_end, first_loss, witness = 0., 0., None, None
  remaining = energy.copy()
  trace, issues = [], []
  try:
    intervals = _field(case, "intervals")
    if not isinstance(intervals, list):
      raise ValueError("冷负荷时序应为有序区间")
    if not intervals:
      raise MissingStorageEvidence("缺少失冷时序")
    for row in intervals:
      start, end = (_value(_field(row, key)) for key in ("start_min", "end_min"))
      if end <= start or start < previous_end:
        raise ValueError("时间轴存在重叠、倒序或零长区间")
      if start > previous_end:
        issues.append(f"{previous_end:g}–{start:g} min 缺少工况记录")
      previous_end = end
      continuous = not issues
      # Without charging, skipping an unknown interval leaves an upper bound on each tank.
      trial_energy = energy.copy() if continuous or no_charge is not None else None
      losses = []
      try:
        step = _interval(network, tanks, allowed, row, start, end, storage_only, trial_energy, losses)
      except MissingStorageEvidence as exc:
        issues.append(f"{start:g}–{end:g} min：{exc}")
      else:
        if trial_energy is not None:
          energy = trial_energy
        if continuous:
          horizon, remaining = end, energy.copy()
          trace.append(step)
      if losses:
        earliest = min(losses, key=lambda loss: loss["by_min"])
        if continuous and first_loss is None and (not issues or earliest["by_min"] == start):
          first_loss = earliest["by_min"]
        if witness is None or earliest["by_min"] < witness["by_min"]:
          witness = {**earliest, "interval_min": [start, end], "source": row["source"]}
          if not continuous and earliest["reason"] == "stored-energy":
            witness["no_charge_source"] = no_charge
  except MissingStorageEvidence as exc:
    issues.append(str(exc))
  return {"confirmed_through_min": horizon, "first_shortfall_min": first_loss,
          "shortfall_by_min": witness["by_min"] if witness else None, "shortfall_witness": witness,
          "remaining_kwh": {k: float(v) for k, v in remaining.items()}, "intervals": trace, "unresolved": issues}


def cooling_case_digest(schedule, name):
  """Identify a named cooling case and its common schedule context independently of sibling cases."""
  return canonical_digest({**schedule, "cases": {name: schedule["cases"][name]}})


def storage_transient(network, inventory, schedule):
  if (type(network.get("schema_version")) is not int or network["schema_version"] != 1
      or (network.get("domain"), network.get("origin"), network.get("kind")) != ("thermal", "physical", "domain-netlist")):
    raise ValueError("需要有实施侧来源的蓄冷热传递网表")
  for record, kind in ((inventory, "storage-inventory"), (schedule, "cooling-sequences")):
    if record.get("kind") != kind or type(record.get("schema_version")) is not int or record["schema_version"] != 1:
      raise ValueError(f"需要版本 1 的 {kind}")
  keys = ("scope", "frame", "baseline")
  header = {key: _text(network[key]) for key in keys}
  tanks, cases, issues = {}, {}, []
  try:
    if not all(all(record.get(key) == header[key] for key in keys) for record in (inventory, schedule)):
      raise MissingStorageEvidence("库存、工况与物理网表的范围、坐标系或基线不一致")
    if not network["complete"] or network["unresolved"] or inventory.get("complete") is not True:
      raise MissingStorageEvidence("热传递网表或蓄冷选型清单尚未完整")
    rows = _field(inventory, "tanks")
    if rows.keys() != network["stores"].keys() or not rows or not network["terminals"]:
      raise MissingStorageEvidence("水箱选型或末端范围与实施清单不符")
    for key, row in rows.items():
      geometry = network["stores"][key]
      tanks[key] = tank_observation(key, geometry["prim"], geometry["bounds_m"], row, _field(row, "heat_capacity_kwh_m3_k"))
      tanks[key]["max_discharge_kw"] = _value(_field(row, "max_discharge_kw"))
    for name, case in _field(schedule, "cases").items():
      _text(name)
      if not isinstance(case, dict):
        raise ValueError("热工况须为对象")
      if not case.get("source"):
        issues.append(f"{name}：缺少工况来源")
        continue
      cases[name] = {"source": _text(case["source"]), "case_digest": cooling_case_digest(schedule, name)}
      for track in ("service", "storage_only"):
        result = _integrate(network, tanks, case, storage_only=track == "storage_only")
        cases[name][track] = result
        issues.extend(f"{name}/{track}：{issue}" for issue in result["unresolved"])
    if not cases:
      raise MissingStorageEvidence("缺少冷源失效工况")
  except MissingStorageEvidence as exc:
    issues.append(str(exc))
  return {"kind": "storage-transient", "schema_version": 1, "domain": "thermal", **header, "scene_digest": network["scene_digest"],
          "water_netlist_digest": network["source_digest"], "stores": tanks, "terminals": sorted(network["terminals"]),
          "network_digest": canonical_digest(network), "inventory_digest": canonical_digest(inventory),
          "cases": cases, "complete": not issues, "unresolved": issues}
