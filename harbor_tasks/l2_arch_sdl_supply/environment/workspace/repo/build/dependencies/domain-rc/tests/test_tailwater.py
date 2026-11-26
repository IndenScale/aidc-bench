from copy import deepcopy

import pytest

from texsys_domain_rc.hydraulic import replay_storage
from texsys_domain_rc.tailwater import extract_drainage_paths, tailwater_study


def sources():
  header = {"schema_version": 1, "frame": "z-up", "scene_digest": "edition-1"}
  installed = {"pipe": "P", "scene_prim": "/P/V", "ports_xyz_m": [[2, 0, 1], [3, 0, 1]],
               "device_type": "backwater-valve", "inlet_station_m": 2, "outlet_station_m": 3}
  paths = {**header, "kind": "drainage-paths", "station_tolerance_m": .000001, "complete": True,
           "valves": {"V": installed}, "outfalls": ["P"], "drains": {
             key: {"room": key, "drain_elevation_m": 2.0, "segments": [{"pipe": "P", "scene_prim": "/P", "start_station_m": start}]}
             for key, start in (("upstream", 1), ("downstream", 4))}}
  cases = {**header, "kind": "tailwater-cases", "source": "storm survey", "valves": {"V": {"maximum_static_head_m": 1.5, "source": "spec"}},
           "cases": {"storm": {"available_valves": ["V"], "outfalls": {"P": {"tailwater_elevation_m": 2.2}}}}}
  return paths, cases


def test_head_is_local_to_the_traversed_pipe_interval():
  paths, schedule = sources()
  study = tailwater_study(paths, schedule)
  rows = study["cases"]["storm"]
  assert study["complete"] and rows["downstream"]["valves"] == []
  assert rows["upstream"]["observed_freeboard_m"] == pytest.approx(-.2)
  valve, = rows["upstream"]["valves"]
  assert valve["rating_margin_m"] == pytest.approx(.3) and valve["aligned_with_discharge"]
  del schedule["valves"]["V"]
  changed = tailwater_study(paths, schedule)
  assert not changed["complete"] and changed["cases"]["storm"]["upstream"]["valves"][0]["rating_margin_m"] is None
  assert changed["cases"]["storm"]["downstream"] == rows["downstream"]


def test_unresolved_attachment_and_incompatible_elevations():
  paths, schedule = sources()
  unknown = deepcopy(paths["valves"]["V"])
  unknown["pipe"] = None
  paths["valves"]["unlocated"] = unknown
  assert tailwater_study(paths, schedule)["unresolved"] == [{"reason": "unknown-installed-pipe", "valve": "unlocated"}]
  result = tailwater_study(paths, {**schedule, "frame": "other-datum"})
  assert not result["cases"] and result["unresolved"][0]["reason"] == "incompatible-installation-or-frame"


def test_volume_replay_crosses_full_and_empty_bounds():
  result = replay_storage(.5, .1, [(4, .2, 0), (2, 0, .5)])
  assert result["first_overflow_s"] == pytest.approx(2)
  assert result["overflow_m3"] == pytest.approx(.4) and result["final_storage_m3"] == 0
  assert result["intervals"][1]["discharged_m3"] == .5
  assert abs(result["mass_balance_residual_m3"]) < 1e-12


def test_partial_pipe_and_ambiguous_junction():
  layout = {"schema_version": 1, "kind": "drainage-layout", "frame": "z-up", "scene_digest": "edition-1",
            "station_tolerance_m": .000001, "outfalls": ["H"], "complete": True, "valves": {},
            "pipes": {"B": {"scene_prim": "/B", "centerline_xyz_m": [[2, 1, 2], [2, 0, 1]]},
                      "H": {"scene_prim": "/H", "centerline_xyz_m": [[0, 0, 1], [2, 0, 1], [4, 0, 1]]}},
            "drains": {"D": {"room": "R", "position_xyz_m": [2, 1, 2], "outlet_path": ["B", "H"]}}}
  installed = extract_drainage_paths(layout)
  assert not installed["unresolved"] and installed["drains"]["D"]["segments"][1]["start_station_m"] == 2
  layout["pipes"]["H"]["centerline_xyz_m"].append([1, 0, 1])
  installed = extract_drainage_paths(layout)
  assert installed["drains"]["D"]["segments"] == [] and installed["unresolved"][0]["candidate_path"] == ["B", "H"]


def test_uncertain_valve_attachment_remains_visible_to_the_consumer():
  paths, schedule = sources()
  valve = paths["valves"]["V"]
  valve.update(inlet_candidates_m=[2, 6], inlet_station_m=None)
  study = tailwater_study(paths, schedule)
  assert study["unresolved"][0]["reason"] == "ambiguous-valve-station"
  assert study["cases"]["storm"]["upstream"]["valves"][0]["aligned_with_discharge"] is None
