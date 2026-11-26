import pytest

from texsys_domain_rc.federation import physical_federation


def test_partial_member_preserves_known_contradictions_and_scoped_open_ports():
  selection = {"domain": "electrical", "scope": "room", "baseline": "E1"}
  power = {**selection, "kind": "domain-netlist", "origin": "physical", "granularity": "port", "schema_version": 1,
           "source_digest": "s1", "complete": False, "unresolved": [{"reason": "pending-cable"}],
           "ports": {"a": {"instance": "UPS", "interface": "ac"}, "b": {"instance": "rack", "interface": "ac"}},
           "connections": {}}
  spec = {"kind": "federation-spec", "schema_version": 1, "scope": "building", "baseline": "coord", "source": "issue",
          "members": {"power": selection}, "assets": {"R": {"source": "asset schedule", "bindings": {"power": {
            "instance": "rack", "ports": {key: {"interface": "ac", "requires_connection": key != "b"} for key in ("a", "b", "c")}}}}}}
  result = physical_federation(spec, {"power": power})
  assert result["status"] == "fail" and not result["complete"]
  assert {r["port"]: r["status"] for r in result["interfaces"]} == {"a": "fail", "b": "pass", "c": "indeterminate"}
  spec["assets"]["other"] = spec["assets"]["R"]
  with pytest.raises(ValueError, match="multiple project assets"):
    physical_federation(spec, {"power": power})
