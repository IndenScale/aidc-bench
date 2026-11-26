"""Trace filter stages and final devices on a directed supply network at one operating point."""

from collections import defaultdict
from graphlib import TopologicalSorter

from texsys.evidence import canonical_digest

STAGES = {"primary": 1, "medium": 2, "sub-high": 0, "chemical": 0}


class IncompleteAirNetwork(ValueError):
  """A missing input prevents the supply graph from being resolved."""


def _required(record, key):
  if key not in record or record[key] is None:
    raise IncompleteAirNetwork(f"风系统资料缺少 {key}")
  return record[key]


def _name(value):
  if not isinstance(value, str) or not value.strip():
    raise ValueError("风系统节点、工况及依据应为非空字符串")
  return value


def trace_system(system):
  """Keep one witness per filtration state, including the possibility of an unconfirmed damper."""
  if not isinstance(system, dict):
    raise TypeError("风系统应为对象")
  nodes, edges = _required(system, "nodes"), _required(system, "edges")
  if not isinstance(nodes, dict) or not isinstance(edges, list):
    raise TypeError("风路节点应为对象，连接应为数组")
  kinds, rooms, filters = {}, {}, {}
  for key, node in nodes.items():
    _name(key)
    if not isinstance(node, dict):
      raise TypeError("风路节点应为对象")
    kind = kinds[key] = _required(node, "kind")
    if kind == "terminal":
      rooms[key] = _name(_required(node, "room"))
    elif kind == "filter":
      grade = node.get("grade")
      if grade is not None and grade not in STAGES:
        raise ValueError(f"未知过滤器等级：{key}")
      filters[key] = {k: node[k] for k in ("grade", "upstream_gauge_pa", "pressure_source") if k in node}
    elif kind not in ("intake", "fan", "branch"):
      raise ValueError(f"未知风路节点类别：{key}")

  parents, children = defaultdict(dict), set()
  for edge in edges:
    if isinstance(edge, list) and len(edge) == 2:
      start, end = edge
      state = "open"
    elif isinstance(edge, dict):
      start, end, state = (_required(edge, k) for k in ("from", "to", "state"))
    else:
      raise ValueError("风路连接需要两个节点 ID 或带工况状态的连接记录")
    if not all(isinstance(k, str) and k in nodes for k in (start, end)) or state not in ("open", "closed", "unknown"):
      raise ValueError("风路连接引用未知节点或开闭状态")
    if start in parents[end] or kinds[start] == "terminal" or kinds[end] == "intake":
      raise ValueError(f"风路重复连接或进出口方向错误：{start} → {end}")
    parents[end][start] = state
    children.add(start)
  if not rooms or "intake" not in kinds.values():
    raise IncompleteAirNetwork("需要标注风系统进风口和送风末端")
  if any((kind != "intake" and not parents[key]) or (kind != "terminal" and key not in children) for key, kind in kinds.items()):
    raise IncompleteAirNetwork("风路存在未接通的节点，无法确认送风路径完整")

  traces, last = {}, {}
  for key in TopologicalSorter({k: sorted(parents[k]) for k in sorted(nodes)}).static_order():
    grade = filters.get(key, {}).get("grade")
    routes = {(0, 0, True): None} if kinds[key] == "intake" else {}
    final = {}
    for parent, state in sorted(parents[key].items()):
      if state == "closed":
        continue
      for previous in traces[parent]:
        mask, unknown, certain = previous
        signature = (mask | STAGES.get(grade, 0), min(2, unknown + int(key in filters and grade is None)),
                     certain and state == "open")
        routes.setdefault(signature, (parent, previous))
      if key not in filters:
        for device, certain in last[parent].items():
          final[device] = final.get(device, False) or (certain and state == "open")
    if key in filters and routes:
      final[key] = any(certain for _, _, certain in routes)
    traces[key], last[key] = routes, final

  terminals = {}
  for terminal, room in sorted(rooms.items()):
    paths = []
    for signature in sorted(traces[terminal]):
      mask, unknown, certain = signature
      path, at = [], (terminal, signature)
      while at:
        node, state = at
        path.append(node)
        at = traces[node][state]
      known = [label for label, flag in STAGES.items() if mask & flag]
      paths.append({"known_stages": known, "distinct_stages_min": len(known),
                    "distinct_stages_max": min(2, len(known) + unknown), "confirmed_open": certain,
                    "nodes": list(reversed(path))})
    terminals[terminal] = {"room": room, "paths": paths, "final_filters": last[terminal]}
  return {"terminals": terminals, "filters": filters}


def filtration_study(network):
  if (type(network.get("schema_version")) is not int or network["schema_version"] != 1
      or network.get("kind") != "air-supply-network"):
    raise ValueError("需要 v1 风系统送风网络")
  header = {k: _name(_required(network, k)) for k in ("baseline", "frame", "case")}
  digests = _required(network, "scene_digests")
  records = _required(network, "systems")
  if not isinstance(records, dict) or not isinstance(digests, dict):
    raise TypeError("风系统清单与场景摘要应为对象")
  systems, issues = {}, []
  for name, system in records.items():
    if not isinstance(system, dict):
      raise TypeError("风系统应为对象")
    row = {k: system.get(k) for k in ("kind", "source", "precision_air_units")}
    try:
      if _required(system, "complete") is not True:
        raise IncompleteAirNetwork("风系统支路尚未确认完整")
      _name(_required(system, "source"))
      row.update(trace_system(system))
    except IncompleteAirNetwork as error:
      row["unresolved"] = str(error)
      issues.append(f"{name}：{error}")
    systems[_name(name)] = row
  complete = _required(network, "systems_complete")
  if type(complete) is not bool:
    raise TypeError("风系统清单完整性应为布尔值")
  if not complete:
    issues.append("风系统清单尚未确认完整")
  return {"unresolved": issues, "schema_version": 1, "kind": "air-filtration-paths", "domain": "hvac", **header,
          "network_digest": canonical_digest(network), "scene_digests": {k: _name(_required(digests, k)) for k in ("building", "equipment")},
          "systems_complete": complete, "systems": systems,
          "paths_digest": canonical_digest({"systems_complete": complete, "systems": systems})}
