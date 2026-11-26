"""Deterministic generator for the 12 multi-view OCP PDK cells in packages/ocp-pdk."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pxr import Gf, Sdf, Usd, UsdGeom

ROOT = Path(__file__).resolve().parents[1] / "src" / "library" / "modules"


def _port(direction: str, kind: str, maximum: int = 1) -> dict[str, Any]:
  return {"direction": direction, "kind": kind, "max_connections": maximum}


def _param(value: float, unit: str, source: str, state: str = "known") -> dict[str, Any]:
  return {"value": value, "unit": unit, "state": state, "source": source}


def _iface(pos: list[float], normal: list[int], spec: str) -> dict[str, Any]:
  return {"position_m": pos, "normal": normal, "spec": spec}


def _conn(idx: int, src: str, dst: str) -> dict[str, str]:
  return {"id": f"link-{idx:03d}", "from": src, "to": dst}


def _render_usda(spec: dict[str, Any]) -> str:
  stage = Usd.Stage.CreateInMemory()
  UsdGeom.SetStageMetersPerUnit(stage, 1)
  UsdGeom.SetStageUpAxis(stage, "Z")
  root = UsdGeom.Xform.Define(stage, "/Module")
  stage.SetDefaultPrim(root.GetPrim())
  UsdGeom.Scope.Define(stage, "/Module/Geometry")
  UsdGeom.Scope.Define(stage, "/Module/Ports")

  envelope = spec["envelope_m"]
  parts = spec["properties"].get("geometry_parts") or {
    "Enclosure": {
      "origin_m": [0.0, 0.0, 0.0],
      "size_m": list(envelope),
      "color": [0.18, 0.24, 0.31],
    }
  }
  for part_name, part in parts.items():
    origin = part["origin_m"]
    size = part["size_m"]
    cube = UsdGeom.Cube.Define(stage, f"/Module/Geometry/{part_name}")
    cube.CreateSizeAttr(1)
    cube.AddTranslateOp().Set(
      Gf.Vec3d(*(o + s / 2.0 for o, s in zip(origin, size, strict=True)))
    )
    cube.AddScaleOp(UsdGeom.XformOp.PrecisionDouble).Set(Gf.Vec3d(*size))
    cube.CreateDisplayColorAttr([Gf.Vec3f(*part["color"])])

  for port_name, iface in spec["interfaces"].items():
    xform = UsdGeom.Xform.Define(stage, f"/Module/Ports/{port_name}")
    xform.AddTranslateOp().Set(Gf.Vec3d(*iface["position_m"]))
    xform.GetPrim().CreateAttribute("texsys:normal", Sdf.ValueTypeNames.Double3).Set(
      Gf.Vec3d(*iface["normal"])
    )

  return stage.GetRootLayer().ExportToString()


def _render_symbol_svg(slug: str, title: str, subtitle: str, ports: dict[str, dict[str, Any]]) -> str:
  width = max(180, 40 + 28 * max(4, (len(ports) + 1) // 2))
  height = 120
  lines = [
    f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}">',
    f'  <rect x="24" y="22" width="{width - 48}" height="76" rx="5" fill="#0f172a" stroke="#38bdf8" stroke-width="1.5" />',
    f'  <text x="{width / 2:.1f}" y="46" text-anchor="middle" fill="#e0f2fe" font-size="8.5" font-weight="bold">{title}</text>',
    f'  <text x="{width / 2:.1f}" y="62" text-anchor="middle" fill="#7dd3fc" font-size="7">{subtitle}</text>',
    f'  <text x="{width / 2:.1f}" y="77" text-anchor="middle" fill="#94a3b8" font-size="6">{slug}</text>',
  ]
  in_ports = [p for p, meta in ports.items() if meta["direction"] == "in"]
  other_ports = [p for p, meta in ports.items() if meta["direction"] != "in"]
  for idx, port_name in enumerate(in_ports):
    x = 34 + (width - 68) * (idx + 0.5) / max(1, len(in_ports))
    lines.append(
      f'  <circle id="port-{port_name}" data-port="{port_name}" cx="{x:.1f}" cy="22" r="3.2" fill="#38bdf8" />'
    )
  for idx, port_name in enumerate(other_ports):
    x = 34 + (width - 68) * (idx + 0.5) / max(1, len(other_ports))
    fill = "#f59e0b" if ports[port_name]["direction"] == "inout" else "#34d399"
    lines.append(
      f'  <circle id="port-{port_name}" data-port="{port_name}" cx="{x:.1f}" cy="98" r="3.2" fill="{fill}" />'
    )
  lines.append("</svg>")
  return "\n".join(lines) + "\n"


def _render_module_toml(cell: dict[str, Any]) -> str:
  slug = cell["slug"]
  lines = [
    "schema_version = 1",
    f'name = {json.dumps(cell["title"], ensure_ascii=False)}',
    'version = "0.1.0"',
    f'entry = "{slug}.sdl.json"',
    "",
  ]
  src = cell["source"]
  for kind, path, fidelity in (
    ("geometry", "assets/geometry.usda", cell["fidelity"]["geometry"]),
    ("symbol", "assets/symbol.svg", cell["fidelity"]["symbol"]),
    ("specification", "assets/specification.json", cell["fidelity"]["specification"]),
    ("behavior", "assets/behavior.json", cell["fidelity"]["behavior"]),
    ("liberty", "assets/liberty.json", cell["fidelity"]["liberty"]),
  ):
    lines += [
      f"[assets.{kind}]",
      f'kind = "{kind}"',
      f'path = "{path}"',
      f'source = "{src}"',
      f'fidelity = "{fidelity}"',
      "",
    ]
  for port_name in cell["ports"]:
    lines += [
      f"[port_bindings.{port_name}]",
      f'geometry = "/Module/Ports/{port_name}"',
      f'symbol = "port-{port_name}"',
      "",
    ]
  return "\n".join(lines)


def _cells() -> list[dict[str, Any]]:
  cells: list[dict[str, Any]] = []

  # 1. orv3-frame-48ou
  cells.append({
    "slug": "orv3-frame-48ou",
    "root": "OcpOrv3Frame48Ou",
    "title": "OCP ORv3 标准机柜框架 (21\" / 48OU)",
    "subtitle": "600x1068x2278 mm | 1600 kg | 48 mm OU",
    "source": "OCP Open Rack v3 Base Specification Rev 1.0",
    "ocp_spec": "OCP Open Rack v3 Base Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.6, 1.068, 2.278],
    "mass_kg": 1600.0,
    "empty_mass_kg": 148.0,
    "clearances_m": {"front_service_m": 1.2, "rear_manifold_and_busbar_m": 1.2, "top_cable_and_busway_m": 0.6},
    "ports": {
      "rails_ou": _port("inout", "rack-mount-ou", 48),
      "busbar_slot": _port("inout", "dc-48v-busbar", 2),
      "manifold_slot": _port("inout", "tcs-bmqc", 2),
      "air_in": _port("in", "room-air", 1),
      "air_out": _port("out", "room-air", 1),
    },
    "interfaces": {
      "rails_ou": _iface([0.3, 0.0, 1.14], [0, -1, 0], "21-inch (538 mm) EIA/ORv3 48OU rails, 48 mm pitch"),
      "busbar_slot": _iface([0.3, 1.068, 1.14], [0, 1, 0], "Rear central 48V/50V blind-mate busbar bay"),
      "manifold_slot": _iface([0.52, 1.068, 1.14], [0, 1, 0], "Rear right vertical BMQC rack manifold bay"),
      "air_in": _iface([0.3, 0.0, 1.0], [0, -1, 0], "Front cold-aisle open perforated intake"),
      "air_out": _iface([0.3, 1.068, 1.0], [0, 1, 0], "Rear hot-aisle exhaust"),
    },
    "properties": {
      "form_factor": "OCP ORv3 21-inch",
      "mounting_width_in": 21,
      "mounting_width_mm": 538.0,
      "total_ou": 48,
      "unit_pitch_m": 0.048,
      "max_static_load_kg": 1600.0,
      "geometry_parts": {
        "Frame": {"origin_m": [0.0, 0.0, 0.0], "size_m": [0.6, 1.068, 2.278], "color": [0.16, 0.21, 0.27]},
        "FrontBezel": {"origin_m": [0.03, 0.0, 0.04], "size_m": [0.54, 0.025, 2.18], "color": [0.10, 0.14, 0.19]},
      },
    },
    "parameters": {
      "max_static_load_kg": (1600.0, "kg"),
      "unit_pitch_m": (0.048, "m"),
      "total_ou": (48.0, "OU"),
    },
    "behavior_model": "ocp-orv3-mechanical-frame",
    "behavior_method": "定义 ORv3 48OU 机械包络、21 英寸导轨间距、静态承载上限与前后检修净距。",
    "limitations": "依据 OCP ORv3 Base Rev 1.0 包络标定；抗震斜撑与地脚锚固按项目结构验算。",
    "liberty": {
      "model": "ocp-orv3-frame-48ou-envelope",
      "axes": [{"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]}],
      "outputs": {
        "static_load_kg": {"unit": "kg", "min_bound": 148.0, "values": [511.0, 874.0, 1237.0, 1600.0]},
        "floor_pressure_kpa": {"unit": "kPa", "min_bound": 0.0, "values": [7.82, 13.38, 18.93, 24.49]},
      },
    },
    "fidelity": {
      "geometry": "600x1068x2278 mm ORv3 框架外形与后部母排/歧管槽位",
      "symbol": "ORv3 标准 48OU 框架符号与端口锚点",
      "specification": "21 英寸导轨模数、48 mm OU 间距、承重及净距约束",
      "behavior": "结构承载与风道压降参考包络",
      "liberty": "载荷比-静载/楼板等效压强包络表",
    },
  })

  # 2. orv3-hpr-frame-48ou
  cells.append({
    "slug": "orv3-hpr-frame-48ou",
    "root": "OcpOrv3HprFrame48Ou",
    "title": "OCP ORv3 HPR 高密液冷机柜框架 (48OU)",
    "subtitle": "600x1200x2495 mm | 1800 kg | Dual Busbar/BMQC",
    "source": "OCP Open Rack v3 High Power Rack (HPR) Specification Rev 1.0",
    "ocp_spec": "OCP Open Rack v3 HPR Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.6, 1.2, 2.495],
    "mass_kg": 1800.0,
    "empty_mass_kg": 175.0,
    "clearances_m": {"front_service_m": 1.2, "rear_manifold_and_busbar_m": 1.2, "top_cable_and_busway_m": 0.6},
    "ports": {
      "rails_ou": _port("inout", "rack-mount-ou", 48),
      "busbar_slot": _port("inout", "dc-48v-busbar", 2),
      "manifold_slot": _port("inout", "tcs-bmqc", 2),
      "tcs_header_top": _port("inout", "tcs", 2),
      "air_in": _port("in", "room-air", 1),
      "air_out": _port("out", "room-air", 1),
    },
    "interfaces": {
      "rails_ou": _iface([0.3, 0.0, 1.24], [0, -1, 0], "21-inch (538 mm) HPR reinforced 48OU rails"),
      "busbar_slot": _iface([0.3, 1.2, 1.24], [0, 1, 0], "Rear HPR 48V/50V blind-mate busbar bay"),
      "manifold_slot": _iface([0.52, 1.2, 1.24], [0, 1, 0], "Rear dual-manifold liquid cooling bay"),
      "tcs_header_top": _iface([0.48, 1.0, 2.495], [0, 0, 1], "Top overhead TCS blind-mate header entry"),
      "air_in": _iface([0.3, 0.0, 1.1], [0, -1, 0], "Front cold-aisle intake"),
      "air_out": _iface([0.3, 1.2, 1.1], [0, 1, 0], "Rear hot-aisle exhaust"),
    },
    "properties": {
      "form_factor": "OCP ORv3 HPR 21-inch",
      "mounting_width_in": 21,
      "mounting_width_mm": 538.0,
      "total_ou": 48,
      "unit_pitch_m": 0.048,
      "max_static_load_kg": 1800.0,
      "geometry_parts": {
        "Frame": {"origin_m": [0.0, 0.0, 0.0], "size_m": [0.6, 1.2, 2.495], "color": [0.14, 0.19, 0.25]},
        "TopPlenum": {"origin_m": [0.02, 0.1, 2.35], "size_m": [0.56, 1.0, 0.145], "color": [0.19, 0.45, 0.62]},
      },
    },
    "parameters": {
      "max_static_load_kg": (1800.0, "kg"),
      "unit_pitch_m": (0.048, "m"),
      "total_ou": (48.0, "OU"),
    },
    "behavior_model": "ocp-orv3-hpr-mechanical-frame",
    "behavior_method": "定义 ORv3 HPR 强化框架（1800 kg 静态承重）及顶部/后部液冷歧管与大电流直流母排安装边界。",
    "limitations": "依据 OCP ORv3 HPR Rev 1.0 标定；不同液冷超节点 OEM 对总高 2278–2495 mm 的微调须在施工图核对。",
    "liberty": {
      "model": "ocp-orv3-hpr-frame-48ou-envelope",
      "axes": [{"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]}],
      "outputs": {
        "static_load_kg": {"unit": "kg", "min_bound": 175.0, "values": [581.25, 987.5, 1393.75, 1800.0]},
        "floor_pressure_kpa": {"unit": "kPa", "min_bound": 0.0, "values": [7.92, 13.45, 18.99, 24.52]},
      },
    },
    "fidelity": {
      "geometry": "600x1200x2495 mm ORv3 HPR 加深加高重型液冷机框",
      "symbol": "ORv3 HPR 机框符号与顶部液冷接入锚点",
      "specification": "1800 kg 承重、双歧管与 HPR 母排槽位参数",
      "behavior": "重型超节点静态载荷与界面净距模型",
      "liberty": "载荷比-静载/楼板压强包络表",
    },
  })

  # 3. orv3-busbar-48v-hpr
  cells.append({
    "slug": "orv3-busbar-48v-hpr",
    "root": "OcpOrv3Busbar48vHpr",
    "title": "OCP ORv3 HPR 48V/50V 盲插直流母排 (3000A)",
    "subtitle": "50V DC | 3000 A / 144 kW | Blind-Mate",
    "source": "OCP ORv3 HPR 48V/50V Busbar Specification Rev 1.0",
    "ocp_spec": "OCP ORv3 HPR Busbar Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.12, 0.08, 2.2],
    "mass_kg": 42.0,
    "clearances_m": {"rear_busbar_access_m": 0.4},
    "ports": {
      "power_shelf_in": _port("in", "dc-48v-busbar", 8),
      "bbu_in": _port("inout", "dc-48v-busbar", 4),
      "tray_tap": _port("out", "dc-48v-busbar", 48),
    },
    "interfaces": {
      "power_shelf_in": _iface([0.06, 0.0, 0.4], [0, -1, 0], "Power shelf blind-mate clip zone (up to 8 shelves)"),
      "bbu_in": _iface([0.06, 0.0, 0.85], [0, -1, 0], "BBU shelf bidirectional 48V-50V blind-mate zone"),
      "tray_tap": _iface([0.06, 0.0, 1.5], [0, -1, 0], "48OU IT compute tray blind-mate busbar taps"),
    },
    "properties": {
      "nominal_voltage_v": 50.0,
      "voltage_window_v": [48.0, 51.0],
      "rated_current_a": 3000.0,
      "rated_power_kw": 144.0,
      "conductor": "Silver-plated copper",
    },
    "parameters": {
      "nominal_voltage_v": (50.0, "V"),
      "rated_current_a": (3000.0, "A"),
      "rated_power_kw": (144.0, "kW"),
    },
    "behavior_model": "ocp-orv3-hpr-dc-busbar",
    "behavior_method": "依据欧姆定律与焦耳热计算 48V/50V 铜母排在不同电流与环境温度下的压降、焦耳损耗与温升。",
    "limitations": "稳态 DC 汇流模型，未包含毫秒级 GPU EDPp 脉冲下的寄生电感暂态压降。",
    "liberty": {
      "model": "ocp-orv3-busbar-48v-hpr-3000a",
      "axes": [
        {"name": "current_a", "unit": "A", "values": [750.0, 1500.0, 2250.0, 3000.0]},
        {"name": "ambient_c", "unit": "degC", "values": [25.0, 35.0, 45.0]},
      ],
      "outputs": {
        "voltage_drop_v": {
          "unit": "V",
          "min_bound": 0.0,
          "values": [
            [0.045, 0.047, 0.049],
            [0.09, 0.094, 0.098],
            [0.135, 0.141, 0.147],
            [0.18, 0.188, 0.196],
          ],
        },
        "joule_loss_w": {
          "unit": "W",
          "min_bound": 0.0,
          "values": [
            [33.75, 35.25, 36.75],
            [135.0, 141.0, 147.0],
            [303.75, 317.25, 330.75],
            [540.0, 564.0, 588.0],
          ],
        },
        "busbar_temp_rise_k": {
          "unit": "K",
          "min_bound": 0.0,
          "values": [
            [3.2, 3.4, 3.6],
            [11.5, 12.1, 12.7],
            [23.8, 25.0, 26.2],
            [38.5, 40.2, 42.0],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "机柜后部垂直 48V/50V 盲插母排包络",
      "symbol": "直流母排汇流符号与电源/BBU/托盘端口",
      "specification": "50V 标称电压、3000A 额定电流与盲插分区坐标",
      "behavior": "焦耳损耗与直流压降模型",
      "liberty": "(电流, 环境温度) 二维压降与温升查找表",
    },
  })

  # 4. orv3-power-shelf-33kw
  cells.append({
    "slug": "orv3-power-shelf-33kw",
    "root": "OcpOrv3PowerShelf33Kw",
    "title": "OCP ORv3 33 kW 电源框 (6x5.5 kW PSU)",
    "subtitle": "400/480V AC -> 50V DC | 33 kW | 97.5% Peak",
    "source": "OCP ORv3 48V Power Shelf Specification (33 kW HPR) Rev 1.0",
    "ocp_spec": "OCP ORv3 Power Shelf Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.538, 0.75, 0.088],
    "mass_kg": 26.5,
    "clearances_m": {"front_hot_swap_m": 0.9},
    "ports": {
      "ac_in_a": _port("in", "ac-power", 1),
      "ac_in_b": _port("in", "ac-power", 1),
      "dc_out": _port("out", "dc-48v-busbar", 1),
      "mgmt": _port("inout", "signal", 1),
    },
    "interfaces": {
      "ac_in_a": _iface([0.14, 0.75, 0.044], [0, 1, 0], "Rear 3-phase AC feed A whip"),
      "ac_in_b": _iface([0.40, 0.75, 0.044], [0, 1, 0], "Rear 3-phase AC feed B whip (N+N/5+1)"),
      "dc_out": _iface([0.269, 0.75, 0.044], [0, 1, 0], "Rear blind-mate 50V DC busbar clip"),
      "mgmt": _iface([0.08, 0.0, 0.044], [0, -1, 0], "Front PMC / Redfish Modbus telemetry port"),
    },
    "properties": {
      "form_factor": "OCP ORv3 2OU / 21-inch",
      "psu_count": 6,
      "psu_rated_kw": 5.5,
      "rated_dc_kw": 33.0,
      "output_voltage_v": 50.0,
    },
    "parameters": {
      "rated_dc_kw": (33.0, "kW"),
      "output_voltage_v": (50.0, "V"),
      "psu_count": (6.0, "count"),
    },
    "behavior_model": "ocp-orv3-power-shelf-rectifier",
    "behavior_method": "三相交流整流至 50V DC 直流输出，随负载率与输入线电压查算转换效率与散热量。",
    "limitations": "不含单 PSU 热插拔毫秒瞬态谐波；单柜需按 N+1 或 N+N 配置冗余框。",
    "liberty": {
      "model": "ocp-orv3-power-shelf-33kw-efficiency",
      "axes": [
        {"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]},
        {"name": "input_voltage_v", "unit": "V", "values": [400.0, 480.0]},
      ],
      "outputs": {
        "efficiency": {
          "unit": "1",
          "min_bound": 0.9,
          "max_bound": 0.99,
          "values": [[0.962, 0.966], [0.974, 0.977], [0.972, 0.975], [0.965, 0.969]],
        },
        "dc_output_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [[8.25, 8.25], [16.5, 16.5], [24.75, 24.75], [33.0, 33.0]],
        },
        "heat_loss_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [[0.326, 0.29], [0.44, 0.388], [0.713, 0.635], [1.197, 1.056]],
        },
      },
    },
    "fidelity": {
      "geometry": "21英寸 2OU 33 kW 电源框包络",
      "symbol": "AC-DC 电源框符号与双路进线/母排盲插端口",
      "specification": "6x5.5 kW PSU 配置与 50V DC 输出界限",
      "behavior": "AC-DC 整流效率与热耗模型",
      "liberty": "(负载率, 输入线电压) 二维效率与损耗曲线",
    },
  })

  # 5. orv3-bbu-shelf-15kw
  cells.append({
    "slug": "orv3-bbu-shelf-15kw",
    "root": "OcpOrv3BbuShelf15Kw",
    "title": "OCP ORv3 机柜级 BBU 备电框 (15 kW)",
    "subtitle": "50V DC | 15 kW / 240 s | In-Rack Ride-Through",
    "source": "OCP ORv3 Battery Backup Unit (BBU) Specification Rev 1.0",
    "ocp_spec": "OCP ORv3 BBU Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.538, 0.75, 0.096],
    "mass_kg": 48.0,
    "clearances_m": {"front_hot_swap_m": 0.9},
    "ports": {
      "dc_bus": _port("inout", "dc-48v-busbar", 1),
      "mgmt": _port("inout", "signal", 1),
    },
    "interfaces": {
      "dc_bus": _iface([0.269, 0.75, 0.048], [0, 1, 0], "Rear 48V-50V DC blind-mate busbar clip"),
      "mgmt": _iface([0.08, 0.0, 0.048], [0, -1, 0], "Front BMS state-of-health telemetry port"),
    },
    "properties": {
      "form_factor": "OCP ORv3 2OU / 21-inch",
      "rated_discharge_kw": 15.0,
      "nominal_energy_kwh": 1.1,
      "nominal_autonomy_s": 240.0,
    },
    "parameters": {
      "rated_discharge_kw": (15.0, "kW"),
      "nominal_autonomy_s": (240.0, "s"),
    },
    "behavior_model": "ocp-orv3-bbu-discharge",
    "behavior_method": "基于放电功率与荷电状态查算机柜级后备支撑时间与放电发热。",
    "limitations": "未包含电芯长期老化容量衰减与热失控泄压风道设计。",
    "liberty": {
      "model": "ocp-orv3-bbu-shelf-15kw-discharge",
      "axes": [
        {"name": "discharge_power_kw", "unit": "kW", "values": [5.0, 10.0, 15.0]},
        {"name": "soc_fraction", "unit": "1", "values": [0.5, 0.8, 1.0]},
      ],
      "outputs": {
        "autonomy_s": {
          "unit": "s",
          "min_bound": 0.0,
          "values": [[360.0, 576.0, 720.0], [180.0, 288.0, 360.0], [120.0, 192.0, 240.0]],
        },
        "efficiency": {
          "unit": "1",
          "min_bound": 0.9,
          "max_bound": 0.99,
          "values": [[0.975, 0.978, 0.98], [0.968, 0.971, 0.974], [0.958, 0.962, 0.965]],
        },
        "heat_loss_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [[0.128, 0.112, 0.102], [0.331, 0.299, 0.267], [0.658, 0.593, 0.544]],
        },
      },
    },
    "fidelity": {
      "geometry": "21英寸 2OU 机柜级 BBU 备电模块包络",
      "symbol": "机柜级直流备电 BBU 符号与端口",
      "specification": "15 kW / 240 s 放电能力与质量参数",
      "behavior": "市电切换穿越期内机柜级直流备电模型",
      "liberty": "(放电功率, SOC) 二维续航时长与热耗曲线",
    },
  })

  # 6. orv3-rack-manifold-bmqc
  cells.append({
    "slug": "orv3-rack-manifold-bmqc",
    "root": "OcpOrv3RackManifoldBmqc",
    "title": "OCP ACS 机柜液冷盲插歧管 (DN32 / BMQC)",
    "subtitle": "316L SS | 24x BMQC | 2200 mm Vertical",
    "source": "OCP ACS Cold Plate Rack Manifold & Blind-Mate Interface Specification Rev 1.1",
    "ocp_spec": "OCP ACS Cold Plate Rack Manifold Specification",
    "ocp_revision": "Rev 1.1",
    "envelope_m": [0.09, 0.12, 2.2],
    "mass_kg": 28.0,
    "clearances_m": {"rear_manifold_service_m": 0.9},
    "ports": {
      "supply_in": _port("in", "tcs", 1),
      "return_out": _port("out", "tcs", 1),
      "branch_supply": _port("out", "tcs-bmqc", 24),
      "branch_return": _port("in", "tcs-bmqc", 24),
      "pressure_sense": _port("out", "control-signal", 4),
    },
    "interfaces": {
      "supply_in": _iface([0.045, 0.06, 2.2], [0, 0, 1], "Top DN32 (1.25-inch) TCS supply tie-in"),
      "return_out": _iface([0.045, 0.06, 0.0], [0, 0, -1], "Bottom/top TCS return manifold outlet"),
      "branch_supply": _iface([0.045, 0.0, 1.1], [0, -1, 0], "24x BMQC blind-mate supply drops"),
      "branch_return": _iface([0.045, 0.12, 1.1], [0, 1, 0], "24x BMQC blind-mate return risers"),
      "pressure_sense": _iface([0.09, 0.06, 2.0], [1, 0, 0], "Differential pressure transmitter tap"),
    },
    "properties": {
      "material": "316L Stainless Steel",
      "inner_diameter_mm": 34.8,
      "branch_coupler_type": "BMQC / UQD04",
      "branch_count": 24,
      "max_working_pressure_kpa_g": 450.0,
    },
    "parameters": {
      "inner_diameter_mm": (34.8, "mm"),
      "length_m": (2.2, "m"),
      "rated_flow_lpm": (140.0, "L/min"),
    },
    "behavior_model": "ocp-acs-rack-manifold-hydraulics",
    "behavior_method": "计算 DN32 不锈钢立管歧管在 PG25 液冷工质下的沿程阻力与管内流速。",
    "limitations": "单相 PG25-water 稳态流动；高瞬态水锤需配合特征线法（MOC）模型复核。",
    "liberty": {
      "model": "ocp-orv3-rack-manifold-dn32-pg25",
      "axes": [
        {"name": "flow_lpm", "unit": "L/min", "values": [40.0, 80.0, 120.0, 180.0]},
        {"name": "coolant_temp_c", "unit": "degC", "values": [25.0, 35.0, 45.0]},
      ],
      "outputs": {
        "manifold_dp_kpa": {
          "unit": "kPa",
          "min_bound": 0.1,
          "values": [
            [0.9, 0.84, 0.79],
            [3.5, 3.25, 3.05],
            [7.8, 7.25, 6.8],
            [17.4, 16.2, 15.2],
          ],
        },
        "velocity_m_s": {
          "unit": "m/s",
          "min_bound": 0.0,
          "values": [
            [0.70, 0.70, 0.70],
            [1.40, 1.40, 1.40],
            [2.10, 2.10, 2.10],
            [3.15, 3.15, 3.15],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "DN32 垂直液冷歧管三维外形与盲插接口位姿",
      "symbol": "机柜液冷供回歧管符号与压差测点",
      "specification": "316L 不锈钢内径、24 路 BMQC 接口与耐压上限",
      "behavior": "立管水力压降与流速约束模型",
      "liberty": "(总流量, 供液温度) 二维歧管压降与流速曲线",
    },
  })

  # 7. ocp-uqd-bmqc-coupler
  cells.append({
    "slug": "ocp-uqd-bmqc-coupler",
    "root": "OcpUqdBmqcCoupler",
    "title": "OCP UQD04 / BMQC 无滴漏盲插快接头对",
    "subtitle": "Cv=2.6 | 450 kPa(g) Max | Dry-Break",
    "source": "OCP Universal Quick Disconnect (UQD / BMQC) Specification Rev 2.0",
    "ocp_spec": "OCP UQD / BMQC Specification",
    "ocp_revision": "Rev 2.0",
    "envelope_m": [0.04, 0.08, 0.04],
    "mass_kg": 0.35,
    "clearances_m": {"blind_mate_float_mm": 2.0},
    "ports": {
      "inlet": _port("in", "tcs-bmqc", 1),
      "outlet": _port("out", "tcs-bmqc", 1),
    },
    "interfaces": {
      "inlet": _iface([0.02, 0.0, 0.02], [0, -1, 0], "Manifold-side BMQC socket"),
      "outlet": _iface([0.02, 0.08, 0.02], [0, 1, 0], "Tray-side BMQC plug"),
    },
    "properties": {
      "coupler_family": "UQD04 / BMQC",
      "nominal_cv": 2.6,
      "max_dynamic_pressure_kpa_g": 450.0,
      "spillage_ml_per_disconnect": 0.05,
    },
    "parameters": {
      "nominal_cv": (2.6, "1"),
      "max_dynamic_pressure_kpa_g": (450.0, "kPa"),
    },
    "behavior_model": "ocp-uqd-bmqc-hydraulic-valve",
    "behavior_method": "依据流通系数 Cv 计算单对供回盲插快接头在不同流量与 PG25 粘度下的局部压降。",
    "limitations": "仅覆盖完全锁紧导通态稳态流阻，热插拔瞬态阀芯闭合特征由动态子模型处理。",
    "liberty": {
      "model": "ocp-uqd04-bmqc-pair-dp",
      "axes": [
        {"name": "flow_lpm", "unit": "L/min", "values": [4.0, 8.0, 12.0, 16.0]},
        {"name": "coolant_temp_c", "unit": "degC", "values": [25.0, 35.0, 45.0]},
      ],
      "outputs": {
        "coupler_dp_kpa": {
          "unit": "kPa",
          "min_bound": 0.1,
          "values": [
            [1.65, 1.54, 1.45],
            [6.6, 6.16, 5.8],
            [14.85, 13.86, 13.05],
            [26.4, 24.64, 23.2],
          ],
        },
        "cv_effective": {
          "unit": "1",
          "min_bound": 1.0,
          "values": [
            [2.52, 2.6, 2.66],
            [2.52, 2.6, 2.66],
            [2.52, 2.6, 2.66],
            [2.52, 2.6, 2.66],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "UQD04/BMQC 快接头机械包络与插合方向",
      "symbol": "干断快接头工程符号与进出口锚点",
      "specification": "Cv 值、允许工作压力 450 kPa(g) 与微滴漏限值",
      "behavior": "局部阻力平方律模型",
      "liberty": "(单路流量, 流体温度) 二维快接压降表",
    },
  })

  # 8. ocp-compute-tray-1ou-lc
  cells.append({
    "slug": "ocp-compute-tray-1ou-lc",
    "root": "OcpComputeTray1OuLc",
    "title": "OCP ORv3 1OU 液冷算力托盘 (6.5 kW)",
    "subtitle": "538x900x48 mm | 90% LC / 10% Air | 48V DC",
    "source": "OCP ORv3 21-inch 1OU Liquid-Cooled Compute Tray Reference Rev 1.0",
    "ocp_spec": "OCP ORv3 1OU Liquid-Cooled Compute Tray",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.538, 0.9, 0.048],
    "mass_kg": 34.0,
    "clearances_m": {"front_extraction_m": 1.1},
    "ports": {
      "dc_in": _port("in", "dc-48v-busbar", 1),
      "bmqc_supply": _port("in", "tcs-bmqc", 1),
      "bmqc_return": _port("out", "tcs-bmqc", 1),
      "air_in": _port("in", "room-air", 1),
      "air_out": _port("out", "room-air", 1),
      "fabric_ew": _port("inout", "ethernet-400g-plane", 4),
      "bmc_interlock": _port("inout", "control-signal", 2),
    },
    "interfaces": {
      "dc_in": _iface([0.269, 0.9, 0.024], [0, 1, 0], "Rear 48V/50V DC blind-mate busbar clip"),
      "bmqc_supply": _iface([0.42, 0.9, 0.024], [0, 1, 0], "Rear BMQC cold-plate supply coupler"),
      "bmqc_return": _iface([0.48, 0.9, 0.024], [0, 1, 0], "Rear BMQC cold-plate return coupler"),
      "air_in": _iface([0.269, 0.0, 0.024], [0, -1, 0], "Front perforated intake (~10% residual air cooling)"),
      "air_out": _iface([0.269, 0.9, 0.024], [0, 1, 0], "Rear hot-aisle exhaust"),
      "fabric_ew": _iface([0.12, 0.0, 0.024], [0, -1, 0], "Front QSFP-DD/OSFP high-speed compute ports"),
      "bmc_interlock": _iface([0.05, 0.0, 0.024], [0, -1, 0], "DC-SCM / OpenBMC leak & thermal interlock"),
    },
    "properties": {
      "form_factor": "OCP ORv3 1OU / 21-inch",
      "rated_it_kw": 6.5,
      "liquid_cooling_fraction": 0.9,
      "nominal_flow_lpm": 8.5,
    },
    "parameters": {
      "rated_it_kw": (6.5, "kW"),
      "nominal_flow_lpm": (8.5, "L/min"),
      "liquid_cooling_fraction": (0.9, "1"),
    },
    "behavior_model": "ocp-1ou-direct-to-chip-compute-tray",
    "behavior_method": "90% 冷板直冷 + 10% 残余风冷热分配；按供液温度与负载率查算托盘流阻与需求流量。",
    "limitations": "冷板与 BMQC 快接按等效串联流阻建模，供液温度超 25–45 degC 返回 indeterminate。",
    "liberty": {
      "model": "ocp-compute-tray-1ou-6p5kw-lc",
      "axes": [
        {"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]},
        {"name": "tcs_supply_c", "unit": "degC", "values": [25.0, 30.0, 35.0, 40.0, 45.0]},
      ],
      "outputs": {
        "required_flow_lpm": {
          "unit": "L/min",
          "min_bound": 2.0,
          "values": [
            [2.4, 2.9, 3.6, 4.8, 7.0],
            [3.2, 3.9, 4.9, 6.5, 9.5],
            [4.5, 5.4, 6.8, 9.0, 13.0],
            [5.8, 7.0, 8.5, 11.4, 16.5],
          ],
        },
        "tray_dp_kpa": {
          "unit": "kPa",
          "min_bound": 1.0,
          "values": [
            [3.2, 4.6, 7.1, 12.6, 26.8],
            [5.6, 8.3, 13.1, 23.1, 49.3],
            [11.1, 16.0, 25.3, 44.3, 92.4],
            [18.4, 26.8, 39.5, 71.1, 149.0],
          ],
        },
        "liquid_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [1.46, 1.46, 1.46, 1.46, 1.46],
            [2.93, 2.93, 2.93, 2.93, 2.93],
            [4.39, 4.39, 4.39, 4.39, 4.39],
            [5.85, 5.85, 5.85, 5.85, 5.85],
          ],
        },
        "air_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [0.16, 0.16, 0.16, 0.16, 0.16],
            [0.32, 0.32, 0.32, 0.32, 0.32],
            [0.49, 0.49, 0.49, 0.49, 0.49],
            [0.65, 0.65, 0.65, 0.65, 0.65],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "21英寸 1OU 液冷托盘三维包络与后部盲插水电接口",
      "symbol": "液冷算力托盘工程符号与液/电/互连端口",
      "specification": "1OU 尺寸、90% 液冷热分配与额定 8.5 L/min 工况",
      "behavior": "直冷托盘热电水耦合契约",
      "liberty": "(负载率, 供液温度) 二维流量与托盘压降表",
    },
  })

  # 9. ocp-orv3-liquid-rack-assembly (Composite SDL v2)
  rack_imports = {
    "Frame": "library/modules/orv3-hpr-frame-48ou/orv3-hpr-frame-48ou.sdl.json",
    "Busbar": "library/modules/orv3-busbar-48v-hpr/orv3-busbar-48v-hpr.sdl.json",
    "PowerShelf": "library/modules/orv3-power-shelf-33kw/orv3-power-shelf-33kw.sdl.json",
    "BbuShelf": "library/modules/orv3-bbu-shelf-15kw/orv3-bbu-shelf-15kw.sdl.json",
    "Manifold": "library/modules/orv3-rack-manifold-bmqc/orv3-rack-manifold-bmqc.sdl.json",
    "ComputeTray": "library/modules/ocp-compute-tray-1ou-lc/ocp-compute-tray-1ou-lc.sdl.json",
  }
  rack_instances: dict[str, Any] = {
    "frame": {"component": "Frame"},
    "busbar": {"component": "Busbar"},
    "manifold": {"component": "Manifold"},
    "bbu_1": {"component": "BbuShelf"},
    "bbu_2": {"component": "BbuShelf"},
  }
  for idx in range(1, 5):
    rack_instances[f"ps_{idx}"] = {"component": "PowerShelf"}
  for idx in range(1, 17):
    rack_instances[f"tray_{idx:02d}"] = {"component": "ComputeTray"}

  rack_conns: list[dict[str, str]] = []
  dc_ids: list[str] = []
  tcs_ids: list[str] = []
  for idx in range(1, 5):
    c = _conn(len(rack_conns) + 1, f"ps_{idx}.dc_out", "busbar.power_shelf_in")
    rack_conns.append(c)
    dc_ids.append(c["id"])
  for idx in (1, 2):
    c = _conn(len(rack_conns) + 1, f"bbu_{idx}.dc_bus", "busbar.bbu_in")
    rack_conns.append(c)
    dc_ids.append(c["id"])
  for idx in range(1, 17):
    t = f"tray_{idx:02d}"
    c1 = _conn(len(rack_conns) + 1, "busbar.tray_tap", f"{t}.dc_in")
    rack_conns.append(c1)
    c2 = _conn(len(rack_conns) + 1, "manifold.branch_supply", f"{t}.bmqc_supply")
    rack_conns.append(c2)
    c3 = _conn(len(rack_conns) + 1, f"{t}.bmqc_return", "manifold.branch_return")
    rack_conns.append(c3)
    dc_ids.append(c1["id"])
    tcs_ids.extend((c2["id"], c3["id"]))

  cells.append({
    "slug": "ocp-orv3-liquid-rack-assembly",
    "root": "OcpOrv3LiquidRackAssembly",
    "title": "OCP ORv3 HPR 液冷整机柜装配体 (96 kW)",
    "subtitle": "4x33kW PSU + 2xBBU + 16x1OU LC | 48V DC",
    "source": "OCP ORv3 HPR + OCP ACS Direct-to-Chip Rack Reference Assembly Rev 1.0",
    "ocp_spec": "OCP ORv3 HPR + ACS Composite Rack",
    "ocp_revision": "Rev 1.0",
    "schema_version": 2,
    "imports": rack_imports,
    "instances": rack_instances,
    "connections": rack_conns,
    "nets": {
      "DcBus48V": {"kind": "dc-48v-busbar", "connections": dc_ids},
      "TcsBranches": {"kind": "tcs-bmqc", "connections": tcs_ids},
    },
    "envelope_m": [0.6, 1.2, 2.495],
    "mass_kg": 1480.0,
    "clearances_m": {"front_service_m": 1.2, "rear_manifold_and_backplane_m": 1.2, "top_cable_and_busway_m": 0.6},
    "ports": {
      "power_a": _port("in", "ac-power", 1),
      "power_b": _port("in", "ac-power", 1),
      "tcs_supply": _port("in", "tcs", 1),
      "tcs_return": _port("out", "tcs", 1),
      "air_in": _port("in", "room-air", 1),
      "air_out": _port("out", "room-air", 1),
      "oob_mgmt": _port("inout", "ethernet-100g-oob", 2),
    },
    "interfaces": {
      "power_a": _iface([0.16, 1.0, 2.495], [0, 0, 1], "Feed A 3-phase AC to power shelves (N+N)"),
      "power_b": _iface([0.44, 1.0, 2.495], [0, 0, 1], "Feed B 3-phase AC to power shelves (N+N)"),
      "tcs_supply": _iface([0.46, 1.2, 2.35], [0, 1, 0], "Rear/top rack manifold supply inlet"),
      "tcs_return": _iface([0.54, 1.2, 2.35], [0, 1, 0], "Rear/top rack manifold return outlet"),
      "air_in": _iface([0.3, 0.0, 1.25], [0, -1, 0], "Front cold-aisle residual intake"),
      "air_out": _iface([0.3, 1.2, 1.25], [0, 1, 0], "Rear hot-aisle residual exhaust"),
      "oob_mgmt": _iface([0.55, 0.24, 2.495], [0, 0, 1], "In-rack management switch OOB uplink"),
    },
    "properties": {
      "form_factor": "OCP ORv3 HPR 21-inch",
      "mounting_width_in": 21,
      "total_ou": 48,
      "unit_pitch_m": 0.048,
      "power_shelves": 4,
      "bbu_shelves": 2,
      "compute_trays": 16,
      "internal_dc_bus_v": 50.0,
      "leak_detection": "Integrated tray & rack manifold leak detection",
      "geometry_parts": {
        "Cabinet": {"origin_m": [0.0, 0.0, 0.0], "size_m": [0.6, 1.2, 2.495], "color": [0.14, 0.19, 0.26]},
        "PowerZone": {"origin_m": [0.03, 0.02, 0.15], "size_m": [0.54, 0.78, 0.56], "color": [0.85, 0.55, 0.18]},
        "ComputeZone": {"origin_m": [0.03, 0.02, 0.76], "size_m": [0.54, 0.90, 1.50], "color": [0.16, 0.54, 0.74]},
      },
    },
    "parameters": {
      "nominal_rack_power_kw": (96.0, "kW"),
      "power_shelf_count": (4.0, "count"),
      "power_shelf_capacity_kw": (33.0, "kW"),
      "liquid_cooling_fraction": (0.9, "1"),
      "loaded_mass_kg": (1480.0, "kg"),
      "min_tcs_supply_c": (25.0, "degC"),
      "max_tcs_supply_c": (45.0, "degC"),
    },
    "behavior_model": "ocp-orv3-hpr-liquid-rack-composite",
    "behavior_method": "复合组合 ORv3 HPR 机框、48V 母排、4×33 kW 电源框、2×BBU、DN32 歧管与 16×1OU 液冷托盘。",
    "limitations": "标准参考整机柜装配，真实项目更换 OEM 超节点时须核对端口兼容与厂商流阻曲线。",
    "liberty": {
      "model": "ocp-orv3-hpr-96kw-liquid-rack",
      "axes": [
        {"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]},
        {"name": "tcs_supply_c", "unit": "degC", "values": [25.0, 30.0, 35.0, 40.0, 45.0]},
      ],
      "outputs": {
        "required_flow_lpm": {
          "unit": "L/min",
          "min_bound": 15.0,
          "values": [
            [20.0, 24.0, 30.0, 40.0, 58.0],
            [28.0, 34.0, 42.5, 56.5, 82.0],
            [38.5, 46.5, 58.5, 78.0, 114.0],
            [49.0, 59.0, 74.0, 99.0, 145.0],
          ],
        },
        "rack_dp_kpa": {
          "unit": "kPa",
          "min_bound": 1.0,
          "values": [
            [3.8, 5.2, 7.9, 13.8, 28.5],
            [6.8, 9.5, 14.5, 25.1, 52.0],
            [12.8, 17.8, 27.3, 47.4, 98.2],
            [21.0, 29.2, 44.8, 77.8, 161.0],
          ],
        },
        "liquid_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [21.6, 21.6, 21.6, 21.6, 21.6],
            [43.2, 43.2, 43.2, 43.2, 43.2],
            [64.8, 64.8, 64.8, 64.8, 64.8],
            [86.4, 86.4, 86.4, 86.4, 86.4],
          ],
        },
        "air_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [2.4, 2.4, 2.4, 2.4, 2.4],
            [4.8, 4.8, 4.8, 4.8, 4.8],
            [7.2, 7.2, 7.2, 7.2, 7.2],
            [9.6, 9.6, 9.6, 9.6, 9.6],
          ],
        },
        "total_power_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [24.0, 24.0, 24.0, 24.0, 24.0],
            [48.0, 48.0, 48.0, 48.0, 48.0],
            [72.0, 72.0, 72.0, 72.0, 72.0],
            [96.0, 96.0, 96.0, 96.0, 96.0],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "OCP ORv3 HPR 液冷整机柜组合包络与接口位姿",
      "symbol": "ORv3 复合整机柜符号与外部机电液端口",
      "specification": "复合机柜边界端口、48V 母排与液冷歧管集成规格",
      "behavior": "机柜级电/水/风耦合行为模型",
      "liberty": "(负载率, 供液温度) 25-45 degC 整机柜水力与热量包络表",
    },
  })

  # 10. ocp-cdu-inrow-1mw
  cells.append({
    "slug": "ocp-cdu-inrow-1mw",
    "root": "OcpCduInRow1Mw",
    "title": "OCP ACS 1 MW 列间液-液冷却分配单元 (CDU)",
    "subtitle": "600x1200x2200 mm | 1000 kW | DN100 FWS/TCS",
    "source": "OCP ACS Liquid-to-Liquid CDU Requirements Specification Rev 1.0",
    "ocp_spec": "OCP ACS Liquid-to-Liquid CDU Specification",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [0.6, 1.2, 2.2],
    "mass_kg": 720.0,
    "clearances_m": {"front_pump_and_hx_service_m": 1.2, "rear_piping_service_m": 0.9, "top_header_tie_in_m": 0.6},
    "ports": {
      "fws_supply": _port("in", "fws", 1),
      "fws_return": _port("out", "fws", 1),
      "tcs_supply": _port("out", "tcs", 1),
      "tcs_return": _port("in", "tcs", 1),
      "power_a": _port("in", "ac-power", 1),
      "power_b": _port("in", "ac-power", 1),
      "dp_ctrl": _port("inout", "control-signal", 4),
    },
    "interfaces": {
      "fws_supply": _iface([0.16, 0.92, 2.2], [0, 0, 1], "4-inch (DN100) primary FWS supply"),
      "fws_return": _iface([0.44, 0.92, 2.2], [0, 0, 1], "4-inch (DN100) primary FWS return"),
      "tcs_supply": _iface([0.16, 0.25, 2.2], [0, 0, 1], "4-inch (DN100) secondary TCS supply (1000 L/min N+1)"),
      "tcs_return": _iface([0.44, 0.25, 2.2], [0, 0, 1], "4-inch (DN100) secondary TCS return"),
      "power_a": _iface([0.15, 0.6, 2.2], [0, 0, 1], "400/480V 3-phase feed A"),
      "power_b": _iface([0.45, 0.6, 2.2], [0, 0, 1], "400/480V 3-phase feed B"),
      "dp_ctrl": _iface([0.3, 0.0, 1.6], [0, -1, 0], "Redundant differential-pressure PID controller interface"),
    },
    "properties": {
      "form_factor": "OCP ORv3 Compatible In-Row CDU",
      "rated_capacity_kw": 1000.0,
      "nominal_approach_k": 4.0,
      "nominal_flow_lpm": 1000.0,
      "pipe_connection_size": "DN100",
      "pump_configuration": "2+1 N+1 VFD pumps",
      "geometry_parts": {
        "Cabinet": {"origin_m": [0.0, 0.0, 0.0], "size_m": [0.6, 1.2, 2.2], "color": [0.18, 0.28, 0.36]},
        "HmiPanel": {"origin_m": [0.1, 0.0, 1.45], "size_m": [0.4, 0.03, 0.25], "color": [0.16, 0.68, 0.72]},
      },
    },
    "parameters": {
      "rated_capacity_kw": (1000.0, "kW"),
      "nominal_approach_k": (4.0, "K"),
      "nominal_flow_lpm": (1000.0, "L/min"),
    },
    "behavior_model": "ocp-acs-1mw-liquid-to-liquid-cdu",
    "behavior_method": "OCP ACS 1 MW 液-液 CDU 换热迫近度、泵功耗、最大可提供外部压头与板换阻力查表。",
    "limitations": "仅适用于单相水-PG25 稳态包络（FWS 18–30 degC）；超温或过滤器堵塞压降增长须另行校核。",
    "liberty": {
      "model": "ocp-acs-1mw-liquid-to-liquid-cdu",
      "axes": [
        {"name": "load_fraction", "unit": "1", "values": [0.2, 0.4, 0.6, 0.8, 1.0]},
        {"name": "fws_supply_c", "unit": "degC", "values": [18.0, 22.0, 26.0, 30.0]},
      ],
      "outputs": {
        "approach_k": {
          "unit": "K",
          "min_bound": 0.5,
          "values": [
            [1.1, 1.15, 1.2, 1.25],
            [1.6, 1.68, 1.75, 1.85],
            [2.2, 2.3, 2.42, 2.55],
            [2.9, 3.05, 3.2, 3.38],
            [3.7, 3.9, 4.1, 4.35],
          ],
        },
        "pump_power_kw": {
          "unit": "kW",
          "min_bound": 0.5,
          "values": [
            [1.6, 1.65, 1.7, 1.8],
            [3.2, 3.3, 3.45, 3.6],
            [6.0, 6.2, 6.5, 6.8],
            [10.2, 10.6, 11.0, 11.5],
            [15.8, 16.4, 17.0, 17.8],
          ],
        },
        "max_cooling_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [1080.0, 1040.0, 990.0, 930.0],
            [1080.0, 1040.0, 990.0, 930.0],
            [1080.0, 1040.0, 990.0, 930.0],
            [1080.0, 1040.0, 990.0, 930.0],
            [1080.0, 1040.0, 990.0, 930.0],
          ],
        },
        "internal_dp_kpa": {
          "unit": "kPa",
          "min_bound": 1.0,
          "values": [
            [5.5, 5.5, 5.7, 5.9],
            [16.0, 16.2, 16.6, 17.0],
            [32.0, 32.5, 33.2, 34.0],
            [54.0, 55.0, 56.2, 57.5],
            [82.0, 83.5, 85.0, 87.0],
          ],
        },
        "max_ext_dp_kpa": {
          "unit": "kPa",
          "min_bound": 20.0,
          "values": [
            [275.0, 275.0, 274.0, 273.0],
            [268.0, 267.0, 266.0, 265.0],
            [258.0, 257.0, 256.0, 254.0],
            [246.0, 244.0, 242.0, 240.0],
            [232.0, 230.0, 228.0, 225.0],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "600x1200x2200 mm OCP 列间 CDU 包络与顶接法兰坐标",
      "symbol": "液-液 CDU 符号与 FWS/TCS/供电/控制端口",
      "specification": "DN100 接口、N+1 泵组与 1 MW 额定换热参数",
      "behavior": "板换迫近度与变频泵压差控制契约",
      "liberty": "(负载率, FWS 供水温度) 多维 CDU 性能曲线",
    },
  })

  # 11. ocp-busway-tap-ac
  cells.append({
    "slug": "ocp-busway-tap-ac",
    "root": "OcpBuswayTapAc",
    "title": "OCP DCF 列顶高密交流母线槽段 (1600A)",
    "subtitle": "3000x240x160 mm | 400/480V 3P+N+PE | 1600 A",
    "source": "OCP Data Center Facility (DCF) Overhead Busway Distribution Reference Rev 1.0",
    "ocp_spec": "OCP DCF Overhead Busway Reference",
    "ocp_revision": "Rev 1.0",
    "envelope_m": [3.0, 0.24, 0.16],
    "mass_kg": 102.0,
    "clearances_m": {"busway_tap_drop_clearance_m": 0.45},
    "ports": {
      "in": _port("in", "ac-power", 1),
      "out": _port("out", "ac-power", 1),
      "tap_1": _port("out", "ac-power", 1),
      "tap_2": _port("out", "ac-power", 1),
      "tap_3": _port("out", "ac-power", 1),
      "tap_4": _port("out", "ac-power", 1),
    },
    "interfaces": {
      "in": _iface([0.0, 0.12, 0.08], [-1, 0, 0], "Busway feed-in joint (1600A 3L+N+PE)"),
      "out": _iface([3.0, 0.12, 0.08], [1, 0, 0], "Busway continuation splice"),
      "tap_1": _iface([0.45, 0.12, 0.0], [0, 0, -1], "Plug-in tap-off box 1"),
      "tap_2": _iface([1.15, 0.12, 0.0], [0, 0, -1], "Plug-in tap-off box 2"),
      "tap_3": _iface([1.85, 0.12, 0.0], [0, 0, -1], "Plug-in tap-off box 3"),
      "tap_4": _iface([2.55, 0.12, 0.0], [0, 0, -1], "Plug-in tap-off box 4"),
    },
    "properties": {
      "rated_current_a": 1600.0,
      "segment_length_m": 3.0,
      "r1_mohm_per_m": 0.029,
      "x1_mohm_per_m": 0.015,
    },
    "parameters": {
      "rated_current_a": (1600.0, "A"),
      "segment_length_m": (3.0, "m"),
    },
    "behavior_model": "ocp-dcf-overhead-busway-1600a",
    "behavior_method": "三相三线焦耳损耗 P = 3 * I^2 * R1 与单位米压降 dU = sqrt(3) * I * (R1*cos + X1*sin)。",
    "limitations": "覆盖 400–1600 A 连续工作区，短路热稳定与插接箱分断须配合开关选型复核。",
    "liberty": {
      "model": "ocp-dcf-busway-1600a-copper",
      "axes": [
        {"name": "current_a", "unit": "A", "values": [400.0, 800.0, 1200.0, 1600.0]},
        {"name": "power_factor", "unit": "1", "values": [0.85, 0.9, 0.95, 1.0]},
      ],
      "outputs": {
        "power_loss_w_per_m": {
          "unit": "W/m",
          "min_bound": 0.0,
          "values": [
            [13.92, 13.92, 13.92, 13.92],
            [55.68, 55.68, 55.68, 55.68],
            [125.28, 125.28, 125.28, 125.28],
            [222.72, 222.72, 222.72, 222.72],
          ],
        },
        "voltage_drop_v_per_m": {
          "unit": "V/m",
          "min_bound": 0.0,
          "values": [
            [0.02256, 0.02261, 0.02233, 0.02009],
            [0.04512, 0.04521, 0.04467, 0.04018],
            [0.06768, 0.06782, 0.06700, 0.06028],
            [0.09024, 0.09042, 0.08933, 0.08037],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "3m 标准长度列顶母线槽与 4 路底部插接位姿",
      "symbol": "架空母线槽工程符号与馈电/插接锚点",
      "specification": "1600A 铜导体单位长度阻抗参数",
      "behavior": "三相交流阻抗压降与铜损模型",
      "liberty": "(母线电流, 功率因数) 二维单位米损耗与压降表",
    },
  })

  # 12. ocp-dcf-modular-it-pod (Composite SDL v2)
  pod_imports = {
    "OcpRack": "library/modules/ocp-orv3-liquid-rack-assembly/ocp-orv3-liquid-rack-assembly.sdl.json",
    "OcpCdu": "library/modules/ocp-cdu-inrow-1mw/ocp-cdu-inrow-1mw.sdl.json",
    "OcpBusway": "library/modules/ocp-busway-tap-ac/ocp-busway-tap-ac.sdl.json",
  }
  pod_local_components = {
    "TcsSupplyHeader": {"ports": {"in": _port("in", "tcs", 1), "out_1": _port("out", "tcs", 1), "out_2": _port("out", "tcs", 1)}},
    "TcsReturnHeader": {"ports": {"in_1": _port("in", "tcs", 1), "in_2": _port("in", "tcs", 1), "out": _port("out", "tcs", 1)}},
  }
  pod_instances = {
    "cdu_a": {"component": "OcpCdu"},
    "cdu_b": {"component": "OcpCdu"},
    "tcs_sup_a": {"component": "TcsSupplyHeader"},
    "tcs_ret_a": {"component": "TcsReturnHeader"},
    "tcs_sup_b": {"component": "TcsSupplyHeader"},
    "tcs_ret_b": {"component": "TcsReturnHeader"},
    "bus_a": {"component": "OcpBusway"},
    "bus_b": {"component": "OcpBusway"},
    "rack_01": {"component": "OcpRack"},
    "rack_02": {"component": "OcpRack"},
    "rack_03": {"component": "OcpRack"},
    "rack_04": {"component": "OcpRack"},
  }
  pod_conns: list[dict[str, str]] = []
  ac_ids: list[str] = []
  tcs_pod_ids: list[str] = []
  for idx in range(1, 5):
    ca = _conn(len(pod_conns) + 1, f"bus_a.tap_{idx}", f"rack_{idx:02d}.power_a")
    pod_conns.append(ca)
    cb = _conn(len(pod_conns) + 1, f"bus_b.tap_{idx}", f"rack_{idx:02d}.power_b")
    pod_conns.append(cb)
    ac_ids.extend((ca["id"], cb["id"]))
  for side, cdu_name, offset in (("a", "cdu_a", 0), ("b", "cdu_b", 2)):
    c_sup = _conn(len(pod_conns) + 1, f"{cdu_name}.tcs_supply", f"tcs_sup_{side}.in")
    pod_conns.append(c_sup)
    c_ret = _conn(len(pod_conns) + 1, f"tcs_ret_{side}.out", f"{cdu_name}.tcs_return")
    pod_conns.append(c_ret)
    tcs_pod_ids.extend((c_sup["id"], c_ret["id"]))
    for local_i in (1, 2):
      rack_idx = offset + local_i
      cs = _conn(len(pod_conns) + 1, f"tcs_sup_{side}.out_{local_i}", f"rack_{rack_idx:02d}.tcs_supply")
      pod_conns.append(cs)
      cr = _conn(len(pod_conns) + 1, f"rack_{rack_idx:02d}.tcs_return", f"tcs_ret_{side}.in_{local_i}")
      pod_conns.append(cr)
      tcs_pod_ids.extend((cs["id"], cr["id"]))

  cells.append({
    "slug": "ocp-dcf-modular-it-pod",
    "root": "OcpDcfModularItPod",
    "title": "OCP DCF 液冷模块化 IT Pod (4x ORv3 + 2x CDU)",
    "subtitle": "3.6x2.8x2.9 m | 416 kW IT | N+1 CDU + 2N Busway",
    "source": "OCP Data Center Facility (DCF) Liquid-Cooled Modular IT Pod Reference Rev 1.0",
    "ocp_spec": "OCP DCF Modular IT Pod Reference",
    "ocp_revision": "Rev 1.0",
    "schema_version": 2,
    "imports": pod_imports,
    "extra_components": pod_local_components,
    "instances": pod_instances,
    "connections": pod_conns,
    "nets": {
      "PodAcDistribution": {"kind": "ac-power", "connections": ac_ids},
      "PodTcsLoop": {"kind": "tcs", "connections": tcs_pod_ids},
    },
    "envelope_m": [3.6, 2.8, 2.9],
    "mass_kg": 8600.0,
    "clearances_m": {"front_service_m": 1.2, "rear_service_m": 1.2},
    "ports": {
      "power_a": _port("in", "ac-power", 1),
      "power_b": _port("in", "ac-power", 1),
      "fws_supply": _port("in", "fws", 2),
      "fws_return": _port("out", "fws", 2),
      "oob_mgmt": _port("inout", "ethernet-100g-oob", 2),
      "alarm": _port("out", "signal", 1),
    },
    "interfaces": {
      "power_a": _iface([0.4, 0.0, 2.9], [0, 0, 1], "Pod Busway A primary AC feed"),
      "power_b": _iface([3.2, 0.0, 2.9], [0, 0, 1], "Pod Busway B redundant AC feed"),
      "fws_supply": _iface([1.2, 2.8, 2.6], [0, 1, 0], "Pod primary FWS supply header (2x DN100)"),
      "fws_return": _iface([2.4, 2.8, 2.6], [0, 1, 0], "Pod primary FWS return header (2x DN100)"),
      "oob_mgmt": _iface([1.8, 0.0, 2.6], [0, -1, 0], "Pod OOB management uplink"),
      "alarm": _iface([3.6, 1.4, 2.2], [1, 0, 0], "Pod leak detection & fire interlock alarm"),
    },
    "properties": {
      "ocp_dcf_profile": "OCP-DCF-Modular-IT-Pod",
      "racks_per_pod": 4,
      "cdu_count": 2,
      "rated_it_kw": 416.0,
      "liquid_cooling_fraction": 0.9,
      "geometry_parts": {
        "PodEnclosure": {"origin_m": [0.0, 0.0, 0.0], "size_m": [3.6, 2.8, 2.9], "color": [0.22, 0.30, 0.38]},
        "CduBay": {"origin_m": [0.1, 0.2, 0.05], "size_m": [1.2, 1.2, 2.2], "color": [0.18, 0.56, 0.68]},
      },
    },
    "parameters": {
      "rated_it_kw": (416.0, "kW"),
      "racks_per_pod": (4.0, "count"),
      "liquid_cooling_fraction": (0.9, "1"),
    },
    "behavior_model": "ocp-dcf-modular-liquid-pod",
    "behavior_method": "OCP DCF 4 柜液冷 IT Pod 宏单元，集成 2×1 MW N+1 CDU 与 A/B 双路架空母线。",
    "limitations": "概念参考模块化 Pod，具体防火分区、气体灭火与箱体抗震按项目所在地规范深化。",
    "liberty": {
      "model": "ocp-dcf-416kw-modular-it-pod",
      "axes": [
        {"name": "load_fraction", "unit": "1", "values": [0.25, 0.5, 0.75, 1.0]},
        {"name": "fws_supply_c", "unit": "degC", "values": [18.0, 22.0, 26.0, 30.0]},
      ],
      "outputs": {
        "total_power_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [107.0, 107.2, 107.5, 107.8],
            [213.0, 213.4, 213.9, 214.5],
            [322.0, 322.6, 323.4, 324.2],
            [434.0, 435.0, 436.2, 437.5],
          ],
        },
        "liquid_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [93.6, 93.6, 93.6, 93.6],
            [187.2, 187.2, 187.2, 187.2],
            [280.8, 280.8, 280.8, 280.8],
            [374.4, 374.4, 374.4, 374.4],
          ],
        },
        "air_heat_kw": {
          "unit": "kW",
          "min_bound": 0.0,
          "values": [
            [10.4, 10.4, 10.4, 10.4],
            [20.8, 20.8, 20.8, 20.8],
            [31.2, 31.2, 31.2, 31.2],
            [41.6, 41.6, 41.6, 41.6],
          ],
        },
      },
    },
    "fidelity": {
      "geometry": "OCP DCF 4 柜液冷模块化 Pod 整体包络与接口位姿",
      "symbol": "模块化 IT Pod 工程符号与设施水电接口",
      "specification": "Pod 级 N+1 CDU 与 2N 母线配置边界",
      "behavior": "Pod 级聚合热量与供电耦合模型",
      "liberty": "(负载率, FWS 供水温度) Pod 总电耗与液/风热分配表",
    },
  })

  return cells


def main() -> None:
  for cell in _cells():
    slug = cell["slug"]
    mod_dir = ROOT / slug
    assets_dir = mod_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    root_comp: dict[str, Any] = {
      "ports": cell["ports"],
      "behavior": {
        "reference": "assets/behavior.json",
        "state": "known",
        "source": cell["source"],
        "parameters": {
          k: _param(v, u, cell["source"]) for k, (v, u) in cell["parameters"].items()
        },
      },
    }
    if "instances" in cell:
      root_comp["instances"] = cell["instances"]
    if "connections" in cell:
      root_comp["connections"] = cell["connections"]
    if "nets" in cell:
      root_comp["nets"] = cell["nets"]

    sdl_doc: dict[str, Any] = {
      "schema_version": cell.get("schema_version", 1),
      "root": cell["root"],
      "components": {**cell.get("extra_components", {}), cell["root"]: root_comp},
    }
    if "imports" in cell:
      sdl_doc["imports"] = cell["imports"]

    spec_doc: dict[str, Any] = {
      "schema_version": 1,
      "state": "calibrated-reference",
      "vendor": "OCP",
      "model_number": slug.upper(),
      "ocp_spec": cell["ocp_spec"],
      "ocp_revision": cell["ocp_revision"],
      "basis": cell["source"],
      "envelope_m": cell["envelope_m"],
      "mass_kg": cell["mass_kg"],
      "clearances_m": cell["clearances_m"],
      "frame": {"origin": "cabinet-minimum-corner", "units": "m", "up_axis": "Z"},
      "interfaces": cell["interfaces"],
      "properties": cell["properties"],
      "limitations": cell["limitations"],
    }

    behavior_doc = {
      "schema_version": 1,
      "state": "calibrated-reference",
      "model": cell["behavior_model"],
      "parameters": {k: u for k, (_, u) in cell["parameters"].items()},
      "method": cell["behavior_method"],
      "limitations": cell["limitations"],
    }

    lib_raw = cell["liberty"]
    liberty_doc = {
      "schema_version": 1,
      "kind": "liberty-table",
      "model": lib_raw["model"],
      "state": "calibrated-reference",
      "source": cell["source"],
      "uncertainty_pct": 3.5,
      "operating_envelope": {
        "ocp_spec": cell["ocp_spec"],
        "ocp_revision": cell["ocp_revision"],
        **{ax["name"] + "_range": [ax["values"][0], ax["values"][-1]] for ax in lib_raw["axes"]},
      },
      "axes": lib_raw["axes"],
      "outputs": lib_raw["outputs"],
      "limitations": cell["limitations"],
    }

    (mod_dir / f"{slug}.sdl.json").write_text(
      json.dumps(sdl_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (mod_dir / "module.toml").write_text(_render_module_toml(cell), encoding="utf-8")
    (assets_dir / "geometry.usda").write_text(_render_usda(spec_doc), encoding="utf-8")
    (assets_dir / "symbol.svg").write_text(
      _render_symbol_svg(slug, cell["title"], cell["subtitle"], cell["ports"]), encoding="utf-8"
    )
    (assets_dir / "specification.json").write_text(
      json.dumps(spec_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (assets_dir / "behavior.json").write_text(
      json.dumps(behavior_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (assets_dir / "liberty.json").write_text(
      json.dumps(liberty_doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"generated {slug}")


if __name__ == "__main__":
  main()
