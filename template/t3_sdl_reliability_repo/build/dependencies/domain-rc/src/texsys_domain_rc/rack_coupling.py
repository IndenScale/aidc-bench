"""Steady equipment-boundary power and sensible liquid heat transfer on federated ports."""

import math

from texsys.evidence import canonical_digest

from .netlist import _table, _text
from .thermal import rack_heat_allocation


def _number(row, key, *, positive=False, signed=False):
  if not isinstance(row, dict):
    raise TypeError(f"{key} requires an observation record.")
  value = row.get(key)
  if value is None:
    return None
  if (type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0)
      or (not signed and value < 0)):
    raise ValueError(f"Invalid equipment boundary reading {key}.")
  return value


def _version(record, kind):
  if not isinstance(record, dict) or type(record.get("schema_version")) is not int or record["schema_version"] != 1 or record.get("kind") != kind:
    raise ValueError(f"Expected version 1 {kind}.")


def rack_heat_coupling(federation, power, calorimetry):
  _version(federation, "physical-netlist-federation")
  if federation.get("origin") != "physical":
    raise ValueError("Equipment heat coupling requires physical interfaces.")
  _version(power, "terminal-power")
  header = {"schema_version": 1, **{k: _text(power.get(k)) for k in ("baseline", "case", "zone", "frame")}}
  unresolved = []
  for schedule, kind in ((power, "terminal-power"), (calorimetry, "rack-calorimetry")):
    _version(schedule, kind)
    _text(schedule["source"])
    if type(schedule.get("complete")) is not bool:
      raise ValueError(f"{kind} requires an inventory declaration.")
    if (any(schedule.get(k) != v for k, v in header.items()) or schedule.get("scope") != federation["scope"]
        or schedule["baseline"] != federation["baseline"]):
      unresolved.append({"reason": "incompatible-case-or-project-selection", "schedule": kind})
    _table(schedule["items"])
  positions = {}
  for row in federation["interfaces"]:
    domain = federation["members"][row["member"]]["domain"]
    if domain in ("electrical", "hydraulic"):
      positions.setdefault(row["asset"], {})[row["member"], row["port"]] = (domain, row)
  powers, heats, traces = {}, {}, {}
  assets = power["items"].keys() | calorimetry["items"].keys()
  if not assets:
    unresolved.append({"reason": "empty-equipment-inventory"})
  eligible_assets = sorted(assets) if not unresolved else []
  for asset in eligible_assets:
    p, h = power["items"].get(asset), calorimetry["items"].get(asset)
    if p is None or h is None or asset not in positions:
      unresolved.append({"instance": asset, "reason": "missing-equipment-or-survey"})
      continue
    ports = positions[asset]
    if not isinstance(p, dict) or not isinstance(h, dict):
      raise TypeError(f"{asset} requires equipment-boundary records.")
    issues, inputs, circuits, used, witnesses = [], [], {}, set(), []
    def bind(member, port, domain):
      ref = (_text(member), _text(port))
      if ref in used:
        raise ValueError(f"{asset}: terminal counted twice: {ref}.")
      used.add(ref)
      item = ports.get(ref)
      if not item or item[0] != domain or item[1]["status"] != "pass" or not item[1].get("connections"):
        issues.append({"reason": "unqualified-terminal", "member": member, "port": port})
      else:
        witnesses.append({"member": member, "port": port, "instance": item[1]["instance"],
                          "connections": item[1]["connections"], "binding_source": item[1]["binding_source"]})

    for member, pins in _table(p.get("members", {})).items():
      for port, reading in _table(pins).items():
        bind(member, port, "electrical")
        kw = _number(reading, "input_kw")
        inputs.append({"member": member, "port": port, "input_kw": kw})
        if kw is None:
          issues.append({"reason": "missing-terminal-power", "port": port})
    if not inputs:
      issues.append({"reason": "missing-electrical-inputs"})
    if "circuits" not in h:
      issues.append({"reason": "missing-liquid-inventory"})
    for key, row in _table(h.get("circuits", {})).items():
      if not isinstance(row, dict):
        raise TypeError(f"{key} requires a liquid circuit record.")
      for port in ("inlet", "outlet"):
        if row.get("member") and row.get(port):
          bind(row["member"], row[port], "hydraulic")
        else:
          issues.append({"reason": "missing-circuit-terminal", "circuit": key, "terminal": port})
      flow = _number(row, "mass_flow_in_to_out_kg_s", signed=True)
      cp = _number(row, "specific_heat_kj_kg_k", positive=True)
      inlet = _number(row, "inlet_c", signed=True)
      outlet = _number(row, "outlet_c", signed=True)
      heat = None if None in (flow, cp, inlet, outlet) else flow * cp * (outlet - inlet)
      if heat is not None and not math.isfinite(heat):
        raise ValueError(f"{key}: liquid heat calculation overflowed.")
      circuits[key] = {**row, "liquid_kw": heat}
      if heat is None or heat < 0:
        issues.append({"reason": "missing-liquid-reading" if heat is None else "net-heat-enters-equipment", "circuit": key})
    for ref, (_, item) in ports.items():
      if item["requires_connection"] and ref not in used:
        issues.append({"reason": "required-terminal-not-in-survey", "member": ref[0], "port": ref[1]})
    room, outside = _number(h, "room_kw"), _number(h, "outside_kw")
    if None in (room, outside) or not p.get("basis"):
      issues.append({"reason": "missing-rejection-or-power-basis"})
    traces[asset] = {"interfaces": witnesses, "power_inputs": inputs, "circuits": circuits, "room_kw": room, "outside_kw": outside}
    if issues:
      unresolved.extend({"instance": asset, **issue} for issue in issues)
      continue
    powers[asset] = {"basis": p["basis"], "power_kw": math.fsum(item["input_kw"] for item in inputs)}
    heats[asset] = {"room_kw": room, "outside_kw": outside, "liquid_kw": math.fsum(c["liquid_kw"] for c in circuits.values())}
  result = rack_heat_allocation({**header, "kind": "operating-power", "source": power["source"], "items": powers, "complete": power["complete"]},
                                {**header, "kind": "heat-rejection", "source": calorimetry["source"], "items": heats, "complete": calorimetry["complete"]})
  return {**result, "complete": result["complete"] and not unresolved, "unresolved": unresolved,
          "method": "federated-terminal-calorimetry", "federation_digest": canonical_digest(federation),
          "scope": federation["scope"], "boundary_observations": traces}
