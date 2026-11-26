"""Self-tests for the ocp-standards capability package."""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest


@pytest.fixture(scope="module", autouse=True)
def _isolate_ambient_domain_modules():
  before = set(sys.modules)
  yield
  for name in list(sys.modules):
    if name not in before and name.startswith("texsys_"):
      sys.modules.pop(name, None)


def test_ocp_ruleset_has_all_4_domains_and_17_clauses():
  from texsys_ocp_standards import load_ruleset

  rules, digest = load_ruleset()
  assert digest.startswith("sha256:")
  assert len(rules) == 17
  assert {
    "OCP-ORV3-MECH-001",
    "OCP-ORV3-PWR-001",
    "OCP-LC-THM-001",
    "OCP-LC-HYD-002",
    "OCP-DCF-001",
    "OCP-DCF-003",
  } <= set(rules)


MANIFEST = (
  'schema_version = 1\n'
  '[project]\nname = "{name}"\n'
  '[layout]\nsource = "src"\nassets = "assets"\nbuild = "build"\n'
)


def test_missing_basis_returns_indeterminate(tmp_path: Path):
  from texsys_ocp_standards import evaluate_project_ocp_compliance

  (tmp_path / "texsys.toml").write_text(MANIFEST.format(name="empty"), encoding="utf-8")
  (tmp_path / "src").mkdir()
  report = evaluate_project_ocp_compliance(tmp_path)
  assert report["status"] == "indeterminate"
  assert report["counts"]["indeterminate"] >= 1


def test_valid_ocp_basis_passes_and_bad_temp_fails(tmp_path: Path):
  from texsys_ocp_standards import evaluate_project_ocp_compliance

  (tmp_path / "texsys.toml").write_text(MANIFEST.format(name="ocp-demo"), encoding="utf-8")
  src = tmp_path / "src"
  src.mkdir()
  basis = {
    "schema_version": 1,
    "project_name": "ocp-demo",
    "liquid_rack_count": 16,
    "rack_power_kw": 100.0,
    "liquid_cooling_fraction": 0.9,
    "rack": {"width_m": 0.6, "depth_m": 1.2, "mass_kg": 1500.0},
    "site": {"max_floor_load_kpa": 18.0},
    "limits": {"max_pue": 1.2, "max_tcs_dp_kpa": 180.0, "max_busway_vdrop_pct": 2.0},
    "thermal": {"tcs_supply_setpoint_c": 35.0, "max_tcs_supply_c": 45.0, "cdu_rated_kw": 1000.0},
  }
  (src / "ocp-basis.json").write_text(json.dumps(basis), encoding="utf-8")
  ok_report = evaluate_project_ocp_compliance(tmp_path)
  assert ok_report["status"] == "pass", ok_report

  basis["thermal"]["max_tcs_supply_c"] = 50.0
  (src / "ocp-basis.json").write_text(json.dumps(basis), encoding="utf-8")
  bad_report = evaluate_project_ocp_compliance(tmp_path)
  assert bad_report["status"] == "fail"
  assert any(f["rule_id"] == "OCP-LC-THM-001" and f["status"] == "fail" for f in bad_report["findings"])
