"""Static downstream water levels on installed gravity drainage paths, in metres."""

import math

from texsys.evidence import canonical_digest

from .hydraulic import pipe_station, pipe_stations
from .netlist import _point, _table, _text


def _level(value):
  if type(value) not in (int, float) or not math.isfinite(value):
    raise ValueError("Water levels and distances must be finite numbers in metres.")
  return value


def _header(record, kind):
  if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record.get("kind") != kind:
    raise ValueError(f"Expected version 1 {kind}.")
  return {key: _text(record.get(key)) for key in ("frame", "scene_digest")}


def extract_drainage_paths(layout):
  """Qualify authored drainage routes against installed centrelines and port locations."""
  header = _header(layout, "drainage-layout")
  tolerance = _level(layout["station_tolerance_m"])
  if tolerance < 0 or type(layout.get("complete")) is not bool:
    raise ValueError("Invalid drainage inventory or station tolerance.")
  pipes = _table(layout["pipes"])
  for pipe, row in pipes.items():
    points = row["centerline_xyz_m"]
    if len(points) < 2 or not any(a != b for a, b in zip(points, points[1:])):
      raise ValueError(f"{pipe} requires a centreline of positive length.")
    for point in points:
      _point(point)
    _text(row["scene_prim"])
  outfalls = layout["outfalls"]
  if not isinstance(outfalls, list) or len(outfalls) != len(set(outfalls)) or set(outfalls) - pipes.keys():
    raise ValueError("Outfall references must identify distinct installed pipes.")
  valves = {}
  for key, row in _table(layout["valves"]).items():
    ports = row["ports_xyz_m"]
    if not isinstance(ports, list) or len(ports) != 2:
      raise ValueError(f"{key} requires two valve terminals.")
    points = pipes.get(row["pipe"], {}).get("centerline_xyz_m", [])
    inlet, outlet = (pipe_stations(_point(port), points, tolerance) for port in ports)
    valves[key] = {**row, "pipe": row["pipe"] if points else None, "inlet_candidates_m": inlet, "outlet_candidates_m": outlet,
                   "inlet_station_m": inlet[0] if len(inlet) == 1 else None, "outlet_station_m": outlet[0] if len(outlet) == 1 else None}
  drains, unresolved = {}, []
  for key, row in _table(layout["drains"]).items():
    position = _point(row["position_xyz_m"])
    path = row["outlet_path"]
    if not isinstance(path, list) or any(not isinstance(pipe, str) for pipe in path):
      raise ValueError(f"{key} requires an ordered list of installed pipe IDs.")
    segments, point = [], position
    for pipe in path:
      if pipe not in pipes:
        break
      line = pipes[pipe]
      station = pipe_station(point, line["centerline_xyz_m"], tolerance)
      if station is None:
        break
      segments.append({"pipe": pipe, "scene_prim": line["scene_prim"], "start_station_m": station})
      point = line["centerline_xyz_m"][-1]
    if not path or len(segments) != len(path) or path[-1] not in outfalls or len(set(path)) != len(path):
      unresolved.append({"drain": key, "candidate_path": path, "reason": "unqualified-installed-path"})
      segments = []
    drains[key] = {"room": _text(row["room"]), "drain_elevation_m": position[2], "segments": segments}
  return {"schema_version": 1, "kind": "drainage-paths", **header, "complete": layout["complete"],
          "station_tolerance_m": tolerance, "outfalls": sorted(outfalls), "drains": drains, "valves": valves, "unresolved": unresolved}


def _valve(key, valve, first, level, ratings, available, tolerance):
  ports = valve["ports_xyz_m"]
  if not isinstance(ports, list) or len(ports) != 2 or any(not isinstance(point, list) or len(point) != 3 for point in ports):
    raise ValueError(f"{key} requires two three-dimensional port coordinates.")
  for point in ports:
    for value in point:
      _level(value)
  inlet, outlet = valve["inlet_station_m"], valve["outlet_station_m"]
  if inlet is not None and outlet is not None:
    _level(inlet)
    _level(outlet)
    if max(inlet, outlet) < first - tolerance:
      return None
  connected = (inlet is not None and outlet is not None and inlet >= first - tolerance
               and outlet > inlet + tolerance and abs(outlet - inlet - math.dist(*ports)) <= tolerance)
  if len(valve.get("inlet_candidates_m", [])) > 1 or len(valve.get("outlet_candidates_m", [])) > 1:
    connected = None
  applied = _level(max(0., level - min(point[2] for point in ports)))
  rating = ratings.get(key)
  head = None if rating is None else _level(rating["maximum_static_head_m"])
  if head is not None and head <= 0:
    raise ValueError(f"{key} requires a positive static head rating.")
  return {**valve, "valve": key, "aligned_with_discharge": connected, "available": key in available,
          "head_at_valve_m": applied, "maximum_static_head_m": head,
          "rating_source": None if rating is None else _text(rating["source"]),
          "rating_margin_m": None if head is None else head - applied}


def tailwater_study(paths, schedule):
  """Deliver per-drain freeboard and valve loading independent of the acceptance threshold."""
  header = _header(paths, "drainage-paths")
  schedule_header = _header(schedule, "tailwater-cases")
  identification = {"schema_version": 1, "kind": "tailwater-study", "domain": "hydraulic", **header,
                    "source": _text(schedule["source"]), "schedule_digest": canonical_digest(schedule),
                    "paths_digest": canonical_digest({k: v for k, v in paths.items() if k != "sources"})}
  if schedule_header != header:
    return {**identification, "cases": {}, "complete": False,
            "unresolved": [{"reason": "incompatible-installation-or-frame", "schedule": schedule_header}]}
  tolerance = _level(paths["station_tolerance_m"])
  if tolerance < 0 or type(paths.get("complete")) is not bool:
    raise ValueError("Invalid drainage path tolerance or inventory completeness.")
  drains, valves = _table(paths["drains"]), _table(paths["valves"])
  outfalls = paths["outfalls"]
  if not isinstance(outfalls, list) or len(outfalls) != len(set(outfalls)) or any(not isinstance(key, str) or not key.strip() for key in outfalls):
    raise ValueError("Invalid installed outfall inventory.")
  ratings = _table(schedule["valves"])
  if ratings.keys() - valves.keys():
    raise ValueError("Unidentified rated valve.")
  valves_by_pipe = {}
  cases, unresolved = {}, []
  for key, valve in sorted(valves.items()):
    if valve.get("pipe") is None:
      unresolved.append({"valve": key, "reason": "unknown-installed-pipe"})
    else:
      valves_by_pipe.setdefault(_text(valve["pipe"]), []).append((key, valve))
  for case, conditions in sorted(_table(schedule["cases"]).items()):
    rows = cases[case] = {}
    levels = _table(conditions["outfalls"])
    if paths["complete"] and levels.keys() - set(outfalls):
      raise ValueError(f"{case} references an unknown installed outfall.")
    available = conditions["available_valves"]
    if not isinstance(available, list) or len(available) != len(set(available)) or set(available) - valves.keys():
      raise ValueError(f"{case} has an invalid valve inventory.")
    for drain, physical in sorted(drains.items()):
      route, elevation = physical["segments"], _level(physical["drain_elevation_m"])
      path = [part["pipe"] for part in route]
      row = rows[drain] = {"room": physical["room"], "drain": drain, "outlet_path": path, "drain_elevation_m": elevation,
                           "valves": [], "pipe_prims": [part["scene_prim"] for part in route]}
      if not path or path[-1] not in levels or path[-1] not in outfalls:
        unresolved.append({"case": case, "drain": drain, "reason": "missing-path-or-tailwater-level"})
        continue
      level = _level(levels[path[-1]]["tailwater_elevation_m"])
      row.update(tailwater_elevation_m=level, observed_freeboard_m=_level(elevation - level))
      for segment in route:
        for key, valve in valves_by_pipe.get(segment["pipe"], ()):
          item = _valve(key, valve, _level(segment["start_station_m"]), level, ratings, available, tolerance)
          if item is not None:
            row["valves"].append(item)
            if item["aligned_with_discharge"] is None:
              unresolved.append({"case": case, "drain": drain, "valve": key, "reason": "ambiguous-valve-station"})
            if item["maximum_static_head_m"] is None or not item.get("device_type"):
              unresolved.append({"case": case, "drain": drain, "valve": key, "reason": "missing-device-type-or-rating"})
  return {**identification, "cases": cases, "complete": paths["complete"] and bool(cases and drains) and not unresolved,
          "unresolved": unresolved}
