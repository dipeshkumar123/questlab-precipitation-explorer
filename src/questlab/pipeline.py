"""Retrieve, normalize, difference, and publish an ECMWF precipitation run."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import cfgrib
import numpy as np
import xarray as xr
from ecmwf.opendata import Client

PIPELINE_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = ROOT / "data"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _run_stamp(run: datetime) -> str:
    return run.strftime("%Y%m%dT%HZ")


def _requested_steps(max_step: int) -> list[int]:
    if max_step < 6 or max_step % 6:
        raise ValueError("--max-step must be a positive multiple of 6, at least 6")
    return list(range(6, max_step + 1, 6))


def _retrieve(
    model: str,
    date: str,
    time_hour: int | None,
    steps: list[int],
    target: Path,
) -> datetime:
    # The library defaults to 500 retries with 120-second backoff. Bound the
    # retry policy so an unavailable source does not leave an ingest stuck for hours.
    client = Client(
        source="ecmwf",
        model=model,
        maximum_retries=3,
        retry_after=3,
        use_server_retry_after=False,
    )
    request: dict[str, Any] = {
        "stream": "oper",
        "type": "fc",
        "param": "tp",
        "step": steps,
        "target": str(target),
    }
    if date != "latest":
        request["date"] = date
        request["time"] = time_hour
    result = client.retrieve(**request)
    if result.datetime is None:
        raise RuntimeError("ECMWF retrieval returned no initialization time")
    run = result.datetime
    return run.replace(tzinfo=timezone.utc) if run.tzinfo is None else run.astimezone(timezone.utc)


def _decode(raw_path: Path, data_dir: Path, expected_steps: list[int]):
    cache_key = raw_path.relative_to(data_dir / "raw").with_suffix("")
    cache_template = data_dir / "cache" / "cfgrib" / cache_key / "{short_hash}.idx"
    cache_template.parent.mkdir(parents=True, exist_ok=True)
    datasets = cfgrib.open_datasets(raw_path, indexpath=str(cache_template))
    try:
        fields: dict[int, np.ndarray] = {}
        latitude = longitude = None
        source_units = None
        for dataset in datasets:
            if "tp" not in dataset:
                continue
            field = dataset["tp"]
            units = field.attrs.get("units", "")
            if source_units is None:
                source_units = units
            elif source_units != units:
                raise ValueError(f"Mixed precipitation units in GRIB: {source_units!r}, {units!r}")
            latitude = np.asarray(dataset.latitude.values, dtype=np.float64)
            longitude = np.asarray(dataset.longitude.values, dtype=np.float64)
            values = np.asarray(field.values, dtype=np.float64)
            if units == "m":
                values *= 1000.0
            elif units not in ("kg m**-2", "kg m-2"):
                raise ValueError(f"Unsupported ECMWF tp units {units!r}; expected metres or kg m-2")
            steps = np.asarray(dataset.step.values)
            if values.shape[0] != len(steps):
                raise ValueError(f"GRIB step dimension mismatch: {values.shape} for {steps}")
            for index, step_value in enumerate(steps):
                hours = int(step_value / np.timedelta64(1, "h"))
                fields[hours] = values[index]
        if latitude is None or longitude is None or source_units is None:
            raise ValueError("GRIB contains no decodable total precipitation field")
        if sorted(fields) != expected_steps:
            raise ValueError(f"Requested steps {expected_steps}; GRIB contains {sorted(fields)}")
        if any(fields[step].shape != (latitude.size, longitude.size) for step in expected_steps):
            raise ValueError("GRIB precipitation field dimensions do not match coordinates")
        if latitude.size < 2 or longitude.size < 2:
            raise ValueError("GRIB grid has fewer than two points on an axis")
        if not (np.all(np.diff(latitude) < 0) and np.all(np.diff(longitude) > 0)):
            raise ValueError("Unexpected coordinate orientation; expected north-to-south latitudes and ascending longitudes")
        if not all(np.isfinite(fields[step]).any() for step in expected_steps):
            raise ValueError("One or more forecast steps contain no finite precipitation values")
        return fields, latitude, longitude, source_units
    finally:
        for dataset in datasets:
            dataset.close()


def _matching_existing(artifact: Path, manifest_path: Path, model: str, run: datetime, steps: list[int]) -> bool:
    if not artifact.exists() or not manifest_path.exists():
        return False
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        manifest.get("processingVersion") == PIPELINE_VERSION
        and manifest.get("model") == model
        and manifest.get("sourceRunUtc") == run.isoformat()
        and manifest.get("stepsHours") == steps
        and manifest.get("artifactSha256") == _sha256(artifact)
    )


def run_pipeline(
    model: str,
    date: str = "latest",
    time_hour: int | None = None,
    max_step: int = 24,
    data_dir: Path = DEFAULT_DATA_DIR,
    force: bool = False,
) -> Path:
    if model not in ("aifs-single", "ifs"):
        raise ValueError("model must be 'aifs-single' or 'ifs'")
    if date == "latest" and time_hour is not None:
        raise ValueError("--time cannot be combined with --date latest")
    if date != "latest":
        datetime.strptime(date, "%Y-%m-%d")
        if time_hour not in (0, 6, 12, 18):
            raise ValueError("explicit --time must be one of 0, 6, 12, 18 UTC")
    steps = _requested_steps(max_step)
    processed_root = data_dir / "processed" / model
    raw_root = data_dir / "raw" / model
    processed_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)

    staged_raw: Path | None = None
    if date != "latest":
        expected_run = datetime.strptime(date, "%Y-%m-%d").replace(hour=int(time_hour), tzinfo=timezone.utc)
        stamp = _run_stamp(expected_run)
        run_dir = processed_root / stamp
        artifact = run_dir / "tp.nc"
        manifest_path = run_dir / "manifest.json"
        raw_path = raw_root / stamp / f"tp-through-{max_step:03d}h.grib2"
        if not force and _matching_existing(artifact, manifest_path, model, expected_run, steps):
            print(f"idempotent hit: {artifact}")
            return artifact
        if not raw_path.exists():
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            handle, temp_name = tempfile.mkstemp(prefix=f"{model}-", suffix=".grib2", dir=raw_root)
            os.close(handle)
            staged_raw = Path(temp_name)
            staged_raw.unlink()
            try:
                run = _retrieve(model, date, time_hour, steps, staged_raw)
            except BaseException:
                staged_raw.unlink(missing_ok=True)
                raise
            if run != expected_run:
                staged_raw.unlink(missing_ok=True)
                raise RuntimeError(f"Requested {expected_run.isoformat()} but ECMWF returned {run.isoformat()}")
            raw_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_raw, raw_path)
            staged_raw = None
        run = expected_run
    else:
        handle, temp_name = tempfile.mkstemp(prefix=f"{model}-latest-", suffix=".grib2", dir=raw_root)
        os.close(handle)
        staged_raw = Path(temp_name)
        staged_raw.unlink()
        try:
            run = _retrieve(model, "latest", None, steps, staged_raw)
        except BaseException:
            staged_raw.unlink(missing_ok=True)
            raise
        stamp = _run_stamp(run)
        run_dir = processed_root / stamp
        artifact = run_dir / "tp.nc"
        manifest_path = run_dir / "manifest.json"
        raw_path = raw_root / stamp / f"tp-through-{max_step:03d}h.grib2"
        if not force and _matching_existing(artifact, manifest_path, model, run, steps):
            staged_raw.unlink(missing_ok=True)
            print(f"idempotent hit after resolving latest run: {artifact}")
            return artifact
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(staged_raw, raw_path)
        staged_raw = None

    retrieved_at = datetime.fromtimestamp(raw_path.stat().st_mtime, tz=timezone.utc)
    fields, latitude, longitude, source_units = _decode(raw_path, data_dir, steps)
    cumulative = np.stack([fields[step] for step in steps], axis=0)
    interval = np.empty_like(cumulative)
    previous = np.zeros_like(cumulative[0])
    for index in range(len(steps)):
        interval[index] = cumulative[index] - previous
        previous = cumulative[index]

    valid_times = np.array([np.datetime64((run + timedelta(hours=step)).replace(tzinfo=None), "ns") for step in steps])
    ds = xr.Dataset(
        data_vars={
            "tp_cumulative_mm": (
                ("step_hours", "latitude", "longitude"),
                cumulative.astype(np.float32),
                {"units": "mm", "long_name": "Cumulative total precipitation from initialization"},
            ),
            "tp_interval_mm": (
                ("step_hours", "latitude", "longitude"),
                interval.astype(np.float32),
                {"units": "mm", "long_name": "Total precipitation during the preceding 6 hours"},
            ),
        },
        coords={
            "step_hours": np.asarray(steps, dtype=np.int16),
            "valid_time_utc": (("step_hours",), valid_times),
            "latitude": latitude.astype(np.float32),
            "longitude": longitude.astype(np.float32),
        },
        attrs={
            "title": "ECMWF total precipitation forecast",
            "source": "ECMWF Open Data",
            "model": model,
            "source_run_utc": run.isoformat(),
            "source_units": source_units,
            "units": "mm water depth",
            "processing_version": PIPELINE_VERSION,
            "latitude_order": "north-to-south",
            "longitude_convention": "[-180, 180)",
        },
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    temp_artifact = run_dir / "tp.nc.tmp"
    encoding = {
        name: {"zlib": True, "complevel": 2, "dtype": "float32", "_FillValue": np.float32(np.nan)}
        for name in ("tp_cumulative_mm", "tp_interval_mm")
    }
    try:
        ds.to_netcdf(temp_artifact, engine="h5netcdf", encoding=encoding)
        ds.close()
        # Verify the exact file to be published, not the in-memory xarray object.
        with xr.open_dataset(temp_artifact, engine="h5netcdf") as check:
            actual_steps = check.step_hours.values.astype(int).tolist()
            if actual_steps != steps:
                raise RuntimeError(f"Serialized steps {actual_steps} differ from requested {steps}")
            intervals = np.asarray(check.tp_interval_mm.values, dtype=np.float64)
            totals = np.asarray(check.tp_cumulative_mm.values, dtype=np.float64)
            reconstructed = intervals.sum(axis=0)
            error = float(np.nanmax(np.abs(reconstructed - totals[-1])))
            if not np.allclose(reconstructed, totals[-1], rtol=1e-6, atol=0.002, equal_nan=True):
                raise RuntimeError(f"Serialized interval mass balance failed; max absolute error={error} mm")
            manifest = {
                "processingVersion": PIPELINE_VERSION,
                "model": model,
                "source": "ECMWF Open Data",
                "sourceRunUtc": run.isoformat(),
                "retrievedAtUtc": retrieved_at.isoformat(),
                "stepsHours": steps,
                "variables": ["tp_cumulative_mm", "tp_interval_mm"],
                "sourceUnits": source_units,
                "outputUnits": "mm",
                "grid": {
                    "shape": [int(latitude.size), int(longitude.size)],
                    "latitudeFirst": float(latitude[0]),
                    "latitudeLast": float(latitude[-1]),
                    "longitudeFirst": float(longitude[0]),
                    "longitudeLast": float(longitude[-1]),
                    "latitudeOrder": "north-to-south",
                    "longitudeConvention": "[-180, 180)",
                },
                "rawSha256": _sha256(raw_path),
                "artifactSha256": None,
                "massBalanceMaxAbsErrorMm": error,
            }
        os.replace(temp_artifact, artifact)
        manifest["artifactSha256"] = _sha256(artifact)
        _atomic_json(manifest_path, manifest)
        latest_pointer = {
            "model": model,
            "sourceRunUtc": run.isoformat(),
            "artifact": str(artifact.relative_to(data_dir)),
            "manifest": str(manifest_path.relative_to(data_dir)),
            "updatedAtUtc": retrieved_at.isoformat(),
        }
        _atomic_json(processed_root / "latest.json", latest_pointer)
    finally:
        ds.close()
        temp_artifact.unlink(missing_ok=True)
        if staged_raw is not None:
            staged_raw.unlink(missing_ok=True)
    print(f"published {artifact}")
    print(f"run={run.isoformat()} steps={steps} outputUnits=mm maxMassBalanceError={error:.8g} mm")
    print(f"manifest={manifest_path}")
    return artifact


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=("aifs-single", "ifs"), required=True)
    parser.add_argument("--date", default="latest", help="latest or YYYY-MM-DD")
    parser.add_argument("--time", type=int, choices=(0, 6, 12, 18), help="initialization hour in UTC for an explicit date")
    parser.add_argument("--max-step", type=int, default=24, help="retrieve every 6-hour step from 6 through this step")
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--force", action="store_true", help="reprocess an existing run from its cached GRIB")
    args = parser.parse_args(argv)
    data_dir = args.data_dir.resolve()
    status_path = data_dir / "processed" / args.model / "ingest-status.json"
    attempted_at = datetime.now(timezone.utc)
    _atomic_json(
        status_path,
        {
            "model": args.model,
            "attemptedAtUtc": attempted_at.isoformat(),
            "lastIngestSucceeded": False,
            "state": "running",
        },
    )
    try:
        artifact = run_pipeline(args.model, args.date, args.time, args.max_step, data_dir, args.force)
    except Exception as exc:
        _atomic_json(
            status_path,
            {
                "model": args.model,
                "attemptedAtUtc": attempted_at.isoformat(),
                "completedAtUtc": datetime.now(timezone.utc).isoformat(),
                "lastIngestSucceeded": False,
                "state": "failed",
                "lastErrorCode": "ingest_failed",
                "lastErrorMessage": "The latest ingest attempt failed; a previously validated forecast, if present, remains available.",
                "errorType": type(exc).__name__,
            },
        )
        print(f"ingest failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    manifest_path = artifact.parent / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    _atomic_json(
        status_path,
        {
            "model": args.model,
            "attemptedAtUtc": attempted_at.isoformat(),
            "completedAtUtc": datetime.now(timezone.utc).isoformat(),
            "lastIngestSucceeded": True,
            "state": "succeeded",
            "sourceRunUtc": manifest["sourceRunUtc"],
            "artifact": str(artifact.relative_to(data_dir)),
        },
    )
    print(f"artifact={artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
