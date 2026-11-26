"""Shared metre/Z-up scene and orthogonal world-box readers."""

import math
from itertools import pairwise


def open_scene(path):
  from pxr import Sdf, Usd, UsdGeom

  layer = Sdf.Layer.FindOrOpen(str(path))
  if not layer or layer.GetCompositionAssetDependencies():
    raise ValueError("场景应为可读的单文件展平 USD")
  stage = Usd.Stage.Open(layer)
  if (not stage or not stage.GetDefaultPrim() or stage.GetCompositionErrors()
      or not UsdGeom.StageHasAuthoredMetersPerUnit(stage)
      or UsdGeom.GetStageMetersPerUnit(stage) != 1 or UsdGeom.GetStageUpAxis(stage) != UsdGeom.Tokens.z):
    raise ValueError("场景应明确使用米制坐标与 Z 向上")
  return stage


def world_box(prim):
  from pxr import Gf, Usd, UsdGeom
  cube = UsdGeom.Cube(prim)
  if not cube:
    raise ValueError(f"{prim.GetPath()} 应为轴对齐的 USD Cube")
  size = cube.GetSizeAttr().Get()
  xf = cube.ComputeLocalToWorldTransform(Usd.TimeCode.Default())
  basis = [xf.TransformDir(Gf.Vec3d(*[float(i == j) for i in range(3)])) for j in range(3)]
  axes = [[i for i, value in enumerate(vec) if abs(value) > 1e-9] for vec in basis]
  if any(len(axis) != 1 for axis in axes) or len({axis[0] for axis in axes}) != 3:
    raise ValueError(f"{prim.GetPath()} 存在非正交变换")
  center = xf.ExtractTranslation()
  half = [size * sum(abs(vec[i]) for vec in basis) / 2 for i in range(3)]
  low, high = tuple(a - b for a, b in zip(center, half, strict=True)), tuple(
    a + b for a, b in zip(center, half, strict=True))
  if not all(math.isfinite(a) and math.isfinite(b) and a < b for a, b in zip(low, high, strict=True)):
    raise ValueError(f"{prim.GetPath()} 的几何范围无效")
  return low, high


def world_polyline(prim, cache):
  from pxr import UsdGeom

  curve = UsdGeom.BasisCurves(prim)
  if not curve or curve.GetTypeAttr().Get() != "linear" or curve.GetWrapAttr().Get() != "nonperiodic":
    raise ValueError(f"{prim.GetPath()} 须为非闭合线性 USD 曲线")
  local = curve.GetPointsAttr().Get()
  if local is None or len(local) < 2 or list(curve.GetCurveVertexCountsAttr().Get() or ()) != [len(local)]:
    raise ValueError(f"{prim.GetPath()} 须包含一根有序中心线")
  matrix = cache.GetLocalToWorldTransform(prim)
  points = [tuple(matrix.Transform(point)) for point in local]
  if not all(math.isfinite(value) for point in points for value in point):
    raise ValueError(f"{prim.GetPath()} 含无效坐标")
  if any(math.dist(a, b) <= 1e-6 for a, b in pairwise(points)):
    raise ValueError(f"{prim.GetPath()} 含零长段")
  return points
