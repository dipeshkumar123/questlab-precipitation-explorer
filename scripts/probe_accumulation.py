"""Compare four successive AIFS and IFS total-precipitation forecasts."""

from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

import cfgrib
import numpy as np
from ecmwf.opendata import Client

ROOT = Path(__file__).resolve().parents[1]
RUN_DATE = "2026-11-18"
RUN_TIME = 18
STEPS = [6, 12, 18, 24]


def retrieve(model: str) -> Path:
    target = ROOT / "data" / "raw" / f"{model}-{RUN_DATE}-t{RUN_TIME:02d}-tp.grib2"
    target.parent.mkdir(parents=True, exist_ok=True)
    client = Client(source="ecmwf", model=model)
    result = client.retrieve(
        date=RUN_DATE,
        time=RUN_TIME,
        stream="oper",
        type="fc",
        param="tp",
        step=STEPS,
        target=str(target),
    )
    print(f"{model} retrieval run datetime: {result.datetime}; file={target}")
    return target


def open_step_fields(path: Path) -> tuple[dict[int, np.ndarray], np.ndarray, np.ndarray, str]:
    datasets = cfgrib.open_datasets(path, indexpath="")
    fields: dict[int, np.ndarray] = {}
    latitude = longitude = None
    for ds in datasets:
        if "tp" not in ds:
            continue
        units = ds.tp.attrs.get("units", "")
        latitude = np.asarray(ds.latitude.values)
        longitude = np.asarray(ds.longitude.values)
        values = np.asarray(ds.tp.values)
        if units == "m":
            values = values * 1000.0
        elif units not in ("kg m**-2", "kg m-2"):
            raise ValueError(f"Cannot convert precipitation units {units!r} in {path}")
        print(f"{path.name}: units={units!r}, GRIB_stepType={ds.tp.attrs.get('GRIB_stepType')}, "
              f"lat first/last={latitude[0]}/{latitude[-1]}, lon first/last={longitude[0]}/{longitude[-1]}")
        step_values = np.asarray(ds.step.values)
        for i, step in enumerate(step_values):
            fields[int(step / np.timedelta64(1, "h"))] = np.asarray(values[i], dtype=np.float64)
        ds.close()
    if latitude is None or longitude is None:
        raise RuntimeError(f"No tp field found in {path}")
    if set(fields) != set(STEPS):
        raise RuntimeError(f"Expected steps {STEPS}, decoded {sorted(fields)} in {path}")
    return fields, latitude, longitude, units


def summarize(model: str, fields: dict[int, np.ndarray], latitude: np.ndarray, longitude: np.ndarray, units: str) -> dict:
    report = {"model": model, "source_units": units, "reported_units": "mm", "steps": {}, "pairwise_monotonicity": {}}
    for step in STEPS:
        arr = fields[step]
        valid = np.isfinite(arr)
        valid_values = arr[valid]
        max_flat = int(np.nanargmax(arr))
        iy, ix = np.unravel_index(max_flat, arr.shape)
        report["steps"][str(step)] = {
            "min": float(np.nanmin(arr)),
            "max": float(arr[iy, ix]),
            "mean": float(np.nanmean(arr)),
            "fraction_above_0_1_mm": float(np.count_nonzero(valid & (arr > 0.1)) / np.count_nonzero(valid)),
            "max_latitude": float(latitude[iy]),
            "max_longitude": float(longitude[ix]),
            "points_above_50_mm": int(np.count_nonzero(valid & (arr > 50.0))),
            "valid_points": int(valid_values.size),
        }
    for previous, current in zip(STEPS, STEPS[1:]):
        a, b = fields[previous], fields[current]
        valid = np.isfinite(a) & np.isfinite(b)
        delta = b - a
        report["pairwise_monotonicity"][f"{previous}->{current}"] = {
            "fraction_non_decreasing": float(np.count_nonzero(valid & (delta >= -1e-6)) / np.count_nonzero(valid)),
            "negative_points": int(np.count_nonzero(valid & (delta < -1e-6))),
            "most_negative_delta_mm": float(np.nanmin(np.where(valid, delta, np.nan))),
            "negative_points_below_minus_0_01_mm": int(np.count_nonzero(valid & (delta < -0.01))),
            "fraction_non_decreasing_with_0_01_mm_tolerance": float(
                np.count_nonzero(valid & (delta >= -0.01)) / np.count_nonzero(valid)
            ),
        }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reuse-existing", action="store_true", help="decode the already retrieved fixed-run GRIB files")
    args = parser.parse_args()
    all_reports = []
    for model in ("aifs-single", "ifs"):
        path = ROOT / "data" / "raw" / f"{model}-{RUN_DATE}-t{RUN_TIME:02d}-tp.grib2"
        if not args.reuse_existing or not path.exists():
            path = retrieve(model)
        fields, lat, lon, units = open_step_fields(path)
        report = summarize(model, fields, lat, lon, units)
        all_reports.append(report)
        print(json.dumps(report, indent=2))
    out = ROOT / "data" / "raw" / f"accumulation-report-{RUN_DATE}-t{RUN_TIME:02d}.json"
    out.write_text(json.dumps({"retrieved_at": datetime.now(timezone.utc).isoformat(), "runs": all_reports}, indent=2))
    print(f"saved report: {out}")


if __name__ == "__main__":
    main()
