from texsys_domain_rc.ups_discharge import runtime_at_load


def curve(basis="cutoff-runtime", monotonic="validated curve"):
  return {"curve": "X", "conditions": {}, "runtime_basis": basis, "monotonic_source": monotonic,
          "product_source": "type test", "installation_source": "bank schedule",
          "ac_output_points": [{"kw": 40, "minutes": 20}, {"kw": 80, "minutes": 8}]}


def test_intermediate_load_has_two_witnesses_and_no_assumed_interpolation():
  row = runtime_at_load(curve(), 60)
  assert row["upper_minutes"] == 20 and row["lower_minutes"] == 8 and row["observed_minutes"] is None
  assert [p["kw"] for p in row["reference_points"]] == [40, 80]


def test_guaranteed_runtime_proves_a_floor_only():
  for load in (60, 80):
    row = runtime_at_load(curve("guaranteed-minimum"), load)
    assert row["lower_minutes"] == 8 and row["upper_minutes"] is None and row["observed_minutes"] is None


def test_exact_only_curve_and_loads_outside_the_qualified_range():
  exact = curve(monotonic=None)
  assert runtime_at_load(exact, 80)["observed_minutes"] == 8
  for candidate, load in ((exact, 60), (curve(), 30), (curve(), 90)):
    row = runtime_at_load(candidate, load)
    assert row["lower_minutes"] is None and row["upper_minutes"] is None
