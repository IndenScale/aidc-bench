"""Steady heat balance and sensible storage, using explicit engineering units."""

import math
from itertools import pairwise


def heat_balance(power_kw, heat_flows_kw, tolerance_kw):
  return math.isclose(power_kw, sum(heat_flows_kw), abs_tol=tolerance_kw, rel_tol=0)


def stored_energy_kwh(volume_m3, temperature_difference_k, usable_fraction, heat_capacity_kwh_m3_k):
  return volume_m3 * temperature_difference_k * usable_fraction * heat_capacity_kwh_m3_k


def support_minutes(energy_kwh, sustained_load_kw):
  if sustained_load_kw <= 0:
    raise ValueError("Sustained load must be positive.")
  return 60 * energy_kwh / sustained_load_kw


def rack_heat_allocation(power, rejection):
  """Join independently authored kW schedules by operating case and stable equipment ID."""
  header = {}
  for source, kind in ((power, "operating-power"), (rejection, "heat-rejection")):
    if (source.get("schema_version") != 1 or type(source["schema_version"]) is not int
        or source.get("kind") != kind or type(source.get("complete")) is not bool):
      raise ValueError(f"Invalid version 1 {kind} schedule.")
    for key in ("baseline", "case", "zone", "frame", "source"):
      if not isinstance(source.get(key), str) or not source[key].strip():
        raise ValueError(f"{kind} requires {key}.")
    for key in ("baseline", "case", "zone", "frame"):
      if header.setdefault(key, source[key]) != source[key]:
        raise ValueError(f"Incompatible electrical and thermal {key}.")
    if not isinstance(source.get("items"), dict):
      raise ValueError(f"{kind} requires an equipment schedule.")
  items, unresolved = {}, []
  for identity in sorted(power["items"].keys() | rejection["items"].keys()):
    if not isinstance(identity, str) or not identity.strip():
      raise ValueError("Invalid equipment identity.")
    row = {}
    missing = []
    for schedule, fields in ((power, ("power_kw", "basis")), (rejection, ("room_kw", "liquid_kw", "outside_kw"))):
      record = schedule["items"].get(identity, {})
      if not isinstance(record, dict):
        raise ValueError(f"{identity} requires an observation record.")
      for key in fields:
        value = record.get(key)
        if value is None:
          missing.append(key)
        elif key == "basis":
          if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{identity} has an invalid power basis.")
          row[key] = value
        elif type(value) not in (float, int) or not math.isfinite(value) or value < 0:
          raise ValueError(f"{identity}.{key} must be a finite nonnegative quantity.")
        else:
          row[key] = value
    if missing:
      unresolved.append({"instance": identity, "missing": missing})
    else:
      row["residual_kw"] = row["power_kw"] - math.fsum(row[key] for key in ("room_kw", "liquid_kw", "outside_kw"))
      items[identity] = row
  return {"schema_version": 1, "kind": "rack-heat-allocation", **header, "items": items,
          "source": f"{power['source']} / {rejection['source']}",
          "complete": power["complete"] and rejection["complete"] and not unresolved, "unresolved": unresolved}

def temperature_transition(samples):
  """Adjacent absolute slopes and the least surface-to-dew-point margin in a sampled sequence."""
  if len(samples) < 2:
    raise ValueError("At least two temperature samples are required.")
  steps = []
  for time, temperature, dew, surface in samples:
    if not all(math.isfinite(v) for v in (time, temperature, dew, surface)) or time < 0:
      raise ValueError("Finite readings and nonnegative elapsed hours are required.")
  for first, last in pairwise(samples):
    elapsed = last[0] - first[0]
    if elapsed <= 0:
      raise ValueError("温变序列的时刻需严格递增")
    steps.append({"start_h": first[0], "end_h": last[0], "interval_h": elapsed,
                  "rate_c_per_h": abs(last[1] - first[1]) / elapsed})
  time, _, dew, surface = min(samples, key=lambda row: row[3] - row[2])
  return {"steps": steps, "peak_rate_c_per_h": max(step["rate_c_per_h"] for step in steps),
          "maximum_interval_h": max(step["interval_h"] for step in steps),
          "minimum_margin_sample": {"elapsed_hours": time, "dew_point_c": dew, "minimum_surface_c": surface}}
