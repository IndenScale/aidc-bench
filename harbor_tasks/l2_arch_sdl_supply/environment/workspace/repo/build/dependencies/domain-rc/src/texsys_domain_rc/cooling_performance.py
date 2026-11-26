"""Interpolate declared steady-state cooling product data at specified outdoor temperatures."""

import math
from itertools import pairwise

from texsys.evidence import canonical_digest

from .netlist import _table, _text


def _number(value):
  if type(value) not in (int, float) or not math.isfinite(value):
    raise ValueError("Expected a finite cooling performance quantity.")
  return value


def _curve(record):
  raw = record.get("performance")
  if raw is None or raw == []:
    return []
  if not isinstance(raw, list):
    raise ValueError("Expected an ordered array of performance points.")
  points = []
  for row in raw:
    if any(row.get(k) is None for k in ("ambient_c", "capacity_kw", "cop")):
      return []
    t, q, cop = (_number(row[k]) for k in ("ambient_c", "capacity_kw", "cop"))
    if q <= 0 or cop <= 0 or (points and t <= points[-1][0]):
      raise ValueError("Capacity and COP must be positive and temperatures strictly increasing.")
    points.append((t, q, cop))
  return points


def cooling_performance(catalog, conditions):
  for item, kind in ((catalog, "cooling-product-data"), (conditions, "cooling-conditions")):
    if type(item.get("schema_version")) is not int or item["schema_version"] != 1 or item.get("kind") != kind:
      raise ValueError(f"Expected version 1 {kind}.")
  products = _table(catalog["units"])
  curves = {key: _curve(record) for key, record in products.items()}
  report = {"schema_version": 1, "kind": "cooling-performance", "domain": "hvac", "catalog_digest": canonical_digest(catalog),
            "conditions_digest": canonical_digest(conditions), "cases": {}, "unresolved": []}
  for name, case in sorted(_table(conditions["cases"]).items()):
    observations = {}
    ambient = case.get("ambient_c")
    if ambient is not None:
      _number(ambient)
    report["cases"][name] = {"ambient_c": ambient, "units": observations}
    for unit, spec in sorted(products.items()):
      if ambient is None or not spec.get("source") or not spec.get("product"):
        report["unresolved"].append({"case": name, "unit": unit, "reason": "missing-temperature-or-product-basis"})
        continue
      for a, b in pairwise(curves[unit]):
        if a[0] <= ambient <= b[0]:
          fraction = (ambient - a[0]) / (b[0] - a[0])
          observations[unit] = {"source": _text(spec["source"]), "product": _text(spec["product"]),
                                "capacity_kw": a[1] + fraction * (b[1] - a[1]), "cop": a[2] + fraction * (b[2] - a[2]),
                                "bracket_c": [a[0], b[0]]}
          break
      else:
        report["unresolved"].append({"case": name, "unit": unit, "reason": "outside-or-missing-product-curve"})
  return report
