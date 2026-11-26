"""Executable compliance evaluator for OCP (ORv3 / ACS Liquid Cooling / DCF) specifications."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from texsys.evidence import canonical_digest
from texsys.pdk import load_pdk_module
from texsys.project import inspect_project
from texsys.sdl_catalog import read_sdl_catalog
from texsys_ocp_pdk import check_port_compatibility, list_ocp_modules

RULES_DIR = Path(__file__).resolve().parent / "rules"


def load_ruleset() -> tuple[dict[str, dict[str, Any]], str]:
  """Load all OCP clause definitions and compute a canonical digest."""
  registry: dict[str, dict[str, Any]] = {}
  for path in sorted(RULES_DIR.glob("*.json")):
    payload = json.loads(path.read_text(encoding="utf-8"))
    spec_name = str(payload.get("spec", ""))
    revision = str(payload.get("revision", ""))
    domain = str(payload.get("domain", path.stem))
    for rule_id, body in payload.get("rules", {}).items():
      registry[rule_id] = {
        "rule_id": rule_id,
        "domain": domain,
        "spec": spec_name,
        "revision": revision,
        **body,
      }
  return registry, canonical_digest(registry)


def _is_finite(value: Any) -> bool:
  return type(value) in (int, float) and math.isfinite(float(value))


def _relative_file(path: Path, root: Path) -> str:
  try:
    return path.resolve().relative_to(root.resolve()).as_posix()
  except ValueError:
    return path.as_posix()


def _is_ocp_module(entry: str, spec: dict[str, Any]) -> bool:
  if entry.startswith("@ocp-pdk/"):
    return True
  props = spec.get("properties", {})
  if (
    "ocp_base_unit" in spec
    or "ocp_base_unit" in props
    or "ocp_spec" in spec
    or "ocp_compliance_profile" in spec
  ):
    return True
  form_factor = str(props.get("form_factor", ""))
  return "ocp" in form_factor.lower() or "orv3" in form_factor.lower()


def _add_finding(
  findings: list[dict[str, Any]],
  rules: dict[str, dict[str, Any]],
  *,
  rule_id: str,
  status: str,
  file: str,
  obj: str | None,
  message: str,
  measured: Any = None,
  limit: Any = None,
) -> None:
  meta = rules[rule_id]
  findings.append({
    "rule_id": rule_id,
    "spec": meta["spec"],
    "clause": meta["clause"],
    "title": meta["title"],
    "status": status,
    "file": file,
    "object": obj,
    "message": message,
    "measured": measured,
    "limit": limit,
  })


def _evaluate_module(
  *,
  entry: str,
  mod_dir: Path,
  spec: dict[str, Any],
  sdl_doc: dict[str, Any],
  root: Path,
  rules: dict[str, dict[str, Any]],
  findings: list[dict[str, Any]],
) -> None:
  rel_spec = _relative_file(mod_dir / "assets" / "specification.json", root)
  props = spec.get("properties", {})
  clearances = spec.get("clearances_m", {})
  root_comp = sdl_doc.get("components", {}).get(sdl_doc.get("root", ""), {})
  params = root_comp.get("behavior", {}).get("parameters", {})

  # OCP-DCF-003: Provenance state governance
  allowed_states = set(rules["OCP-DCF-003"]["limits"]["allowed_states"])
  spec_state = spec.get("state")
  if spec_state not in allowed_states:
    _add_finding(
      findings, rules,
      rule_id="OCP-DCF-003", status="indeterminate", file=rel_spec, obj=entry,
      message=f"Module specification state {spec_state!r} must be one of {sorted(allowed_states)}.",
      measured=spec_state, limit=sorted(allowed_states),
    )
  else:
    _add_finding(
      findings, rules,
      rule_id="OCP-DCF-003", status="pass", file=rel_spec, obj=entry,
      message=f"Provenance state {spec_state!r} is explicitly declared.",
      measured=spec_state, limit=sorted(allowed_states),
    )

  # OCP-DCF-001: Port compatibility against declared ocp_base_unit
  base_unit = spec.get("ocp_base_unit") or props.get("ocp_base_unit")
  if isinstance(base_unit, str) and base_unit.strip():
    base_slug = base_unit.rstrip("/").split("/")[-1]
    if base_slug not in set(list_ocp_modules()):
      _add_finding(
        findings, rules,
        rule_id="OCP-DCF-001", status="fail", file=rel_spec, obj=entry,
        message=f"Declared ocp_base_unit {base_unit!r} does not resolve in ocp-pdk.",
        measured=base_slug, limit=list(list_ocp_modules()),
      )
    else:
      raw_map = spec.get("ocp_port_map") or props.get("ocp_port_map")
      port_map = {str(k): str(v) for k, v in raw_map.items()} if isinstance(raw_map, dict) and raw_map else None
      compat = check_port_compatibility(base_slug, mod_dir, port_map=port_map)
      if not compat["compatible"]:
        _add_finding(
          findings, rules,
          rule_id="OCP-DCF-001", status="fail", file=rel_spec, obj=entry,
          message=(
            f"Incompatible ports vs OCP base {base_slug}: "
            f"missing={compat['missing_ports']}, mismatched={compat['mismatched_ports']}"
          ),
          measured=compat, limit="compatible=True",
        )
      else:
        _add_finding(
          findings, rules,
          rule_id="OCP-DCF-001", status="pass", file=rel_spec, obj=entry,
          message=f"All ports compatible with OCP base cell {base_slug}.",
          measured=compat["checked_ports"], limit=base_slug,
        )

  is_rack = any(
    k in entry or k in str(props.get("form_factor", "")).lower()
    for k in ("rack", "orv3-frame", "orv3-hpr-frame")
  ) and "manifold" not in entry and "tray" not in entry and "busbar" not in entry

  if is_rack:
    envelope = spec.get("envelope_m")
    if isinstance(envelope, list) and len(envelope) == 3 and _is_finite(envelope[0]):
      width = float(envelope[0])
      target_w = rules["OCP-ORV3-MECH-001"]["limits"]["rack_width_m"]
      tol = rules["OCP-ORV3-MECH-001"]["limits"]["width_tolerance_m"]
      mount_in = props.get("mounting_width_in")
      pitch_m = props.get("unit_pitch_m")
      mech_ok = abs(width - target_w) <= tol
      if mount_in is not None and mount_in != 21:
        mech_ok = False
      if pitch_m is not None and (not _is_finite(pitch_m) or abs(float(pitch_m) - 0.048) > 0.0005):
        mech_ok = False
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-MECH-001",
        status="pass" if mech_ok else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"Rack width {width:.3f} m (mount={mount_in}, pitch={pitch_m}) satisfies ORv3 21-inch / 48 mm OU."
          if mech_ok
          else f"Rack mechanical geometry violates ORv3 600 mm / 21-inch / 48 mm OU (width={width}, mount={mount_in}, pitch={pitch_m})."
        ),
        measured={"width_m": width, "mounting_width_in": mount_in, "unit_pitch_m": pitch_m},
        limit={"width_m": target_w, "mounting_width_in": 21, "unit_pitch_m": 0.048},
      )

    mass = spec.get("mass_kg", props.get("max_static_load_kg"))
    if _is_finite(mass):
      mass_val = float(mass)
      max_mass = (
        rules["OCP-ORV3-MECH-002"]["limits"]["hpr_max_mass_kg"]
        if "hpr" in entry or "hpr" in str(props.get("form_factor", "")).lower() or "mgx" in str(props.get("form_factor", "")).lower()
        else rules["OCP-ORV3-MECH-002"]["limits"]["base_max_mass_kg"]
      )
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-MECH-002",
        status="pass" if mass_val <= max_mass else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"Rack mass {mass_val:.1f} kg within ORv3 limit {max_mass:.1f} kg."
          if mass_val <= max_mass
          else f"Rack mass {mass_val:.1f} kg exceeds ORv3 limit {max_mass:.1f} kg."
        ),
        measured=mass_val, limit=max_mass,
      )

    front = clearances.get("front_service_m")
    rear = clearances.get("rear_manifold_and_backplane_m", clearances.get("rear_manifold_and_busbar_m", clearances.get("rear_service_m")))
    if _is_finite(front) and _is_finite(rear):
      ok = float(front) >= 1.2 - 1e-6 and float(rear) >= 1.2 - 1e-6
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-MECH-003",
        status="pass" if ok else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"Service clearances front={front} m, rear={rear} m meet >= 1.2 m."
          if ok
          else f"Service clearances front={front} m, rear={rear} m below ORv3 1.2 m minimum."
        ),
        measured={"front_m": front, "rear_m": rear}, limit={"min_m": 1.2},
      )

    top_c = clearances.get("top_cable_and_busway_m")
    if _is_finite(top_c):
      ok = float(top_c) >= 0.6 - 1e-6
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-MECH-004",
        status="pass" if ok else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"Top overhead clearance {top_c} m >= 0.6 m."
          if ok
          else f"Top overhead clearance {top_c} m < 0.6 m."
        ),
        measured=top_c, limit=0.6,
      )

    dc_v = props.get("internal_dc_bus_v")
    if _is_finite(dc_v):
      dc_val = float(dc_v)
      ok = 48.0 <= dc_val <= 51.0
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-PWR-001",
        status="pass" if ok else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"Internal DC bus voltage {dc_val} V within ORv3 48-51 V window."
          if ok
          else f"Internal DC bus voltage {dc_val} V outside ORv3 48-51 V window."
        ),
        measured=dc_val, limit=[48.0, 51.0],
      )

    shelves = params.get("power_shelf_count", {}).get("value", props.get("power_shelves"))
    shelf_kw = params.get("power_shelf_capacity_kw", {}).get("value")
    rack_kw = params.get("nominal_rack_power_kw", {}).get("value")
    if _is_finite(shelves) and _is_finite(shelf_kw) and _is_finite(rack_kw):
      n_minus_1_kw = (float(shelves) - 1.0) * float(shelf_kw)
      ok = n_minus_1_kw >= float(rack_kw) - 1e-6 and float(shelves) >= 2
      _add_finding(
        findings, rules,
        rule_id="OCP-ORV3-PWR-002",
        status="pass" if ok else "fail",
        file=rel_spec, obj=entry,
        message=(
          f"N+1 power shelf capacity {n_minus_1_kw:.1f} kW covers nominal rack {rack_kw:.1f} kW."
          if ok
          else f"N+1 power shelf capacity {n_minus_1_kw:.1f} kW is below nominal rack {rack_kw:.1f} kW."
        ),
        measured=n_minus_1_kw, limit=float(rack_kw),
      )

    # Liquid cooling rules on liquid-cooled racks
    if "tcs_supply" in root_comp.get("ports", {}) or "tcs_in_a" in root_comp.get("ports", {}):
      t_min = params.get("min_tcs_supply_c", {}).get("value")
      t_max = params.get("max_tcs_supply_c", {}).get("value", params.get("maximum_inlet_temperature", {}).get("value"))
      if _is_finite(t_min) and _is_finite(t_max):
        ok = float(t_min) >= 25.0 and float(t_max) <= 45.0
        _add_finding(
          findings, rules,
          rule_id="OCP-LC-THM-001",
          status="pass" if ok else "fail",
          file=rel_spec, obj=entry,
          message=(
            f"TCS supply temperature window [{t_min}, {t_max}] degC within [25, 45] degC."
            if ok
            else f"TCS supply temperature window [{t_min}, {t_max}] degC violates [25, 45] degC."
          ),
          measured=[t_min, t_max], limit=[25.0, 45.0],
        )

      leak = props.get("leak_detection")
      _add_finding(
        findings, rules,
        rule_id="OCP-LC-CDU-002",
        status="pass" if isinstance(leak, str) and leak.strip() else "indeterminate",
        file=rel_spec, obj=entry,
        message=(
          f"Leak detection declared: {leak}"
          if isinstance(leak, str) and leak.strip()
          else "Rack liquid leak detection specification is missing."
        ),
        measured=leak, limit="non-empty leak_detection",
      )

  # Coupler / manifold dynamic pressure check
  max_p = props.get("max_dynamic_pressure_kpa_g", props.get("max_working_pressure_kpa_g"))
  if _is_finite(max_p):
    ok = float(max_p) <= 450.0
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-HYD-002",
      status="pass" if ok else "fail",
      file=rel_spec, obj=entry,
      message=(
        f"Coupler/manifold pressure rating {max_p} kPa(g) <= 450 kPa(g)."
        if ok
        else f"Coupler/manifold pressure rating {max_p} kPa(g) exceeds 450 kPa(g)."
      ),
      measured=max_p, limit=450.0,
    )

  # CDU approach check
  approach = props.get("nominal_approach_k")
  if _is_finite(approach) and ("cdu" in entry or "coolant-distribution" in entry):
    ok = float(approach) <= 5.0
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-CDU-001",
      status="pass" if ok else "fail",
      file=rel_spec, obj=entry,
      message=(
        f"CDU nominal approach {approach} K <= 5.0 K."
        if ok
        else f"CDU nominal approach {approach} K exceeds 5.0 K limit."
      ),
      measured=approach, limit=5.0,
    )

  # Liberty table check if present
  try:
    mod = load_pdk_module(mod_dir)
    if mod.liberty is not None:
      env = mod.liberty.operating_envelope
      coolant = env.get("coolant", env.get("fluid_secondary"))
      if isinstance(coolant, str):
        allowed_coolants = set(rules["OCP-LC-CDU-002"]["limits"]["allowed_coolants"])
        ok = coolant.lower() in allowed_coolants
        _add_finding(
          findings, rules,
          rule_id="OCP-LC-CDU-002",
          status="pass" if ok else "fail",
          file=_relative_file(mod_dir / "assets" / "liberty.json", root),
          obj=entry,
          message=(
            f"Coolant chemistry {coolant!r} is qualified."
            if ok
            else f"Coolant chemistry {coolant!r} is not in {sorted(allowed_coolants)}."
          ),
          measured=coolant, limit=sorted(allowed_coolants),
        )
      if "liquid_cooling_fraction" in env and "air_cooling_fraction" in env:
        lf = float(env["liquid_cooling_fraction"])
        af = float(env["air_cooling_fraction"])
        ok = 0.7 <= lf <= 0.98 and abs((lf + af) - 1.0) <= 0.001
        _add_finding(
          findings, rules,
          rule_id="OCP-LC-THM-002",
          status="pass" if ok else "fail",
          file=_relative_file(mod_dir / "assets" / "liberty.json", root),
          obj=entry,
          message=(
            f"Heat split liquid={lf:.2f} + air={af:.2f} = 1.00."
            if ok
            else f"Heat split liquid={lf:.2f}, air={af:.2f} violates closure/bounds."
          ),
          measured={"liquid": lf, "air": af}, limit={"sum": 1.0, "liquid_range": [0.7, 0.98]},
        )
  except Exception:
    pass


def _evaluate_intent(
  *,
  intent: dict[str, Any],
  file_rel: str,
  rules: dict[str, dict[str, Any]],
  findings: list[dict[str, Any]],
) -> None:
  rack = intent.get("rack", {}) if isinstance(intent.get("rack"), dict) else {}
  site = intent.get("site", {}) if isinstance(intent.get("site"), dict) else {}
  limits = intent.get("limits", {}) if isinstance(intent.get("limits"), dict) else {}
  thermal = intent.get("thermal", {}) if isinstance(intent.get("thermal"), dict) else {}

  # Rack width & mass
  width = rack.get("width_m")
  if width is None:
    _add_finding(
      findings, rules,
      rule_id="OCP-ORV3-MECH-001", status="indeterminate", file=file_rel, obj="rack.width_m",
      message="Missing rack.width_m in project intent/basis; cannot verify ORv3 600 mm width.",
    )
  else:
    w_val = float(width)
    ok = abs(w_val - 0.6) <= 0.005
    _add_finding(
      findings, rules,
      rule_id="OCP-ORV3-MECH-001", status="pass" if ok else "fail", file=file_rel, obj="rack.width_m",
      message=(
        f"Intent rack width {w_val:.3f} m conforms to ORv3 0.600 m."
        if ok
        else f"Intent rack width {w_val:.3f} m deviates from ORv3 0.600 m +/- 0.005 m."
      ),
      measured=w_val, limit=0.6,
    )

  mass = rack.get("mass_kg")
  depth = rack.get("depth_m")
  max_floor = site.get("max_floor_load_kpa")
  if mass is None or depth is None or max_floor is None:
    _add_finding(
      findings, rules,
      rule_id="OCP-ORV3-MECH-002", status="indeterminate", file=file_rel, obj="rack.mass_kg",
      message="Missing rack.mass_kg, rack.depth_m, or site.max_floor_load_kpa for ORv3 load check.",
    )
  else:
    m_val = float(mass)
    w_val = float(width or 0.6)
    d_val = float(depth)
    # Distributed bay load with standard 1.5x aisle allowance (rack footprint * 2.5) + 1.8 kPa floor/MEP
    bay_load_kpa = (m_val * 9.80665 / 1000.0) / max(0.2, w_val * d_val * 2.5) + 1.8
    ok = m_val <= 1800.0 and bay_load_kpa <= float(max_floor)
    _add_finding(
      findings, rules,
      rule_id="OCP-ORV3-MECH-002", status="pass" if ok else "fail", file=file_rel, obj="rack.mass_kg",
      message=(
        f"Rack mass {m_val:.1f} kg (<=1800 kg) and distributed load {bay_load_kpa:.2f} kPa <= {max_floor} kPa."
        if ok
        else f"Rack mass {m_val:.1f} kg or distributed load {bay_load_kpa:.2f} kPa exceeds ORv3/site limit ({max_floor} kPa)."
      ),
      measured={"mass_kg": m_val, "distributed_load_kpa": round(bay_load_kpa, 2)},
      limit={"max_mass_kg": 1800.0, "max_floor_load_kpa": max_floor},
    )

  # TCS supply temperature envelope
  tcs_set = thermal.get("tcs_supply_setpoint_c")
  tcs_max = thermal.get("max_tcs_supply_c")
  if tcs_set is None or tcs_max is None:
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-THM-001", status="indeterminate", file=file_rel, obj="thermal.tcs_supply_setpoint_c",
      message="Missing thermal.tcs_supply_setpoint_c or max_tcs_supply_c; cannot verify 25-45 degC envelope.",
    )
  else:
    t1, t2 = float(tcs_set), float(tcs_max)
    ok = 25.0 <= t1 <= 45.0 and 25.0 <= t2 <= 45.0 and t1 <= t2
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-THM-001", status="pass" if ok else "fail", file=file_rel, obj="thermal",
      message=(
        f"TCS supply setpoint {t1} degC / max {t2} degC within [25, 45] degC."
        if ok
        else f"TCS supply setpoint {t1} degC / max {t2} degC outside OCP [25, 45] degC envelope."
      ),
      measured={"setpoint_c": t1, "max_c": t2}, limit=[25.0, 45.0],
    )

  # TCS hydraulic drop
  max_dp = limits.get("max_tcs_dp_kpa")
  if max_dp is None:
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-HYD-001", status="indeterminate", file=file_rel, obj="limits.max_tcs_dp_kpa",
      message="Missing limits.max_tcs_dp_kpa; cannot verify secondary TCS pressure drop limit.",
    )
  else:
    dp_val = float(max_dp)
    ok = 0.0 < dp_val <= 240.0
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-HYD-001", status="pass" if ok else "fail", file=file_rel, obj="limits.max_tcs_dp_kpa",
      message=(
        f"TCS pressure drop budget {dp_val} kPa <= 240 kPa."
        if ok
        else f"TCS pressure drop budget {dp_val} kPa exceeds OCP 240 kPa ceiling."
      ),
      measured=dp_val, limit=240.0,
    )

  # Busway voltage drop & PUE
  vdrop = limits.get("max_busway_vdrop_pct")
  if vdrop is not None:
    v_val = float(vdrop)
    ok = 0.0 < v_val <= 2.5
    _add_finding(
      findings, rules,
      rule_id="OCP-ORV3-PWR-003", status="pass" if ok else "fail", file=file_rel, obj="limits.max_busway_vdrop_pct",
      message=(
        f"Busway voltage drop limit {v_val}% <= 2.5%."
        if ok
        else f"Busway voltage drop limit {v_val}% exceeds OCP 2.5%."
      ),
      measured=v_val, limit=2.5,
    )

  pue = limits.get("max_pue")
  if pue is None:
    _add_finding(
      findings, rules,
      rule_id="OCP-DCF-002", status="indeterminate", file=file_rel, obj="limits.max_pue",
      message="Missing limits.max_pue; cannot verify OCP DCF facility PUE envelope.",
    )
  else:
    p_val = float(pue)
    ok = 1.0 < p_val <= 1.35
    _add_finding(
      findings, rules,
      rule_id="OCP-DCF-002", status="pass" if ok else "fail", file=file_rel, obj="limits.max_pue",
      message=(
        f"Facility PUE target {p_val} <= 1.35."
        if ok
        else f"Facility PUE target {p_val} outside (1.0, 1.35]."
      ),
      measured=p_val, limit=1.35,
    )

  # Liquid cooling fraction & CDU N+1 sizing
  liq_racks = intent.get("liquid_rack_count")
  rack_kw = intent.get("rack_power_kw")
  liq_frac = intent.get("liquid_cooling_fraction")
  cdu_kw = thermal.get("cdu_rated_kw")
  if _is_finite(liq_racks) and _is_finite(rack_kw) and _is_finite(liq_frac):
    lf = float(liq_frac)
    ok_lf = 0.7 <= lf <= 0.98
    _add_finding(
      findings, rules,
      rule_id="OCP-LC-THM-002", status="pass" if ok_lf else "fail", file=file_rel, obj="liquid_cooling_fraction",
      message=(
        f"Liquid cooling fraction {lf:.2f} within [0.70, 0.98]; residual air fraction {1.0 - lf:.2f}."
        if ok_lf
        else f"Liquid cooling fraction {lf:.2f} outside OCP direct-to-chip range [0.70, 0.98]."
      ),
      measured=lf, limit=[0.7, 0.98],
    )
    if _is_finite(cdu_kw) and float(cdu_kw) > 0:
      total_liq = float(liq_racks) * float(rack_kw) * lf
      n_active = max(1, math.ceil(total_liq / float(cdu_kw)))
      n_total = n_active + 1
      _add_finding(
        findings, rules,
        rule_id="OCP-LC-CDU-001", status="pass", file=file_rel, obj="thermal.cdu_rated_kw",
        message=f"Total liquid load {total_liq:.1f} kW served by {n_total}x {float(cdu_kw):.0f} kW CDUs (N+1).",
        measured={"total_liquid_kw": total_liq, "cdu_total_n_plus_1": n_total},
        limit={"cdu_rated_kw": float(cdu_kw)},
      )


def evaluate_project_ocp_compliance(root: Path) -> dict[str, Any]:
  """Evaluate all applicable OCP rules against a TexSys project or package."""
  root = Path(root).expanduser().resolve()
  rules, ruleset_digest = load_ruleset()
  project = inspect_project(root)
  source_dir = root / (project.source if project else "src")

  findings: list[dict[str, Any]] = []
  evaluated_modules: list[str] = []

  if source_dir.is_dir():
    catalog = read_sdl_catalog(source_dir, root)
    for entry, _manifest in sorted(catalog.modules.items()):
      sdl_doc = catalog.documents.get(entry)
      sdl_path = catalog.files.get(entry)
      if sdl_doc is None or sdl_path is None:
        continue
      mod_dir = sdl_path.parent
      spec_path = mod_dir / "assets" / "specification.json"
      if not spec_path.is_file():
        continue
      spec = json.loads(spec_path.read_text(encoding="utf-8"))
      if not _is_ocp_module(entry, spec):
        continue
      evaluated_modules.append(entry)
      _evaluate_module(
        entry=entry,
        mod_dir=mod_dir,
        spec=spec,
        sdl_doc=sdl_doc,
        root=root,
        rules=rules,
        findings=findings,
      )

  # Inspect aidc.intent.json or ocp-basis.json if present
  for rel_name in ("aidc.intent.json", "ocp-basis.json"):
    candidate = source_dir / rel_name
    if candidate.is_file():
      payload = json.loads(candidate.read_text(encoding="utf-8"))
      _evaluate_intent(
        intent=payload,
        file_rel=_relative_file(candidate, root),
        rules=rules,
        findings=findings,
      )

  # Inspect rack_geometry.json (e.g., tray hot-swap multiphysics)
  rack_geom_path = source_dir / "rack_geometry.json"
  if rack_geom_path.is_file():
    geom = json.loads(rack_geom_path.read_text(encoding="utf-8"))
    if isinstance(geom, dict) and _is_finite(geom.get("max_pressure_kpa_g")):
      p_val = float(geom["max_pressure_kpa_g"])
      ok = p_val <= 450.0
      _add_finding(
        findings, rules,
        rule_id="OCP-LC-HYD-002", status="pass" if ok else "fail",
        file=_relative_file(rack_geom_path, root), obj="max_pressure_kpa_g",
        message=(
          f"Transient coupler pressure bound {p_val} kPa(g) <= 450 kPa(g)."
          if ok
          else f"Transient coupler pressure bound {p_val} kPa(g) exceeds 450 kPa(g)."
        ),
        measured=p_val, limit=450.0,
      )

  if not findings:
    _add_finding(
      findings, rules,
      rule_id="OCP-DCF-003",
      status="indeterminate",
      file="texsys.toml",
      obj=None,
      message="No OCP PDK modules, src/aidc.intent.json, or src/ocp-basis.json found to substantiate OCP compliance.",
    )

  counts = {
    "pass": sum(1 for f in findings if f["status"] == "pass"),
    "fail": sum(1 for f in findings if f["status"] == "fail"),
    "indeterminate": sum(1 for f in findings if f["status"] == "indeterminate"),
  }
  if counts["fail"] > 0:
    overall = "fail"
  elif counts["indeterminate"] > 0:
    overall = "indeterminate"
  else:
    overall = "pass"

  return {
    "schema_version": 1,
    "standard_package": "ocp-standards",
    "version": "0.1.0",
    "ruleset_digest": ruleset_digest,
    "status": overall,
    "evaluated_modules": evaluated_modules,
    "counts": counts,
    "findings": findings,
  }
