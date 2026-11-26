"""Read independent steady-state room differential-pressure observations in Pa."""

import math
from datetime import datetime

from texsys.evidence import canonical_digest


def _named(value):
  return isinstance(value, str) and bool(value.strip())


def pressure_run(survey, selected_digest, *, baseline, frame, scene_digest, case):
  """Resolve the reviewed field run without requiring a solved airflow model."""
  if (not isinstance(survey, dict) or type(survey.get("schema_version")) is not int or survey["schema_version"] != 1
      or survey.get("kind") != "room-pressure-observations" or survey.get("domain") != "hvac"
      or not _named(baseline) or (survey.get("baseline"), survey.get("frame"), survey.get("scene_digest")) !=
      (baseline, frame, scene_digest)):
    return {}, "缺少与当前基线、场景及坐标系对应的压差测量记录"
  cases = survey.get("cases")
  run = cases.get(case) if isinstance(cases, dict) else None
  if not isinstance(run, dict) or not _named(selected_digest) or canonical_digest(run) != selected_digest:
    return {}, "工况缺少项目选定修订的压差测量批次"
  if (run.get("steady_state") is not True or not all(_named(run.get(k)) for k in ("run_id", "source", "observed_at"))
      or not isinstance(run.get("rooms"), dict)):
    return {}, "稳态测量批次的工况依据、时间或测点表不完整"
  try:
    timestamp = datetime.fromisoformat(run["observed_at"])
    if timestamp.utcoffset() is None:
      raise ValueError
  except ValueError:
    return {}, "测量时间需要含时区的 ISO 8601 日期时间"
  return run, None


def room_pressure_interval(run, room, reference):
  """Normalize meter high-minus-low to room-minus-reference, retaining uncertainty."""
  group = run["rooms"].get(room)
  row = group.get(reference) if isinstance(group, dict) else None
  if not isinstance(row, dict):
    return {"unresolved": f"缺少 {room} 对 {reference} 的独立压差读数"}
  if row.get("run_id", run["run_id"]) != run["run_id"]:
    return {"unresolved": "测点与选定稳态批次不一致"}
  if not all(_named(row.get(k)) for k in ("meter", "source", "calibration_source")):
    return {"unresolved": "缺少压差仪表标识、读数出处或校准依据"}
  taps = row.get("high"), row.get("low")
  if taps not in ((room, reference), (reference, room)) or room == reference:
    return {"unresolved": "仪表高低压取压端与当前房间及参照边界不符"}
  value, uncertainty = row.get("value"), row.get("uncertainty")
  if (row.get("unit") != "Pa" or not all(type(v) in (int, float) and math.isfinite(v) for v in (value, uncertainty))
      or uncertainty < 0):
    return {"unresolved": "缺少有效的 Pa 读数或非负仪表不确定度"}
  delta = value if taps[0] == room else -value
  interval = [delta - uncertainty, delta + uncertainty]
  if not all(math.isfinite(v) for v in interval):
    return {"unresolved": "压差观测区间超出有限数值范围"}
  return {"difference_pa": delta, "interval_pa": interval, "uncertainty_pa": uncertainty,
          "raw_value_pa": value, "high": taps[0], "low": taps[1], "meter": row["meter"],
          "measurement_source": row["source"], "calibration_source": row["calibration_source"]}
