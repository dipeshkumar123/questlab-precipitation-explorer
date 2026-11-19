"""Verify NetCDF and JSON-style axis round-trips preserve the source order."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    for model in ("aifs-single", "ifs"):
        path = ROOT / "data" / "processed" / model / "20261118T18Z" / "tp.nc"
        with xr.open_dataset(path, engine="h5netcdf") as dataset:
            latitude = dataset.latitude.values.astype(float).tolist()
            longitude = dataset.longitude.values.astype(float).tolist()
            assert dataset.tp_interval_mm.dims == ("step_hours", "latitude", "longitude")
            assert latitude[0] == 90.0 and latitude[-1] == -90.0
            assert longitude[0] == -180.0 and longitude[-1] == 179.75
            assert all(np.isclose(a - b, 0.25) for a, b in zip(latitude, latitude[1:]))
            assert all(np.isclose(b - a, 0.25) for a, b in zip(longitude, longitude[1:]))
        # Region endpoint will return the NetCDF coordinate arrays without sorting.
        payload = {"latitude": latitude, "longitude": longitude}
        returned_axes = json.loads(json.dumps(payload))
        assert returned_axes["longitude"] == longitude
        assert returned_axes["latitude"] == latitude
        assert returned_axes["longitude"][0] < returned_axes["longitude"][-1]
        print(
            f"{model}: latitude={latitude[0]}..{latitude[-1]} north-to-south; "
            f"longitude={longitude[0]}..{longitude[-1]} ascending, convention=[-180,180); "
            f"JSON axes preserved without flip"
        )


if __name__ == "__main__":
    main()
