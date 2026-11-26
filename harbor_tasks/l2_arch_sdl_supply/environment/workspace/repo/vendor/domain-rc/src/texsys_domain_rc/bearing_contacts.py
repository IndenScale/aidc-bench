"""Extract vertical bearing contacts from a selected orthogonal installation."""

import math
from itertools import pairwise

from texsys.evidence import canonical_digest, file_digest

from .netlist import _table, _text
from .usd_geometry import open_scene, world_box

CONTACT_TOLERANCE_M = 1e-6


def _covers(outer, inner):
  return all(outer[0][axis] - CONTACT_TOLERANCE_M <= inner[0][axis]
             and inner[1][axis] <= outer[1][axis] + CONTACT_TOLERANCE_M for axis in (0, 1))


def _at_level(first, second):
  return abs(first - second) <= CONTACT_TOLERANCE_M


def _face(bounds, level):
  area = math.prod(bounds[1][axis] - bounds[0][axis] for axis in (0, 1))
  if not math.isfinite(area) or area <= 0:
    raise ValueError("Invalid bearing area.")
  return {"area_m2": area, "contact_xyz_m": [[*corner[:2], level] for corner in bounds]}


def _partition(bounds, matches, boxes):
  """Require a single contact plane with exactly one receiver across the footprint."""
  levels = [boxes[zone][1][2] for zone in matches]
  if not _at_level(min(levels), max(levels)):
    return None
  faces = {}
  for zone in matches:
    lo, hi = boxes[zone]
    faces[zone] = ([max(bounds[0][i], lo[i]) for i in (0, 1)],
                   [min(bounds[1][i], hi[i]) for i in (0, 1)])
  xs = sorted({bounds[0][0], bounds[1][0], *(corner[0] for face in faces.values() for corner in face)})
  # Independent USD transforms may place a shared edge a few ulps apart.
  epsilon = min(CONTACT_TOLERANCE_M, 8 * max(math.ulp(c[i]) for c in bounds for i in (0, 1)))
  if any(bounds[1][i] - bounds[0][i] <= epsilon for i in (0, 1)):
    return None
  for left, right in pairwise(xs):
    if right - left <= epsilon:
      continue
    ys = sorted((lo[1], hi[1]) for lo, hi in faces.values() if lo[0] <= left and right <= hi[0])
    end = bounds[0][1]
    for low, high in ys:
      if abs(low - end) > epsilon:
        return None
      end = high
    if not ys or abs(end - bounds[1][1]) > epsilon:
      return None
  return {zone: _face(face, boxes[zone][1][2]) for zone, face in faces.items()}


def bearing_contacts(scene, selection):
  """Extract full bearing on one zone or on a project-selected partition."""
  if type(selection.get("schema_version")) is not int or selection["schema_version"] != 1 or selection.get("kind") != "bearing-layout":
    raise ValueError("Expected a version 1 bearing-layout.")
  mode = selection.get("contact_mode", "single-zone")
  if mode not in ("single-zone", "partitioned"):
    raise ValueError("Unknown bearing contact_mode.")
  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  frame, digest = _text(root.GetCustomDataByKey("frame")), file_digest(scene)
  report = {"schema_version": 1, "kind": "bearing-contacts", "domain": "structural", "frame": frame,
            "scene_digest": digest, "selection_digest": canonical_digest(selection), "contacts": {}, "unresolved": []}
  if (frame, digest) != (selection.get("frame"), selection.get("scene_digest")):
    report["unresolved"].append({"reason": "layout-baseline-mismatch"})
    return report
  assets, zones, pads = (_table(selection[key]) for key in ("assets", "zones", "pads"))
  paths = [*assets.values(), *zones.values(), *(p["prim"] for p in pads.values())]
  if len(set(assets) | set(zones) | set(pads)) != len(paths) or len(set(paths)) != len(paths):
    raise ValueError("Bearing roles require distinct identifiers and scene objects.")
  boxes = {}
  for key, path in {**assets, **zones, **{k: p["prim"] for k, p in pads.items()}}.items():
    prim = stage.GetPrimAtPath(_text(path))
    if prim and prim.GetPath().HasPrefix(root.GetPath()):
      boxes[key] = world_box(prim)
    else:
      report["unresolved"].append({"object": key, "reason": "missing-selected-object"})
  for pad, row in sorted(pads.items()):
    asset = _text(row["asset"])
    if asset not in assets:
      raise ValueError(f"Unknown supported asset on pad {pad}.")
    if asset not in boxes or pad not in boxes:
      continue
    bounds, body = boxes[pad], boxes[asset]
    matches = [zone for zone in sorted(zones) if zone in boxes and _at_level(bounds[0][2], boxes[zone][1][2])
               and all(min(bounds[1][i], boxes[zone][1][i]) > max(bounds[0][i], boxes[zone][0][i])
                       for i in (0, 1))]
    if _at_level(body[0][2], bounds[1][2]) and _covers(body, bounds) and not zones.keys() - boxes.keys():
      if len(matches) == 1 and _covers(boxes[matches[0]], bounds):
        zone, = matches
        report["contacts"][pad] = {"asset": asset, "zone": zone, **_face(bounds, boxes[zone][1][2])}
        continue
      if len(matches) > 1 and mode == "partitioned":
        patches = _partition(bounds, matches, boxes)
        if patches:
          report["contacts"][pad] = {"asset": asset, "patches": patches, **_face(bounds, bounds[0][2])}
          continue
    report["unresolved"].append({"pad": pad, "asset": asset, "candidate_zones": matches, "reason": "unconfirmed-bearing-contact"})
  return report
