from itertools import combinations

import pytest

from texsys_domain_rc.cooling_redistribution import _maximum_service, cooling_redistribution
from texsys_domain_rc.cooling_service import cooling_dispatch
from texsys_domain_rc.hvac import parallel_capacities


def records():
  h = {"schema_version": 1, "scope": "rooms", "baseline": "A", "complete": True}
  ids = {"U": "R", "V": "R"}
  names = {"UA": "U", "UB": "U", "VA": "V"}
  net = {**h, "kind": "domain-netlist", "origin": "physical", "domain": "hvac", "method": "direct-unit-to-zone-centerline",
         "frame": "Z", "scene_digest": "a", "unit_prims": {u: "/" + u for u in ids}, "inventory_complete": True,
         "products": {"U": "P", "V": "P"}, "units": list(ids), "rooms": ["R"], "observed_objects": [*ids, "R"],
         "service_routes": {k: {"ends": [{"candidates": [u]}, {"candidates": ["R"]}]} for k, u in names.items()},
         "connections": {k: {"ports": [u, "R"]} for k, u in names.items()}, "unresolved": []}
  plan = {**h, "kind": "cooling-service-plan", "routes": {r: {"room": "R", "unit": u, "source": "design"} for r, u in names.items()}}
  case = {"source": "control plan", "unavailable_units": [], "dispatch_kw": {"U": {"R": 10}, "V": {"R": 12}}}
  return h, net, plan, case


def test_unselected_parallel_routes_and_idle_standby():
  header, net, plan, case = records()
  schedule = {**header, "kind": "cooling-dispatch-cases", "cases": {"peak": case}}
  def peak():
    return cooling_dispatch(net, plan, schedule)["cases"]["peak"]
  assert peak()["rooms"]["R"] == {"routed_kw": 12, "pending_kw": 10, "withheld_kw": 0}
  case["dispatch_routes"] = {"U": {"R": "UA"}}
  case["unavailable_routes"] = ["UA"]
  assert peak()["rooms"]["R"] == {"routed_kw": 12, "pending_kw": 0, "withheld_kw": 10}
  assert peak()["paths"]["UB"]["state"] == "available"
  case["dispatch_routes"]["U"]["R"] = "VA"
  with pytest.raises(ValueError, match="Selected route"):
    peak()
  del case["dispatch_routes"]
  case["unavailable_routes"].append("UB")
  assert peak()["rooms"]["R"]["withheld_kw"] == 10


def test_concurrent_service_uses_residual_reallocation_and_has_an_independent_cut_bound():
  units, loads = {"U": 30, "V": 20}, {"A": 20, "B": 30}
  routes = {"1": ("U", "A", 30), "2": ("U", "B", 30), "3": ("V", "A", 20)}
  for lost in ((), ("1",), ("2",), ("3",)):
    active = {k: v for k, v in routes.items() if k not in lost}
    report = _maximum_service(units, loads, active)
    # Exhaust all source/sink partitions of the four equipment/room vertices in the reduced graph.
    labels = [*units, *loads]
    cuts = []
    for n in range(len(labels) + 1):
      for subset in combinations(labels, n):
        cut = sum(q for u, q in units.items() if u not in subset) + sum(q for r, q in loads.items() if r in subset)
        cuts.append(cut + sum(q for u, r, q in active.values() if u in subset and r not in subset))
    assert report["maximum_kw"] == min(cuts) == report["cut_capacity_kw"]
    if not lost:
      assert report["route_kw"] == {"1": 0, "2": 30, "3": 20}


def test_unknown_endpoint_gives_separate_confirmed_and_conditional_solutions():
  h, net, plan, _ = records()
  del net["connections"]["VA"]
  net["service_routes"]["VA"]["ends"][0]["candidates"].append("U")
  spec = {"source": "independent circuits", "independent_routes": True, "ambient_c": 30, "room_loads_kw": {"R": 18},
          "unavailable_units": [], "routes": {k: {"source": "terminal limit", "maximum_kw": 20} for k in plan["routes"]}}
  study = {**h, "kind": "cooling-redistribution-cases", "catalog_digest": "curve", "conditions_digest": "temperatures", "cases": {"day": spec}}
  performance = {"kind": "cooling-performance", "schema_version": 1, "conditions_digest": "temperatures", "catalog_digest": "curve",
                 "cases": {"day": {"ambient_c": 30, "units": {k: {"capacity_kw": 10, "product": "P", "source": "table"} for k in net["units"]}}}}
  def run():
    return cooling_redistribution(net, plan, performance, study)
  row = run()["cases"]["day"]
  assert row["confirmed_routes"]["maximum_kw"] == 10
  assert row["including_unverified_routes"]["maximum_kw"] == 18 and row["unverified_routes"] == ["VA"]
  spec["routes"]["UA"] = {}
  assert "issue" in run()["cases"]["day"]
  study["baseline"] = "stale"
  assert run()["cases"] == {}


def test_independent_parallel_capacity_reports_different_design_and_contingency_totals():
  assert parallel_capacities({"unit-B": 52, "unit-A": 80, "unit-C": 43}, 2, 1) == {
    "count": 3, "normal": 175, "basic": 132, "remaining": 95, "unavailable": ["unit-A"]}
