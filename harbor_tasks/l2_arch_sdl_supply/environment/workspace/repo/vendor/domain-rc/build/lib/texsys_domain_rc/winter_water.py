"""Review declared winter operating evidence for the wetted sections of condenser-water systems."""

import math

from texsys.evidence import canonical_digest, file_digest

from .usd_geometry import open_scene


def _named(value):
  return isinstance(value, str) and bool(value.strip())


def water_inventory(path):
  from pxr import Sdf, Usd

  stage = open_scene(path)
  root = stage.GetDefaultPrim()
  plants, sections, ids = {}, {}, set()
  for prim in Usd.PrimRange(root):
    role = prim.GetCustomDataByKey("role")
    if role not in ("water-cooled-chiller", "cooling-water-section"):
      continue
    key = prim.GetAttribute("texsys:identity").Get()
    if not _named(key) or key in ids:
      raise ValueError("水冷机组与冷却水分段需要独立设备标识")
    ids.add(key)
    if role == "water-cooled-chiller":
      plants[key] = str(prim.GetPath())
    else:
      attr = prim.GetAttribute("texsys:waterChillers")
      if attr and attr.GetTypeName() != Sdf.ValueTypeNames.StringArray:
        raise ValueError("冷却水分段的机组标识应为字符串数组")
      owners = attr.Get() if attr else None
      sections[key] = {"prim": str(prim.GetPath()), "plants": sorted(owners) if owners is not None else []}
  valid = all(row["plants"] and len(set(row["plants"])) == len(row["plants"]) and set(row["plants"]) <= plants.keys()
              for row in sections.values())
  covered = {p for row in sections.values() for p in row["plants"]}
  return {"plants": plants, "sections": sections, "frame": root.GetCustomDataByKey("frame"),
          "baseline": root.GetCustomDataByKey("baseline"), "plants_complete": root.GetCustomDataByKey("hvacEnergyInventoryComplete") is True,
          "sections_complete": root.GetCustomDataByKey("coolingWaterSectionsComplete") is True and valid and covered == plants.keys()}


def _finite(value):
  return type(value) in (int, float) and math.isfinite(value)


def _interval(value, *, nonnegative=False):
  return (isinstance(value, list) and len(value) == 2 and all(type(v) in (float, int) and math.isfinite(v) for v in value)
          and value[0] <= value[1] and (not nonnegative or value[0] >= 0))


def _measure(row, duration):
  if not isinstance(row, dict) or not all(_named(row.get(k)) for k in ("method", "action", "source")):
    return {"status": "indeterminate", "reason": "缺少防冻措施、验算方法或工程依据"}
  result = {k: row[k] for k in ("method", "action", "source")}
  window = row.get("window_h")
  if not _interval(window, nonnegative=True) or not 0 <= window[0] < window[1] <= duration:
    return {**result, "status": "indeterminate", "reason": "缺少工况时段内可定位的措施证据区间"}
  result["window_h"] = window
  if row["method"] == "fluid-temperature":
    fluid, freezing = row.get("minimum_fluid_c"), row.get("freezing_point_c")
    if not (_interval(fluid) and _interval(freezing) and _named(row.get("fluid_source"))):
      return {**result, "status": "indeterminate", "reason": "缺少整个工况的最低液温区间、介质冰点区间或物性依据"}
    low, high = fluid[0]-freezing[1], fluid[1]-freezing[0]
    if not all(math.isfinite(v) for v in (low, high)):
      raise ValueError("温差超出有限数值范围")
    return {**result, "minimum_fluid_c": fluid, "freezing_point_c": freezing, "fluid_source": row["fluid_source"],
            "margin_k": [low, high], "status": "pass" if low > 0 else "fail" if high <= 0 else "indeterminate"}
  if row["method"] == "drain-down":
    volume = row.get("residual_volume_l")
    if not _interval(volume, nonnegative=True):
      return {**result, "status": "indeterminate", "reason": "缺少排空后残留液量的非负区间"}
    return {**result, "residual_volume_l": volume,
            "status": "pass" if volume[1] == 0 else "fail" if volume[0] > 0 else "indeterminate"}
  return {**result, "status": "indeterminate", "reason": "该措施的专业验算结果尚未接入"}


def _adverse_window(methods, duration):
  """Locate a shared shortfall without assuming that separate temperature minima coincide."""
  if not methods:
    return [0, duration]
  if any(row["status"] != "fail" for row in methods.values()):
    return None
  # A strictly positive lower bound on retained water rules out full drainage throughout its window.
  drains = [row["window_h"] for row in methods.values() if row["method"] == "drain-down"]
  start = max((w[0] for w in drains), default=0)
  end = min((w[1] for w in drains), default=duration)
  minima = [row["window_h"] for row in methods.values() if row["method"] == "fluid-temperature"]
  if not minima and start < end:
    return [start, end]
  if len(minima) == 1 and start <= minima[0][0] < minima[0][1] <= end:
    return minima[0]
  return None


def _section(record, duration):
  if not isinstance(record, dict) or not _named(record.get("source")) or not isinstance(record.get("measures"), dict):
    return {"status": "indeterminate", "reason": "缺少分段防冻措施清单及出处"}
  methods = {name: _measure(row, duration) for name, row in sorted(record["measures"].items())}
  windows = sorted(row["window_h"] for row in methods.values() if row["status"] == "pass")
  gaps, end = [], 0
  for low, high in windows:
    if low > end:
      gaps.append([end, low])
    end = max(end, high)
  if end < duration:
    gaps.append([end, duration])
  complete = record.get("complete") is True
  adverse = _adverse_window(methods, duration) if complete else None
  status = "pass" if not gaps else "fail" if adverse is not None else "indeterminate"
  return {"status": status, "source": record["source"], "measures": methods, "complete": complete,
          "unverified_windows_h": gaps, "joint_shortfall_window_h": adverse}


def winter_water_study(scene, schedule):
  if (type(schedule.get("schema_version")) is not int or schedule["schema_version"] != 1
      or schedule.get("kind") != "winter-water-cases" or not isinstance(schedule.get("cases"), dict)):
    raise ValueError("需要 v1 冬季冷却水工况清单")
  inventory, digest = water_inventory(scene), file_digest(scene)
  issues, cases = [], {}
  bound = (all(_named(schedule.get(k)) for k in ("frame", "baseline", "scene_digest")) and
           (schedule["frame"], schedule["baseline"], schedule["scene_digest"]) == (inventory["frame"], inventory["baseline"], digest))
  for key, run in sorted(schedule["cases"].items()):
    if not _named(key) or not isinstance(run, dict):
      raise ValueError("冬季工况需按名称索引")
    if not bound or run.get("season") != "winter" or not _named(run.get("source")) or not isinstance(run.get("sections"), dict):
      cases[key] = {"unresolved": "场景与工况的修订不符，或冬季边界工况及其出处不完整"}
      issues.append(key)
      continue
    duration, outdoor = run.get("duration_h"), run.get("outdoor_design_c")
    if not _finite(duration) or duration <= 0 or not _finite(outdoor):
      cases[key] = {"unresolved": "冬季工况缺少有依据的室外温度或暴露时长"}
      issues.append(key)
      continue
    records = run["sections"]
    extras = sorted(records.keys() - inventory["sections"].keys())
    rows = {name: _section(records.get(name), duration) for name in sorted(inventory["sections"])}
    cases[key] = {"source": run["source"], "duration_h": duration, "outdoor_design_c": outdoor, "sections": rows, "unknown_sections": extras}
    if extras or any(row["status"] == "indeterminate" for row in rows.values()):
      issues.append(key)
  if not inventory["plants_complete"] or not inventory["sections_complete"]:
    issues.append("实施侧水冷设备或冷却水分段及归属清单不完整")
  return {"schema_version": 1, "kind": "winter-water-protection", "domain": "thermal", **inventory, "scene_digest": digest,
          "schedule_digest": canonical_digest(schedule), "cases": cases, "cases_digest": canonical_digest(cases), "unresolved": issues}
