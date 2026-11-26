import pytest

from texsys_domain_rc.assessment import assess
from texsys_domain_rc.netlist import cable_netlist, compare_netlists, feeder_links, physical_netlist, schematic_netlist


def design(domain):
  header = {"schema_version": 1, "domain": domain, "scope": "test", "baseline": "A", "complete": True}
  devices = {"a.in": ("a", 0), "a.out": ("a", .1), "b.in": ("b", 2)}
  ports = {key: {"instance": item, "interface": "joint"} for key, (item, _) in devices.items()}
  intent = {**header, "kind": "domain-schematic", "ports": ports, "connections": {"line": ["a.out", "b.in"]}}
  placed = {key: {**port, "xyz_m": [devices[key][1], 0, 0]} for key, port in ports.items()}
  ends = [{"joint": "point-mate", "interface": "joint", "xyz_m": [.1, 0, 0], "tolerance_m": .001},
          {"port": "b.in"}]
  return intent, {**header, "kind": "port-layout", "frame": "equipment", "ports": placed,
                  "routes": {"route": {"ends": ends}}}


@pytest.mark.parametrize("domain", ["hydraulic", "electrical", "hvac", "thermal", "spatial"])
def test_lvs_on_discrete_interfaces(domain):
  intent, layout = design(domain)
  reference = schematic_netlist(intent)
  assert compare_netlists(reference, physical_netlist(layout))["status"] == "pass"
  layout["routes"]["route"]["ends"][0]["xyz_m"] = [0, 0, 0]
  mismatch = compare_netlists(reference, physical_netlist(layout))
  assert mismatch["status"] == "fail"
  assert mismatch["missing_connections"] == [("a.out", "b.in")]
  assert mismatch["extra_connections"] == [("a.in", "b.in")]


def test_unresolved_and_incomplete_evidence():
  intent, layout = design("electrical")
  reference = schematic_netlist(intent)
  layout["routes"]["route"]["ends"][0]["tolerance_m"] = .2
  result = compare_netlists(reference, physical_netlist(layout))
  assert result["status"] == "indeterminate"
  assert result["unresolved"][0]["candidates"] == ["a.in", "a.out"]
  layout["routes"]["extra"] = {"ends": [{"port": "a.in"}, {"port": "b.in"}]}
  assert compare_netlists(reference, physical_netlist(layout))["status"] == "fail"


def test_parallel_connections_and_revision():
  intent, layout = design("hydraulic")
  reference = schematic_netlist(intent)
  layout["routes"]["parallel"] = layout["routes"]["route"]
  assert compare_netlists(reference, physical_netlist(layout))["extra_connections"] == [("a.out", "b.in")]
  layout["baseline"] = "B"
  with pytest.raises(ValueError, match="baseline"):
    compare_netlists(reference, physical_netlist(layout))


def test_configured_predicate_and_missing_evidence():
  rule = {"allowed": 10, "rc": {"conditions": [{"left": "fact.gap", "relation": "minimum",
                                                "right": "parameter.allowed"}]}}
  assert assess(rule, {}) == "indeterminate"
  assert assess(rule, {"gap": 10}) == "pass"
  rule["allowed"] = 11
  assert assess(rule, {"gap": 10}) == "fail"
  del rule["allowed"]
  with pytest.raises(KeyError):
    assess(rule, {"gap": 10})


def test_cable_envelope_is_separate_from_individual_cores():
  intent, layout = design("electrical")
  layout["routes"] = {"cable": {"ends": [{}, {}], "prim": "/room/cable"}}
  for key, port in layout["ports"].items():
    port["prim"] = "/room/" + key
  header = {key: layout[key] for key in ("schema_version", "domain", "scope", "baseline", "frame", "complete")}
  schedule = {**header, "kind": "cable-terminations", "source": "installation record",
              "feeders": {"cable": {"feed_end": 1, "cores": {"core-1": ["b.in", "a.out"]}}}}
  installed = cable_netlist(layout, schedule)
  assert compare_netlists(schematic_netlist(intent), installed)["status"] == "pass"
  assert feeder_links(installed) == [{"route": "cable", "from": "a", "to": "b", "feed_end": 1}]
  schedule["feeders"]["cable"]["cores"] = {}
  empty = cable_netlist(layout, schedule)
  assert not empty["complete"] and empty["unresolved"][0]["reason"] == "missing-core-inventory"
  assert compare_netlists(schematic_netlist(intent), empty)["status"] == "indeterminate"
  with pytest.raises(ValueError, match="baseline"):
    cable_netlist(layout, {**schedule, "baseline": "another drawing"})


def test_parallel_lvs_difference_keeps_all_candidate_records():
  intent, layout = design("hydraulic")
  layout["routes"]["second"] = layout["routes"]["route"]
  mismatch = compare_netlists(schematic_netlist(intent), physical_netlist(layout))
  item, = mismatch["extra_connection_records"]
  assert item["difference_count"] == 1
  assert [record["id"] for record in item["records"]] == ["route", "second"]
