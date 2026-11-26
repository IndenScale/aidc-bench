"""A skid pad may bear on one zone or cross a physical joint between zones."""

import math

from pxr import Gf, Usd, UsdGeom
from texsys.evidence import file_digest
from texsys_domain_rc.bearing_contacts import _partition, bearing_contacts


def test_full_contact_and_split_bearing(tmp_path):
  path = tmp_path / "skid.usda"
  stage = Usd.Stage.CreateNew(str(path))
  UsdGeom.SetStageMetersPerUnit(stage, 1)
  UsdGeom.SetStageUpAxis(stage, "Z")
  root = UsdGeom.Xform.Define(stage, "/Plant").GetPrim()
  root.SetCustomDataByKey("frame", "Plant")
  stage.SetDefaultPrim(root)

  def box(name, center, size):
    cube = UsdGeom.Cube.Define(stage, "/Plant/" + name)
    cube.CreateSizeAttr(1)
    shift = cube.AddTranslateOp()
    shift.Set(Gf.Vec3d(*center))
    cube.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*size))
    return shift

  box("Unit", (0, 0, 1.5), (4, 2, 1))
  pad = box("Pad", (-.5, 0, .5), (.4, .5, 1))
  box("West", (-1, 0, -.5), (2, 2, 1))
  east = box("East", (1, 0, -.5), (2, 2, 1))
  stage.GetRootLayer().Save()
  layout = {"schema_version": 1, "kind": "bearing-layout", "frame": "Plant", "scene_digest": file_digest(path),
            "assets": {"skid": "/Plant/Unit"}, "zones": {"A": "/Plant/West", "B": "/Plant/East"},
            "pads": {"foot": {"prim": "/Plant/Pad", "asset": "skid"}}}
  placed = bearing_contacts(path, layout)
  assert not placed["unresolved"] and placed["contacts"]["foot"]["zone"] == "A"
  assert math.isclose(placed["contacts"]["foot"]["area_m2"], .2)
  pad.Set(Gf.Vec3d(0, 0, .5))
  stage.GetRootLayer().Save()
  stale = bearing_contacts(path, layout)
  assert not stale["contacts"] and stale["unresolved"][0]["reason"] == "layout-baseline-mismatch"
  layout["scene_digest"] = file_digest(path)
  split = bearing_contacts(path, layout)
  assert not split["contacts"] and split["unresolved"][0]["candidate_zones"] == ["A", "B"]
  layout["contact_mode"] = "partitioned"
  split = bearing_contacts(path, layout)
  assert not split["unresolved"]
  patches = split["contacts"]["foot"]["patches"]
  assert set(patches) == {"A", "B"} and all(math.isclose(p["area_m2"], .1) for p in patches.values())
  for dx, dz in ((.01, 0), (-.01, 0), (0, -.01)):
    east.Set(Gf.Vec3d(1 + dx, 0, -.5 + dz))
    stage.GetRootLayer().Save()
    layout["scene_digest"] = file_digest(path)
    survey = bearing_contacts(path, layout)
    assert not survey["contacts"] and survey["unresolved"][0]["pad"] == "foot"


def test_three_zone_joint_and_equal_area_gap_overlap():
  pad = ((0, 0, 0), (2, 2, 1))
  zones = {"west": ((0, 0, -1), (1, 2, 0)),
           "north-east": ((1, 1, -1), (2, 2, 0)),
           "south-east": ((1, 0, -1), (2, 1, 0))}
  faces = _partition(pad, sorted(zones), zones)
  assert {k: f["area_m2"] for k, f in faces.items()} == {"west": 2, "north-east": 1, "south-east": 1}
  # Total area still equals the pad's area, but a gap and a double bearing coexist.
  zones["north-east"] = ((1, .75, -1), (2, 1.75, 0))
  assert _partition(pad, sorted(zones), zones) is None
