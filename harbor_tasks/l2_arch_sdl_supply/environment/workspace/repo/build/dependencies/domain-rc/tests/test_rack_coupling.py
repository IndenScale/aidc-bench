from copy import deepcopy

import pytest

from texsys_domain_rc.rack_coupling import rack_heat_coupling


def boundary():
  fed = {"schema_version": 1, "kind": "physical-netlist-federation", "baseline": "A", "origin": "physical",
         "scope": "module", "members": {key: {"domain": key} for key in ("electrical", "hydraulic")}, "interfaces": []}
  for member, ports in (("electrical", ["p1", "p2"]), ("hydraulic", ["s", "r"])):
    for port in ports:
      fed["interfaces"].append({"member": member, "asset": "R", "instance": "local", "port": port,
                                "status": "pass", "requires_connection": True, "connections": ["line-"+port],
                                "binding_source": "inventory"})
  header = {"schema_version": 1, "baseline": "A", "scope": "module", "case": "normal", "zone": "zone", "frame": "F", "complete": True}
  power = {**header, "kind": "terminal-power", "source": "electrical meter", "items": {"R": {"basis": "measured", "members": {
    "electrical": {"p1": {"input_kw": 40}, "p2": {"input_kw": 0}}}}}}
  heat = {**header, "kind": "rack-calorimetry", "source": "thermal survey", "items": {"R": {"room_kw": 8, "outside_kw": 0,
    "circuits": {"q": {"member": "hydraulic", "inlet": "s", "outlet": "r", "inlet_c": 20, "outlet_c": 28,
                       "specific_heat_kj_kg_k": 4, "mass_flow_in_to_out_kg_s": 1}}}}}
  return fed, power, heat


def test_signed_direction_and_asset_identity():
  fed, power, heat = boundary()
  assert rack_heat_coupling(fed, power, heat)["items"]["R"]["residual_kw"] == 0
  circuit = heat["items"]["R"]["circuits"]["q"]
  circuit.update(inlet_c=28, outlet_c=20, mass_flow_in_to_out_kg_s=-1)
  assert rack_heat_coupling(fed, power, heat)["items"]["R"]["liquid_kw"] == 32
  circuit["mass_flow_in_to_out_kg_s"] = 1
  result = rack_heat_coupling(fed, power, heat)
  assert not result["complete"] and result["boundary_observations"]["R"]["circuits"]["q"]["liquid_kw"] == -32
  assert not rack_heat_coupling(fed, power, {**heat, "case": "other"})["items"]


def test_omit_inactive_feed_or_double_count_flow():
  fed, power, heat = boundary()
  del power["items"]["R"]["members"]["electrical"]["p2"]
  result = rack_heat_coupling(fed, power, heat)
  assert not result["complete"] and result["unresolved"][0]["reason"] == "required-terminal-not-in-survey"
  circuits = heat["items"]["R"]["circuits"]
  circuits["again"] = deepcopy(circuits["q"])
  with pytest.raises(ValueError, match="counted twice"):
    rack_heat_coupling(fed, power, heat)
