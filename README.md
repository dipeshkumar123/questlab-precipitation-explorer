# QUEST precipitation explorer

An end-to-end precipitation forecast pipeline and read-only API for ECMWF AIFS Single and IFS. The pipeline retrieves global forecasts, converts cumulative `tp` into 6-hour interval totals, and writes a compressed NetCDF artefact plus a manifest. The API serves point series, bounded regional fields, and forecast freshness. The frontend and deployment have not been started yet.

## Verified data behavior

- Parameter: ECMWF total precipitation, `tp` (parameter 228).
- Verified run: `2026-11-18 18:00 UTC`, steps 6, 12, 18, and 24, for both AIFS Single and IFS.
- Both products encode steps as cumulative from forecast initialization (`stepRange=0-6`, `0-12`, `0-18`, `0-24`). The pipeline differences consecutive steps.
- AIFS GRIB units are `kg m**-2`; IFS uses `m`. Output fields use millimetres of water depth.
- Source grid: 721×1440 at 0.25°, latitude ordered north-to-south, longitude −180° to 179.75°.
- ECMWF Open Data retains only recent runs (up to four days per the project brief). Raw GRIB and processed output are kept locally in ignored `data/` paths; no cloud archive or deployment exists yet.

## Setup

Python 3.11 or newer is recommended. From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e .
```

The pipeline uses `ecmwf-opendata`, `cfgrib`/ecCodes, xarray, h5netcdf/h5py, and NumPy. The inspection script also uses Matplotlib.

## Run the data pipeline

Retrieve and process one model/run through 24 hours (steps 6, 12, 18, 24):

```powershell
questlab-ingest --model aifs-single --date 2026-11-18 --time 18 --max-step 24
questlab-ingest --model ifs --date 2026-11-18 --time 18 --max-step 24
```

To resolve ECMWF's latest matching run, use `--date latest` and omit `--time`:

```powershell
questlab-ingest --model aifs-single --date latest --max-step 24
```

For an existing explicit run with a matching manifest and checksum, reruns skip the work. Pass `--force` to reprocess its cached GRIB. Retrieval needs network access; ECMWF failures return a nonzero exit code. The source client is configured for three retries with a 3-second backoff.

The raw GRIB is stored at `data/raw/<model>/<run>/tp-through-<max-step>h.grib2`. Processed output is stored at `data/processed/<model>/<run>/tp.nc` with `manifest.json`; `data/processed/<model>/latest.json` points to the last successful product. Each ingest attempt atomically updates `data/processed/<model>/ingest-status.json`, so a failed new attempt is visible while the API continues serving the prior verified artifact. Both `tp_cumulative_mm` and `tp_interval_mm` use dimensions `[step_hours, latitude, longitude]`. cfgrib indexes live separately under `data/cache/cfgrib/<model>/<run>/<raw-file-stem>/` to avoid incompatible sibling indexes.

## Run the API

After installing the project, start the read-only API from the repository root:

```powershell
questlab-api
```

The default address is `http://127.0.0.1:8000`. Set `QUEST_API_HOST`, `QUEST_API_PORT`, or `QUEST_DATA_DIR` before starting to change the bind address, port, or artifact root. The service reads `latest.json`, its manifest, and NetCDF files at startup; rerun the service after a new ingest. It does not fetch ECMWF data or regenerate processed artifacts.

The v1 endpoints are:

- `GET /api/v1/health` — per-model run time, retrieval time, steps, processing version, age, stale flag, and load/ingest status.
- `GET /api/v1/point?lat=12.97&lon=77.59&model=all` — nearest-cell interval and cumulative series in mm.
- `GET /api/v1/field?model=aifs-single&stepHours=24&kind=interval&bbox=70,0,100,20&stride=1` — one bounded JSON grid with coordinate axes.

The API serves only each model's latest pointer. Health reports the latest ingest attempt time, success flag, and a safe error summary; point and field responses carry the success flag and attempt time. A stale forecast remains available and every point/field response includes `stale` and `ageSeconds`. If no valid artifacts exist, the service returns a consistent JSON 503 error. Negative interval values are clipped to zero at the API boundary with clipping counts and flags; stored NetCDF values remain signed so they conserve the cumulative forecast. Region requests are limited to 20° latitude × 30° longitude, 10,000 cells, one model and step, and 1 MiB JSON response size. Longitude uses `[-180,180)`; axes are returned in `[latitude,longitude]` order with latitude north-to-south.

## Verify the API

With `questlab-api` running in another terminal:

```powershell
python scripts/test_api.py --failure-scenarios
```

The client checks health, point, maximum-size region, coordinate conventions, clipping metadata, errors, and runs separate real uvicorn instances for no-artifact and stale-manifest scenarios. API response latency measurements are written to `artifacts/api-latency-stage2.json`.

## Inspect the forecast field

After running a pipeline command for the pinned four-step AIFS run:

```powershell
python scripts/inspect_field.py --model aifs-single --run-date 2026-11-18 --time 18 --step 24
```

This writes `artifacts/field-inspection-aifs-single-2026-11-18-t18-step24.png`, showing step-24 cumulative precipitation beside the step-18-to-24 increment on a shared logarithmic scale. It prints the global maximum and five spatially separated local maxima. The image is committed as the data-inspection evidence; its source GRIB remains local.

## Decisions and current state

- [DECISIONS.md](DECISIONS.md) records parameter semantics, measured retrieval/index behavior, the data-inspection findings, pipeline trade-offs, and the API contract prepared before endpoint work.
- [SESSION_NOTES.md](SESSION_NOTES.md) records verified work, known limitations, and the next stage.
- Deployment URL: none yet. Frontend and deployment stages remain.
- Session log: record the raw Codex rollout path here at handover. Rollouts are stored under `C:\Users\panji\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`.
