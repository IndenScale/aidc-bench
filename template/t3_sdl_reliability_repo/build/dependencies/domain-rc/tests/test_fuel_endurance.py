from copy import deepcopy

import pytest
from texsys.evidence import canonical_digest
from texsys_domain_rc.fuel_endurance import fuel_endurance


def design():
  inventory = {"kind": "fuel-inventory", "schema_version": 1, "frame": "site", "scene_digest": "installation",
               "tanks": {k: {"generators": [g], "usable_liters": 300, "capacity_source": "dip chart",
                              "connection_source": "survey"} for k, g in (("T1", "G1"), ("T2", "G2"))}}
  schedule = {"kind": "fuel-duty-schedule", "schema_version": 1, "inventory_digest": canonical_digest(inventory),
              "required_cases": ["combined", "one"], "source": "operation plan", "cases": {
                "combined": {"source": "fuel curves", "active_generators": ["G1", "G2"], "fuel_liters_per_hour": {"G1": 30}},
                "one": {"source": "fuel curves", "active_generators": ["G2"], "fuel_liters_per_hour": {"G2": 5}}}}
  return inventory, schedule


def test_missing_concurrent_rate_is_local_to_the_tank_serving_it():
  inventory, schedule = design()
  out = fuel_endurance(inventory, schedule)
  assert out["tanks"]["T1"]["observed_hours"] == 10 and out["tanks"]["T1"]["complete"]
  t2 = out["tanks"]["T2"]
  assert t2["observed_hours"] is None and t2["hours_upper_bound"] == 60
  assert t2["unresolved_cases"] == {"combined": ["G2"]} and out["unresolved"] == ["T2"]


def test_stale_schedule_and_unqualified_tank_volume():
  inventory, schedule = design()
  del inventory["tanks"]["T1"]["capacity_source"]
  assert fuel_endurance(inventory, schedule)["tanks"] == {}
  schedule["inventory_digest"] = canonical_digest(inventory)
  assert fuel_endurance(inventory, schedule)["tanks"]["T1"]["hours_upper_bound"] is None


def test_overlapping_tank_assignments_and_inactive_consumers_are_invalid():
  inventory, schedule = design()
  invalid = deepcopy(inventory)
  invalid["tanks"]["T2"]["generators"].append("G1")
  with pytest.raises(ValueError, match="多个油箱"):
    fuel_endurance(invalid, {**schedule, "inventory_digest": canonical_digest(invalid)})
  schedule["cases"]["one"]["fuel_liters_per_hour"]["G1"] = 30
  with pytest.raises(ValueError, match="未运行"):
    fuel_endurance(inventory, schedule)
