import copy

import pytest
from texsys.evidence import canonical_digest
from texsys_domain_rc.water_pressure import pressure_check, water_pressure


def inputs():
  pairs = {"main": ["source", "tee"], "a": ["tee", "a"], "b": ["tee", "b"]}
  topology = {"supply": pairs, "return": {"r"+k: v[::-1] for k, v in pairs.items()}}
  network = {"schema_version": 1, "kind": "chilled-water-network", "frame": "site", "scope": "loop", "baseline": "1",
             "scene_digest": "s", "water_netlist_digest": "p", "complete": True, "unresolved": [], "topology": topology,
             "nodes": {k: {"kind": v} for k, v in zip(("source", "tee", "a", "b"), ("plant", "junction", "terminal", "terminal"), strict=True)}}
  case = {"source": "bench", "pressure_datum": "test gauge origin", "complete": True, "plants": {"source": {"supply_kpa": 100, "return_kpa": 30, "source": "pump"}},
          "pipes": {k: {"state": "open", "source": "test", "resistance_kpa_per_lps2": 1} for side in topology.values() for k in side},
          "terminals": {k: {"flow_lps": q, "source": "terminal curve", "minimum_dp_kpa": 12} for k, q in (("a", 2), ("b", 3))}}
  return network, {"schema_version": 1, "kind": "water-pressure-schedule", "cases": {"base": case}}


def solve(network, schedule):
  schedule["network_digest"] = canonical_digest(network)
  return water_pressure(network, schedule)["cases"]["base"]


def test_common_main_and_parallel_alternative():
  network, schedule = inputs()
  result = solve(network, schedule)
  # Total duty 5 L/s costs 25 kPa on each main. Branch b costs a further 9 kPa each way.
  assert result["circuits"]["supply"]["flows_lps"]["main"] == pytest.approx(5)
  assert result["circuits"]["supply"]["pipes"]["main"]["pressure_drop_kpa"] == pytest.approx(25)
  assert result["terminals"]["a"]["available_dp_kpa"] == pytest.approx(12, abs=1e-5)
  assert result["terminals"]["b"]["margin_kpa"] == pytest.approx(-10, abs=1e-5)
  assert result["least_measured_margin_terminal"] == "b" and result["status"] == "fail"
  network["topology"]["supply"]["parallel"] = ["tee", "source"]
  pipes = schedule["cases"]["base"]["pipes"]
  pipes["parallel"] = copy.copy(pipes["main"])
  better = solve(network, schedule)
  assert better["status"] == "pass"
  assert better["circuits"]["supply"]["flows_lps"]["parallel"] == pytest.approx(-2.5)
  assert better["terminals"]["b"]["available_dp_kpa"] == pytest.approx(20.75, abs=1e-5)


def test_isolated_branch_missing_evidence_and_revision():
  network, schedule = inputs()
  case = schedule["cases"]["base"]
  case["pipes"]["a"]["state"] = "closed"
  del case["pipes"]["ra"]["resistance_kpa_per_lps2"]
  result = solve(network, schedule)
  assert result["terminals"]["a"]["isolated_circuits"] == ["supply"]
  assert result["terminals"]["a"]["status"] == "fail" and result["terminals"]["b"]["status"] == "indeterminate"
  assert result["status"] == "fail"
  schedule["network_digest"] = "old"
  assert water_pressure(network, schedule)["unresolved"]


def test_independent_plants_must_each_close_the_water_balance():
  network, schedule = inputs()
  network["nodes"]["other"] = {"kind": "plant"}
  network["topology"]["return"]["rmain"] = ["tee", "other"]
  schedule["cases"]["base"]["plants"]["other"] = {"supply_kpa": 100, "return_kpa": 30, "source": "second pump"}
  result = solve(network, schedule)
  assert result["status"] == "indeterminate"
  assert result["plant_balance"]["other"]["residual_lps"] == pytest.approx(-5)
  assert result["plant_balance"]["source"]["residual_lps"] == pytest.approx(5)

def test_acceptance_uses_terminal_evidence_even_when_case_summary_is_wrong():
  network, schedule = inputs()
  schedule["network_digest"] = canonical_digest(network)
  study = water_pressure(network, schedule)
  plan = {"source": "coordination plan", "schedule_digest": study["schedule_digest"], "required_cases": ["base"]}
  case = study["cases"]["base"]
  case["status"] = "pass"
  del case["terminals"]["a"]
  assert pressure_check(study, plan)["status"] == "fail"
  del case["terminals"]["b"]["available_dp_kpa"]
  case["status"] = "fail"
  assert pressure_check(study, plan)["status"] == "indeterminate"


def test_outages_inherit_duty_and_leave_other_cases_unchanged():
  network, schedule = inputs()
  network["topology"]["supply"]["standby"] = ["source", "tee"]
  base = schedule["cases"]["base"]
  base["pipes"]["standby"] = {"state": "closed", "source": "standby pipe test", "resistance_kpa_per_lps2": .25}
  event = {"base_case": "base", "base_case_digest": canonical_digest(base), "source": "maintenance sequence",
           "unavailable_pipes": ["main"], "switching": {"standby": "open"}}
  schedule.update(network_digest=canonical_digest(network), pipe_outages={"reroute": event, "isolated": {**event, "switching": {}}})
  original = copy.deepcopy(schedule)
  study = water_pressure(network, schedule)
  cases = study["cases"]
  assert schedule == original and cases["base"]["operating_point"]["pipe_states"]["main"] == "open"
  assert cases["reroute"]["status"] == "pass" and cases["isolated"]["status"] == "fail"
  assert cases["reroute"]["operating_point"]["terminal_flow_lps"] == {"a": 2, "b": 3}
  # 70 kPa less (0.25 + 1) * 5² at common mains and 2 * 3² on branch b.
  assert cases["reroute"]["terminals"]["b"]["available_dp_kpa"] == pytest.approx(20.75)
  assert cases["reroute"]["circuits"]["supply"]["pipes"]["main"]["flow_lps"] == 0
  assert cases["isolated"]["terminals"]["b"]["isolated_circuits"] == ["supply"]
  assert cases["reroute"]["pipe_outage"]["pipes"]["standby"]["before"] == "closed"
  assert cases["reroute"]["pipe_outage"]["base_case_digest"] == canonical_digest(base)


def test_outage_scope_and_stale_baseline():
  network, schedule = inputs()
  base = schedule["cases"]["base"]
  event = {"base_case": "base", "base_case_digest": canonical_digest(base), "source": "maintenance",
           "unavailable_pipes": ["main", "rmain"]}
  schedule.update(network_digest=canonical_digest(network),
                  pipe_outages={"pair": event, "bad": {**event, "unavailable_pipes": ["missing"]}})
  study = water_pressure(network, schedule)
  assert study["cases"]["pair"]["terminals"]["a"]["isolated_circuits"] == ["supply", "return"]
  plan = {"source": "test plan", "required_cases": ["pair", "bad"], "schedule_digest": canonical_digest(schedule)}
  decision = pressure_check(study, plan)
  assert decision["status"] == "fail" and decision["cases"]["bad"]["status"] == "indeterminate"
  base["terminals"]["a"]["flow_lps"] = 1.5
  assert "修订" in water_pressure(network, schedule)["cases"]["pair"]["unresolved"][0]
  event["base_case_digest"] = canonical_digest(base)
  event["switching"] = {"main": "open"}
  with pytest.raises(ValueError, match="切换"):
    water_pressure(network, schedule)
  del event["switching"]
  schedule["pipe_outages"]["base"] = event
  with pytest.raises(ValueError, match="重名"):
    water_pressure(network, schedule)


def test_outage_leaves_open_dead_ends_at_terminal_pressure():
  network, schedule = inputs()
  base = schedule["cases"]["base"]
  for node in ("dead1", "dead2"):
    network["nodes"][node] = {"kind": "junction"}
  for side, circuit in network["topology"].items():
    for name, ends in (("tail", ["b", "dead1"]), ("tip", ["dead1", "dead2"]), ("parallel-tip", ["dead2", "dead1"])):
      pipe = side + name
      circuit[pipe] = ends
      base["pipes"][pipe] = {"state": "open", "source": "instrumented dead leg", "resistance_kpa_per_lps2": 0.5}
  case = solve(network, schedule)
  for side, circuit in case["circuits"].items():
    assert circuit["pressure_kpa"]["b"] == circuit["pressure_kpa"]["dead2"]
    assert all(circuit["flows_lps"][side + pipe] == 0 for pipe in ("tail", "tip", "parallel-tip"))
    assert max(map(abs, circuit["balance_residual_lps"].values())) < 1e-8
  assert case["terminals"]["b"]["margin_kpa"] == pytest.approx(-10, abs=1e-5)


def test_transfer_durations_by_terminal_and_feedback_revision():
  network, schedule = inputs()
  base = schedule["cases"]["base"]
  network["topology"]["supply"]["reserve"] = ["source", "tee"]
  base["pipes"]["reserve"] = {"state": "closed", "source": "reserve test", "resistance_kpa_per_lps2": .25}
  schedule.update(network_digest=canonical_digest(network), pipe_outages={"switch": {
    "source": "operating plan", "base_case": "base", "base_case_digest": canonical_digest(base),
    "unavailable_pipes": ["main"], "switching": {"reserve": "open"}}})
  study = water_pressure(network, schedule)
  ids = {"clock": "logger clock", "run_id": "test1"}
  trial = {**ids, "case": "switch", "source": "switch test", "terminals": {}}
  for key, name, t in (("before", "base", 0.05), ("after", "switch", 0.45)):
    trial[key] = {**ids, "time_s": t, "time_error_s": .01, "source": "position log",
                  "pipe_states": study["cases"][name]["operating_point"]["pipe_states"]}
  for key in ("a", "b"):
    trial["terminals"][key] = {**ids, "asset": key, "meter": "meter-" + key, "source": "draw test", "calibration_source": "lab",
                               "kind": "continuous-extrema", "direction": "supply-to-return", "unit": "L/s",
                               "edge_error_s": 0, "absolute_error_lps": .1, "intervals": [
                                 {"window_s": [0, .1], "minimum_lps": 1.9}, {"window_s": [.1, .4], "maximum_lps": 1.6},
                                 {"window_s": [.4, .5], "minimum_lps": 1.9}]}
  spec = {**ids, "run_digest": canonical_digest(trial), "window_s": [0, .5], "terminals": {
    "a": {"minimum_flow_lps": 1.8, "maximum_deficit_s": .3}, "b": {"minimum_flow_lps": 1.8, "maximum_deficit_s": .29}}}
  data = {k: study[k] for k in ("scene_digest", "water_netlist_digest", "schedule_digest", "baseline", "frame", "scope")}
  data.update(kind="water-pressure-observations", schema_version=1, transfers={"test1": trial})
  plan = {"required_cases": ["switch"], "source": "review", "schedule_digest": study["schedule_digest"],
          "flow_transfers": {"source": "two terminals", "cases": {"switch": spec}}}
  result = pressure_check(study, plan, data)
  assert result["status"] == "fail" and result["design_status"] == "pass"
  rows = result["flow_transfers"]["cases"]["switch"]["terminals"]
  assert rows["a"]["longest_deficit_bounds_s"] == [.3, .3] and rows["a"]["status"] == "pass"
  assert rows["b"]["status"] == "fail"
  trial["before"]["pipe_states"] = trial["after"]["pipe_states"]
  assert pressure_check(study, plan, data)["flow_transfers"]["status"] == "indeterminate"
  spec["run_digest"] = canonical_digest(trial)
  assert pressure_check(study, plan, data)["flow_transfers"]["status"] == "indeterminate"
  # A steady isolation of already closed pipes has no observed transfer.
  study["cases"]["base"]["operating_point"]["pipe_states"] = trial["after"]["pipe_states"]
  result = pressure_check(study, plan, data)["flow_transfers"]["cases"]["switch"]
  assert result["status"] == "indeterminate" and "前后阀位相同" in result["reason"]
