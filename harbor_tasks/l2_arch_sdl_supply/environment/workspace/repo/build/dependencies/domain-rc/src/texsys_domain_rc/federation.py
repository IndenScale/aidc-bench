"""A project view of independent physical netlists, joined by explicit equipment references."""

from texsys.evidence import canonical_digest

from .netlist import DOMAINS, _incidence, _table, _text


def physical_federation(spec, netlists):
  if type(spec.get("schema_version")) is not int or spec["schema_version"] != 1 or spec.get("kind") != "federation-spec":
    raise ValueError("Expected a version 1 federation-spec.")
  baseline, scope, source = (_text(spec[k]) for k in ("baseline", "scope", "source"))
  members, assets = _table(spec["members"]), _table(spec["assets"])
  if not members or netlists.keys() - members.keys():
    raise ValueError("Expected named member netlists matching the project selection.")
  views, installed, interfaces = {}, {}, []
  mismatches, unresolved = [], []
  for name, expected in sorted(members.items()):
    domain, local_scope, revision = (_text(expected[k]) for k in ("domain", "scope", "baseline"))
    if domain not in DOMAINS:
      raise ValueError(f"Unsupported domain for {name}.")
    view = views[name] = {"domain": domain, "scope": local_scope, "baseline": revision}
    doc = netlists.get(name)
    if doc is None:
      unresolved.append({"member": name, "reason": "missing-member"})
      continue
    if not isinstance(doc, dict):
      raise ValueError(f"Expected a physical netlist object for {name}.")
    ports, _ = _incidence(doc, "physical")
    view["digest"] = canonical_digest(doc)
    pinned = expected.get("netlist_digest")
    if pinned is not None and _text(pinned) != view["digest"]:
      unresolved.append({"member": name, "reason": "member-digest-mismatch", "expected_digest": pinned})
      continue
    if (doc["domain"], doc["scope"], doc["baseline"]) != (domain, local_scope, revision):
      unresolved.append({"member": name, "reason": "member-selection-mismatch",
                         "observed": {key: doc[key] for key in ("domain", "scope", "baseline")}})
      continue
    view.update(source_digest=doc["source_digest"], sources=doc.get("sources", {}), complete=doc["complete"], ports=doc["ports"],
                connections=doc["connections"], unresolved=doc["unresolved"])
    if not doc["complete"]:
      unresolved.append({"member": name, "reason": "incomplete-member", "unresolved": doc["unresolved"]})
    incident = {}
    for connection, row in sorted(doc["connections"].items()):
      for port in row["ports"]:
        incident.setdefault(port, []).append(connection)
    installed[name] = ports, incident, doc["complete"]

  identities = {}
  for asset, entry in sorted(assets.items()):
    bindings = _table(entry["bindings"])
    if not bindings or bindings.keys() - members.keys():
      raise ValueError(f"Equipment {asset} requires known member bindings.")
    basis = _text(entry["source"])
    for name, request in sorted(bindings.items()):
      owner = _text(request["instance"])
      if (name, owner) in identities:
        raise ValueError(f"Instance {name}/{owner} is assigned to multiple project assets.")
      identities[name, owner] = asset
      selected = _table(request["ports"])
      if not selected:
        raise ValueError(f"No interface declared for {asset}/{name}.")
      for port, requirement in sorted(selected.items()):
        interface = _text(requirement["interface"])
        required = requirement["requires_connection"]
        if type(required) is not bool:
          raise ValueError("requires_connection must be a boolean.")
        ref = {"asset": asset, "member": name, "instance": owner, "port": port, "interface": interface,
               "requires_connection": required, "binding_source": basis}
        interfaces.append(ref)
        if name not in installed:
          ref["status"] = "indeterminate"
          continue
        ports, incident, complete = installed[name]
        actual = ports.get(port)
        ref["connections"] = incident.get(port, [])
        if actual is None:
          reason, certain = "missing-port", complete
        elif (actual["instance"], actual["interface"]) != (owner, interface):
          ref["actual"] = actual
          reason, certain = "port-binding-mismatch", True
        elif required and not ref["connections"]:
          reason, certain = "unconnected-port", complete
        else:
          ref["status"] = "pass"
          continue
        ref["status"] = "fail" if certain else "indeterminate"
        (mismatches if certain else unresolved).append({**ref, "reason": reason})
  return {"schema_version": 1, "kind": "physical-netlist-federation", "origin": "physical", "scope": scope,
          "baseline": baseline, "source": source, "members": views, "interfaces": interfaces,
          "mismatches": mismatches, "unresolved": unresolved, "complete": not unresolved,
          "status": "fail" if mismatches else "indeterminate" if unresolved else "pass"}
