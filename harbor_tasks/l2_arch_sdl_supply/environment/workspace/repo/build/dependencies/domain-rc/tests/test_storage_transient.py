"""Hand calculations for two stores feeding two loads with fixed allocation."""

import pytest

from texsys_domain_rc.storage_transient import cooling_case_digest, storage_transient


def inputs():
  header = {"schema_version": 1, "scope": "room", "frame": "plant", "baseline": "as-designed"}
  pairs = [(tank, load) for tank in ("A", "B") for load in ("X", "Y")]
  network = {**header, "kind": "domain-netlist", "domain": "thermal", "origin": "physical", "complete": True,
             "unresolved": [], "scene_digest": "scene", "source_digest": "water", "junctions": [],
             "terminals": {"X": {}, "Y": {}},
             "connections": {a+b: {"ports": [a, b]} for a, b in pairs},
             "stores": {a: {"prim": "/"+a, "bounds_m": [[0, 0, 0], [1, 1, 1]]} for a in ("A", "B")},
             "hydraulic_topology": {"supply": {a+b: [a, b] for a, b in pairs}, "return": {b+a: [b, a] for a, b in pairs}}}
  inventory = {**header, "kind": "storage-inventory", "complete": True, "tanks": {
    k: {"minimum_level_m": 0, "initial_level_m": 1, "usable_fraction": 1, "heat_capacity_kwh_m3_k": 1,
        "usable_delta_k": capacity, "max_discharge_kw": 10, "source": "inventory"} for k, capacity in (("A", 5), ("B", 10))}}
  interval = {"start_min": 0, "end_min": 60, "unavailable_segments": [], "source": "sequence",
              "available_discharge_kw": {"A": 10, "B": 10},
              "terminals": {k: {"load_kw": 5, "other_delivered_kw": 0, "dispatch_fraction": {"A": .5, "B": .5}} for k in ("X", "Y")}}
  schedule = {**header, "kind": "cooling-sequences", "cases": {
    "outage": {"source": "loss of cooling", "intervals": [interval, {**interval, "start_min": 60, "end_min": 90}]}}}
  return network, inventory, schedule


def test_depletion_shared_between_terminals():
  network, inventory, schedule = inputs()
  result = storage_transient(network, inventory, schedule)["cases"]["outage"]["storage_only"]
  first, second = result["intervals"]
  assert first["final_kwh"] == {"A": 0, "B": 5}
  assert first["unserved_kwh"] == {"X": 0, "Y": 0}
  assert result["first_shortfall_min"] == 60
  assert second["unserved_kwh"] == {"X": 1.25, "Y": 1.25}
  assert result["remaining_kwh"] == {"A": 0, "B": 2.5}
  assert all(r["energy_balance_residual_kwh"] == pytest.approx(0) for r in result["intervals"])


def test_interrupted_record_and_missing_case_source():
  network, inventory, schedule = inputs()
  schedule["cases"]["outage"]["intervals"][1]["start_min"] = 65
  schedule["cases"]["unqualified"] = {}
  result = storage_transient(network, inventory, schedule)
  assert not result["complete"]
  first = result["cases"]["outage"]["service"]
  assert first["first_shortfall_min"] is None and first["confirmed_through_min"] == 60
  assert first["unresolved"]
  assert "unqualified" not in result["cases"]


def test_missing_interval_retains_later_shortfall_and_continuous_prefix_separately():
  network, inventory, schedule = inputs()
  case = schedule["cases"]["outage"]
  first, later = case["intervals"]
  first["end_min"] = 30
  later.update(start_min=45, end_min=100)
  def check():
    return storage_transient(network, inventory, schedule)["cases"]["outage"]["storage_only"]
  assert check()["shortfall_by_min"] is None
  case["no_charge_source"] = "charging isolated for entire outage"
  row = check()
  assert row["first_shortfall_min"] is None and row["confirmed_through_min"] == 30
  assert row["remaining_kwh"] == {"A": 2.5, "B": 7.5}
  assert row["shortfall_by_min"] == 75
  assert row["shortfall_witness"]["initial_kwh_upper_bound"] == 2.5
  assert row["shortfall_witness"]["no_charge_source"] == case["no_charge_source"]
  del case["no_charge_source"]
  later["available_discharge_kw"] = {"A": 4, "B": 10}
  assert check()["shortfall_by_min"] == 45
  assert check()["shortfall_witness"]["reason"] == "discharge-power"


def test_late_thermal_shortfall_depends_on_recovery_and_complete_installed_path():
  network, inventory, schedule = inputs()
  case = schedule["cases"]["outage"]
  first, later = case["intervals"]
  first["end_min"] = 30
  later.update(start_min=40, end_min=70, unavailable_segments=["XA"])
  later["terminals"] = {load: {**row, "other_delivered_kw": row["load_kw"]} for load, row in later["terminals"].items()}
  result = storage_transient(network, inventory, schedule)["cases"]["outage"]
  assert result["service"]["shortfall_by_min"] is None
  witness = result["storage_only"]["shortfall_witness"]
  assert (witness["by_min"], witness["terminal"], witness["reason"]) == (40, "X", "no-round-trip")
  assert result["storage_only"]["first_shortfall_min"] is None


@pytest.mark.parametrize("known", ["X", "Y"])
def test_independent_power_violation_with_missing_sibling_load_and_unknown_operating_rating(known):
  network, inventory, schedule = inputs()
  case = schedule["cases"]["outage"]
  interval = case["intervals"][1]
  interval.update(start_min=70, end_min=80, available_discharge_kw={})
  interval["terminals"] = {known: {"load_kw": 11, "dispatch_fraction": {"A": 1}, "other_delivered_kw": 0}}
  result = storage_transient(network, inventory, schedule)["cases"]["outage"]["service"]
  assert result["confirmed_through_min"] == 60
  witness = result["shortfall_witness"]
  assert witness["by_min"] == 70 and witness["capacity_upper_kw"] == 10
  assert witness["assigned_kw"] == {known: 11}
  assert result["first_shortfall_min"] is None


@pytest.mark.parametrize(("second_kw", "shortfall"), [(0.2, None), (0.20000000000000004, 70)])
def test_shared_decimal_rating_boundary_after_gap(second_kw, shortfall):
  network, inventory, schedule = inputs()
  stages = schedule["cases"]["outage"]["intervals"]
  stages[1].update(start_min=70, available_discharge_kw={"A": .3, "B": 10},
                   terminals={k: {"load_kw": kw, "other_delivered_kw": 0, "dispatch_fraction": {"A": 1}}
                              for k, kw in [("X", .1), ("Y", second_kw)]})
  row = storage_transient(network, inventory, schedule)["cases"]["outage"]["storage_only"]
  assert row["shortfall_by_min"] == shortfall


def test_exhaustion_at_end_of_decimal_interval_does_not_prove_a_shortfall():
  network, inventory, schedule = inputs()
  for tank in inventory["tanks"].values():
    tank["usable_delta_k"] = .3
  stages = schedule["cases"]["outage"]["intervals"]
  stages.pop()
  stages[0].update(terminals={k: {"load_kw": kw, "other_delivered_kw": 0, "dispatch_fraction": {"A": 1}}
                              for k, kw in [("X", .1), ("Y", .2)]})
  row = storage_transient(network, inventory, schedule)["cases"]["outage"]["service"]
  assert row["first_shortfall_min"] is None and row["remaining_kwh"]["A"] == 0


def test_case_revision_binds_issuing_scope_and_name_but_ignores_other_cases():
  _, _, schedule = inputs()
  old = cooling_case_digest(schedule, "outage")
  schedule["cases"]["other"] = schedule["cases"]["outage"].copy()
  assert cooling_case_digest(schedule, "outage") == old
  assert cooling_case_digest(schedule, "other") != old
  for key in ("scope", "frame", "baseline"):
    assert cooling_case_digest({**schedule, key: "another"}, "outage") != old
