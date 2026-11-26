"""Evaluate named facts against ordered, declarative acceptance conditions."""

import math


class MissingFact(KeyError):
  pass


def _operand(binding, facts, parameters):
  if type(binding) in (float, int, bool):
    return binding
  scope, field = binding.split(".", 1)
  if scope == "fact":
    if field not in facts or facts[field] is None:
      raise MissingFact(field)
    return facts[field]
  if scope == "parameter":
    return parameters[field]
  raise ValueError(f"Unknown RC binding {binding}.")


def _matches(condition, facts, parameters):
  left = _operand(condition["left"], facts, parameters)
  right = _operand(condition["right"], facts, parameters)
  relation = condition["relation"]
  if relation == "one_of":
    if not isinstance(right, list) or not right:
      raise ValueError("RC one_of requires a nonempty list of alternatives.")
    return any(type(left) is type(item) and left == item for item in right)
  if relation == "equals":
    return type(left) is type(right) and left == right
  tolerance = condition.get("tolerance", 0)
  if isinstance(tolerance, str):
    tolerance = _operand(tolerance, facts, parameters)
  if relation == "between":
    if not isinstance(right, list) or len(right) != 2:
      raise ValueError("RC between requires a two-value closed interval.")
    low, high = right
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in (left, low, high, tolerance)) or low > high or tolerance < 0:
      raise ValueError("Invalid RC interval, tolerance or measured quantity.")
    return low - tolerance <= left <= high + tolerance
  if any(type(v) not in (float, int) or not math.isfinite(v) for v in (left, right, tolerance)) or tolerance < 0:
    raise ValueError("Numeric RC conditions require finite quantities and nonnegative tolerance.")
  if relation == "above":
    return left > right + tolerance
  if relation == "below":
    return left < right - tolerance
  if relation == "minimum":
    return left >= right or math.isclose(left, right, abs_tol=tolerance, rel_tol=0)
  if relation == "maximum":
    return left <= right or math.isclose(left, right, abs_tol=tolerance, rel_tol=0)
  if relation == "within":
    return math.isclose(left, right, abs_tol=tolerance, rel_tol=0)
  raise ValueError(f"Unknown RC comparison {relation}.")


def qualifies(rule, facts):
  """Evidence must match all configured measurement conditions before its value is used."""
  try:
    return all(_matches(condition, facts, rule) for condition in rule["rc"].get("qualifiers", []))
  except MissingFact:
    return False


def _condition_status(condition, facts, rule):
  on_violation = condition.get("on_violation", "fail")
  if on_violation not in ("fail", "indeterminate"):
    raise ValueError("Invalid RC violation status.")
  try:
    return "pass" if _matches(condition, facts, rule) else on_violation
  except MissingFact:
    return "indeterminate"


def _status(statuses):
  pending = False
  for status in statuses:
    if status == "fail":
      return "fail"
    pending |= status == "indeterminate"
  return "indeterminate" if pending else "pass"


def assess(rule, facts):
  """Each condition must hold. A known violation takes precedence over missing evidence."""
  conditions = rule["rc"]["conditions"]
  if not conditions:
    raise ValueError("RC requires at least one acceptance condition.")
  if not qualifies(rule, facts):
    return "indeterminate"
  return _status(_condition_status(condition, facts, rule) for condition in conditions)


def assess_ranges(rule, readings, bounds):
  """Apply configured limits and report a separate verdict per observed metric."""
  facts = dict(readings)
  for metric, (lower, upper) in bounds.items():
    facts["lower_" + metric] = lower
    facts["upper_" + metric] = upper
  verdicts = {}
  conditions = rule["rc"]["conditions"]
  if not conditions:
    raise ValueError("RC requires at least one range condition.")
  qualified = qualifies(rule, facts)
  for condition in conditions:
    scope, metric = condition["left"].split(".", 1)
    if scope != "fact" or metric not in bounds:
      raise ValueError("A range check must name an observed metric with a declared range.")
    status = _condition_status(condition, facts, rule) if qualified else "indeterminate"
    verdicts[metric] = _status((verdicts.get(metric, "pass"), status))
  if verdicts.keys() != bounds.keys():
    raise ValueError("Each declared range requires a configured check.")
  return _status(verdicts.values()), verdicts
