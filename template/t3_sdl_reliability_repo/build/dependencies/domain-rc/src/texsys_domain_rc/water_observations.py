"""Compare commissioned steady-state readings with an installed chilled-water study."""

import math

from texsys.evidence import canonical_digest


def _named(value):
  return isinstance(value, str) and bool(value.strip())


def _finite(value):
  return type(value) in (int, float) and math.isfinite(value)


def _unknown(reason):
  return {"status": "indeterminate", "reason": reason}


def _aggregate(records):
  states = {r["status"] for r in records.values()}
  return "fail" if "fail" in states else "pass" if states == {"pass"} else "indeterminate"


def _reading(row, predicted, tolerance, unit, run_id, *, sign=1):
  if not isinstance(row, dict) or not _named(row.get("meter")) or not _named(row.get("source")):
    return _unknown("缺少仪表标识或读数出处")
  if row.get("run_id", run_id) != run_id:
    return _unknown("测量记录与选定的稳态试验批次不一致")
  value, uncertainty = row.get("value"), row.get("uncertainty")
  if (row.get("unit") != unit or not all(_finite(v) for v in (value, uncertainty, tolerance, predicted))
      or uncertainty < 0 or tolerance < 0):
    return _unknown("读数、仪表不确定度、计算值、项目容差或单位未核实")
  error = sign * value - predicted
  # Compensate only for floating-point rounding at the acceptance boundary.
  upper, lower = abs(error) + uncertainty, max(0., abs(error) - uncertainty)
  if upper <= tolerance or math.isclose(upper, tolerance, abs_tol=1e-9, rel_tol=0):
    status = "pass"
  elif lower > tolerance and not math.isclose(lower, tolerance, abs_tol=1e-9, rel_tol=0):
    status = "fail"
  else:
    status = "indeterminate"
  return {"status": status, "unit": unit, "meter": row["meter"], "source": row["source"],
          "raw_value": value, "normalized_value": sign * value, "uncertainty": uncertainty,
          "prediction": predicted, "difference": error, "absolute_tolerance": tolerance}


def _boundary(case, snapshot, plan):
  boundary = case.get("operating_point")
  if not isinstance(boundary, dict) or not snapshot or snapshot.get("steady") is not True or not _named(snapshot.get("run_id")) or not _named(snapshot.get("source")):
    return _unknown("缺少稳态运行记录、出处或模型工况边界")
  if snapshot.get("pressure_datum") != case.get("pressure_datum") or not _named(case.get("pressure_datum")):
    return _unknown("压力读数和计算采用的测压管水头基准不一致")
  if (not case.get("plant_balance") or any(v.get("status") != "pass" for v in case["plant_balance"].values())
      or any(v.get("isolated_circuits") and v.get("flow_lps") for v in case.get("terminals", {}).values())):
    return _unknown("模型尚未建立闭合的同时流量工况")
  valves = snapshot.get("pipe_states", {})
  if valves != boundary["pipe_states"] or not _named(snapshot.get("valve_source")):
    return _unknown("现场阀位或出处与计算工况不一致")
  points = {}
  for quantity, unit, tolerance in (("plant_supply_kpa", "kPa", "boundary_tolerance_kpa"),
                                    ("plant_return_kpa", "kPa", "boundary_tolerance_kpa"),
                                    ("terminal_flow_lps", "L/s", "boundary_tolerance_lps")):
    expected, observed = boundary[quantity], snapshot.get(quantity, {})
    if not isinstance(observed, dict) or observed.keys() != expected.keys():
      return _unknown(f"{quantity} 边界测点与计算对象不符")
    points[quantity] = {k: _reading(observed[k], v, plan.get(tolerance), unit, snapshot["run_id"]) for k, v in expected.items()}
  qualified = all(r["status"] == "pass" for group in points.values() for r in group.values())
  return {"status": "pass" if qualified else "indeterminate", "readings": points, "valve_source": snapshot["valve_source"],
          "run_id": snapshot["run_id"], "source": snapshot["source"]}


def _point(spec, sample, case, run_id):
  if not isinstance(spec, dict) or not isinstance(sample, dict):
    return _unknown("缺少必测点定义或读数")
  kind, asset = spec.get("quantity"), spec.get("asset")
  if not _named(asset) or (kind, asset) != (sample.get("quantity"), sample.get("asset")):
    return _unknown("读数对象或物理量与必测点不符")
  if kind == "terminal-dp":
    terminal = case.get("terminals", {}).get(asset, {})
    if terminal.get("margin_kpa") is None or terminal.get("status") not in ("pass", "fail"):
      return _unknown("所选末端缺少已求得的工作压差")
    ends, prediction, unit = ["supply", "return"], terminal["available_dp_kpa"], "kPa"
  elif kind == "pipe-flow":
    circuit = spec.get("circuit")
    if circuit not in ("supply", "return") or sample.get("circuit") != circuit:
      return _unknown("供回水回路身份不符")
    pipe = case.get("circuits", {}).get(circuit, {}).get("pipes", {}).get(asset, {})
    if not pipe:
      return _unknown("研究缺少选定的管段")
    ends, prediction, unit = [pipe["from"], pipe["to"]], pipe.get("flow_lps"), "L/s"
  else:
    return _unknown("未知测点物理量")
  orientation = sample.get("direction")
  if orientation != ends and orientation != ends[::-1]:
    return _unknown("仪表正方向与实施端点或压差取压口不符")
  result = _reading(sample, prediction, spec.get("absolute_tolerance"), unit, run_id, sign=1 if orientation == ends else -1)
  result["agreement_status"] = result["status"]
  if kind == "terminal-dp" and "normalized_value" in result:
    value, uncertainty, minimum = result["normalized_value"], result["uncertainty"], terminal["minimum_dp_kpa"]
    low, high = value - uncertainty, value + uncertainty
    if low >= minimum or math.isclose(low, minimum, rel_tol=0, abs_tol=1e-9):
      service = "pass"
    elif high < minimum and not math.isclose(high, minimum, rel_tol=0, abs_tol=1e-9):
      service = "fail"
    else:
      service = "indeterminate"
    result.update(measured_service_status=service, minimum_dp_kpa=minimum)
    result["status"] = _aggregate({"agreement": {"status": result["agreement_status"]}, "service": {"status": service}})
  return {**result, "asset": asset, "quantity": kind, "direction": orientation, "reference_direction": ends}


def matching_observations(study, observations):
  return (isinstance(observations, dict) and observations.get("kind") == "water-pressure-observations"
          and type(observations.get("schema_version")) is int and observations["schema_version"] == 1
          and study.get("kind") == "water-pressure-study" and study.get("domain") == "hydraulic"
          and type(study.get("schema_version")) is int and study["schema_version"] == 1 and not study.get("unresolved")
          and all(_named(study.get(k)) and observations.get(k) == study[k]
                  for k in ("scene_digest", "water_netlist_digest", "schedule_digest", "baseline", "frame", "scope")))


def compare_observations(study, plan, observations):
  result = {"status": "indeterminate", "cases": {}, "source": plan.get("source") if isinstance(plan, dict) else None}
  if not isinstance(plan, dict) or not _named(result["source"]) or not isinstance(plan.get("cases"), dict) or not plan["cases"]:
    return {**result, "reason": "缺少现场对照计划、适用工况或其出处"}
  if not matching_observations(study, observations) or not isinstance(observations.get("cases"), dict):
    return {**result, "reason": "现场资料缺失或未绑定同一安装场景、水力网表和计算工况"}
  result["observations_digest"] = canonical_digest(observations)
  for name, points in plan["cases"].items():
    case = study.get("cases", {}).get(name, {})
    snapshot = observations["cases"].get(name, {})
    if not isinstance(snapshot, dict) or not isinstance(points, dict) or not points:
      result["cases"][name] = _unknown("缺少必测点清单或现场快照")
      continue
    boundary = _boundary(case, snapshot, plan)
    evidence = {"operating_point": boundary}
    if boundary["status"] != "pass":
      result["cases"][name] = {**evidence, **_unknown("现场和模型的运行边界未对齐")}
      continue
    samples = snapshot.get("readings", {})
    if not isinstance(samples, dict):
      samples = {}
    comparisons = {key: _point(spec, samples.get(key), case, snapshot["run_id"]) for key, spec in points.items()}
    result["cases"][name] = {**evidence, "readings": comparisons, "status": _aggregate(comparisons)}
  result["status"] = _aggregate(result["cases"])
  return result
