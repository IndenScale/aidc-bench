"""Check conjugate air-film and prescribed-interface boundaries against a series resistance."""

import pytest
from texsys_domain_rc.planar_surface import _surface


def calculate(boundary, conductivity=0.25):
  section = {"one_dimensional_basis": "Uniform section", "layers": [
    {"material": "board", "source": "datasheet", "thickness_m": .05, "conductivity_w_mk": conductivity}]}
  return _surface("/Wall", section, {"source": "design", "air_c": 25, "dew_point_c": 15},
                  {"source": "design", "inside_film_m2k_w": .1, **boundary})


def test_temperature_at_prescribed_interface_matches_outer_film_heat_balance():
  air = calculate({"opposite_air_c": 5, "opposite_film_m2k_w": .1})
  interface = calculate({"opposite_surface_c": 10})
  assert air["surface_c"] == interface["surface_c"] == pytest.approx(20)
  for row in (air, interface):
    assert row["outward_flux_w_m2"] == pytest.approx(50)
    assert (row["surface_c"] - 10) / row["layers"][0]["resistance_m2k_w"] == pytest.approx(50)
  assert calculate({"opposite_surface_c": 25})["outward_flux_w_m2"] == 0


def test_excludes_duplicated_boundary_and_nonphysical_material_data():
  with pytest.raises(ValueError, match="Choose opposite"):
    calculate({"opposite_air_c": 5, "opposite_surface_c": 10, "opposite_film_m2k_w": .1})
  with pytest.raises(ValueError, match="conductivity"):
    calculate({"opposite_surface_c": 10}, conductivity=0)
