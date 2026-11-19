"""Read-only API over the validated Stage 1 NetCDF forecast artifacts."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import uvicorn
import xarray as xr
from fastapi import FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

LOGGER = logging.getLogger("questlab.api")
ROOT = Path(__file__).resolve().parents[2]
MODELS = ("aifs-single", "ifs")
FRESHNESS_SECONDS = 12 * 60 * 60
MAX_REGION_CELLS = 10_000
MAX_RESPONSE_BYTES = 1_048_576
MAX_POINT_STEPS = 64


def _parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Forecast:
    model: str
    source_run: datetime
    retrieved_at: datetime
    processing_version: str
    steps: np.ndarray
    latitude: np.ndarray
    longitude: np.ndarray
    cumulative_mm: np.ndarray
    interval_mm: np.ndarray
    last_ingest_succeeded: bool
    last_ingest_attempted_at: datetime | None
    last_error: dict[str, str] | None

    def age_seconds(self, now: datetime) -> int:
        return max(0, int((now - self.source_run).total_seconds()))

    def stale(self, now: datetime) -> bool:
        return self.age_seconds(now) > FRESHNESS_SECONDS

    def step_index(self, step_hours: int) -> int | None:
        found = np.flatnonzero(self.steps == step_hours)
        return int(found[0]) if found.size else None


class ForecastStore:
    """Load and validate only latest pointers; arrays are immutable in-memory snapshots."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir.resolve()
        self.forecasts: dict[str, Forecast] = {}
        self.model_states: dict[str, dict[str, Any]] = {}
        for model in MODELS:
            self._load_model(model)

    def _load_model(self, model: str) -> None:
        pointer_path = self.data_dir / "processed" / model / "latest.json"
        if not pointer_path.is_file():
            self.model_states[model] = {"available": False, "lastIngestSucceeded": False, "errorCode": "latest_manifest_missing"}
            return
        try:
            pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
            if pointer.get("model") != model:
                raise ValueError("latest pointer model does not match its directory")
            artifact_path = (self.data_dir / pointer["artifact"]).resolve()
            manifest_path = (self.data_dir / pointer["manifest"]).resolve()
            if not artifact_path.is_relative_to(self.data_dir) or not manifest_path.is_relative_to(self.data_dir):
                raise ValueError("latest pointer escapes the configured data directory")
            if not artifact_path.is_file() or not manifest_path.is_file():
                raise FileNotFoundError("latest pointer references a missing artifact or manifest")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if manifest.get("model") != model:
                raise ValueError("manifest model does not match the latest pointer")
            if manifest.get("artifactSha256") != _sha256(artifact_path):
                raise ValueError("processed NetCDF checksum does not match the manifest")
            source_run = _parse_utc(manifest["sourceRunUtc"])
            retrieved_at = _parse_utc(manifest["retrievedAtUtc"])
            ingest_status_path = pointer_path.parent / "ingest-status.json"
            last_ingest_succeeded = True  # Legacy validated artifacts predate this status file.
            last_ingest_attempted_at = None
            last_error = None
            if ingest_status_path.is_file():
                try:
                    ingest_status = json.loads(ingest_status_path.read_text(encoding="utf-8"))
                    last_ingest_succeeded = ingest_status.get("lastIngestSucceeded") is True
                    attempted = ingest_status.get("attemptedAtUtc")
                    if attempted:
                        last_ingest_attempted_at = _parse_utc(attempted)
                    if not last_ingest_succeeded:
                        last_error = {"code": "ingest_failed", "message": "Latest ingest attempt failed; serving previous verified forecast."}
                except Exception:
                    last_ingest_succeeded = False
                    last_error = {"code": "ingest_status_invalid", "message": "Latest ingest status is unreadable; serving previous verified forecast."}
            expected_steps = [int(step) for step in manifest["stepsHours"]]
            with xr.open_dataset(artifact_path, engine="h5netcdf") as dataset:
                required_vars = ("tp_cumulative_mm", "tp_interval_mm")
                if any(name not in dataset for name in required_vars):
                    raise ValueError("NetCDF is missing a required precipitation variable")
                if dataset.tp_cumulative_mm.attrs.get("units") != "mm" or dataset.tp_interval_mm.attrs.get("units") != "mm":
                    raise ValueError("NetCDF precipitation variables do not declare mm units")
                steps = dataset.step_hours.values.astype(np.int16, copy=True)
                latitude = dataset.latitude.values.astype(np.float64, copy=True)
                longitude = dataset.longitude.values.astype(np.float64, copy=True)
                cumulative = dataset.tp_cumulative_mm.values.astype(np.float32, copy=True)
                interval = dataset.tp_interval_mm.values.astype(np.float32, copy=True)
            if steps.astype(int).tolist() != expected_steps:
                raise ValueError("manifest and NetCDF step axes do not match")
            if cumulative.shape != interval.shape or cumulative.shape != (len(steps), len(latitude), len(longitude)):
                raise ValueError("NetCDF forecast variable dimensions do not match coordinate axes")
            if latitude.size != 721 or longitude.size != 1440:
                raise ValueError("unexpected source grid shape")
            if not np.all(np.diff(latitude) < 0) or latitude[0] != 90.0 or latitude[-1] != -90.0:
                raise ValueError("NetCDF latitude axis is not north-to-south")
            if not np.all(np.diff(longitude) > 0) or longitude[0] != -180.0 or longitude[-1] != 179.75:
                raise ValueError("NetCDF longitude axis is not [-180,180) ascending")
            for array in (steps, latitude, longitude, cumulative, interval):
                array.setflags(write=False)
            self.forecasts[model] = Forecast(
                model=model,
                source_run=source_run,
                retrieved_at=retrieved_at,
                processing_version=str(manifest["processingVersion"]),
                steps=steps,
                latitude=latitude,
                longitude=longitude,
                cumulative_mm=cumulative,
                interval_mm=interval,
                last_ingest_succeeded=last_ingest_succeeded,
                last_ingest_attempted_at=last_ingest_attempted_at,
                last_error=last_error,
            )
            self.model_states[model] = {"available": True, "lastIngestSucceeded": last_ingest_succeeded}
        except Exception as exc:
            LOGGER.error("Could not load latest %s forecast (%s): %s", model, type(exc).__name__, exc)
            self.model_states[model] = {"available": False, "lastIngestSucceeded": False, "errorCode": "artifact_invalid"}


def _api_error(status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
    raise StarletteHTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, "details": details or {}},
    )


def _bounded_response(payload: dict[str, Any], status_code: int = 200) -> Response:
    response = JSONResponse(content=payload, status_code=status_code)
    if len(response.body) > MAX_RESPONSE_BYTES:
        return JSONResponse(
            status_code=413,
            content={"error": {"code": "response_too_large", "message": "JSON response exceeds 1 MiB", "details": {"maxBytes": MAX_RESPONSE_BYTES}}},
        )
    return response


def _freshness(forecast: Forecast, now: datetime) -> dict[str, Any]:
    return {
        "sourceRunUtc": _iso_utc(forecast.source_run),
        "retrievedAtUtc": _iso_utc(forecast.retrieved_at),
        "ageSeconds": forecast.age_seconds(now),
        "stale": forecast.stale(now),
        "lastIngestSucceeded": forecast.last_ingest_succeeded,
        "lastIngestAttemptedAtUtc": _iso_utc(forecast.last_ingest_attempted_at) if forecast.last_ingest_attempted_at else None,
    }


def _model_for_request(store: ForecastStore, model: str) -> tuple[dict[str, Forecast], list[str]]:
    if model not in (*MODELS, "all"):
        _api_error(400, "invalid_model", "model must be aifs-single, ifs, or all")
    requested = MODELS if model == "all" else (model,)
    available = {name: store.forecasts[name] for name in requested if name in store.forecasts}
    unavailable = [name for name in requested if name not in store.forecasts]
    if not available:
        _api_error(503, "forecast_unavailable", "No valid latest forecast is available", {"models": unavailable})
    if model != "all" and unavailable:
        _api_error(503, "model_unavailable", f"No valid latest forecast is available for {model}", {"model": model})
    return available, unavailable


@asynccontextmanager
async def lifespan(app: FastAPI):
    data_dir = Path(os.environ.get("QUEST_DATA_DIR", str(ROOT / "data")))
    app.state.store = ForecastStore(data_dir)
    yield


app = FastAPI(
    title="QUEST Precipitation API",
    version="1.0.0",
    description="Read-only point, bounded regional field, and freshness endpoints over validated NetCDF forecasts.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("QUEST_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if not isinstance(detail, dict) or not {"code", "message"}.issubset(detail):
        detail = {"code": "http_error", "message": str(detail), "details": {}}
    detail.setdefault("details", {})
    return JSONResponse(status_code=exc.status_code, content={"error": detail})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    issues = [
        {"field": ".".join(str(part) for part in error.get("loc", ())), "issue": error.get("msg", "invalid value")}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "invalid_request", "message": "Query parameters are invalid", "details": {"issues": issues}}},
    )


@app.exception_handler(Exception)
async def internal_error_handler(request: Request, exc: Exception) -> JSONResponse:
    LOGGER.exception("Unhandled API error for %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "The server could not complete this request", "details": {}}},
    )


@app.get("/api/v1/health")
def health(request: Request) -> Response:
    store: ForecastStore = request.app.state.store
    now = datetime.now(timezone.utc)
    models: dict[str, Any] = {}
    for model in MODELS:
        forecast = store.forecasts.get(model)
        if forecast is None:
            models[model] = {"available": False, "lastIngestSucceeded": False, "errorCode": store.model_states[model]["errorCode"]}
            continue
        models[model] = {
            "available": True,
            **_freshness(forecast, now),
            "stepsHours": forecast.steps.astype(int).tolist(),
            "processingVersion": forecast.processing_version,
            "lastError": forecast.last_error,
        }
    available = bool(store.forecasts)
    payload = {"available": available, "models": models}
    if not available:
        return _bounded_response(
            {"error": {"code": "forecast_unavailable", "message": "No valid latest forecast artifact is available", "details": {"models": models}}},
            status_code=503,
        )
    return _bounded_response(payload)


@app.get("/api/v1/point")
def point_series(
    request: Request,
    lat: float = Query(ge=-90, le=90),
    lon: float = Query(ge=-180, lt=180),
    model: str = Query(default="all"),
) -> Response:
    if not math.isfinite(lat) or not math.isfinite(lon):
        _api_error(400, "invalid_coordinate", "Latitude and longitude must be finite numbers")
    store: ForecastStore = request.app.state.store
    forecasts, unavailable = _model_for_request(store, model)
    now = datetime.now(timezone.utc)
    series_by_model: dict[str, Any] = {}
    for name, forecast in forecasts.items():
        if len(forecast.steps) > MAX_POINT_STEPS:
            _api_error(503, "artifact_step_limit", "Forecast artifact exceeds the 64-step point response limit", {"model": name})
        latitude_index = int(np.abs(forecast.latitude - lat).argmin())
        longitude_index = int(np.abs(forecast.longitude - lon).argmin())
        records = []
        clipped_count = 0
        for index, step in enumerate(forecast.steps.astype(int)):
            raw_interval = float(forecast.interval_mm[index, latitude_index, longitude_index])
            cumulative = float(forecast.cumulative_mm[index, latitude_index, longitude_index])
            interval_clipped = math.isfinite(raw_interval) and raw_interval < 0.0
            if interval_clipped:
                clipped_count += 1
                raw_interval = 0.0
            records.append(
                {
                    "stepHours": int(step),
                    "validTimeUtc": _iso_utc(forecast.source_run + timedelta(hours=int(step))),
                    "intervalMm": raw_interval if math.isfinite(raw_interval) else None,
                    "intervalClipped": interval_clipped,
                    "cumulativeMm": cumulative if math.isfinite(cumulative) else None,
                }
            )
        series_by_model[name] = {
            **_freshness(forecast, now),
            "nearestCell": {
                "latitude": float(forecast.latitude[latitude_index]),
                "longitude": float(forecast.longitude[longitude_index]),
            },
            "gridResolutionDeg": 0.25,
            "negativeIntervalPolicy": "clip-to-zero",
            "negativeIntervalsClipped": clipped_count > 0,
            "clippedIntervalCount": clipped_count,
            "stepsHours": forecast.steps.astype(int).tolist(),
            "series": records,
        }
    return _bounded_response(
        {
            "units": "mm",
            "requested": {"latitude": lat, "longitude": lon},
            "models": series_by_model,
            "unavailableModels": unavailable,
        }
    )


@app.get("/api/v1/field")
def region_field(
    request: Request,
    model: str,
    step_hours: int = Query(alias="stepHours", ge=1, le=360),
    kind: Literal["interval", "cumulative"] = Query(...),
    bbox: str = Query(...),
    stride: int = Query(default=1, ge=1, le=64),
) -> Response:
    if model not in MODELS:
        _api_error(400, "invalid_model", "model must be aifs-single or ifs")
    parts = bbox.split(",")
    if len(parts) != 4:
        _api_error(400, "invalid_bbox", "bbox must contain west,south,east,north")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError:
        _api_error(400, "invalid_bbox", "bbox values must be numbers")
    if not all(math.isfinite(value) for value in (west, south, east, north)):
        _api_error(400, "invalid_bbox", "bbox values must be finite")
    if west < -180 or east > 180 or south < -90 or north > 90 or west >= east or south >= north:
        _api_error(400, "invalid_bbox", "bbox must be within lon [-180,180], lat [-90,90], with west<east and south<north")
    if east - west > 30 or north - south > 20:
        _api_error(400, "region_too_large", "Region may span at most 30° longitude and 20° latitude", {"maxLongitudeSpanDeg": 30, "maxLatitudeSpanDeg": 20})
    store: ForecastStore = request.app.state.store
    forecasts, _ = _model_for_request(store, model)
    forecast = forecasts[model]
    index = forecast.step_index(step_hours)
    if index is None:
        _api_error(404, "step_unavailable", f"Forecast step {step_hours} is not available", {"availableSteps": forecast.steps.astype(int).tolist()})
    latitude_indices = np.flatnonzero((forecast.latitude >= south) & (forecast.latitude <= north))[::stride]
    longitude_indices = np.flatnonzero((forecast.longitude >= west) & (forecast.longitude <= east))[::stride]
    cell_count = int(latitude_indices.size * longitude_indices.size)
    if not cell_count:
        _api_error(404, "region_empty", "The requested bounds contain no source grid cell centers")
    if cell_count > MAX_REGION_CELLS:
        _api_error(400, "region_too_many_cells", "Region contains too many cells; increase stride or reduce bbox", {"maxCells": MAX_REGION_CELLS, "requestedCells": cell_count})
    source = forecast.interval_mm if kind == "interval" else forecast.cumulative_mm
    values = np.asarray(source[index][np.ix_(latitude_indices, longitude_indices)], dtype=np.float32).copy()
    clipped_count = 0
    if kind == "interval":
        negative_mask = np.isfinite(values) & (values < 0)
        clipped_count = int(np.count_nonzero(negative_mask))
        values[negative_mask] = 0.0
    safe_values = [
        [float(value) if math.isfinite(float(value)) else None for value in row]
        for row in values
    ]
    now = datetime.now(timezone.utc)
    payload = {
        "model": model,
        "kind": kind,
        "stepHours": step_hours,
        "sourceRunUtc": _iso_utc(forecast.source_run),
        "retrievedAtUtc": _iso_utc(forecast.retrieved_at),
        "validTimeUtc": _iso_utc(forecast.source_run + timedelta(hours=step_hours)),
        "ageSeconds": forecast.age_seconds(now),
        "stale": forecast.stale(now),
        "lastIngestSucceeded": forecast.last_ingest_succeeded,
        "lastIngestAttemptedAtUtc": _iso_utc(forecast.last_ingest_attempted_at) if forecast.last_ingest_attempted_at else None,
        "units": "mm",
        "negativeIntervalPolicy": "clip-to-zero" if kind == "interval" else "not-applicable",
        "negativeIntervalsClipped": clipped_count > 0,
        "clippedCellCount": clipped_count,
        "arrayOrder": "[latitude,longitude]",
        "latitudeOrder": "north-to-south",
        "longitudeConvention": "[-180,180)",
        "latitude": forecast.latitude[latitude_indices].tolist(),
        "longitude": forecast.longitude[longitude_indices].tolist(),
        "shape": [int(latitude_indices.size), int(longitude_indices.size)],
        "values": safe_values,
    }
    return _bounded_response(payload)


def main() -> None:
    uvicorn.run(
        "questlab.api:app",
        host=os.environ.get("QUEST_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("QUEST_API_PORT", "8000")),
        log_level=os.environ.get("QUEST_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
