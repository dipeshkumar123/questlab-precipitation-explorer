# QUEST precipitation explorer

An end-to-end precipitation forecast pipeline and read-only API for ECMWF AIFS Single and IFS. The pipeline retrieves global forecasts, converts cumulative `tp` into 6-hour interval totals, and writes a compressed NetCDF artefact plus a manifest. The API serves point series, bounded regional fields, and forecast freshness. The static frontend can run locally or with the API from one origin.

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

For the full local application, build the frontend and start the API on the same origin with one command:

```powershell
python scripts/run_local.py
```

Open `http://127.0.0.1:8000/`. The service reads `latest.json`, its manifest, and NetCDF files at startup; rerun after a new ingest. It does not retrieve data on startup. `QUEST_DATA_DIR`, `QUEST_STATIC_DIR`, `QUEST_FRESHNESS_HOURS`, `QUEST_API_HOST`, and `PORT` configure the paths, 12-hour freshness threshold, bind address, and port. The API is one Uvicorn worker; deploy binds `0.0.0.0` and uses the host-provided `PORT`.

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

## Build and run the front end

The front end is dependency-free static HTML, CSS, and JavaScript. The Docker build runs `python scripts/build_frontend.py` with `QUEST_API_BASE_URL` empty, so the browser calls the API on the same origin. For a standalone local preview, build it with:

```powershell
python scripts/build_frontend.py
```

Preview the built files with:

```powershell
python -m http.server 5173 --directory dist
```

Open `http://127.0.0.1:5173/`. The build writes `dist/index.html`, `dist/styles.css`, `dist/app.js`, and generated `dist/config.js`. Set `QUEST_API_BASE_URL` before the build only when intentionally targeting a separate API origin. Production packages keep it empty and serve `/api/*` and `/` from one origin.

The interface shows two regional fields bounded to 20°×30° and compares them on one logarithmic scale. Click a grid cell to see its full point forecast sequence across both models. Change the region center or forecast step and select cumulative total or six-hour increment. The header shows source initialization, selected valid time, forecast age and stale state. Interval fields show the API's clipped-cell count. Requests use API latitude/longitude axes as returned; a global map is out of scope under the 10,000-cell/1 MiB response bound.

## Inspect the forecast field

After running a pipeline command for the pinned four-step AIFS run:

```powershell
python scripts/inspect_field.py --model aifs-single --run-date 2026-11-18 --time 18 --step 24
```

This writes `artifacts/field-inspection-aifs-single-2026-11-18-t18-step24.png`, showing step-24 cumulative precipitation beside the step-18-to-24 increment on a shared logarithmic scale. It prints the global maximum and five spatially separated local maxima. The image is committed as the data-inspection evidence; its source GRIB remains local.

## Decisions and current state

- [DECISIONS.md](DECISIONS.md) records parameter semantics, measured retrieval/index behavior, the data-inspection findings, pipeline trade-offs, and the API contract prepared before endpoint work.
- [SESSION_NOTES.md](SESSION_NOTES.md) records verified work, known limitations, and the next stage.
- [SUBMISSION.md](SUBMISSION.md) is the reviewer-facing submission checklist and verification map.
- Deployment topology: one Render Free Docker service serves the static app and FastAPI API with baked processed snapshots and no scheduled ingest. The public source repository is [`dipeshkumar123/questlab-precipitation-explorer`](https://github.com/dipeshkumar123/questlab-precipitation-explorer). The live app is [questlab-precipitation-explorer.onrender.com](https://questlab-precipitation-explorer.onrender.com/).
- Session log: `C:\Users\panji\.codex\sessions\2026\11\19\rollout-2026-11-19T10-07-26-01a1f218-5ff0-73b3-9394-e61118a92b59.jsonl`.

## Deployment

The initial deployment uses the selected processed forecast snapshots committed to the public repository for Render's Docker build. Only the two latest pointers, manifests, and NetCDF files are included; raw GRIB files and cfgrib caches are excluded. The Docker image builds the front end and starts nginx plus one supervised Uvicorn worker. The local image was rebuilt in 223.04 seconds and is 135,315,786 bytes (129.0 MiB). Local container checks returned HTTP 200 for `/` and `/api/v1/health`, HTTP 200 for a point query, and HTTP 404 for a missing step (48h). Stopping the API worker left `/` at 200 and made API health return 502 through nginx. The container used about 215–218 MiB after loading, below Render Free's 512 MiB memory limit.

The live Render service is one Free Docker web service in Oregon, on branch `master`, with no secrets or scheduled ingest. Render serves the app and `/api/*` from the same HTTPS origin, so browser API calls need no cross-origin configuration. The initial deployment of commit `9206198` succeeded. Edge and Brave both loaded the fields and point profile; health and point API routes returned data in the browser; unavailable step 48 returned the documented JSON error. A click on the AIFS field updated the selected grid cell and profile. Field changes, region loading, and stale forecast messaging were observed. Precise paint/data timing and a deployed API-process-stop test were not measured; the latter is verified in the local container below.

Render Free services sleep after 15 minutes without traffic and typically take about a minute to wake. The plan includes 750 instance hours per workspace each month and has no SLA. This service uses one worker and no scheduler. The baked snapshot ages continuously and should be visibly stale after 12 hours; a week after deployment it remains viewable with its actual age. A forecast refresh requires ingesting a new available ECMWF run and redeploying. The source's recent-run retention window is limited (the project observed/documented up to four days); there is no archive mirror and later retrieval of a specific old run is not promised.

The previous Railway attempt was blocked before project creation because Railway required plan selection after trial expiry. It was superseded by the approved Render route. The `prepare_deploy.py` staging context remains available for hosts that need it, but the selected Render build uses repository files. The Dockerfile builds the front end and starts nginx on `${PORT}` with one supervised `uvicorn questlab.api:app --host 127.0.0.1 --port 8001 --workers 1`. Nginx serves static assets and proxies `/api/*`; it remains available when the API worker stops. No secrets are required. Set `QUEST_FRESHNESS_HOURS` to change the stale threshold; the default is 12 hours. A manual forecast refresh requires ingesting a new available ECMWF run and redeploying.

- Public URL: https://questlab-precipitation-explorer.onrender.com/ (Render Free, Docker, Oregon). The free instance sleeps after inactivity, so first requests after sleep may be delayed; the deployed snapshot is a fixed run and becomes stale over time.

### Session log integrity

The Codex rollout file is `C:\Users\panji\.codex\sessions\2026\11\19\rollout-2026-11-19T10-07-26-01a1f218-5ff0-73b3-9394-e61118a92b59.jsonl`. At the 2026-11-19 21:50 IST inspection it was 25,394,318 bytes and 4,930 lines. It contains four `compacted` markers at lines 1,518, 2,487, 3,830, and 4,756; the latest occurred at 13:54:59 IST. The raw file retains prior message/event records before each marker, including visible decisions and tool calls/results (for example, lines 1–4,755 precede the last marker). Compaction changed the model's active context; it did not truncate the rollout log. The rollout is an activity record, not a transcript of private internal reasoning. See [DECISIONS.md](DECISIONS.md) for the dated integrity assessment.
