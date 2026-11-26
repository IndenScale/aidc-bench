import pytest
from texsys.evidence import canonical_digest

from texsys_domain_rc.zonal_airflow import airflow_study, shared_vertical_face


def inputs():
  zones = {"a": {"neighbors": {"b": {}}}, "b": {"neighbors": {"a": {}}}}
  header = {"schema_version": 1, "baseline": "1", "frame": "site"}
  geom = {**header, "kind": "airflow-boundaries", "complete": True, "unresolved": [], "zones": zones, "scene_digest": "source",
          "openings": {k: {"ends": pair} for k, pair in (("ab", ["a", "b"]), ("ao", ["a", "outdoors"]), ("bo", ["b", "outdoors"]))}}
  case = {"complete": True, "source": "reference network", "reference_pa": {"outdoors": 0},
          "rooms": {"a": {"source": "fan A", "flows_m3_h": {"supply": 18, "return": 0, "exhaust": 0}, "target_outdoor_pa": 12},
                    "b": {"source": "fan B", "flows_m3_h": {"supply": 0, "return": 1, "exhaust": 0}}},
          "openings": {k: {"source": "test curve", "state": "normal", "coefficient_m3_h_pa_n": c, "exponent": 1}
                       for k, c in (("ab", 2), ("ao", 1), ("bo", 1))}}
  return geom, {**header, "kind": "airflow-cases", "cases": {"normal": case}}


def test_two_unknown_zone_pressures_and_target_resolve():
  geometry, schedule = inputs()
  study = airflow_study(geometry, schedule)
  assert study["schedule_digest"] == canonical_digest(schedule)
  solved = study["cases"]["normal"]
  # 3a - 2b = 18 and -2a + 3b = -1; at a=12 the second room must rebalance.
  assert solved["pressure_pa"] == pytest.approx({"a": 10.4, "b": 6.6, "outdoors": 0}, abs=1e-6)
  assert solved["rooms"]["a"]["required_net_mechanical_m3_h"] == pytest.approx(12 + 2*(12-23/3), abs=1e-6)
  a, b = (solved["rooms"][k] for k in ("a", "b"))
  assert a["target_path_flows_out_m3_h"] == pytest.approx({"ao": 12, "ab": 2*(12-23/3)}, abs=1e-6)
  assert sum(a["target_path_flows_out_m3_h"].values()) == pytest.approx(a["required_net_mechanical_m3_h"])
  assert a["references"]["b"]["leakage_out_m3_h"] == -b["references"]["a"]["leakage_out_m3_h"]
  assert all(abs(room["flow_balance_residual_m3_h"]) <= 1e-6 for room in (a, b))


def test_pressure_unanchored_is_distinct_from_a_closed_opening():
  geometry, schedule = inputs()
  case = schedule["cases"]["normal"]
  for key in ("ao", "bo"):
    case["openings"][key]["coefficient_m3_h_pa_n"] = 0
  result = airflow_study(geometry, schedule)
  assert not result["complete"] and "定压边界" in result["cases"]["normal"]["unresolved"][0]


def test_parallel_power_law_paths_keep_their_own_exponents():
  geometry, schedule = inputs()
  case = schedule["cases"]["normal"]
  case["reference_pa"]["b"] = 0
  del case["rooms"]["b"]
  case["openings"]["ab"].update(coefficient_m3_h_pa_n=2, exponent=.5)
  case["rooms"]["a"]["flows_m3_h"]["supply"] = 15  # p + 2*sqrt(p) = 15
  result = airflow_study(geometry, schedule)["cases"]["normal"]
  assert result["pressure_pa"]["a"] == pytest.approx(9)
  assert result["path_flows_m3_h"]["ab"] == pytest.approx(6)


def test_face_contact_excludes_edges_and_corners():
  box = ((0, 0, 0), (1, 1, 1))
  assert shared_vertical_face(box, ((1, 1, 0), (2, 2, 1))) is None
  assert shared_vertical_face(box, ((1, 0, 0), (2, 1, 1)))["area_m2"] == 1
