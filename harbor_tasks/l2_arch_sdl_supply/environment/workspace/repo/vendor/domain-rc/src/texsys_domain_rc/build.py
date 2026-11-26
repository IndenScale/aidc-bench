"""Texsys build adapters for independently sourced netlists and LVS."""

import json
from pathlib import PurePosixPath

from texsys.evidence import file_digest, write_json
from texsys.packages import TexsysPackage
from texsys.project import inspect_project
from texsys.targets import Artifact, TargetDefinition, TargetResult

from .planar_surface import planar_surface_study
from .annual_energy import annual_energy
from .bearing_contacts import bearing_contacts
from .clearance import read_clearance_profile
from .cooling_performance import cooling_performance
from .cooling_redistribution import cooling_redistribution
from .cooling_service import cooling_dispatch, cooling_service_netlist
from .dew_history import dew_margin_history
from .distribution_loading import distribution_loading, power_dispatch
from .equipment_clearance import equipment_clearances
from .federation import physical_federation
from .filtration import filtration_study
from .flow_capacity import airflow_capacity
from .fuel_endurance import fuel_endurance
from .generator_duty import generator_load_study, generator_ratings
from .netlist import cable_netlist, compare_netlists, diagram_netlist, feeder_conductors, physical_netlist, schematic_netlist
from .project_lvs import project_lvs
from .rack_coupling import rack_heat_coupling
from .storage_transient import storage_network, storage_transient
from .tailwater import extract_drainage_paths, tailwater_study
from .thermal import rack_heat_allocation
from .ups_discharge import ups_discharge_curves
from .water_network import chilled_water_network
from .water_pressure import pressure_check, water_pressure
from .winter_water import winter_water_study
from .zonal_airflow import airflow_netlist, airflow_study, read_airflow_boundaries

OPERATIONS = {
  "domain-rc:winter-water-protection": (winter_water_study, ("scene", "schedule")),
  "domain-rc:air-filtration-paths": (filtration_study, ("network",)),
  "domain-rc:airflow-capacity": (airflow_capacity, ("network",)),
  "domain-rc:annual-energy": (annual_energy, ("basis", "runs")),
  "domain-rc:ups-discharge-curves": (ups_discharge_curves, ("scene", "catalog", "selection")),
  "domain-rc:fuel-endurance": (fuel_endurance, ("inventory", "schedule")),
  "domain-rc:generator-ratings": (generator_ratings, ("scene", "catalog")),
  "domain-rc:generator-load-study": (generator_load_study, ("ratings", "schedule")),
  "domain-rc:chilled-water-network": (chilled_water_network, ("scene", "water_netlist")),
  "domain-rc:terminal-pressure-check": (pressure_check, ("study", "requirements")),
  "domain-rc:water-pressure": (water_pressure, ("network", "schedule")),
  "domain-rc:planar-surface-study": (planar_surface_study, ("scene", "sections", "schedule")),
  "domain-rc:bearing-contacts": (bearing_contacts, ("scene", "selection")),
  "domain-rc:cooling-redistribution": (cooling_redistribution, ("network", "plan", "performance", "study")),
  "domain-rc:cooling-service-netlist": (cooling_service_netlist, ("scene", "selection")),
  "domain-rc:cooling-dispatch": (cooling_dispatch, ("network", "plan", "schedule")),
  "domain-rc:equipment-clearances": (equipment_clearances, ("scene", "selection")),
  "domain-rc:cooling-performance": (cooling_performance, ("catalog", "conditions")),
  "domain-rc:power-dispatch": (power_dispatch, ("network", "schedule")),
  "domain-rc:distribution-loading": (distribution_loading, ("network", "schedule")),
  "domain-rc:drainage-paths": (extract_drainage_paths, ("installation",)),
  "domain-rc:tailwater-study": (tailwater_study, ("paths", "schedule")),
  "domain-rc:rack-heat-coupling": (rack_heat_coupling, ("federation", "power", "calorimetry")),
  "domain-rc:dew-margin-history": (dew_margin_history, ("plan", "observations")),
  "domain-rc:project-lvs": (project_lvs, ("spec", "schematics", "netlists")),
  "domain-rc:physical-federation": (physical_federation, ("spec", "netlists")),
  "domain-rc:feeder-conductors": (feeder_conductors, ("physical_netlist", "designations")),
  "domain-rc:storage-network": (storage_network, ("scene", "water_netlist")),
  "domain-rc:storage-transient": (storage_transient, ("network", "inventory", "schedule")),
  "domain-rc:airflow-boundaries": (read_airflow_boundaries, ("scene",)),
  "domain-rc:airflow-netlist": (airflow_netlist, ("boundaries",)),
  "domain-rc:zonal-pressure": (airflow_study, ("boundaries", "schedule")),
  "domain-rc:clearance-profile": (read_clearance_profile, ("scene", "route")),
  "domain-rc:schematic-netlist": (schematic_netlist, ("schematic",)),
  "domain-rc:diagram-netlist": (diagram_netlist, ("drawing", "selection")),
  "domain-rc:cable-netlist": (cable_netlist, ("layout", "terminations")),
  "domain-rc:physical-netlist": (physical_netlist, ("layout",)),
  "domain-rc:rack-heat-allocation": (rack_heat_allocation, ("power", "rejection")),
  "domain-rc:lvs": (compare_netlists, ("schematic_netlist", "physical_netlist")),
}


def _unique(pairs):
  result = {}
  for key, value in pairs:
    if key in result:
      raise ValueError(f"Duplicate JSON key: {key}")
    result[key] = value
  return result


def _read_input(context, project, key, value):
  relative = PurePosixPath(value)
  suffixes = (".json", ".usda", ".usdc") if key == "layout" else (".json",)
  if key == "scene":
    suffixes = (".usda", ".usdc")
  if relative.is_absolute() or ".." in relative.parts or relative.suffix not in suffixes:
    raise ValueError(f"{key} requires a supported project-relative input path.")
  if relative.is_relative_to(project.build):
    path = context.build_path / relative.relative_to(project.build)
  elif any(relative.is_relative_to(prefix) for prefix in (project.source, project.assets)):
    path = context.root / relative
  else:
    raise ValueError(f"{key} is outside declared project inputs.")
  if path.resolve() != path:
    raise ValueError(f"Indirect input path: {relative}")
  if not path.is_file():
    raise FileNotFoundError(str(relative))
  if key == "scene":
    document = path
  elif relative.suffix == ".json":
    document = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique)
  else:
    from .usd_layout import read_port_layout
    document = read_port_layout(path)
  return document, {"path": str(relative), "digest": file_digest(path)}


def _inputs(context):
  operation, keys = OPERATIONS[context.target]
  if context.target == "domain-rc:terminal-pressure-check" and "observations" in context.scope:
    keys = (*keys, "observations")
  if context.scope.keys() != set(keys):
    raise ValueError(f"{context.target} requires scope {keys}.")
  project = inspect_project(context.root)
  documents, sources = [], {}
  for key in keys:
    if key == "route":
      documents.append(context.scope[key])
      continue
    if key in ("netlists", "schematics"):
      entries = context.scope[key]
      if not isinstance(entries, dict) or any(not isinstance(name, str) or not name.strip() for name in entries):
        raise ValueError(f"{key} must map member IDs to project-relative paths.")
      members, sources[key] = {}, {}
      for name, value in sorted(entries.items()):
        try:
          members[name], sources[key][name] = _read_input(context, project, key, value)
        except FileNotFoundError:
          sources[key][name] = {"path": value, "digest": None}
      documents.append(members)
    else:
      try:
        document, sources[key] = _read_input(context, project, key, context.scope[key])
      except FileNotFoundError:
        if key != "observations":
          raise
        document, sources[key] = {}, {"path": context.scope[key], "digest": None}
      documents.append(document)
  return operation, documents, sources


def build_netlist(context):
  try:
    operation, documents, sources = _inputs(context)
  except FileNotFoundError as error:
    return TargetResult("indeterminate", diagnostics=({"rule": context.target, "message": str(error)},))
  result = operation(*documents)
  result["sources"] = sources
  output = context.build_path / (context.output or f"rc/{context.target.split(':')[1]}.json")
  write_json(output, result)
  # A complete extraction *record* can enumerate unresolved joints. Only the LVS
  # target decides engineering equivalence and may use definite partial mismatches.
  status = result.get("status", "pass")
  diagnostics = ()
  if status != "pass":
    label = "LVS" if context.target == "domain-rc:lvs" else result["kind"]
    detail = {key: result[key] for key in ("mismatches", "unresolved")} if label == "physical-netlist-federation" else result
    diagnostics = ({"rule": context.target, "message": f"{label} {status}", **detail},)
  return TargetResult(status, artifacts=(Artifact(result["kind"], str(output)),), diagnostics=diagnostics,
                      details={**{key: result[key] for key in ("domain", "scope", "zone", "case") if key in result},
                               "unresolved_count": len(result["unresolved"])})


class DomainRCPackage(TexsysPackage):
  name = "domain-rc"
  version = "0.1.0"

  def targets(self):
    return tuple(TargetDefinition(key, self.name, self.version, build_netlist, named_output=True)
                 for key in OPERATIONS)


package = DomainRCPackage()
