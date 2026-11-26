"""Integrate independent hourly mean input-power runs over one project calendar year."""

import math
from datetime import datetime, timedelta, timezone

from texsys.evidence import canonical_digest

from .netlist import _table, _text


def _ranges(indices):
  spans = []
  for i in indices:
    if spans and i == spans[-1][1]:
      spans[-1][1] += 1
    else:
      spans.append([i, i + 1])
  return spans


def _integrate(blocks, start, hours):
  if not isinstance(blocks, list):
    raise ValueError("Expected a list of hourly blocks.")
  values = [None] * hours
  seen, overlaps = set(), set()
  for block in blocks:
    block = _table(block)
    when = datetime.fromisoformat(_text(block["start"]))
    if when.tzinfo is None:
      raise ValueError("Hourly blocks require an explicit UTC offset.")
    delta = when - start
    index, remainder = divmod(delta, timedelta(hours=1))
    samples = block["mean_kw"]
    if (remainder or not isinstance(samples, list) or not samples or index < 0 or index + len(samples) > hours):
      raise ValueError("Hourly block is empty, off the hour grid, or beyond the selected calendar year.")
    for i, value in enumerate(samples, start=index):
      if value is not None and (type(value) not in (float, int) or not math.isfinite(value) or value < 0):
        raise ValueError("Expected finite nonnegative hourly mean input power in kW.")
      if i in seen:
        overlaps.add(i)
        values[i] = None
      else:
        seen.add(i)
        values[i] = value
  gaps = _ranges(i for i, value in enumerate(values) if value is None)
  known = [v for v in values if v is not None]
  total = math.fsum(known)
  return {"covered_hours": len(known), "missing_hour_ranges": gaps, "overlap_hour_ranges": _ranges(sorted(overlaps)),
          "known_kwh": total, "annual_kwh": None if gaps else total}


def annual_energy(basis, runs):
  for doc, kind in ((basis, "annual-energy-basis"), (runs, "annual-energy-runs")):
    if type(doc.get("schema_version")) is not int or doc["schema_version"] != 1 or doc.get("kind") != kind:
      raise ValueError(f"Expected version 1 {kind}.")
  year, offset = basis.get("year"), basis.get("utc_offset_minutes")
  if type(year) is not int or not 1 <= year <= 9998 or type(offset) is not int or not -1440 < offset < 1440:
    raise ValueError("Expected a calendar year and fixed UTC offset in minutes.")
  start = datetime(year, 1, 1, tzinfo=timezone(timedelta(minutes=offset)))
  hours = (start.replace(year=year + 1) - start) // timedelta(hours=1)
  digest = canonical_digest(basis)
  common = {key: _text(basis[key]) for key in ("frame", "scene_digest", "comparison_basis", "weather_digest",
                                               "operation_digest", "meter_boundary", "source")}
  report = {"schema_version": 1, "kind": "annual-energy-study", **common, "basis_digest": digest,
            "runs_digest": canonical_digest(runs), "start": start.isoformat(), "expected_hours": hours,
            "rooms": {}, "unresolved": []}
  for room, options in sorted(_table(runs["rooms"]).items()):
    results = report["rooms"][room] = {}
    for key, run in sorted(_table(options).items()):
      try:
        run = _table(run)
        if run.get("basis_digest") != digest or run.get("quantity") != "hourly-mean-input-kw":
          raise ValueError("Run does not match the selected comparison basis or energy quantity.")
        source, model = _text(run["source"]), _text(run["model_digest"])
        u_values = _table(run["u_values_w_m2k"])
        if not u_values or any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in u_values.values()):
          raise ValueError("Expected positive envelope U-values.")
        study = _integrate(run["blocks"], start, hours)
        results[key] = {**study, "source": source, "model_digest": model, "u_values_w_m2k": u_values}
        if study["annual_kwh"] is None:
          report["unresolved"].append({"room": room, "option": key, "reason": "incomplete-year"})
      except (ValueError, KeyError, TypeError, OverflowError) as error:
        report["unresolved"].append({"room": room, "option": key, "reason": str(error)})
  return report
