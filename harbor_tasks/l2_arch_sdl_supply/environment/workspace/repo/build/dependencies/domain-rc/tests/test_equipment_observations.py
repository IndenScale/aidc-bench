import pytest

from texsys_domain_rc.assessment import assess
from texsys_domain_rc.cooling_performance import cooling_performance
from texsys_domain_rc.equipment_clearance import face_distances, service_volume


def test_straight_service_face_and_wider_task_have_different_obstructions():
  bounds, space = ((1, 1, 0), (2, 2, 2)), ((0, 0, 0), (5, 4, 3))
  obstacles = {"behind": ((0, 1, 0), (.5, 2, 1)), "corner": ((2.5, 2, 0), (3, 3, 1))}
  observed = face_distances(bounds, space, obstacles, "room")
  assert observed["faces"]["+x"]["clear_m"] == 3
  assert observed["faces"]["-x"]["clear_m"] == .5
  solids = [(k, "/" + k, box) for k, box in obstacles.items()]
  narrow = service_volume(bounds, space, "+x", 1, 1, 2.2, solids)
  wide = service_volume(bounds, space, "+x", 1, 2, 2.2, solids)
  assert narrow["envelope_inside_room"] and not narrow["collisions"]
  assert wide["collisions"][0]["object"] == "corner"
  assert not service_volume(bounds, space, "+x", 4, 1, 2.2, solids)["envelope_inside_room"]


def test_partial_performance_curves_do_not_cancel_other_units():
  points = [{"ambient_c": 20, "capacity_kw": 100, "cop": 4}, {"ambient_c": 40, "capacity_kw": 80, "cop": 2}]
  catalog = {"schema_version": 1, "kind": "cooling-product-data", "units": {
    "u": {"product": "P", "source": "datasheet", "performance": points}, "unknown": {"product": "X", "source": "catalog"}}}
  temp = {"schema_version": 1, "kind": "cooling-conditions", "cases": {"d": {"ambient_c": 30}, "edge": {"ambient_c": 40},
                                                                        "extreme": {"ambient_c": 41}}}
  result = cooling_performance(catalog, temp)
  assert result["cases"]["d"]["units"]["u"] == {"product": "P", "source": "datasheet", "bracket_c": [20, 40], "capacity_kw": 90, "cop": 3}
  assert result["cases"]["edge"]["units"]["u"]["capacity_kw"] == 80
  assert result["cases"]["extreme"]["units"] == {} and "unknown" not in result["cases"]["d"]["units"]
  points.reverse()
  with pytest.raises(ValueError, match="increasing"):
    cooling_performance(catalog, temp)


def test_closed_catalog_interval_includes_endpoints_and_rejects_invalid_bounds():
  rule = {"bounds": [.15, .20], "rc": {"conditions": [{"left": "fact.margin", "relation": "between", "right": "parameter.bounds"}]}}
  assert [assess(rule, {"margin": x}) for x in (.14, .15, .20, .21, None)] == ["fail", "pass", "pass", "fail", "indeterminate"]
  for bounds in ([.2, .15], [.15], [True, .2]):
    with pytest.raises(ValueError):
      assess({**rule, "bounds": bounds}, {"margin": .18})
