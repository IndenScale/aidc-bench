import pytest

from texsys.evidence import canonical_digest
from texsys_domain_rc.generator_duty import generator_load_study


def profile(intervals, window):
  ratings = {"kind": "generator-ratings", "schema_version": 1, "catalog_matches_scene": True,
             "scene_digest": "site", "generators": {"A": {}, "B": {}}}
  case = {"source": "project load schedule", "complete": True, "averaging_seconds": window,
          "duration_seconds": 13, "intervals": [{"start_s": start, "end_s": end, "source": "assigned load",
                                                "generator_kw": kw} for start, end, kw in intervals]}
  schedule = {"kind": "generator-load-schedule", "schema_version": 1, "ratings_digest": canonical_digest(ratings),
              "cases": {"peak": case}}
  return generator_load_study(ratings, schedule)["generators"]


def test_maximum_average_can_start_inside_a_segment_and_is_per_generator():
  rows = profile([(0, 5, {"A": 100, "B": 0}), (5, 10, {"A": 200}), (10, 13, {"A": 0, "B": 500})], 8)
  assert rows["A"]["peak"]["peak_window"] == {"average_kw": 162.5, "start_s": 2, "end_s": 10}
  assert rows["A"]["peak"]["complete"]
  assert rows["B"]["peak"]["peak_window"] is None
  assert not rows["B"]["peak"]["complete"]


def test_gap_preserves_known_window_and_does_not_fill_missing_load():
  row = profile([(0, 4, {"A": 190}), (8, 13, {"A": 20})], 4)["A"]["peak"]
  assert row["peak_window"] == {"average_kw": 190, "start_s": 0, "end_s": 4}
  assert not row["complete"]


def test_overlapping_intervals_rejected():
  with pytest.raises(ValueError, match="重叠"):
    profile([(0, 5, {"A": 20}), (4, 13, {"A": 10})], 3)
