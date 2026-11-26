"""Extract vertical airflow interfaces and solve a steady, lumped pressure network in Pa and m³/h."""

import math
from itertools import combinations

from texsys.evidence import canonical_digest, file_digest

from .pressure_network import PressureUnresolved as UnresolvedAirflow
from .pressure_network import solve_pressures
from .netlist import physical_netlist
from .usd_geometry import open_scene, world_box

OUTSIDE = "outdoors"
EPS = 1e-8


def _text(value):
  if not isinstance(value, str) or not value.strip():
    raise ValueError("气流模型缺少标识或来源")
  return value


def _number(value):
  if type(value) not in (int, float) or not math.isfinite(value):
    raise ValueError("气流模型需要有限数值")
  return value


def shared_vertical_face(a, b):
  low = [max(x, y) for x, y in zip(a[0], b[0], strict=True)]
  high = [min(x, y) for x, y in zip(a[1], b[1], strict=True)]
  extent = [y-x for x, y in zip(low, high, strict=True)]
  for axis in (0, 1):
    cross = 1-axis
    if abs(extent[axis]) <= 1e-9 and min(extent[cross], extent[2]) > 1e-9:
      return {"axis": "xy"[axis], "station_m": (low[axis]+high[axis])/2, "area_m2": extent[cross]*extent[2],
              "span_m": [low[cross], high[cross]], "elevation_m": [low[2], high[2]]}
  return None


def _overlap(first, second):
  return min(first[1], second[1]) - max(first[0], second[0])


def _contains(outer, inner):
  return outer[0] - EPS <= inner[0] and inner[1] <= outer[1] + EPS


def read_airflow_boundaries(scene):
  from pxr import Usd

  stage = open_scene(scene)
  if stage.GetRootLayer().ListAllTimeSamples():
    raise ValueError("气流边界提取需要静态布置，运行状态由工况提供")
  root = stage.GetDefaultPrim()
  zones, openings, issues = {}, {}, []
  for level in root.GetChildren():
    spaces = level.GetChild("ClassifiedSpaces")
    for prim in spaces.GetChildren() if spaces else ():
      key = _text(prim.GetCustomDataByKey("identity"))
      if key in zones or key == OUTSIDE:
        raise ValueError(f"气流区域标识重复或保留：{key}")
      zones[key] = {"prim": str(prim.GetPath()), "use": _text(prim.GetCustomDataByKey("spaceUse")),
                    "bounds_m": world_box(prim), "neighbors": {}}
  for a, b in combinations(zones, 2):
    first, second = (zones[key]["bounds_m"] for key in (a, b))
    if all(_overlap((first[0][i], first[1][i]), (second[0][i], second[1][i])) > EPS for i in range(3)):
      issues.append(f"气流分区体积重叠：{a}、{b}")
    if face := shared_vertical_face(first, second):
      zones[a]["neighbors"][b] = zones[b]["neighbors"][a] = face
  seen = set()
  for prim in Usd.PrimRange(root):
    data = prim.GetCustomData()
    if data.get("rcRole") != "airflow-opening":
      continue
    key = _text(data["identity"])
    if key in seen:
      raise ValueError(f"气流开口标识重复：{key}")
    seen.add(key)
    owner, normal, kind = data["zone"], data["normal"], data["boundaryKind"]
    if owner not in zones or normal not in ("+x", "-x", "+y", "-y") or kind not in ("interior", "exterior"):
      raise ValueError(f"{key} 的所属区域、面法向或边界类别无效")
    axis = "xy".index(normal[1])
    cross = 1-axis
    bounds = zones[owner]["bounds_m"]
    station = bounds[int(normal[0] == "+")][axis]
    low, high = world_box(prim)
    span, elevation = [low[cross], high[cross]], [low[2], high[2]]
    hits = {other: face for other, face in zones[owner]["neighbors"].items()
            if face["axis"] == normal[1] and abs(face["station_m"]-station) <= EPS
            and min(_overlap(face["span_m"], span), _overlap(face["elevation_m"], elevation)) > EPS}
    located = (abs((low[axis]+high[axis])/2-station) <= EPS
               and _contains([bounds[0][cross], bounds[1][cross]], span)
               and _contains([bounds[0][2], bounds[1][2]], elevation))
    if kind == "exterior":
      located = located and not hits
      other = OUTSIDE
    else:
      other = next(iter(hits), None)
      located = located and len(hits) == 1 and _contains(hits[other]["span_m"], span) and _contains(hits[other]["elevation_m"], elevation)
    if not located:
      issues.append(f"{key} 未落在与标注相符的唯一边界面")
      continue
    opening = {"ends": [owner, other], "axis": normal[1], "station_m": station, "span_m": span,
               "elevation_m": elevation, "area_m2": (span[1]-span[0])*(elevation[1]-elevation[0]), "prim": str(prim.GetPath())}
    for previous, item in openings.items():
      if (set(item["ends"]) == set(opening["ends"]) and item["axis"] == opening["axis"]
          and abs(item["station_m"]-station) <= EPS
          and min(_overlap(item["span_m"], span), _overlap(item["elevation_m"], elevation)) > EPS):
        issues.append(f"气流开口重复占用边界面：{previous}、{key}")
    openings[key] = opening
  if not zones or root.GetCustomDataByKey("spaceUsesComplete") is not True or root.GetCustomDataByKey("airflowOpeningsComplete") is not True:
    issues.append("气流分区或有效开口清单未确认完整")
  return {"kind": "airflow-boundaries", "schema_version": 1, "domain": "hvac", "frame": _text(root.GetCustomDataByKey("frame")),
          "baseline": _text(root.GetCustomDataByKey("baseline")), "scope": str(root.GetPath()), "scene_digest": file_digest(scene), "zones": zones,
          "openings": openings, "complete": not issues, "unresolved": issues}


def airflow_netlist(geometry):
  """One lumped air port per zone, one installed edge per explicitly located opening."""
  if geometry.get("kind") != "airflow-boundaries" or geometry.get("domain") != "hvac":
    raise ValueError("分区气流网表需要实施侧开口清单")
  ports = {key: {"instance": key, "interface": "zonal-air"} for key in (*geometry["zones"], OUTSIDE)}
  layout = {**geometry, "kind": "port-layout", "ports": ports, "routes": {
    key: {"prim": item["prim"], "ends": [{"port": p} for p in item["ends"]]} for key, item in geometry["openings"].items()}}
  result = physical_netlist(layout)
  result["source_digest"] = canonical_digest(geometry)
  result["unresolved"] = [{"reason": issue} for issue in geometry["unresolved"]]
  result["complete"] = result["complete"] and not result["unresolved"]
  return result


def _solve_case(geometry, case):
  zones, openings = geometry["zones"], geometry["openings"]
  if geometry["unresolved"] or geometry["complete"] is not True or case.get("complete") is not True:
    raise UnresolvedAirflow("气流几何或运行工况清单不完整")
  _text(case["source"])
  if case.get("openings", {}).keys() != openings.keys():
    raise UnresolvedAirflow("工况的开口状态与实施侧开口清单不一致")
  if "rooms" not in case or "reference_pa" not in case:
    raise UnresolvedAirflow("缺少分区机械风量或定压边界")
  if any(value is None for value in case["reference_pa"].values()):
    raise UnresolvedAirflow("参照区压力未确定")
  duties, references = case["rooms"], {k: _number(v) for k, v in case["reference_pa"].items()}
  if (OUTSIDE not in references or duties.keys() & references.keys()
      or duties.keys() | references.keys() != zones.keys() | {OUTSIDE}):
    raise UnresolvedAirflow("每一区域须给出机械风量或参考压力，并提供室外压力")
  edges, nets, flows = {}, {}, {}
  for key, opening in openings.items():
    params = case["openings"][key]
    if any(params.get(field) is None for field in ("coefficient_m3_h_pa_n", "exponent", "source", "state")):
      raise UnresolvedAirflow(f"缺少 {key} 的开口状态或漏风特性依据")
    coefficient, exponent = _number(params["coefficient_m3_h_pa_n"]), _number(params["exponent"])
    if coefficient < 0 or not .5 <= exponent <= 1:
      raise ValueError(f"{key} 的漏风特性超出模型范围")
    edges[key] = {**opening, "coefficient_m3_h_pa_n": coefficient, "exponent": exponent,
                  "state": _text(params["state"]), "source": _text(params["source"])}
  for zone, record in duties.items():
    if any(record.get("flows_m3_h", {}).get(k) is None for k in ("supply", "return", "exhaust")):
      raise UnresolvedAirflow(f"缺少 {zone} 的送回排风量")
    flow = {k: _number(record["flows_m3_h"][k]) for k in ("supply", "return", "exhaust")}
    if min(flow.values()) < 0:
      raise ValueError("送、回、排风量应为非负数")
    flows[zone] = flow
    nets[zone] = math.fsum((flow["supply"], -flow["return"], -flow["exhaust"]))
  pressures, leakage, outgoing, residuals = solve_pressures(edges, nets, references)
  rows = {}
  for zone, record in sorted(duties.items()):
    peers = {**zones[zone]["neighbors"], OUTSIDE: None}
    readings = {}
    for other, face in peers.items():
      connected = {k: q if edges[k]["ends"][0] == zone else -q for k, q in leakage.items()
                   if set(edges[k]["ends"]) == {zone, other}}
      readings[other] = {"interface": face, "reference_pressure_pa": pressures[other], "difference_pa": pressures[zone]-pressures[other],
                         "leakage_out_m3_h": math.fsum(connected.values()), "path_flows_m3_h": connected}
    row = {"room_pressure_pa": pressures[zone], "net_mechanical_m3_h": nets[zone], "flow_m3_h": flows[zone],
           "flow_balance_residual_m3_h": residuals[zone], "references": readings, "schedule_source": _text(record["source"])}
    if "target_outdoor_pa" in record:
      target = _number(record["target_outdoor_pa"])
      remaining = {k: v for k, v in nets.items() if k != zone}
      row["target_outdoor_pa"] = target
      try:
        _, target_flows, target_out, _ = solve_pressures(edges, remaining, {**references, zone: references[OUTSIDE]+target})
        row["required_net_mechanical_m3_h"] = target_out[zone]
        row["target_path_flows_out_m3_h"] = {
          key: q if edges[key]["ends"][0] == zone else -q for key, q in target_flows.items() if zone in edges[key]["ends"]
        }
      except UnresolvedAirflow as exc:
        row["target_unresolved"] = str(exc)
    rows[zone] = row
  return {"rooms": rows, "pressure_pa": pressures, "openings": edges, "path_flows_m3_h": leakage,
          "net_outflow_m3_h": outgoing, "source": case["source"]}


def airflow_study(geometry, schedule):
  for item, kind in ((geometry, "airflow-boundaries"), (schedule, "airflow-cases")):
    if type(item.get("schema_version")) is not int or item["schema_version"] != 1 or item.get("kind") != kind:
      raise ValueError(f"需要版本 1 的 {kind}")
  current = (geometry["frame"], geometry["baseline"]) == (_text(schedule["frame"]), _text(schedule["baseline"]))
  cases, issues = {}, list(geometry["unresolved"])
  if not schedule.get("cases"):
    issues.append("没有风量工况")
  for name, case in sorted(schedule["cases"].items()):
    _text(name)
    try:
      if not current:
        raise UnresolvedAirflow("气流区域与工况的坐标系或基线不一致")
      solved = _solve_case(geometry, case)
      cases[name] = {**solved, "unresolved": []}
      issues.extend(f"{name}/{zone} 设计目标：{row['target_unresolved']}" for zone, row in solved["rooms"].items() if "target_unresolved" in row)
    except UnresolvedAirflow as exc:
      cases[name] = {"unresolved": [str(exc)]}
      issues.append(f"{name}：{exc}")
  return {"kind": "zonal-pressure-study", "schema_version": 1, "domain": "hvac", "frame": geometry["frame"],
          "baseline": geometry["baseline"], "scene_digest": geometry["scene_digest"], "zones": geometry["zones"],
          "schedule_digest": canonical_digest(schedule), "cases": cases, "complete": not issues, "unresolved": issues}
