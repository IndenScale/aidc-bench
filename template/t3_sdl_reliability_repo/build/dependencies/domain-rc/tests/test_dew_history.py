import pytest
from texsys_domain_rc.dew_history import _pair, reading_bounds, temperature_margin_bounds


def channel(quantity, rows, clock_error=0):
  return {"quantity": quantity, "source": "readings", "calibration": "instruments", "interval_basis": "continuous envelopes",
          "time_error_s": clock_error, "intervals": [{"time_s": [a, b], "value_c": v, "error_c": e} for a, b, v, e in rows]}


def test_unaligned_intervals_clip_to_the_required_window_and_conserve_time():
  run = {"channels": {"S": channel("surface-temperature", [(-1, 3, 10, .1), (3, 8, 20, .2)]),
                      "D": channel("air-dew-point", [(-5, 1, 9, .2), (1, 5, 11, .1), (6, 10, 19, .1)])}}
  result = _pair({"surface_point": "S", "dew_point": "D"}, run, 0, 9)
  assert [s["time_s"] for s in result["spans"]] == [[0, 1], [1, 3], [3, 5], [6, 8]]
  assert [s["margin_bounds_c"] for s in result["spans"]] == [[.7, 1.3], [-1.2, -.8], [8.7, 9.3], [.7, 1.3]]
  assert result["gaps_s"] == [[5, 6], [8, 9]]


def test_decimal_equality_at_zero_and_rejected_inverted_measurement_errors():
  assert temperature_margin_bounds(reading_bounds(19, .1), reading_bounds(19.2, .1)) == [-.4, 0]
  with pytest.raises(ValueError, match="uncertainty"):
    reading_bounds(12, -.1)
