"""Count issued project ports compared against independently sourced domain netlists."""

from collections import Counter, defaultdict

from texsys.evidence import canonical_digest

from .federation import physical_federation
from .netlist import compare_netlists


def _incidents(document):
  by_port = defaultdict(list)
  for key, row in sorted(document["connections"].items()):
    for port in set(row["ports"]):
      by_port[port].append({"id": key, **row})
  return by_port


def _selection_issue(expected, schematic, physical, view):
  if schematic is None or physical is None:
    return "missing-netlist"
  if physical.get("origin") != "physical" or physical.get("kind") != "domain-netlist":
    return "wrong-physical-origin"
  if expected.get("netlist_digest") is not None and expected["netlist_digest"] != view.get("digest"):
    return "physical-digest-mismatch"
  if "ports" not in view or any(schematic.get(k) != expected[k] for k in ("domain", "scope", "baseline")):
    return "selection-mismatch"
  if schematic.get("origin") != "schematic" or schematic.get("kind") != "domain-netlist":
    return "wrong-schematic-origin"
  if "schematic_digest" in expected and canonical_digest(schematic) != expected["schematic_digest"]:
    return "schematic-digest-mismatch"
  basis = expected.get("lvs_basis") or {}
  if not isinstance(basis, dict):
    raise ValueError("lvs_basis must identify the two connectivity sources.")
  refs = [basis.get(k) for k in ("schematic_source", "physical_source")]
  if not all(isinstance(ref, str) and ref.strip() for ref in refs):
    return "missing-independence-basis"
  # Compare the underlying connectivity source when the build supplies file evidence.
  design = schematic.get("sources", {})
  installed = physical.get("sources", {})
  a = design.get("schematic", design.get("drawing", {})).get("digest")
  b = installed.get("terminations", installed.get("layout", {})).get("digest")
  if refs[0].strip() == refs[1].strip() or schematic["source_digest"] == physical["source_digest"] or (a and a == b):
    return "shared-connectivity-source"
  return None


def _port_result(ref, schematic, physical, intent, installed, comparison, affected):
  port = ref["port"]
  design, built = intent[port], installed[port]
  issues = []
  for side, doc, rows in (("schematic", schematic, design), ("physical", physical, built)):
    actual = doc["ports"].get(port)
    if actual is None:
      if doc["complete"]:
        issues.append(side + "-missing-port")
    elif any(actual[k] != ref[k] for k in ("instance", "interface")):
      issues.append(side + "-binding-mismatch")
    elif ref["requires_connection"] and not rows and doc["complete"]:
      issues.append(side + "-unconnected")
  issues.extend(affected.get(port, ()))
  status = "fail" if issues else "pass" if schematic["complete"] and physical["complete"] else "indeterminate"
  if status == "indeterminate":
    issues.append("incomplete-netlist")
  return {**ref, "status": status, "reasons": sorted(set(issues)), "schematic_connections": design,
          "physical_connections": built, "member_lvs_status": comparison["status"]}


def _counts(rows):
  counts = Counter(row["status"] for row in rows)
  return {"declared_ports": len(rows), "matched": counts["pass"], "mismatched": counts["fail"],
          "indeterminate": counts["indeterminate"]}


def project_lvs(spec, schematics, netlists):
  """Measure the ports explicitly listed in the federation's issued asset bindings."""
  complete = spec.get("lvs_inventory_complete", False)
  if type(complete) is not bool:
    raise ValueError("lvs_inventory_complete must be boolean.")
  if schematics.keys() - spec["members"].keys() or netlists.keys() - spec["members"].keys():
    raise ValueError("Netlist map contains an unselected member.")
  if any(not isinstance(doc, dict) for documents in (schematics, netlists) for doc in documents.values()):
    raise ValueError("Member netlists must be objects.")
  physical_docs = {k: v for k, v in netlists.items() if v.get("origin") == "physical" and v.get("kind") == "domain-netlist"}
  federation = physical_federation(spec, physical_docs)
  ports = defaultdict(list)
  seen = set()
  for interface in federation["interfaces"]:
    row = {k: interface[k] for k in ("asset", "member", "instance", "port", "interface", "requires_connection", "binding_source")}
    selected = spec["members"][row["member"]]
    key = (selected["domain"], selected["scope"], selected["baseline"], row["port"])
    if key in seen:
      raise ValueError(f"Repeated project LVS port {key}.")
    seen.add(key)
    ports[row["member"]].append(row)
  members, results, unresolved = {}, [], []
  if not complete:
    unresolved.append({"reason": "port-inventory-not-confirmed"})
  for name, selected in sorted(spec["members"].items()):
    schematic, physical = schematics.get(name), netlists.get(name)
    view = federation["members"][name]
    member = members[name] = {k: selected[k] for k in ("domain", "scope", "baseline")}
    member["lvs_basis"] = selected.get("lvs_basis")
    for side, doc in (("schematic", schematic), ("physical", physical)):
      if doc is not None:
        member[side + "_digest"] = canonical_digest(doc)
        member[side + "_sources"] = doc.get("sources", {})
        member[side + "_selection"] = {k: doc.get(k) for k in ("origin", "domain", "scope", "baseline", "source_digest")}
    if not ports[name]:
      unresolved.append({"member": name, "reason": "no-issued-ports"})
    issue = _selection_issue(selected, schematic, physical, view)
    if issue:
      unresolved.append({"member": name, "reason": issue})
      rows = [{**ref, "status": "indeterminate", "reasons": [issue]} for ref in ports[name]]
    else:
      comparison = compare_netlists(schematic, physical)
      member["comparison"] = comparison
      intent, installed = _incidents(schematic), _incidents(physical)
      affected = defaultdict(set)
      for key in ("missing_connections", "extra_connections"):
        for pair in comparison[key]:
          for port in pair:
            affected[port].add(key)
      for peer in comparison["different_ports"]:
        for row in intent[peer] + installed[peer]:
          for port in row["ports"]:
            affected[port].add("endpoint-identity-mismatch")
      rows = [_port_result(ref, schematic, physical, intent, installed, comparison, affected) for ref in ports[name]]
    results.extend(rows)
    member["counts"] = _counts(rows)
    unresolved.extend({"member": name, "port": row["port"], "reasons": row["reasons"]}
                      for row in rows if row["status"] == "indeterminate")
  counts = _counts(results)
  denominator_known = complete and bool(results) and all(ports.values())
  conclusive = counts["matched"] + counts["mismatched"]
  return {"schema_version": 1, "kind": "project-lvs-coverage", "scope": spec["scope"], "baseline": spec["baseline"],
          "source": spec["source"], "spec_digest": canonical_digest(spec), "inventory_complete": denominator_known,
          "counts": counts, "conclusive_fraction": conclusive / len(results) if denominator_known else None,
          "matched_fraction": counts["matched"] / len(results) if denominator_known else None,
          "members": members, "ports": results, "unresolved": unresolved,
          "status": "fail" if counts["mismatched"] else "indeterminate" if unresolved else "pass"}
