from copy import deepcopy

import pytest
from texsys.evidence import canonical_digest
from texsys_domain_rc.netlist import physical_netlist, schematic_netlist
from texsys_domain_rc.project_lvs import project_lvs


def inputs():
  header = {"schema_version": 1, "domain": "hydraulic", "scope": "cooling", "baseline": "H1", "complete": True}
  ports = {k: {"instance": k[0], "interface": "pipe"} for k in ("A.s", "B.s", "A.r")}
  design = schematic_netlist({**header, "kind": "domain-schematic", "ports": ports, "connections": {"s": ["A.s", "B.s"]}})
  layout = physical_netlist({**header, "kind": "port-layout", "frame": "F", "ports": ports,
                             "routes": {"x": {"ends": [{"port": "A.s"}, {"port": "B.s"}]}}})
  spec = {"schema_version": 1, "kind": "federation-spec", "scope": "receiver", "baseline": "P1", "source": "port list",
          "lvs_inventory_complete": True, "members": {"H": {**{k: header[k] for k in ("domain", "scope", "baseline")},
            "lvs_basis": {"schematic_source": "P&ID", "physical_source": "installed joints"}}},
          "assets": {"unit": {"source": "IDs", "bindings": {"H": {"instance": "A", "ports":
            {"A.s": {"interface": "pipe", "requires_connection": True}, "A.r": {"interface": "pipe", "requires_connection": False}}}}}}}
  return spec, design, layout


def test_parallel_connections_and_peer_identity_are_scoped_to_incident_ports():
  spec, design, physical = inputs()
  def compare():
    return project_lvs(spec, {"H": design}, {"H": physical})
  assert compare()["counts"]["matched"] == 2
  physical["connections"]["second"] = deepcopy(physical["connections"]["x"])
  report = compare()
  first, = [r for r in report["ports"] if r["port"] == "A.s"]
  assert report["counts"] == {"declared_ports": 2, "matched": 1, "mismatched": 1, "indeterminate": 0}
  assert {r["id"] for r in first["physical_connections"]} == {"x", "second"}
  del physical["connections"]["second"]
  physical["ports"]["B.s"]["instance"] = "C"
  assert "endpoint-identity-mismatch" in next(r for r in compare()["ports"] if r["port"] == "A.s")["reasons"]


def test_selection_and_independent_sources_are_checked_before_assigning_credit():
  spec, design, physical = inputs()
  selected = spec["members"]["H"]
  selected["netlist_digest"] = canonical_digest(physical)
  physical["ports"]["B.s"]["instance"] = "C"
  def reason():
    record = project_lvs(spec, {"H": design}, {"H": physical})
    assert record["counts"]["indeterminate"] == 2 and record["conclusive_fraction"] == 0
    return record["ports"][0]["reasons"][0]
  assert reason() == "physical-digest-mismatch"
  del selected["netlist_digest"]
  design["sources"] = {"schematic": {"digest": "same-end-table"}}
  physical["sources"] = {"terminations": {"digest": "same-end-table"}}
  assert reason() == "shared-connectivity-source"
  physical["origin"] = "schematic"
  assert reason() == "wrong-physical-origin"


def test_repeated_local_port_cannot_inflate_project_denominator():
  spec, design, physical = inputs()
  spec["assets"]["other"] = deepcopy(spec["assets"]["unit"])
  spec["assets"]["other"]["bindings"]["H"]["instance"] = "other"
  with pytest.raises(ValueError, match="Repeated project LVS port"):
    project_lvs(spec, {"H": design}, {"H": physical})

def test_alias_of_same_issued_member_does_not_double_count_the_same_port():
  spec, design, physical = inputs()
  spec["members"]["alias"] = deepcopy(spec["members"]["H"])
  bindings = spec["assets"]["unit"]["bindings"]
  bindings["alias"] = deepcopy(bindings["H"])
  with pytest.raises(ValueError, match="Repeated project LVS port"):
    project_lvs(spec, {"H": design, "alias": design}, {"H": physical, "alias": physical})
