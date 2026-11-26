"""Bound a continuous service interruption using intervals with a common time unit."""


def continuous_service_bounds(window, segments, edge_error):
  """True means service, False means interruption, None is an unknown interval."""
  start, stop = window
  runs = []
  for begin, end, state in segments:
    if begin >= end or (runs and begin < runs[-1][1]):
      raise ValueError("Expected ordered, non-overlapping service intervals.")
    if runs and begin == runs[-1][1] and state is runs[-1][2]:
      runs[-1][1] = end
    else:
      runs.append([begin, end, state])
  supplied, interrupted = [], []
  for begin, end, state in runs:
    lo, hi = max(start, begin + edge_error), min(stop, end - edge_error)
    if state is not None and lo < hi:
      (supplied if state else interrupted).append([lo, hi])
  lower = max((hi - lo for lo, hi in interrupted), default=0)
  bracketed = bool(supplied and supplied[0][0] == start and supplied[-1][1] == stop)
  upper = max((right[0] - left[1] for left, right in zip(supplied, supplied[1:])), default=0) if bracketed else None
  return lower, upper, supplied, interrupted, bracketed
