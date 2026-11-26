"""Steady chilled-water pressure at prescribed simultaneous terminal duties."""

import math
from collections import defaultdict

from texsys.evidence import canonical_digest

from .netlist import _table, _text
from .pressure_network import PressureUnresolved, solve_pressures
from .water_observations import compare_observations
from .water_transfers import compare_flow_transfers


def _sourced(record):
  source = record.get("source")
  return isinstance(source, str) and bool(source.strip())


def _number(record, key, *, minimum=None):
  value = record.get(key)
  if value is None:
    raise PressureUnresolved(f"缺少 {key}")
  if type(value) not in (int, float) or not math.isfinite(value) or minimum is not None and value < minimum:
    raise ValueError(f"{key} 超出数值范围")
  return value


def _components(nodes, edges):
  adjacent = defaultdict(set)
  for a, b in edges.values():
    adjacent[a].add(b)
    adjacent[b].add(a)
  remaining = set(nodes)
  while remaining:
    group, pending = set(), [min(remaining)]
    while pending:
      node = pending.pop()
      if node not in group:
        group.add(node)
        pending.extend(adjacent[node] - group)
    remaining -= group
    yield group


def _circuit(side, topology, nodes, states, plants, loads):
  open_edges = {}
  for key, ends in topology.items():
    state = states.get(key, {})
    if not _sourced(state) or state.get("state") not in ("open", "closed"):
      raise PressureUnresolved(f"{key} 缺少有依据的开闭状态")
    if state["state"] == "open":
      open_edges[key] = ends
  active_nodes = loads.keys() | plants.keys() | {node for ends in open_edges.values() for node in ends}
  result = {"pressure_kpa": {}, "flows_lps": {k: 0. for k in topology if k not in open_edges},
            "balance_residual_lps": {}, "plant_outgoing_lps": {}, "isolated": [], "unresolved": {}}
  for group in _components(active_nodes, open_edges):
    terminals = group & loads.keys()
    sources = group & plants.keys()
    if not terminals and not sources:
      continue
    if any(nodes[k]["kind"] not in ("junction", "terminal", "plant") for k in group):
      result["unresolved"].update(dict.fromkeys(terminals, "运行路径含未建模的储能或其他水力边界"))
      continue
    if not sources:
      result["isolated"].extend(sorted(terminals))
      continue
    try:
      fixed = {}
      for key in sorted(sources):
        if not _sourced(plants[key]):
          raise PressureUnresolved(f"{key} 缺少冷源压力依据")
        fixed[key] = 1000 * _number(plants[key], f"{side}_kpa")
      nets = dict.fromkeys(sorted(group - sources), 0.)
      for key in terminals:
        if not _sourced(loads[key]):
          raise PressureUnresolved(f"{key} 缺少工况流量依据")
        nets[key] = (-3.6 if side == "supply" else 3.6) * _number(loads[key], "flow_lps", minimum=0)
      edges = {}
      for key, (a, b) in open_edges.items():
        if a not in group:
          continue
        resistance = _number(states[key], "resistance_kpa_per_lps2", minimum=0)
        if resistance == 0:
          raise ValueError(f"{key} 的开放管段等效阻力须为正")
        edges[key] = {"ends": [a, b], "coefficient_m3_h_pa_n": 3.6 / math.sqrt(1000 * resistance), "exponent": .5}
      pressure, flow, outgoing, residual = solve_pressures(edges, nets, fixed, absolute_flow_tolerance=1e-9, relative_flow_tolerance=1e-11)
      result["plant_outgoing_lps"].update({k: outgoing[k]/3.6 for k in sources})
      result["pressure_kpa"].update({k: v/1000 for k, v in pressure.items()})
      result["flows_lps"].update({k: v/3.6 for k, v in flow.items()})
      result["balance_residual_lps"].update({k: v/3.6 for k, v in residual.items()})
    except PressureUnresolved as error:
      result["unresolved"].update(dict.fromkeys(terminals, str(error)))
  pressure = result["pressure_kpa"]
  result["pipes"] = {
    key: {"from": a, "to": b, "state": states[key]["state"], "source": states[key]["source"],
          **({"state_source": states[key]["state_source"]} if "state_source" in states[key] else {}),
          "resistance_kpa_per_lps2": states[key].get("resistance_kpa_per_lps2"), "flow_lps": result["flows_lps"].get(key),
          "pressure_drop_kpa": pressure[a] - pressure[b] if a in pressure and b in pressure else None}
    for key, (a, b) in topology.items()}
  return result


def _case(network, case):
  nodes, pipes = network["nodes"], network["topology"]
  loads, plants, states = (_table(case.get(key, {})) for key in ("terminals", "plants", "pipes"))
  expected_loads = {k for k, v in nodes.items() if v["kind"] == "terminal"}
  expected_plants = {k for k, v in nodes.items() if v["kind"] == "plant"}
  if not isinstance(case.get("pressure_datum"), str) or not case["pressure_datum"].strip():
    raise PressureUnresolved("缺少各冷源共用的测压管水头基准")
  if (not _sourced(case) or case.get("complete") is not True or not expected_loads or not expected_plants
      or loads.keys() != expected_loads or states.keys() != pipes["supply"].keys() | pipes["return"].keys()
      or expected_plants != plants.keys()):
    raise PressureUnresolved("工况出处、冷源、末端或管段运行清单不完整")
  circuits = {}
  for side, paths in pipes.items():
    try:
      circuits[side] = _circuit(side, paths, nodes, states, plants, loads)
    except PressureUnresolved as error:
      circuits[side] = {"pressure_kpa": {}, "flows_lps": {}, "balance_residual_lps": {}, "isolated": [],
                        "unresolved": dict.fromkeys(loads, str(error))}
  isolated_duty = {k for side in circuits.values() for k in side["isolated"]
                   if _sourced(loads[k]) and loads[k].get("flow_lps") is not None and _number(loads[k], "flow_lps", minimum=0) > 0}
  plant_balance = {}
  for key in plants:
    supply = circuits["supply"].get("plant_outgoing_lps", {}).get(key)
    returned = circuits["return"].get("plant_outgoing_lps", {}).get(key)
    if supply is None or returned is None:
      plant_balance[key] = {"status": "indeterminate"}
      continue
    residual = supply + returned
    tolerance = max(1e-7, max(abs(supply), abs(returned))*1e-9)
    plant_balance[key] = {"supply_lps": supply, "return_lps": -returned, "residual_lps": residual,
                          "status": "pass" if abs(residual) <= tolerance and min(supply, -returned) >= -tolerance else "indeterminate"}
  rows = {}
  for key, load in sorted(loads.items()):
    supply, returned = (circuits[c]["pressure_kpa"].get(key) for c in ("supply", "return"))
    available = None if supply is None or returned is None else supply - returned
    isolated = [c for c in circuits if key in circuits[c]["isolated"]]
    issue = [v["unresolved"][key] for v in circuits.values() if key in v["unresolved"]]
    flow = load.get("flow_lps")
    minimum = load.get("minimum_dp_kpa")
    status, margin = "indeterminate", None
    if flow is not None and _sourced(load):
      flow = _number(load, "flow_lps", minimum=0)
      if flow == 0:
        status = "not-applicable"
      elif isolated:
        status = "fail"
      elif isolated_duty:
        issue.append("有末端无法建立给定流量的回路，其他末端需按修订后的同时流量重新计算")
      elif any(r["status"] != "pass" for r in plant_balance.values()):
        issue.append("冷源供回水量未闭合或存在反向过流，需补充冷源之间的连通或运行依据")
      elif available is not None and minimum is not None:
        margin = available - _number(load, "minimum_dp_kpa", minimum=0)
        status = "pass" if margin >= -1e-6 else "fail"
    if status == "indeterminate" and not issue:
      issue.append("缺少末端设计流量、最低压差或出处")
    rows[key] = {"status": status, "flow_lps": flow, "minimum_dp_kpa": minimum, "available_dp_kpa": available,
                 "margin_kpa": margin, "source": load.get("source"), "isolated_circuits": isolated, "unresolved": issue}
  ranked = [(r["margin_kpa"], k) for k, r in rows.items() if r["margin_kpa"] is not None]
  statuses = {r["status"] for r in rows.values()}
  status = ("fail" if "fail" in statuses else "indeterminate" if "indeterminate" in statuses else
            "pass" if "pass" in statuses else "not-applicable")
  operating_point = {"pipe_states": {k: v.get("state") for k, v in states.items()},
                     "terminal_flow_lps": {k: v.get("flow_lps") for k, v in loads.items()},
                     **{f"plant_{side}_kpa": {k: v.get(f"{side}_kpa") for k, v in plants.items()} for side in pipes}}
  return {"status": status, "operating_point": operating_point, "source": case["source"], "pressure_datum": case["pressure_datum"], "plant_balance": plant_balance, "circuits": circuits, "terminals": rows,
          "least_measured_margin_terminal": min(ranked)[1] if ranked else None}


def _outage_case(network, base_cases, event):
  """Apply the specified isolation and switching to one independently selected duty."""
  if not isinstance(event, dict) or event.keys() - {"source", "base_case", "base_case_digest", "unavailable_pipes", "switching"}:
    raise ValueError("管段退出方案含未知字段或格式错误")
  base_name = event.get("base_case")
  if not isinstance(base_name, str) or not _sourced(event):
    raise PressureUnresolved("管段退出方案缺少基准工况或出处")
  base = base_cases.get(base_name)
  if not isinstance(base, dict) or canonical_digest(base) != event.get("base_case_digest"):
    raise PressureUnresolved("管段退出方案选定的基准工况缺失或修订不符")
  failed = event.get("unavailable_pipes")
  if not isinstance(failed, list) or not failed:
    raise PressureUnresolved("缺少本次共同退出的管段清单")
  if any(not isinstance(k, str) or not k.strip() for k in failed) or len(set(failed)) != len(failed):
    raise ValueError("退出管段须使用唯一的非空安装编号")
  switching = _table(event.get("switching", {}))
  if set(failed) & switching.keys() or any(v not in ("open", "closed") for v in switching.values()):
    raise ValueError("切换指令须给出其他管段的开闭状态")
  states = dict(_table(base.get("pipes", {})))
  installed = network["topology"]["supply"].keys() | network["topology"]["return"].keys()
  changes = {}
  for pipe, target in (dict.fromkeys(failed, "closed") | switching).items():
    original = states.get(pipe)
    if pipe not in installed or not isinstance(original, dict) or not _sourced(original) or original.get("state") not in ("open", "closed"):
      raise PressureUnresolved(f"{pipe} 缺少安装管段或有出处的基准阀位")
    changes[pipe] = {"before": original["state"], "after": target, "baseline_source": original["source"],
                     "action": "unavailable" if pipe in failed else "switching"}
    states[pipe] = {**original, "state": target, "state_source": event["source"]}
  result = _case(network, {**base, "pipes": states})
  result["pipe_outage"] = {**event, "pipes": changes}
  return result


def water_pressure(network, schedule):
  for obj, kind in ((network, "chilled-water-network"), (schedule, "water-pressure-schedule")):
    if type(obj.get("schema_version")) is not int or obj["schema_version"] != 1 or obj.get("kind") != kind:
      raise ValueError(f"需要版本 1 的 {kind}")
  header = {k: _text(network.get(k)) for k in ("scene_digest", "frame", "scope", "baseline", "water_netlist_digest")}
  issues, cases = [], {}
  if network.get("complete") is not True or network.get("unresolved"):
    issues.append("安装管网的接续或清单不完整")
  if schedule.get("network_digest") != canonical_digest(network):
    issues.append("压力工况与选定的安装管网摘要不一致")
  if not issues:
    base_cases = _table(schedule.get("cases", {}))
    outages = _table(schedule.get("pipe_outages", {}))
    if base_cases.keys() & outages.keys():
      raise ValueError("管段退出工况与基准工况重名")
    for name, case in sorted(base_cases.items()):
      try:
        cases[name] = _case(network, case)
      except PressureUnresolved as error:
        cases[name] = {"status": "indeterminate", "unresolved": [str(error)]}
    for name, event in sorted(outages.items()):
      try:
        cases[name] = _outage_case(network, base_cases, event)
      except PressureUnresolved as error:
        cases[name] = {"status": "indeterminate", "pipe_outage": event, "unresolved": [str(error)]}
  return {"kind": "water-pressure-study", "schema_version": 1, "domain": "hydraulic", **header,
          "terminals": sorted(k for k, v in network["nodes"].items() if v["kind"] == "terminal"),
          "schedule_digest": canonical_digest(schedule), "cases": cases, "unresolved": issues}


def _terminal_evidence(key, row, case):
  if not isinstance(row, dict) or not _sourced(row) or type(row.get("flow_lps")) not in (int, float) or not math.isfinite(row["flow_lps"]):
    return "indeterminate"
  if row["flow_lps"] == 0 and row.get("status") == "not-applicable":
    return "not-applicable"
  if row["flow_lps"] <= 0:
    return "indeterminate"
  if any(key in case.get("circuits", {}).get(side, {}).get("isolated", []) for side in row.get("isolated_circuits", [])
         if side in ("supply", "return")):
    return "fail"
  observed, required = row.get("available_dp_kpa"), row.get("minimum_dp_kpa")
  if (row.get("isolated_circuits") or row.get("unresolved") or not all(type(v) in (int, float) and math.isfinite(v)
                                                                      for v in (observed, required)) or required < 0):
    return "indeterminate"
  if observed < required - 1e-6:
    return "fail"
  return "pass" if row.get("status") == "pass" else "indeterminate"


def _design_check(study, plan):
  """Independent project decision on named duties, traceable to the chosen schedule."""
  result = {"kind": "terminal-pressure-check", "schema_version": 1, "domain": "hydraulic",
            "status": "indeterminate", "source": plan.get("source"), "schedule_digest": plan.get("schedule_digest"),
            "study_digest": canonical_digest(study), "cases": {}, "unresolved": []}
  required = plan.get("required_cases")
  if (not isinstance(required, list) or not required or any(not isinstance(k, str) or not k.strip() for k in required)
      or len(required) != len(set(required)) or not isinstance(result["source"], str) or not result["source"].strip()):
    result["unresolved"].append("项目水力验证缺少有出处的必验工况清单")
    return result
  if (study.get("kind") != "water-pressure-study" or study.get("domain") != "hydraulic"
      or type(study.get("schema_version")) is not int or study["schema_version"] != 1 or study.get("unresolved")
      or not result["schedule_digest"] or result["schedule_digest"] != study.get("schedule_digest")):
    result["unresolved"].append("水力研究缺失、接续未决或工况摘要与项目选择不一致")
    return result
  expected = study.get("terminals")
  if not isinstance(expected, list) or not expected or any(not isinstance(k, str) for k in expected) or len(set(expected)) != len(expected):
    result["unresolved"].append("水力研究缺少明确的末端清单")
    return result
  for key in required:
    case = study.get("cases", {}).get(key, {})
    rows = case.get("terminals") if isinstance(case, dict) else None
    if not isinstance(rows, dict):
      reason = case.get("unresolved") if isinstance(case, dict) else None
      outage = {"pipe_outage": case["pipe_outage"]} if isinstance(case, dict) and "pipe_outage" in case else {}
      case = {**outage, "status": "indeterminate", "unresolved": reason or ["缺少适用工况或逐末端结果"]}
    else:
      states = {_terminal_evidence(k, rows.get(k), case) for k in expected}
      if set(rows) != set(expected):
        states.add("indeterminate")
      status = ("fail" if "fail" in states else "indeterminate" if "indeterminate" in states or "pass" not in states else "pass")
      if status == "pass" and case.get("status") != "pass":
        status = "indeterminate"
      if case.get("status") != status:
        case = {**case, "status": status, "reported_status": case.get("status"),
                "unresolved": ["工况汇总与逐末端可核实的结论不一致"]}
    result["cases"][key] = case
    if case["status"] == "indeterminate":
      result["unresolved"].append(key)
  states = {v["status"] for v in result["cases"].values()}
  result["status"] = "fail" if "fail" in states else "indeterminate" if "indeterminate" in states else "pass"
  return result

def pressure_check(study, plan, observations=None):
  result = _design_check(study, plan)
  checks = []
  if "field_comparison" in plan or (observations is not None and "flow_transfers" not in plan):
    checks.append(("field_comparison", compare_observations, "现场对照"))
  if "flow_transfers" in plan:
    checks.append(("flow_transfers", compare_flow_transfers, "末端切换流量"))
  if checks:
    result["design_status"] = result["status"]
  for key, compare, label in checks:
    if not plan.get("schedule_digest") or plan["schedule_digest"] != study.get("schedule_digest"):
      comparison = {"status": "indeterminate", "reason": "项目选择的工况摘要与计算不符"}
    else:
      comparison = compare(study, plan.get(key), observations)
    result[key] = comparison
    states = {result["status"], comparison["status"]}
    result["status"] = "fail" if "fail" in states else "indeterminate" if "indeterminate" in states else "pass"
    if comparison["status"] == "indeterminate":
      result["unresolved"].append(label)
  return result
