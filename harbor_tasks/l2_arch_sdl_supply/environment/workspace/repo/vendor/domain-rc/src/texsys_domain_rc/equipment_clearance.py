"""Signed straight withdrawal distances for installed orthogonal equipment."""

import math

from texsys.evidence import canonical_digest, file_digest

from .netlist import _table, _text
from .usd_geometry import open_scene, world_box

EPS_M = 1e-6
CONTACT_M = 1e-9
FACES = ("-x", "+x", "-y", "+y", "-z", "+z")


def face_distances(unit, space, obstacles, space_id):
  """Sweep the full face in a world-axis direction to the first wall or solid."""
  overlaps, faces = [], {}
  for axis in range(3):
    for side in (0, 1):
      gap = (space[1][axis] - unit[1][axis]) if side else (unit[0][axis] - space[0][axis])
      faces[FACES[2 * axis + side]] = {"clear_m": gap, "boundary_m": gap, "controls": [space_id]}
  for key, other in sorted(obstacles.items()):
    intersection = [min(unit[1][i], other[1][i]) - max(unit[0][i], other[0][i]) for i in range(3)]
    if min(intersection) > CONTACT_M:
      overlaps.append(key)
    for axis in range(3):
      if any(intersection[i] <= CONTACT_M for i in range(3) if i != axis):
        continue
      for side in (0, 1):
        # An obstruction entirely behind the swept face cannot limit this direction.
        if (side and other[1][axis] <= unit[0][axis]) or (not side and other[0][axis] >= unit[1][axis]):
          continue
        gap = max(0., other[0][axis] - unit[1][axis] if side else unit[0][axis] - other[1][axis])
        face = faces[FACES[2 * axis + side]]
        if gap < face["clear_m"]:
          face.update(clear_m=gap, controls=[key])
        elif gap == face["clear_m"]:
          face["controls"].append(key)
  return {"faces": faces, "collisions": overlaps}


def box_intersection(first, second):
  lo, hi = (tuple(op(a, b) for a, b in zip(first[index], second[index], strict=True))
            for index, op in ((0, max), (1, min)))
  return [lo, hi] if all(b - a > EPS_M for a, b in zip(lo, hi, strict=True)) else None


def box_fits(bounds, room):
  return all(a - EPS_M <= lo < hi <= b + EPS_M for lo, hi, a, b in zip(*bounds, *room, strict=True))


def service_envelope(bounds, front, depth, width, height):
  axis = "xy".index(front[1])
  cross = 1 - axis
  lo, hi = map(list, bounds)
  center = (lo[cross] + hi[cross]) / 2
  lo[cross], hi[cross] = center - width / 2, center + width / 2
  hi[2] = lo[2] + height
  face = hi[axis] if front[0] == "+" else lo[axis]
  lo[axis], hi[axis] = (face, face + depth) if front[0] == "+" else (face - depth, face)
  return [lo, hi]


def service_volume(bounds, room, face, depth, width, height, obstacles):
  """Sweep a centred rectangular service tool or removable component from a horizontal face."""
  if face not in ("+x", "-x", "+y", "-y") or any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0
                                                     for v in (depth, width, height)):
    raise ValueError("Specify a horizontal world face and positive finite task dimensions.")
  envelope = service_envelope(bounds, face, depth, width, height)
  hits = [{"object": key, "prim": prim, "overlap_xyz_m": overlap}
          for key, prim, box in obstacles if (overlap := box_intersection(envelope, box))]
  return {"service_envelope_xyz_m": envelope, "envelope_inside_room": box_fits(envelope, room), "collisions": hits}


def equipment_clearances(scene, selection):
  if type(selection.get("schema_version")) is not int or selection["schema_version"] != 1 or selection.get("kind") != "equipment-placement":
    raise ValueError("Expected equipment-placement version 1.")
  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  frame = _text(root.GetCustomDataByKey("frame"))
  digest = file_digest(scene)
  complete = selection["obstacles_complete"]
  if type(complete) is not bool:
    raise ValueError("Declare completeness of the fixed obstacle inventory.")
  report = {"schema_version": 1, "kind": "equipment-clearances", "domain": "drc", "frame": frame, "scene_digest": digest,
            "selection_digest": canonical_digest(selection), "obstacles_complete": complete, "units": {}, "unresolved": []}
  if (selection.get("frame"), selection.get("scene_digest")) != (frame, digest):
    report["unresolved"].append({"reason": "incompatible-scene"})
    return report
  spaces, units, extras = (_table(selection[k]) for k in ("spaces", "units", "obstacles"))
  paths = [*spaces.values(), *(r["prim"] for r in units.values()), *extras.values()]
  if len(set(paths)) != len(paths) or len(set(spaces) | set(units) | set(extras)) != len(paths):
    raise ValueError("Equipment, spaces and obstacles require distinct IDs and prims.")
  boxes = {}
  for key, path in {**spaces, **{k: r["prim"] for k, r in units.items()}, **extras}.items():
    prim = stage.GetPrimAtPath(_text(path))
    if not prim or not prim.GetPath().HasPrefix(root.GetPath()):
      report["unresolved"].append({"id": key, "reason": "missing-selected-prim"})
    else:
      boxes[key] = world_box(prim)
  for key, row in sorted(units.items()):
    space = row.get("space")
    if key not in boxes or space not in spaces or space not in boxes:
      report["unresolved"].append({"id": key, "reason": "unresolved-equipment-or-plant-space"})
      continue
    obstacles = {k: boxes[k] for k in (*units, *extras) if k != key and k in boxes}
    report["units"][key] = {"prim": row["prim"], "space": space, "bounds_m": boxes[key],
                            **face_distances(boxes[key], boxes[space], obstacles, space)}
    tasks = _table(row.get("tasks", {}))
    if tasks:
      prims = {**extras, **{k: u["prim"] for k, u in units.items()}}
      solids = [(k, prims[k], box) for k, box in obstacles.items()]
      report["units"][key]["tasks"] = {
        name: service_volume(boxes[key], boxes[space], task["face"], task["depth_m"], task["width_m"], task["height_m"], solids)
        for name, task in tasks.items()}
  return report
