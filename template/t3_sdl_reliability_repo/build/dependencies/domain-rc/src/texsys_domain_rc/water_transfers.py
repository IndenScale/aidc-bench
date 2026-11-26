"""Evaluate observed terminal flow during a selected chilled-water pipe transfer."""

from fractions import Fraction

from texsys.evidence import canonical_digest

from .service_intervals import continuous_service_bounds
from .water_observations import _aggregate, _finite, _named, _unknown, matching_observations


def _window(value):
  if not isinstance(value, list) or len(value) != 2 or not all(_finite(v) for v in value) or value[0] >= value[1]:
    return None
  return tuple(Fraction(str(v)) for v in value)


def _terminal(asset, spec, trace, trial, window):
  if not isinstance(spec, dict) or not isinstance(trace, dict):
    return _unknown("缺少项目末端判据或连续流量记录")
  minimum, limit = spec.get("minimum_flow_lps"), spec.get("maximum_deficit_s")
  if not _finite(minimum) or minimum <= 0 or not _finite(limit) or limit < 0:
    return _unknown("缺少有效的最低流量和允许连续缺流时间")
  if (trace.get("asset") != asset or trace.get("kind") != "continuous-extrema" or trace.get("unit") != "L/s"
      or trace.get("direction") not in ("supply-to-return", "return-to-supply")
      or trace.get("run_id") != trial["run_id"] or trace.get("clock") != trial["clock"]
      or not all(_named(trace.get(key)) for key in ("meter", "source", "calibration_source"))):
    return _unknown("流量记录的末端归属、连续性、方向、仪表、出处、批次或时基未核实")
  error, edge = trace.get("absolute_error_lps"), trace.get("edge_error_s")
  if not all(_finite(v) and v >= 0 for v in (error, edge)) or not isinstance(trace.get("intervals"), list):
    return _unknown("缺少流量或时间边界误差界、连续观测区间")
  segments = []
  threshold, radius = Fraction(str(minimum)), Fraction(str(error))
  for row in trace["intervals"]:
    times = _window(row.get("window_s")) if isinstance(row, dict) else None
    if times is None or (segments and times[0] < segments[-1][1]):
      return _unknown("连续流量区间应有正时长、按时间顺序排列且互不重叠")
    lo, hi = row.get("minimum_lps"), row.get("maximum_lps")
    if any(v is not None and not _finite(v) for v in (lo, hi)) or (lo is not None and hi is not None and lo > hi):
      return _unknown("仪表区间流量极值无效")
    if trace["direction"] == "return-to-supply":
      lo, hi = (None if hi is None else -hi), (None if lo is None else -lo)
    state = None
    if lo is not None and Fraction(str(lo)) - radius >= threshold:
      state = True
    elif hi is not None and Fraction(str(hi)) + radius < threshold:
      state = False
    segments.append((*times, state))
  lower, upper, supplied, deficit, bracketed = continuous_service_bounds(window, segments, Fraction(str(edge)))
  deadline = Fraction(str(limit))
  status = "fail" if lower > deadline else "pass" if upper is not None and upper <= deadline else "indeterminate"
  return {"status": status, "asset": asset, "minimum_flow_lps": minimum, "maximum_deficit_s": limit,
          "longest_deficit_bounds_s": [float(lower), None if upper is None else float(upper)],
          "confirmed_deficit_s": [[float(a), float(b)] for a, b in deficit],
          "confirmed_service_s": [[float(a), float(b)] for a, b in supplied], "bracketed": bracketed,
          **{k: trace[k] for k in ("meter", "direction", "source", "calibration_source", "absolute_error_lps", "edge_error_s")}}


def _feedback(record, case, trial):
  states = case.get("operating_point", {}).get("pipe_states")
  if (not states or not isinstance(record, dict) or record.get("pipe_states") != states
      or record.get("run_id") != trial["run_id"] or record.get("clock") != trial["clock"] or not _named(record.get("source"))):
    return None
  t, e = record.get("time_s"), record.get("time_error_s")
  if not _finite(t) or not _finite(e) or e < 0:
    return None
  t, e = Fraction(str(t)), Fraction(str(e))
  return t - e, t + e


def _trial(study, case_name, selection, trials):
  case = study.get("cases", {}).get(case_name, {})
  outage = case.get("pipe_outage") if isinstance(case, dict) else None
  if not isinstance(outage, dict) or not _named(outage.get("base_case")):
    return _unknown("所选工况缺少安装管段退出与基准工况的关联")
  base = study["cases"].get(outage["base_case"])
  if not isinstance(base, dict):
    return _unknown("缺少所选退出事件的基准工况")
  if (not isinstance(selection, dict) or not _named(selection.get("run_id")) or not _named(selection.get("clock"))
      or not isinstance(selection.get("terminals"), dict) or not selection["terminals"]):
    return _unknown("缺少试验选择、时基或必测末端清单")
  run_id = selection["run_id"]
  trial = trials.get(run_id)
  if (not isinstance(trial, dict) or canonical_digest(trial) != selection.get("run_digest")
      or trial.get("run_id") != run_id or trial.get("case") != case_name or not _named(trial.get("source"))
      or trial.get("clock") != selection["clock"]):
    return _unknown("选定试验缺失或修订、工况、时基不符")
  window = _window(selection.get("window_s"))
  before, after = _feedback(trial.get("before"), base, trial), _feedback(trial.get("after"), case, trial)
  if not window or not before or not after or not window[0] <= before[0] <= before[1] < after[0] <= after[1] <= window[1]:
    return _unknown("缺少核验窗口内同批次、按序且与基准及退出工况一致的阀位反馈")
  if trial["before"]["pipe_states"] == trial["after"]["pipe_states"]:
    return _unknown("前后阀位相同，所选批次未证实发生了水路切换")
  traces = trial.get("terminals")
  if not isinstance(traces, dict):
    traces = {}
  terminals = {key: (_terminal(key, spec, traces.get(key), trial, window) if key in study.get("terminals", [])
                     else _unknown("末端未绑定本版安装管网"))
               for key, spec in selection["terminals"].items()}
  return {"status": _aggregate(terminals), "terminals": terminals, "base_case": outage["base_case"],
          "window_s": selection["window_s"], "source": trial["source"], "run_id": run_id, "run_digest": selection["run_digest"],
          "clock": trial["clock"], "before": trial["before"], "after": trial["after"]}


def compare_flow_transfers(study, plan, observations):
  if not isinstance(plan, dict) or not _named(plan.get("source")) or not isinstance(plan.get("cases"), dict) or not plan["cases"]:
    return _unknown("缺少有出处的水路切换试验选择")
  if not matching_observations(study, observations) or not isinstance(observations.get("transfers"), dict):
    return _unknown("水路切换记录缺失或未绑定同版场景、网表与工况表")
  cases = {key: _trial(study, key, selection, observations["transfers"]) for key, selection in plan["cases"].items()}
  return {"status": _aggregate(cases), "source": plan["source"], "observations_digest": canonical_digest(observations), "cases": cases}
