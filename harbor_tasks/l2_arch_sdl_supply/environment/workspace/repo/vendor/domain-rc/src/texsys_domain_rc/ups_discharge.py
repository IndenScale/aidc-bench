"""Installed AC-output battery discharge curves and constant-load runtime bounds."""

import math

from texsys.evidence import canonical_digest, file_digest

from .netlist import _table, _text
from .usd_geometry import open_scene


def _number(value, *, minimum=None):
  if type(value) not in (int, float) or not math.isfinite(value) or minimum is not None and value < minimum:
    raise ValueError("UPS 放电数据应为范围内的有限数")
  return value


def _conditions(row):
  keys = ("configuration", "ageing_basis", "battery_temperature_c", "dc_cutoff_v", "initial_soc_percent")
  if any(row.get(key) is None for key in keys):
    return None
  for key in keys[:2]:
    _text(row[key])
  for key in keys[2:]:
    _number(row[key])
  if row["dc_cutoff_v"] <= 0 or not 0 < row["initial_soc_percent"] <= 100:
    raise ValueError("放电终止电压或起始荷电状态无效")
  return {key: row[key] for key in keys}


def ups_discharge_curves(scene, catalog, selection):
  from pxr import Usd

  for doc, kind in ((catalog, "ups-discharge-catalog"), (selection, "ups-discharge-selection")):
    if doc.get("kind") != kind or type(doc.get("schema_version")) is not int or doc["schema_version"] != 1:
      raise ValueError(f"需要版本 1 的 {kind}")
  root = open_scene(scene)
  prim = root.GetDefaultPrim()
  frame, digest = _text(prim.GetCustomDataByKey("frame")), file_digest(scene)
  out = {"kind": "ups-discharge-curves", "domain": "electrical", "schema_version": 1, "frame": frame, "scene_digest": digest,
         "catalog_digest": canonical_digest(catalog), "selection_digest": canonical_digest(selection), "ups": {}, "unresolved": {}}
  if (selection.get("frame"), selection.get("scene_digest"), selection.get("catalog_digest")) != (frame, digest, out["catalog_digest"]):
    out["unresolved"]["selection"] = "选型资料与放电曲线或场景版本不符"
    return out
  installed = {}
  for obj in Usd.PrimRange(prim):
    role = obj.GetCustomDataByKey("role")
    if ((role == "standby-power-equipment" and obj.GetCustomDataByKey("equipmentKind") == "ups")
        or (role == "electrical-layout-node" and obj.GetCustomDataByKey("deviceKind") == "ups")):
      identity = _text(obj.GetCustomDataByKey("identity"))
      if identity in installed:
        raise ValueError(f"UPS 场景标识重复：{identity}")
      installed[identity] = str(obj.GetPath())
  curves, units = _table(catalog.get("curves", {})), _table(selection.get("ups", {}))
  for key in sorted(installed.keys() | units.keys()):
    unit = _table(units.get(key, {}))
    curve_id = unit.get("curve")
    curve = _table(curves.get(curve_id, {}))
    if key not in installed or unit.get("prim") != installed[key] or not _source(unit):
      out["unresolved"][key] = "安装对象、选型或现场工况出处缺失"
      continue
    conditions = _conditions(unit)
    if conditions is None or conditions != _conditions(curve) or not _source(curve):
      out["unresolved"][key] = "产品数据与所选电池配置、温度、老化、荷电状态或截止电压不匹配"
      continue
    basis = curve.get("runtime_basis")
    if basis not in ("cutoff-runtime", "guaranteed-minimum"):
      out["unresolved"][key] = "产品资料未说明时长是至截止电压的续航还是保证的最短时长"
      continue
    points = curve.get("ac_output_points", [])
    if not isinstance(points, list):
      raise ValueError("UPS 放电曲线应为按交流输出 kW 递增的点列")
    if not points:
      out["unresolved"][key] = "所选产品曲线缺少交流输出负荷与续航数据"
      continue
    monotonic = _source(curve, "monotonic_source")
    knots = []
    for point in points:
      point = _table(point)
      kw, minutes = _number(point.get("kw"), minimum=0), _number(point.get("minutes"), minimum=0)
      if kw == 0 or knots and (kw <= knots[-1]["kw"] or monotonic and minutes > knots[-1]["minutes"]):
        raise ValueError("放电曲线的负荷须为正且递增，续航须随负荷非增")
      knots.append({"kw": kw, "minutes": minutes})
    out["ups"][key] = {"prim": installed[key], "curve": curve_id, "conditions": conditions, "ac_output_points": knots,
                       "runtime_basis": basis, "product_source": curve["source"], "installation_source": unit["source"],
                       "monotonic_source": monotonic}
  return out


def _source(row, field="source"):
  source = row.get(field)
  return source.strip() if isinstance(source, str) and source.strip() else None


def runtime_at_load(curve, demand_kw):
  """Use bracketing points only within the documented constant-load operating range."""
  _number(demand_kw, minimum=0)
  points = curve["ac_output_points"]
  result = {"required_load_kw": demand_kw, "observed_minutes": None, "lower_minutes": None, "upper_minutes": None,
            "curve": curve["curve"], "product_source": curve["product_source"], "installation_source": curve["installation_source"],
            "runtime_basis": curve["runtime_basis"], "conditions": curve["conditions"], "monotonic_source": curve["monotonic_source"], "reference_points": []}
  cutoff = curve["runtime_basis"] == "cutoff-runtime"
  for i, point in enumerate(points):
    if point["kw"] == demand_kw:
      minutes = point["minutes"]
      return {**result, "observed_minutes": minutes if cutoff else None, "lower_minutes": minutes, "upper_minutes": minutes if cutoff else None, "reference_points": [point]}
    if point["kw"] > demand_kw:
      if i and curve["monotonic_source"]:
        low_load = points[i-1]
        lower, upper = point["minutes"], low_load["minutes"] if cutoff else None
        return {**result, "lower_minutes": lower, "upper_minutes": upper, "observed_minutes": lower if lower == upper else None,
                "reference_points": [low_load, point]}
      break
  return {**result, "unresolved": "负荷没有匹配的曲线点或有依据的相邻点区间"}
