"""Pair surface temperature and local dew point over confirmed common time intervals."""

import math
from datetime import datetime
from decimal import Decimal

from texsys.evidence import canonical_digest

from .netlist import _table, _text


def _number(value):
  if type(value) not in (float, int) or not math.isfinite(value):
    raise ValueError("Expected a finite observation value.")
  return value


def _delta(a, b):
  return _number(float(Decimal(str(_number(a))) - Decimal(str(_number(b)))))


def reading_bounds(value, error):
  if _number(error) < 0:
    raise ValueError("Negative measurement uncertainty.")
  return [_delta(value, error), _delta(value, -error)]


def temperature_margin_bounds(surface, dew):
  return [_delta(surface[0], dew[1]), _delta(surface[1], dew[0])]


def _basis(row, key):
  if row.get(key) is None or row[key] == "":
    raise KeyError(key)
  return _text(row[key])


def _interval(value):
  if not isinstance(value, list) or len(value) != 2 or _number(value[0]) >= _number(value[1]):
    raise ValueError("Expected an increasing time interval.")
  return value


def _channel(run, point, quantity):
  channel = run["channels"][point]
  if channel is None or channel.get("quantity") != quantity:
    raise KeyError("channel-quantity-mismatch")
  for key in ("source", "calibration", "interval_basis"):
    _basis(channel, key)
  if channel.get("time_error_s") is None or channel.get("intervals") is None:
    raise KeyError("missing-time-error-or-intervals")
  error = _number(channel["time_error_s"])
  if error < 0:
    raise ValueError("Negative timestamp error.")
  spans, last_end = [], None
  for row in channel["intervals"]:
    a, b = _interval(row["time_s"])
    if last_end is not None and a < last_end:
      raise ValueError("Overlapping intervals on a measurement channel.")
    last_end = b
    if row.get("value_c") is None or row.get("error_c") is None:
      continue
    v, e = _number(row["value_c"]), _number(row["error_c"])
    bounds = reading_bounds(v, e)
    # Retain only times guaranteed to lie within this recorded envelope.
    lo, hi = _delta(a, -error), _delta(b, error)
    if lo < hi:
      spans.append((lo, hi, bounds))
  return spans, {k: channel[k] for k in ("source", "calibration", "interval_basis", "time_error_s")}


def _pair(case, run, start, end):
  surface_point, dew_point = (_text(case[key]) for key in ("surface_point", "dew_point"))
  if surface_point == dew_point:
    raise KeyError("surface-and-dew-channels-not-distinct")
  surface, surface_basis = _channel(run, surface_point, "surface-temperature")
  dew, dew_basis = _channel(run, dew_point, "air-dew-point")
  spans, gaps = [], []
  i = j = 0
  cursor = start
  while i < len(surface) and j < len(dew):
    a, b, s = surface[i]
    c, d, t = dew[j]
    lo, hi = max(start, a, c), min(end, b, d)
    if lo < hi:
      if cursor < lo:
        gaps.append([cursor, lo])
      spans.append({"time_s": [lo, hi], "surface_bounds_c": s, "dew_bounds_c": t,
                    "margin_bounds_c": temperature_margin_bounds(s, t)})
      cursor = hi
    if b <= d:
      i += 1
    if d <= b:
      j += 1
  if cursor < end:
    gaps.append([cursor, end])
  return {"surface_point": surface_point, "dew_point": dew_point, "surface_basis": surface_basis,
          "dew_basis": dew_basis, "spans": spans, "gaps_s": gaps}


def dew_margin_history(plan, observations):
  if type(plan.get("schema_version")) is not int or plan["schema_version"] != 1 or plan.get("kind") != "dew-observation-plan":
    raise ValueError("Expected a version 1 dew-observation-plan.")
  frame, scene = (_text(plan[k]) for k in ("frame", "scene_digest"))
  result = {"schema_version": 1, "kind": "dew-margin-history", "domain": "thermal", "frame": frame,
            "scene_digest": scene, "plan_digest": canonical_digest(plan), "observations_digest": canonical_digest(observations),
            "segments": {}, "unresolved": []}
  if (type(observations.get("schema_version")) is not int or observations["schema_version"] != 1 or
      (observations.get("kind"), observations.get("frame"), observations.get("scene_digest")) != ("dew-observations", frame, scene)):
    result["unresolved"].append({"reason": "missing-observations-or-revision-mismatch"})
    return result
  runs = _table(observations["runs"])
  for key, spec in sorted(_table(plan["segments"]).items()):
    index = spec["segment_index"]
    if type(index) is not int or index < 0:
      raise ValueError("Expected a nonnegative segment index.")
    segment = result["segments"][key] = {"pipe": _text(spec["pipe"]), "prim": _text(spec["prim"]), "segment_index": index, "cases": {}}
    for name, case in sorted(_table(spec["cases"]).items()):
      try:
        start, end = _interval(case["window_s"])
        run_id = _text(case["run"])
        run = runs[run_id]
        if case.get("run_digest") != canonical_digest(run) or (run.get("segment"), run.get("case")) != (key, name):
          raise KeyError("wrong-run-or-revision")
        if (run.get("pipe"), run.get("prim"), type(run.get("segment_index")), run.get("segment_index")) != (
            segment["pipe"], segment["prim"], int, index):
          raise KeyError("observation-segment-mismatch")
        origin = _basis(case, "time_origin")
        if datetime.fromisoformat(origin.replace("Z", "+00:00")).utcoffset() is None:
          raise ValueError("Observation time origin requires a UTC offset.")
        clock = _text(case["clock"])
        if (origin, clock) != (run.get("time_origin"), run.get("clock")):
          raise KeyError("time-base-mismatch")
        row = {"source": _basis(run, "source"), "clock_source": _basis(run, "clock_source"), "location_basis": _basis(case, "location_basis"), "run": run_id,
               "run_digest": case["run_digest"], "clock": clock, "time_origin": origin, "window_s": [start, end]}
        row.update(_pair(case, run, start, end))
        segment["cases"][name] = row
        if row["gaps_s"]:
          result["unresolved"].append({"segment": key, "case": name, "gaps_s": row["gaps_s"]})
      except KeyError as error:
        result["unresolved"].append({"segment": key, "case": name, "missing": error.args[0]})
  return result
