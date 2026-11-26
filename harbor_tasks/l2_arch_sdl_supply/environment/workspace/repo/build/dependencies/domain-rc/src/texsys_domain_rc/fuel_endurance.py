"""Constant-duty autonomy for independently supplied tanks and concurrent generator lineups."""

from math import fsum, isfinite

from texsys.evidence import canonical_digest

from .netlist import _table, _text


def _ids(value):
  if not isinstance(value, list) or any(not isinstance(k, str) or not k.strip() for k in value) or len(set(value)) != len(value):
    raise ValueError("机组或工况清单应为无重复的标识数组")
  return set(value)


def _source(value):
  return value.strip() if isinstance(value, str) and value.strip() else None


def _quantity(value, *, zero=False):
  if value is None:
    return None
  if type(value) not in (int, float) or not isfinite(value) or value < 0 or value == 0 and not zero:
    raise ValueError("有效储油量应为非负有限数，运行耗油量应为正有限数")
  return value


def tank_endurance(tank, assigned, cases, required, *, complete, require_all_generators=False):
  """Missing concurrent consumption can only shorten the witnessed upper bound."""
  capacity_source = _source(tank.get("capacity_source"))
  volume = _quantity(tank.get("usable_liters"), zero=True) if capacity_source else None
  observed, by_generator, sources, missing, seen = {}, {}, {}, {}, set()
  for name in sorted(required):
    case = cases.get(name, {})
    source = _source(case.get("source"))
    if not source or case.get("active_generators") is None:
      missing[name] = "缺少运行机组清单或工况出处"
      continue
    lineup = _ids(case["active_generators"])
    active = assigned & lineup
    rates = _table(case.get("fuel_liters_per_hour", {}))
    if rates.keys() - lineup:
      raise ValueError(f"{name} 的耗油记录含未运行的机组")
    known = {g: _quantity(rates.get(g)) for g in sorted(active)}
    if absent := [g for g, rate in known.items() if rate is None]:
      missing[name] = absent
    seen.update(active)
    sources[name] = source
    by_generator[name] = {g: rate for g, rate in known.items() if rate is not None}
    if by_generator[name]:
      observed[name] = fsum(by_generator[name].values())
  controlling = max(observed, key=observed.get, default=None)
  bound = volume / observed[controlling] if volume is not None and controlling else None
  complete = bool(complete and bound is not None and not missing and (not require_all_generators or seen == assigned))
  return {"usable_liters": volume, "capacity_source": capacity_source, "hours_upper_bound": bound, "complete": complete,
          "observed_hours": bound if complete else None, "limiting_case": controlling if complete else None,
          "witness_case": controlling, "case_fuel_liters_per_hour": observed, "case_sources": sources,
          "case_generator_liters_per_hour": by_generator,
          "unresolved_cases": missing, "generators_without_duty": sorted(assigned - seen)}


def fuel_endurance(inventory, schedule):
  for doc, kind in ((inventory, "fuel-inventory"), (schedule, "fuel-duty-schedule")):
    if doc.get("kind") != kind or type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
      raise ValueError(f"需要版本 1 的 {kind}")
  digest = canonical_digest(inventory)
  out = {"kind": "fuel-endurance", "domain": "electrical", "schema_version": 1, "frame": _text(inventory.get("frame")),
         "scene_digest": _text(inventory.get("scene_digest")), "inventory_digest": digest, "schedule_digest": canonical_digest(schedule),
         "tanks": {}, "unresolved": []}
  if schedule.get("inventory_digest") != digest or not _source(schedule.get("source")):
    out["unresolved"].append("工况清单缺少来源或与储油资料版本不符")
    return out
  required = _ids(schedule.get("required_cases", []))
  cases = _table(schedule.get("cases", {}))
  tanks = _table(inventory.get("tanks", {}))
  assigned = {key: _ids(row.get("generators", [])) for key, row in tanks.items()}
  all_units = set().union(*assigned.values())
  if len(all_units) != sum(map(len, assigned.values())):
    raise ValueError("同一机组关联多个油箱，需要另行建模切换或并联供油")
  for name in required & cases.keys():
    lineup = _table(cases[name]).get("active_generators")
    if lineup is not None and _ids(lineup) - all_units:
      raise ValueError(f"{name} 引用了供油清单外的机组")
  for key, tank in sorted(tanks.items()):
    if not assigned[key] or not _source(tank.get("connection_source")):
      out["unresolved"].append(key)
      continue
    observation = tank_endurance(tank, assigned[key], cases, required, complete=True)
    out["tanks"][key] = {**observation, "generators": sorted(assigned[key]), "connection_source": tank["connection_source"]}
    if not observation["complete"]:
      out["unresolved"].append(key)
  return out
