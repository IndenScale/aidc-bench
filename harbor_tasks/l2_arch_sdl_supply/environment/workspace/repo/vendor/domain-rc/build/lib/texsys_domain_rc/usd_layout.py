"""Read independently placed ports and single linear routes from flattened metre USD."""

from pxr import Usd, UsdGeom


def read_port_layout(path):
  stage = Usd.Stage.Open(str(path), load=Usd.Stage.LoadNone)
  if not stage or not stage.GetDefaultPrim():
    raise ValueError("Port extraction requires a USD default prim.")
  layer = stage.GetRootLayer()
  if layer.ListAllTimeSamples() or layer.subLayerPaths or layer.GetExternalReferences():
    raise ValueError("Expected a static, flattened implementation scene.")
  if not UsdGeom.StageHasAuthoredMetersPerUnit(stage) or UsdGeom.GetStageMetersPerUnit(stage) != 1:
    raise ValueError("Expected declared metre coordinates.")
  root = stage.GetDefaultPrim()
  meta = root.GetCustomData()
  ports, routes = {}, {}
  cache = UsdGeom.XformCache()
  for prim in Usd.PrimRange(root):
    record = prim.GetCustomData()
    role = record.get("rcRole")
    if role not in ("port", "route"):
      continue
    key = record["identity"]
    matrix = cache.GetLocalToWorldTransform(prim)
    if role == "port":
      if key in ports:
        raise ValueError(f"Duplicate physical port {key}.")
      ports[key] = {"instance": record["instance"], "interface": record["interface"],
                    "xyz_m": list(matrix.ExtractTranslation()), "prim": str(prim.GetPath())}
      continue
    curve = UsdGeom.BasisCurves(prim)
    if not curve or curve.GetTypeAttr().Get() != "linear":
      raise ValueError(f"{key} requires a linear route.")
    points = curve.GetPointsAttr().Get()
    if not points or len(points) < 2 or list(curve.GetCurveVertexCountsAttr().Get() or []) != [len(points)]:
      raise ValueError(f"{key} requires one continuous polyline.")
    if key in routes:
      raise ValueError(f"Duplicate physical route {key}.")
    ends = []
    for side, point in (("start", points[0]), ("end", points[-1])):
      end = {"xyz_m": list(matrix.Transform(point))}
      if side + "Port" in record:
        end["port"] = record[side + "Port"]
      if side + "Joint" in record:
        end.update(joint=record[side + "Joint"], interface=record[side + "Interface"],
                   tolerance_m=record[side + "ToleranceM"])
      ends.append(end)
    routes[key] = {"ends": ends, "prim": str(prim.GetPath())}
  return {"schema_version": meta["schema_version"], "kind": "port-layout",
          **{key: meta[key] for key in ("domain", "scope", "baseline", "complete", "frame")},
          "ports": ports, "routes": routes}
