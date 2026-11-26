import pytest

from texsys_domain_rc.clearance import _section_profile, clearance_observations


def corridor_profile(corridors, obstacles=()):
  volumes = {"entrance": {"role": "entrance", "bounds_m": [[-.1, 0, 0], [.1, 5, 4]]},
             "finish": {"role": "main-room-entry", "bounds_m": [[9.9, 0, 0], [10.1, 5, 4]]}}
  for role, entries in (("transport-corridor", corridors), ("transport-obstacle", obstacles)):
    for key, low, high in entries:
      volumes[key] = {"role": role, "bounds_m": [low, high]}
  result = {"kind": "straight-clearance-profile", "schema_version": 1, "scope": "delivery", "domain": "spatial",
            "frame": "L1", "axis": "x", "complete": True, "sections": [], "volumes": volumes, "unresolved": []}
  _section_profile(result, volumes)
  if result["unresolved"]:
    result["complete"] = False
  return result


def test_widest_lane_can_be_limited_by_an_offset_seam():
  profile = corridor_profile([("first", [0, 0, 0], [4, 2, 3]), ("second", [4, 1.5, 0], [10, 3.5, 3])])
  access, body = clearance_observations(profile, 2)
  assert access == {"observed_m": .5, "station_range_m": [4, 4], "scene_prims": ["first", "second"]}
  assert body["clear_envelope_m"] == [.5, 3]


def test_floor_lane_can_move_laterally_but_a_straight_shipment_keeps_its_offset():
  profile = corridor_profile([("room", [0, 0, 0], [10, 4, 3])],
                             [("left", [1, 0, 0], [2, 2, 3]), ("right", [5, 2, 0], [6, 4, 3])])
  access, body = clearance_observations(profile, 2)
  assert access["observed_m"] == 2
  assert body["clear_envelope_m"] == [0, 3]
  assert not body["clear_lateral_intervals_m"]


def test_unknown_span_still_bounds_width_on_a_known_segment():
  profile = corridor_profile([("first", [0, 0, 0], [2, 1, 3]), ("last", [8, 0, 0], [10, 3, 3])])
  assert profile["unresolved"] and not profile["complete"]
  access, _ = clearance_observations(profile)
  assert access["observed_m"] == 1


def test_positive_height_and_tolerance_binding():
  from texsys_domain_rc.assessment import assess

  profile = corridor_profile([("room", [0, 0, 0], [10, 2, 3])])
  with pytest.raises(ValueError, match="高度"):
    clearance_observations(profile, float("nan"))
  rule = {"rc": {"conditions": [{"left": "fact.width", "right": 1.5, "relation": "minimum", "tolerance": "fact.tol"}]}}
  assert assess(rule, {"width": 1.4999999, "tol": 1e-6}) == "pass"
  assert assess(rule, {"width": 1.4999999, "tol": 1e-9}) == "fail"
  assert assess(rule, {"width": 1.4999999}) == "indeterminate"
