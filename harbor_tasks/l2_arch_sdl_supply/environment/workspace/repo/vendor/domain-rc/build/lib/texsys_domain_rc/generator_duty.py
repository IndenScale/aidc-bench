"""Site-adjusted generator ratings and time-weighted duty on project-defined averaging windows."""

import math
from bisect import bisect_right

from texsys.evidence import canonical_digest, file_digest

from .netlist import _table, _text
from .usd_geometry import open_scene


def _number(value, *, positive=False):
  if value is None:
    return None
  if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or positive and value == 0:
    raise ValueError("发电机工程量须为有效范围内的有限数")
  return value


def _source(row):
  value = row.get("source")
  return value.strip() if isinstance(value, str) and value.strip() else None


def generator_ratings(scene, catalog):
  """Bind the installed generator identity to a sourced product rating and its site correction."""
  from pxr import Usd

  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  frame, digest = _text(root.GetCustomDataByKey("frame")), file_digest(scene)
  if catalog.get("kind") != "generator-rating-catalog" or type(catalog.get("schema_version")) is not int or catalog["schema_version"] != 1:
    raise ValueError("需要版本 1 的发电机额定资料")
  installed, rows, missing = {}, {}, []
  for prim in Usd.PrimRange(root):
    if prim.GetCustomDataByKey("role") == "standby-power-equipment" and prim.GetCustomDataByKey("equipmentKind") == "generator":
      key = _text(prim.GetCustomDataByKey("identity"))
      if key in installed:
        raise ValueError(f"发电机标识重复：{key}")
      installed[key] = {"prim": str(prim.GetPath()), "system": _text(prim.GetCustomDataByKey("systemId"))}
  binding = (catalog.get("scene_digest"), catalog.get("frame")) == (digest, frame)
  specs = _table(catalog.get("generators", {}))
  if binding and specs.keys() - installed.keys():
    raise ValueError("额定资料引用未定位的机组")
  for key, placement in sorted(installed.items()):
    spec = _table(specs.get(key, {})) if binding else {}
    source = _source(spec)
    site_source = spec.get("site_source")
    basis = spec.get("rating_basis")
    if basis not in (None, "unlimited", "500h", "other"):
      raise ValueError("未知的发电机运行额定类别")
    limit = _number(spec.get("product_annual_limit_hours"), positive=True)
    row = {**placement, "rating_basis": basis if source else None, "rating_source": source, "site_source": site_source,
           "product_annual_limit_hours": limit if source else None}
    for unit in ("kw", "kva"):
      nameplate = _number(spec.get(f"rated_{unit}"), positive=True)
      factor = _number(spec.get(f"site_factor_{unit}"))
      if factor is not None and factor > 1:
        raise ValueError("现场降额系数须在 0 至 1 之间")
      qualified = source and isinstance(site_source, str) and site_source.strip() and nameplate is not None and factor is not None
      row.update({f"rated_{unit}": nameplate, f"site_factor_{unit}": factor, f"available_{unit}": nameplate * factor if qualified else None})
    if None not in (row["rated_kw"], row["rated_kva"]) and row["rated_kw"] > row["rated_kva"]:
      raise ValueError(f"{key} 的额定有功功率不得大于额定视在功率")
    if None not in (row["available_kw"], row["available_kva"]):
      row["available_kw"] = min(row["available_kw"], row["available_kva"])
    if any(row[k] is None for k in ("available_kw", "available_kva", "rating_basis")):
      missing.append(key)
    rows[key] = row
  return {"kind": "generator-ratings", "schema_version": 1, "domain": "electrical", "frame": frame, "scene_digest": digest,
          "catalog_digest": canonical_digest(catalog), "catalog_matches_scene": binding, "generators": rows, "unresolved": missing}


def _peak(intervals, window):
  """A moving integral changes slope only when either end crosses a load transition."""
  times, energy = [intervals[0][0]], [0.]
  levels = []
  for start, end, kw in intervals:
    times.append(end)
    levels.append(kw)
    energy.append(energy[-1] + (end - start) * kw)

  def integral(t):
    index = min(bisect_right(times, t) - 1, len(levels) - 1)
    return energy[index] + (t - times[index]) * levels[index]

  first, last = times[0], times[-1] - window
  candidates = {t for edge in times for t in (edge, edge - window) if first <= t <= last}
  if not candidates:
    return None
  average, start = max(((integral(t + window) - integral(t)) / window, -t) for t in candidates)
  return {"average_kw": average, "start_s": -start, "end_s": -start + window}


def generator_load_study(ratings, schedule):
  for value, kind in ((ratings, "generator-ratings"), (schedule, "generator-load-schedule")):
    if value.get("kind") != kind or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
      raise ValueError(f"需要版本 1 的 {kind}")
  result = {"kind": "generator-load-study", "schema_version": 1, "domain": "electrical",
            "scene_digest": ratings["scene_digest"], "ratings_digest": canonical_digest(ratings),
            "schedule_digest": canonical_digest(schedule), "generators": {}, "unresolved": []}
  if schedule.get("ratings_digest") != result["ratings_digest"] or not ratings.get("catalog_matches_scene"):
    result["unresolved"].append("负荷时序与已定位的机组额定资料不一致")
    return result
  keys = set(ratings["generators"])
  for name, case in sorted(_table(schedule.get("cases", {})).items()):
    case = _table(case)
    window = _number(case.get("averaging_seconds"), positive=True)
    horizon = _number(case.get("duration_seconds"), positive=True)
    source = _source(case)
    intervals = case.get("intervals", [])
    if not isinstance(intervals, list):
      raise ValueError("机组负荷时序应为有序区间")
    spans = {k: [] for k in keys}
    last = 0.
    for interval in intervals:
      interval = _table(interval)
      start, end = (_number(interval.get(field)) for field in ("start_s", "end_s"))
      if start is None or end is None or start < last or end <= start or horizon is not None and end > horizon:
        raise ValueError(f"{name} 负荷区间超出工况范围、逆序或重叠")
      loads = _table(interval.get("generator_kw", {}))
      if loads.keys() - keys:
        raise ValueError(f"{name} 的负荷分配含有未定位的机组")
      for k in keys:
        kw = _number(loads.get(k))
        if kw is not None and _source(interval):
          if not spans[k] or spans[k][-1][-1][1] != start:
            spans[k].append([])
          spans[k][-1].append((start, end, kw))
      last = end
    for k, blocks in sorted(spans.items()):
      peaks = [peak for block in blocks if (peak := _peak(block, window))] if window and source else []
      witness = max(peaks, key=lambda v: v["average_kw"], default=None)
      complete = bool(witness and case.get("complete") is True and len(blocks) == 1
                      and blocks[0][0][0] == 0 and blocks[0][-1][1] == horizon)
      result["generators"].setdefault(k, {})[name] = {"complete": complete, "peak_window": witness,
          "averaging_seconds": window, "duration_seconds": horizon, "source": source,
          "interval_sources": sorted({_source(i) for i in intervals if k in i.get("generator_kw", {}) and _source(i)})}
      if not complete:
        result["unresolved"].append({"generator": k, "case": name})
  return result
