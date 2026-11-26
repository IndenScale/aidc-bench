from texsys.evidence import canonical_digest

from texsys_domain_rc.air_observations import pressure_run, room_pressure_interval


def test_run_identity_includes_selected_time_and_scene():
  run = {"run_id": "doors-closed", "steady_state": True, "observed_at": "2026-10-15T09:30:00+08:00",
         "source": "balancing log", "rooms": {}}
  survey = {"schema_version": 1, "kind": "room-pressure-observations", "domain": "hvac",
            "frame": "grid", "scene_digest": "room-layout", "baseline": "issued", "cases": {"normal": run}}
  selection = {"frame": "grid", "scene_digest": "room-layout", "baseline": "issued", "case": "normal"}
  digest = canonical_digest(run)
  assert pressure_run(survey, digest, **selection) == (run, None)
  assert pressure_run(survey, digest, **{**selection, "case": "backup"})[1]
  assert pressure_run(survey, digest, **{**selection, "scene_digest": "revised"})[1]
  run["observed_at"] = "2026-10-15T09:30:00"
  assert pressure_run(survey, digest, **selection)[1]
  assert pressure_run(survey, canonical_digest(run), **selection)[1]


def test_room_minus_reference_with_negative_meter_reading():
  point = {"high": "corridor", "low": "hall", "value": -5.5, "uncertainty": 0.5, "unit": "Pa", "meter": "P1",
           "source": "record 15", "calibration_source": "certificate 2"}
  run = {"run_id": "full-load", "rooms": {"hall": {"corridor": point}}}
  row = room_pressure_interval(run, "hall", "corridor")
  assert row["raw_value_pa"] == -5.5 and row["interval_pa"] == [5, 6]
  assert "unresolved" in room_pressure_interval(run, "hall", "outdoors")
  point["low"] = "corridor"
  assert "unresolved" in room_pressure_interval(run, "hall", "corridor")
