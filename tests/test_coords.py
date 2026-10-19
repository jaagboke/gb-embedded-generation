import pytest

from gbeg.transform.coords import (
    InvalidLocationError,
    from_en,
    from_grid_ref,
    from_latlon,
    grid_ref_to_en,
)


@pytest.mark.parametrize(
    ("grid_ref", "expected"),
    [
        ("SJ 838 980", (383_800, 398_000)),      # Manchester city centre
        ("SJ8380098000", (383_800, 398_000)),    # same, 10-digit no spaces
        ("sh 609 543", (260_900, 354_300)),      # Snowdon summit, lower case
        ("TQ 30 80", (530_000, 180_000)),        # central London, 4-digit
        ("NT 25 73", (325_000, 673_000)),        # Edinburgh
        ("SV 0 0", (0, 0)),                      # grid origin square
    ],
)
def test_grid_ref_to_en(grid_ref, expected):
    assert grid_ref_to_en(grid_ref) == expected


@pytest.mark.parametrize("bad", ["", "SJ", "SJ 838 98", "IJ 100 100", "12345 67890", "SJ 83A 980"])
def test_grid_ref_rejects_malformed(bad):
    with pytest.raises(InvalidLocationError):
        grid_ref_to_en(bad)


def test_grid_ref_to_wgs84_manchester():
    loc = from_grid_ref("SJ 838 980")
    assert loc.latitude == pytest.approx(53.48, abs=0.01)
    assert loc.longitude == pytest.approx(-2.245, abs=0.01)


def test_latlon_round_trip():
    loc = from_latlon(53.0685, -4.0763)  # Snowdon summit
    back = from_en(loc.easting, loc.northing)
    assert back.latitude == pytest.approx(53.0685, abs=1e-4)
    assert back.longitude == pytest.approx(-4.0763, abs=1e-4)
    assert loc.easting == pytest.approx(260_900, abs=150)


@pytest.mark.parametrize(("lat", "lon"), [(0, 0), (40.4, -3.7), (53.0, 10.0)])
def test_latlon_outside_gb_rejected(lat, lon):
    with pytest.raises(InvalidLocationError):
        from_latlon(lat, lon)


def test_en_outside_grid_rejected():
    with pytest.raises(InvalidLocationError):
        from_en(-10, 100)
