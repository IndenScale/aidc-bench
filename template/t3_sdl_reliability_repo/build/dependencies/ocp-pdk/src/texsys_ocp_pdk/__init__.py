"""OCP (Open Compute Project) multi-view PDK standard cell catalog and port compatibility helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from texsys.pdk import PdkModule, load_pdk_module

PACKAGE_ROOT = Path(__file__).resolve().parents[2]
MODULES_ROOT = PACKAGE_ROOT / "src" / "library" / "modules"

OCP_PORT_KINDS: dict[str, str] = {
  "ac-power": "三相或单相交流供电接口（OCP 设施母线/机柜 PDU/UPS 端口）",
  "dc-48v-busbar": "OCP ORv3 48V/50V 直流盲插母排汇流接口",
  "tcs": "OCP ACS 技术冷却水（TCS）一次/机柜级供回液接口",
  "tcs-bmqc": "OCP ACS UQD/BMQC 盲插快接支路液冷接口",
  "fws": "OCP DCF 设施冷却水（FWS）供回水接口",
  "room-air": "机房冷热通道残余风冷换气接口",
  "rack-mount-ou": "OCP ORv3 21英寸（538 mm）/ 48 mm OU 导轨装配接口",
  "ethernet-400g-plane": "AI 算力东西向高速互联平面端口",
  "ethernet-800g-spine": "上行 Spine 交换网络端口",
  "ethernet-100g-oob": "带外管理上行接口",
  "signal": "电源框/BBU 管理与告警遥测信号接口",
  "control-signal": "CDU/歧管/托盘压差闭环与安全联锁控制信号接口",
}

OCP_SPEC_CATALOG: dict[str, dict[str, str]] = {
  "orv3-frame-48ou": {
    "spec": "OCP Open Rack v3 Base Specification",
    "revision": "Rev 1.0",
    "category": "Rack & Power / Mechanical Frame",
  },
  "orv3-hpr-frame-48ou": {
    "spec": "OCP Open Rack v3 High Power Rack (HPR) Specification",
    "revision": "Rev 1.0",
    "category": "Rack & Power / High-Density Mechanical Frame",
  },
  "orv3-busbar-48v-hpr": {
    "spec": "OCP ORv3 HPR 48V/50V Busbar Specification",
    "revision": "Rev 1.0",
    "category": "Rack & Power / DC Distribution",
  },
  "orv3-power-shelf-33kw": {
    "spec": "OCP ORv3 48V Power Shelf Specification (33 kW HPR)",
    "revision": "Rev 1.0",
    "category": "Rack & Power / AC-DC Rectifier",
  },
  "orv3-bbu-shelf-15kw": {
    "spec": "OCP ORv3 Battery Backup Unit (BBU) Specification",
    "revision": "Rev 1.0",
    "category": "Rack & Power / Rack-Level Ride-Through",
  },
  "orv3-rack-manifold-bmqc": {
    "spec": "OCP ACS Cold Plate Rack Manifold & Blind-Mate Interface Specification",
    "revision": "Rev 1.1",
    "category": "Cooling Environments / ACS Cold Plate",
  },
  "ocp-uqd-bmqc-coupler": {
    "spec": "OCP Universal Quick Disconnect (UQD / BMQC) Specification",
    "revision": "Rev 2.0",
    "category": "Cooling Environments / Fluid Coupler",
  },
  "ocp-compute-tray-1ou-lc": {
    "spec": "OCP ORv3 21-inch 1OU Liquid-Cooled Compute Tray Reference",
    "revision": "Rev 1.0",
    "category": "Server & ACS / Compute Tray",
  },
  "ocp-orv3-liquid-rack-assembly": {
    "spec": "OCP ORv3 HPR + ACS Direct-to-Chip Liquid-Cooled Rack Assembly",
    "revision": "Rev 1.0",
    "category": "Rack & Power + ACS / Composite Rack",
  },
  "ocp-cdu-inrow-1mw": {
    "spec": "OCP ACS Liquid-to-Liquid CDU Requirements Specification (1 MW Class)",
    "revision": "Rev 1.0",
    "category": "Cooling Environments / Coolant Distribution Unit",
  },
  "ocp-busway-tap-ac": {
    "spec": "OCP Data Center Facility (DCF) Overhead Busway Distribution Reference",
    "revision": "Rev 1.0",
    "category": "Data Center Facility / Power Distribution",
  },
  "ocp-dcf-modular-it-pod": {
    "spec": "OCP Data Center Facility (DCF) Liquid-Cooled Modular IT Pod Reference",
    "revision": "Rev 1.0",
    "category": "Data Center Facility / Composite Pod",
  },
}


def list_ocp_modules() -> tuple[str, ...]:
  """Return sorted OCP PDK module slugs available in this package."""
  if not MODULES_ROOT.is_dir():
    return ()
  return tuple(
    sorted(
      entry.name
      for entry in MODULES_ROOT.iterdir()
      if entry.is_dir() and (entry / "module.toml").is_file()
    )
  )


def ocp_module_dir(slug: str) -> Path:
  """Return the absolute path to an OCP PDK module directory by slug."""
  candidate = (MODULES_ROOT / slug).resolve()
  if not candidate.is_dir() or not (candidate / "module.toml").is_file():
    available = ", ".join(list_ocp_modules())
    raise FileNotFoundError(f"Unknown OCP PDK module {slug!r}. Available: {available}")
  return candidate


def load_ocp_module(slug: str) -> PdkModule:
  """Load and validate a multi-view OCP PDK module from this package."""
  return load_pdk_module(ocp_module_dir(slug))


def _load_root_ports(module_dir: Path) -> dict[str, dict[str, Any]]:
  sdl_files = sorted(module_dir.glob("*.sdl.json"))
  if not sdl_files:
    raise FileNotFoundError(f"No .sdl.json found in {module_dir}")
  doc = json.loads(sdl_files[0].read_text(encoding="utf-8"))
  root_name = doc["root"]
  return dict(doc["components"][root_name].get("ports", {}))


def check_port_compatibility(
  ocp_slug: str,
  target_module_dir: Path,
  *,
  required_ports: tuple[str, ...] | None = None,
  port_map: dict[str, str] | None = None,
) -> dict[str, Any]:
  """Verify a derived/vendor module exposes compatible ports against an OCP base cell."""
  base_ports = _load_root_ports(ocp_module_dir(ocp_slug))
  target_ports = _load_root_ports(Path(target_module_dir).resolve())
  if port_map is not None:
    effective_map = dict(port_map)
  elif required_ports is not None:
    effective_map = {p: p for p in required_ports}
  else:
    effective_map = {p: p for p in sorted(base_ports)}

  missing: list[str] = []
  mismatched: list[dict[str, Any]] = []
  for base_port, target_port in effective_map.items():
    if base_port not in base_ports:
      missing.append(f"unknown-base:{base_port}")
      continue
    if target_port not in target_ports:
      missing.append(f"{base_port}->{target_port}")
      continue
    expected = base_ports[base_port]
    actual = target_ports[target_port]
    if expected.get("kind") != actual.get("kind") or expected.get("direction") != actual.get("direction"):
      mismatched.append({
        "port": f"{base_port}->{target_port}",
        "expected": {"kind": expected.get("kind"), "direction": expected.get("direction")},
        "actual": {"kind": actual.get("kind"), "direction": actual.get("direction")},
      })

  return {
    "compatible": not missing and not mismatched,
    "ocp_base": ocp_slug,
    "target": Path(target_module_dir).name,
    "checked_ports": list(effective_map.keys()),
    "port_map": effective_map,
    "missing_ports": missing,
    "mismatched_ports": mismatched,
  }


__all__ = [
  "MODULES_ROOT",
  "OCP_PORT_KINDS",
  "OCP_SPEC_CATALOG",
  "PACKAGE_ROOT",
  "check_port_compatibility",
  "list_ocp_modules",
  "load_ocp_module",
  "ocp_module_dir",
]
