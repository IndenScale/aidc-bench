"""Time bounds for first undersupply from continuous, calibrated flow extrema."""

from fractions import Fraction

from .service_intervals import continuous_service_bounds
from .water_observations import _finite


def first_flow_deficit(intervals, required, horizon, flow_error, time_error):
  """Windows are half-open hours since isolation. Flow values use one common unit."""
  if not all(_finite(v) and v >= 0 for v in (required, horizon, flow_error, time_error)) or not horizon:
    raise ValueError("Invalid horizon, flow threshold or measurement error.")
  if not isinstance(intervals, list):
    raise ValueError("Expected continuous flow intervals.")
  threshold, stop, radius, edge = (Fraction(str(v)) for v in (required, horizon, flow_error, time_error))
  segments, witnesses = [], []
  for row in intervals:
    window = row.get("window_h") if isinstance(row, dict) else None
    if not isinstance(window, list) or len(window) != 2 or not all(_finite(v) for v in window):
      raise ValueError("Invalid flow observation window.")
    a, b = (Fraction(str(v)) for v in window)
    low, high = row.get("minimum_m3_h"), row.get("maximum_m3_h")
    if (any(v is not None and not _finite(v) for v in (low, high))
        or (low is not None and high is not None and low > high)):
      raise ValueError("Invalid flow extrema.")
    low = None if low is None else Fraction(str(low))
    high = None if high is None else Fraction(str(high))
    state = None
    if low is not None and low - radius >= threshold:
      state = True
    elif high is not None and high + radius < threshold:
      state = False
    # A measured minimum was attained somewhere in this interval. It only
    # witnesses failure inside the review window if the whole interval fits.
    if low is not None and low + radius < threshold and a - edge >= 0 and b + edge <= stop:
      witnesses.append((b + edge, False))
    segments.append((a, b, state))
  _, _, service, deficit, _ = continuous_service_bounds((0, stop), segments, edge)
  prefix = service[0][1] if service and service[0][0] == 0 else 0
  witnesses.extend((a, True) for a, _ in deficit)
  upper, inclusive = min(witnesses, default=(None, None))
  status = "fail" if upper is not None else "pass" if prefix == stop else "indeterminate"
  return {"status": status, "confirmed_from_start_h": float(prefix),
          "first_deficit_by_h": None if upper is None else float(upper),
          "first_deficit_by_inclusive": inclusive,
          "confirmed_deficit_windows_h": [[float(a), float(b)] for a, b in deficit]}
