"""Extract chilled-water circuits against a port-level installation netlist."""

from texsys.evidence import canonical_digest, file_digest

from .netlist import _text
from .usd_geometry import open_scene, world_box
from .usd_layout import read_port_layout


def chilled_water_network(scene, hydraulic):
  """Installed pipe circuits, device identities and port terminations."""
  from pxr import Usd

  stage = open_scene(scene)
  root = stage.GetDefaultPrim()
  if stage.GetRootLayer().ListAllTimeSamples():
    raise ValueError("水力实施场景须为静态")
  digest = file_digest(scene)
  header = {key: _text(root.GetCustomDataByKey(key)) for key in ("scope", "baseline", "frame")}
  nodes, segments, issues = {}, {}, []
  for prim in Usd.PrimRange(root):
    role = prim.GetCustomDataByKey("role")
    if role not in ("chilled-water-node", "chilled-water-segment"):
      continue
    key = _text(prim.GetCustomDataByKey("identity"))
    if key in nodes or key in segments:
      raise ValueError(f"重复的冷冻水构件 {key}")
    if role == "chilled-water-node":
      nodes[key] = {"kind": _text(prim.GetCustomDataByKey("nodeKind")), "prim": str(prim.GetPath()), "bounds_m": world_box(prim)}
    else:
      circuit = prim.GetCustomDataByKey("circuit")
      if circuit not in ("supply", "return"):
        raise ValueError(f"{key} 未声明管段用途")
      segments[key] = circuit
  if (hydraulic.get("kind") != "domain-netlist" or hydraulic.get("origin") != "physical"
      or hydraulic.get("domain") != "hydraulic" or hydraulic.get("granularity") != "port"
      or type(hydraulic.get("schema_version")) is not int or hydraulic["schema_version"] != 1):
    raise ValueError("水力提取需要端口级水力物理网表")
  if (hydraulic.get("scope"), hydraulic.get("baseline"), hydraulic.get("sources", {}).get("layout", {}).get("digest")) != (
      header["scope"], header["baseline"], digest):
    issues.append("水力网表与实施场景的范围、基线或来源摘要不一致")
  if (hydraulic.get("complete") is not True or hydraulic.get("unresolved") or root.GetCustomDataByKey("chilledWaterInventoryComplete") is not True
      or set(hydraulic["connections"]) != segments.keys()):
    issues.append("管段、设备或实施端接清单未确认完整")
  topology = {"supply": {}, "return": {}}
  if not issues:
    layout = read_port_layout(scene)
    circuits_by_port = {}
    for key, conn in hydraulic["connections"].items():
      ends = [hydraulic["ports"][p]["instance"] for p in conn["ports"]]
      if len(ends) != 2 or not all(end in nodes for end in ends):
        raise ValueError(f"{key} 的实施端接引用未知设备")
      for port in conn["ports"]:
        if circuits_by_port.setdefault(port, segments[key]) != segments[key]:
          issues.append(f"{port} 同时端接供水和回水，无法建立独立压力节点")
      for placed, owner in zip(layout["routes"][key]["ends"], ends, strict=True):
        low, high = nodes[owner]["bounds_m"]
        if not all(a-1e-6 <= x <= b+1e-6 for x, a, b in zip(placed["xyz_m"], low, high, strict=True)):
          issues.append(f"{key} 的管段端点位于 {owner} 的设备包络之外")
      topology[segments[key]][key] = ends
  return {"kind": "chilled-water-network", "schema_version": 1, "domain": "hydraulic", **header,
          "scene_digest": digest, "water_netlist_digest": canonical_digest(hydraulic),
          "nodes": nodes, "topology": topology, "complete": not issues, "unresolved": issues}
