"""Steady one-dimensional conduction through a planar detail with prescribed opposite air or interface temperature."""

import math

from texsys.evidence import canonical_digest, file_digest

from .netlist import _table, _text
from .usd_geometry import open_scene


def _value(row, key, *, positive=False):
  value = row.get(key)
  if value is None:
    raise KeyError(key)
  if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
    raise ValueError(f"Invalid {key}.")
  return value


def _basis(row, key):
  if not row.get(key):
    raise KeyError(key)
  return _text(row[key])


def _resistance(section):
  layers = section.get("layers")
  if not layers:
    raise KeyError("layers")
  if not isinstance(layers, list):
    raise ValueError("Expected an ordered list of section layers.")
  values = []
  for layer in layers:
    thickness = _value(layer, "thickness_m", positive=True)
    conductivity = _value(layer, "conductivity_w_mk", positive=True)
    values.append({"material": _basis(layer, "material"), "source": _basis(layer, "source"), "thickness_m": thickness,
                   "conductivity_w_mk": conductivity, "resistance_m2k_w": thickness / conductivity})
  return values


def _opposite_boundary(local):
  if local.get("opposite_surface_c") is not None:
    if local.get("opposite_air_c") is not None or local.get("opposite_film_m2k_w") is not None:
      raise ValueError("Choose opposite surface temperature or opposite air and film resistance.")
    return "opposite_surface_c", _value(local, "opposite_surface_c"), 0.0
  return "opposite_air_c", _value(local, "opposite_air_c"), _value(local, "opposite_film_m2k_w", positive=True)


def _surface(path, section, case, local):
  applicability = _basis(section, "one_dimensional_basis")
  layers = _resistance(section)
  source, boundary_source = _basis(case, "source"), _basis(local, "source")
  indoor, dew = _value(case, "air_c"), _value(case, "dew_point_c")
  if dew > indoor:
    raise ValueError("Dew point exceeds the same case's air temperature.")
  inside = _value(local, "inside_film_m2k_w", positive=True)
  boundary_key, opposite, outside = _opposite_boundary(local)
  total = math.fsum([inside, outside, *(row["resistance_m2k_w"] for row in layers)])
  flux = (indoor - opposite) / total
  surface = indoor - flux * inside
  if not all(math.isfinite(value) for value in (total, flux, surface)):
    raise ValueError("Non-finite planar section result.")
  return {"prim": path, "case_source": source, "boundary_source": boundary_source,
          "one_dimensional_basis": applicability, "layers": layers, "air_c": indoor, "dew_point_c": dew,
          boundary_key: opposite, "inside_film_m2k_w": inside, "opposite_film_m2k_w": outside,
          "total_resistance_m2k_w": total, "outward_flux_w_m2": flux, "surface_c": surface}


def planar_surface_study(scene, sections, schedule):
  for doc, kind in ((sections, "planar-sections"), (schedule, "surface-boundaries")):
    if type(doc.get("schema_version")) is not int or doc["schema_version"] != 1 or doc.get("kind") != kind:
      raise ValueError(f"Expected version 1 {kind}.")
  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  frame, digest = _text(root.GetCustomDataByKey("frame")), file_digest(scene)
  section_digest = canonical_digest(sections)
  report = {"schema_version": 1, "kind": "planar-surface-study", "domain": "thermal", "frame": frame,
            "scene_digest": digest, "sections_digest": section_digest, "schedule_digest": canonical_digest(schedule),
            "rooms": {}, "unresolved": []}
  if ((sections.get("frame"), sections.get("scene_digest")) != (frame, digest)
      or schedule.get("sections_digest") != section_digest):
    report["unresolved"].append({"reason": "section-or-scene-revision-mismatch"})
    return report
  faces = _table(sections["faces"])
  for room, cases in sorted(_table(schedule["rooms"]).items()):
    room_results = report["rooms"][room] = {}
    for name, case in sorted(_table(cases).items()):
      boundaries = _table(case.get("boundaries", {}))
      results = room_results[name] = {}
      selected = {key for key, face in faces.items() if face.get("room") == room}
      for key in sorted(selected | boundaries.keys()):
        try:
          if key not in selected:
            raise KeyError("selected-face-for-room")
          section = faces[key]
          path = _basis(section, "prim")
          prim = stage.GetPrimAtPath(path)
          if (not prim or not prim.GetPath().HasPrefix(root.GetPath()) or prim.GetCustomDataByKey("identity") != key
              or prim.GetCustomDataByKey("roomId") != room):
            raise KeyError("installed-face-for-room")
          results[key] = _surface(path, section, case, boundaries[key])
        except KeyError as error:
          report["unresolved"].append({"room": room, "case": name, "face": key, "missing": error.args[0]})
  return report
