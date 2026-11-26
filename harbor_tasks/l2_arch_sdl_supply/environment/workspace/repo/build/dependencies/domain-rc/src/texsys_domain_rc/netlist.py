"""Version 1 port-level schematic and implementation exchange for discrete connections."""

import math
from collections import Counter
from itertools import chain

from texsys.evidence import canonical_digest

DOMAINS = ("electrical", "thermal", "hydraulic", "hvac", "spatial")


def _text(value):
  if not isinstance(value, str) or not value.strip():
    raise ValueError("Expected a nonempty identifier.")
  return value


def _table(value):
  if not isinstance(value, dict):
    raise ValueError("Expected an ID-indexed object.")
  for key in value:
    _text(key)
  return value


def _point(value):
  if not isinstance(value, list) or len(value) != 3 or any(
    type(x) not in (int, float) or not math.isfinite(x) for x in value
  ):
    raise ValueError("Expected three finite coordinates in metres.")
  return value


def _header(source, kind):
  if type(source.get("schema_version")) is not int or source["schema_version"] != 1 or source.get("kind") != kind:
    raise ValueError(f"Expected a version 1 {kind}.")
  if source.get("domain") not in DOMAINS or type(source.get("complete")) is not bool:
    raise ValueError("Domain and explicit inventory completeness are required.")
  return {key: _text(source[key]) for key in ("domain", "scope", "baseline")}


def _port_table(ports):
  return {key: {field: _text(port[field]) for field in ("instance", "interface")}
          for key, port in sorted(_table(ports).items())}


def _netlist(source, origin, ports, connections, unresolved):
  return {"schema_version": 1, "kind": "domain-netlist", **_header(source, source["kind"]),
          "origin": origin, "source_digest": canonical_digest(source), "granularity": "port",
          "complete": source["complete"] and not unresolved,
          "ports": ports, "connections": connections, "unresolved": unresolved}


def schematic_netlist(source):
  """Project declared two-terminal connections. The drawing's page geometry is irrelevant."""
  _header(source, "domain-schematic")
  ports = _port_table(source["ports"])
  connections = {}
  for key, ends in sorted(_table(source["connections"]).items()):
    if not isinstance(ends, list) or len(ends) != 2 or any(_text(end) not in ports for end in ends):
      raise ValueError(f"Unknown or missing schematic terminal on {key}.")
    connections[key] = {"ports": ends, "evidence": f"connections/{key}"}
  return _netlist(source, "schematic", ports, connections, [])


def diagram_netlist(drawing, selection):
  """Read semantic port references from a Texsys schematic; exclude page geometry."""
  _header(selection, "domain-selection")
  if drawing.get("deliverable") != "schematic" or type(drawing.get("schema_version")) is not int or drawing["schema_version"] != 1:
    raise ValueError("Expected a Texsys schematic drawing, version 1.")
  if _text(selection["model_digest"]) != drawing.get("model_digest"):
    raise ValueError("Schematic selection references another source model revision.")
  interfaces = _table(selection["interfaces"])
  if not interfaces:
    raise ValueError("Declare at least one interface kind for the selected domain.")
  port_refs, ports, connections = {}, {}, {}
  matched_kinds = set()
  for node in drawing["nodes"]:
    for port in node["ports"]:
      kind = port["kind"]
      if kind not in interfaces:
        continue
      matched_kinds.add(kind)
      identifier, reference = _text(port["id"]), _text(port["semantic_ref"])
      if reference in ports or identifier in port_refs:
        raise ValueError(f"Ambiguous diagram port {reference}.")
      port_refs[identifier] = reference
      ports[reference] = {"instance": _text(node["semantic_ref"]), "interface": _text(interfaces[kind])}
  if matched_kinds != interfaces.keys():
    raise ValueError("A selected interface kind is absent from the schematic.")
  for edge in drawing["edges"]:
    source, target = edge["source"], edge["target"]
    if source not in port_refs and target not in port_refs:
      continue
    if source not in port_refs or target not in port_refs:
      raise ValueError("A schematic connection crosses the selected interface boundary.")
    key = _text(edge["semantic_ref"])
    if key in connections:
      raise ValueError(f"Duplicate schematic connection {key}.")
    connections[key] = {"ports": [port_refs[source], port_refs[target]], "evidence": edge["id"]}
  result = _netlist(selection, "schematic", ports, connections, [])
  result["source_digest"] = canonical_digest(drawing)
  result["selection_digest"] = canonical_digest(selection)
  return result


def physical_netlist(layout):
  """Extract from implementation terminations alone; geometric matching is opt-in per joint."""
  _header(layout, "port-layout")
  _text(layout["frame"])
  ports = _port_table(layout["ports"])
  positions = {key: _point(port["xyz_m"]) for key, port in layout["ports"].items() if "xyz_m" in port}
  connections, unresolved = {}, []
  for key, route in sorted(_table(layout["routes"]).items()):
    ends = route["ends"]
    if not isinstance(ends, list) or len(ends) != 2:
      raise ValueError(f"Route {key} requires two end records.")
    resolved = []
    for index, end in enumerate(ends):
      if not isinstance(end, dict):
        raise ValueError(f"Invalid end on route {key}.")
      if "port" in end:
        identity = _text(end["port"])
        if identity not in ports:
          raise ValueError(f"{key} names an unknown physical port: {identity}")
        if "joint" in end:
          raise ValueError(f"{key} end has conflicting termination methods.")
        resolved.append(identity)
        continue
      candidates = []
      if end.get("joint") == "point-mate":
        point = _point(end["xyz_m"])
        interface = _text(end["interface"])
        tolerance = end["tolerance_m"]
        if type(tolerance) not in (int, float) or not math.isfinite(tolerance) or tolerance < 0:
          raise ValueError(f"{key} requires a finite, nonnegative mating tolerance.")
        candidates = sorted(port for port, xyz in positions.items()
                            if ports[port]["interface"] == interface and math.dist(point, xyz) <= tolerance)
      elif "joint" in end:
        raise ValueError(f"Unsupported joint rule on {key}.")
      if len(candidates) == 1:
        resolved.append(candidates[0])
      else:
        unresolved.append({"route": key, "end": index, "candidates": candidates,
                           "evidence": route.get("prim", f"routes/{key}") + f"/ends/{index}"})
    if len(resolved) == 2:
      connections[key] = {"ports": resolved, "evidence": route.get("prim", f"routes/{key}/ends")}
  return _netlist(layout, "physical", ports, connections, unresolved)


def _incidence(document, origin):
  _header(document, "domain-netlist")
  if document.get("origin") != origin or document.get("granularity") != "port":
    raise ValueError(f"Expected a {origin} port-level netlist.")
  _text(document["source_digest"])
  ports = _port_table(document["ports"])
  if not isinstance(document["unresolved"], list) or (document["complete"] and document["unresolved"]):
    raise ValueError("Unresolved ends cannot substantiate a complete netlist.")
  incidence = Counter()
  for record in _table(document["connections"]).values():
    ends = record["ports"]
    _text(record["evidence"])
    if not isinstance(ends, list) or len(ends) != 2 or any(_text(end) not in ports for end in ends):
      raise ValueError("Netlist connection references an invalid port.")
    incidence[tuple(sorted(ends))] += 1
  return ports, incidence


def _difference_records(document, differences):
  # Parallel connections have indistinguishable incidence. Report all candidates at that pair.
  if not differences:
    return []
  counts = Counter(differences)
  rows = {pair: [] for pair in counts}
  for key, connection in sorted(document["connections"].items()):
    pair = tuple(sorted(connection["ports"]))
    if pair in rows:
      rows[pair].append({"id": key, **connection})
  return [{"ports": pair, "difference_count": counts[pair], "records": rows[pair]} for pair in sorted(rows)]


def compare_netlists(schematic, physical):
  """Compare undirected installed incidence, retaining parallel edges and definite differences."""
  intended_ports, intended = _incidence(schematic, "schematic")
  installed_ports, installed = _incidence(physical, "physical")
  header = {key: schematic[key] for key in ("domain", "scope", "baseline")}
  if any(physical[key] != value for key, value in header.items()):
    raise ValueError("LVS requires the same domain, scope and design baseline.")
  missing = list((intended - installed).elements()) if physical["complete"] else []
  extra = list((installed - intended).elements()) if schematic["complete"] else []
  different_ports = sorted(key for key in installed_ports.keys() & intended_ports.keys()
                           if installed_ports[key] != intended_ports[key])
  missing_ports = sorted(intended_ports.keys() - installed_ports.keys()) if physical["complete"] else []
  extra_ports = sorted(installed_ports.keys() - intended_ports.keys()) if schematic["complete"] else []
  mismatch = any((missing, extra, different_ports, missing_ports, extra_ports))
  complete = schematic["complete"] and physical["complete"]
  return {"schema_version": 1, "kind": "domain-lvs", **header,
          "status": "fail" if mismatch else "pass" if complete else "indeterminate",
          "missing_connections": sorted(missing), "extra_connections": sorted(extra),
          "missing_connection_records": _difference_records(schematic, missing),
          "extra_connection_records": _difference_records(physical, extra),
          "different_ports": different_ports, "missing_ports": missing_ports, "extra_ports": extra_ports,
          "unresolved": list(chain(schematic["unresolved"], physical["unresolved"])),
          "schematic_digest": canonical_digest(schematic), "physical_digest": canonical_digest(physical)}


def cable_netlist(layout, terminations):
  """Expand independently recorded multicore terminations on installed USD feeder routes."""
  header = _header(layout, "port-layout")
  if (_header(terminations, "cable-terminations") != header or header["domain"] != "electrical"
      or _text(terminations["frame"]) != _text(layout["frame"])):
    raise ValueError("Cable and layout records require the same electrical scope, baseline and frame.")
  _text(terminations["source"])
  feeders = _table(terminations["feeders"])
  routes = _table(layout["routes"])
  if feeders.keys() - routes.keys():
    raise ValueError("A termination record references an unknown installed feeder.")
  physical_routes, cable_cores, feed_ends, missing = {}, {}, {}, []
  for route_id, route in sorted(routes.items()):
    prim = _text(route["prim"])
    ends = route["ends"]
    if (not isinstance(ends, list) or len(ends) != 2
        or any(not isinstance(end, dict) or "port" in end or "joint" in end for end in ends)):
      raise ValueError("Multicore routes require two unassigned envelope ends.")
    schedule = _table(feeders.get(route_id, {}))
    feed_end = schedule.get("feed_end")
    if feed_end is not None and (type(feed_end) is not int or feed_end not in (0, 1)):
      raise ValueError("Feeding end must identify route end 0 or 1.")
    feed_ends[route_id] = feed_end
    cores = _table(schedule.get("cores", {}))
    if not cores:
      missing.append({"route": route_id, "reason": "missing-core-inventory", "evidence": prim})
    for key, terminals in cores.items():
      if key in physical_routes or not isinstance(terminals, list) or len(terminals) != 2:
        raise ValueError(f"Expected one unique two-ended core record for {key}.")
      cable_cores[key] = route_id
      physical_routes[key] = {"prim": prim, "ends": [{"port": port} if port is not None else {} for port in terminals]}
  expanded = {**layout, "routes": physical_routes, "complete": layout["complete"] and terminations["complete"]}
  result = physical_netlist(expanded)
  result["source_digest"] = canonical_digest([layout, terminations])
  result["termination_source"] = terminations["source"]
  for key, port in result["ports"].items():
    port["xyz_m"] = _point(layout["ports"][key]["xyz_m"])
    port["prim"] = _text(layout["ports"][key]["prim"])
  for core, connection in result["connections"].items():
    connection["feeder"] = cable_cores[core]
    connection["termination_record"] = ["feeders", cable_cores[core], "cores", core]
  for item in result["unresolved"]:
    item["core"] = item["route"]
    item["route"] = cable_cores[item["core"]]
    item["termination_record"] = ["feeders", item["route"], "cores", item["core"], item["end"]]
  result["unresolved"].extend(missing)
  result["complete"] = result["complete"] and not missing
  result["feeder_ends"] = feed_ends
  return result


class FeederProjectionUnavailable(ValueError):
  """Installed incidence alone does not establish a single directed equipment feed."""


def feeder_links(physical):
  """Project a complete core inventory into fixed-direction equipment feeds for a case."""
  ports, _ = _incidence(physical, "physical")
  if physical["domain"] != "electrical" or not physical["complete"]:
    raise ValueError("Feeder projection requires a complete electrical physical netlist.")
  feed_ends = _table(physical["feeder_ends"])
  owners = {}
  for key, connection in physical["connections"].items():
    feeder = _text(connection["feeder"])
    pair = [ports[port]["instance"] for port in connection["ports"]]
    if feeder not in feed_ends:
      raise ValueError(f"Core {key} references an unknown feeder.")
    if pair[0] == pair[1] or owners.setdefault(feeder, pair) != pair:
      raise FeederProjectionUnavailable(f"馈线 {feeder} 的芯线未形成同一对设备端点（{key}）")
  if owners.keys() != feed_ends.keys():
    raise ValueError("Feeder and core inventories disagree.")
  links = []
  for feeder, pair in sorted(owners.items()):
    end = feed_ends[feeder]
    if end is None:
      raise FeederProjectionUnavailable(f"馈线 {feeder} 在本次工况下的送电端未确认")
    if type(end) is not int or end not in (0, 1):
      raise ValueError(f"Invalid feed end on {feeder}.")
    links.append({"route": feeder, "from": pair[end], "to": pair[1-end], "feed_end": end})
  return links


def feeder_conductors(physical, designations):
  """Join installed two-ended cores to independently declared terminal functions."""
  ports, _ = _incidence(physical, "physical")
  header = _header(designations, "terminal-designations")
  if header["domain"] != "electrical" or physical["domain"] != "electrical":
    raise ValueError("Conductor observations require electrical evidence.")
  source = _text(designations["source"])
  declared = _table(designations["terminals"])
  roles = {"L", "N", "PE", "PEN", "DC+", "DC-"}
  if any(role is not None and role not in roles for role in declared.values()):
    raise ValueError("Unknown terminal function.")
  feeders = {key: {"cores": {}, "conductors": [], "conflicts": [], "unknown_cores": []}
             for key in sorted(_table(physical["feeder_ends"]))}
  issues = []
  matched = all(physical[key] == header[key] for key in header)
  if not matched:
    issues.append({"reason": "designation-baseline-mismatch"})
  elif declared.keys() - ports.keys():
    raise ValueError("Terminal designations reference ports outside the installed inventory.")
  if not designations["complete"]:
    issues.append({"reason": "unconfirmed-designation-inventory"})
  if not physical["complete"]:
    issues.append({"reason": "unconfirmed-installed-inventory"})
  for core, connection in sorted(physical["connections"].items()):
    feeder = _text(connection["feeder"])
    if feeder not in feeders:
      raise ValueError("Core references unknown feeder.")
    row = feeders[feeder]
    ends = connection["ports"]
    pair = [declared.get(port) if matched else None for port in ends]
    row["cores"][core] = {"ports": ends, "terminal_roles": pair, "evidence": connection["evidence"]}
    if None in pair:
      row["unknown_cores"].append(core)
      issues.append({"feeder": feeder, "core": core, "reason": "unknown-terminal-function"})
    elif pair[0] != pair[1]:
      row["conflicts"].append(core)
    elif pair[0] not in row["conductors"]:
      row["conductors"].append(pair[0])
  for row in feeders.values():
    row["conductors"].sort()
    row["complete"] = physical["complete"] and designations["complete"] and matched and not row["unknown_cores"]
  return {"schema_version": 1, "kind": "feeder-conductors", "domain": "electrical",
          "baseline": physical["baseline"], "scope": physical["scope"], "netlist_digest": canonical_digest(physical),
          "designation_source": source, "feeders": feeders, "unresolved": issues, "complete": not issues}
