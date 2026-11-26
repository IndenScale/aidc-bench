"""Steady outdoor air and summer ventilation calculations."""


import math


def minimum_outdoor_air(occupants, per_person_m3_h, pressure_flow_m3_h):
  """Return the occupant demand and the exact minimum when both demands are known."""
  people_flow = None if occupants is None else occupants * per_person_m3_h
  minimum = None if people_flow is None or pressure_flow_m3_h is None else max(people_flow, pressure_flow_m3_h)
  return people_flow, minimum


def summer_air_exchange(flow_m3_h, density_kg_m3, inside, outside):
  """Multiply dry-air mass flow by a positive outdoor-to-indoor property difference."""
  return density_kg_m3 * flow_m3_h * max(0, outside - inside)


def boundary_leakage(pressure, boundaries):
  result = {}
  for key, item in boundaries.items():
    delta = pressure - item["pressure_pa"]
    magnitude = item["coefficient_m3_h_pa_n"] * abs(delta) ** item["exponent"]
    result[key] = math.copysign(magnitude, delta)
  return result


def room_pressure(net, boundaries):
  active = [item for item in boundaries.values() if item["coefficient_m3_h_pa_n"] > 0]
  span = min((abs(net) / item["coefficient_m3_h_pa_n"]) ** (1 / item["exponent"]) for item in active)
  lo = min(item["pressure_pa"] for item in active) - span - 1
  hi = max(item["pressure_pa"] for item in active) + span + 1
  if not math.isfinite(lo) or not math.isfinite(hi) or not math.isfinite(hi - lo):
    raise ValueError("风量或压力超出数值求解范围")
  for _ in range(100):
    mid = lo + (hi - lo) / 2
    if math.fsum(boundary_leakage(mid, boundaries).values()) < net:
      lo = mid
    else:
      hi = mid
  pressure = lo + (hi - lo) / 2
  leakage = boundary_leakage(pressure, boundaries)
  residual = math.fsum(leakage.values()) - net
  if abs(residual) > max(1e-6, abs(net) * 1e-9):
    raise ValueError("压力求解的风量残差超限")
  return pressure, leakage, residual


def parallel_capacities(ratings, basic_units, outage_units):
  """Independent, simultaneously available units, all rated at the same boundary and in the same units."""
  if type(basic_units) is not int or basic_units < 1 or type(outage_units) is not int or not 0 <= outage_units <= basic_units:
    raise ValueError("Invalid design or outage unit count.")
  if any(type(v) not in (float, int) or not math.isfinite(v) or v <= 0 for v in ratings.values()):
    raise ValueError("Parallel ratings must be finite positive quantities.")
  capacities = sorted(((v, k) for k, v in ratings.items()), reverse=True)
  return {"count": len(ratings), "normal": math.fsum(ratings.values()), "basic": math.fsum(v for v, _ in capacities[:basic_units]),
          "remaining": math.fsum(v for v, _ in capacities[outage_units:]), "unavailable": [k for _, k in capacities[:outage_units]]}
