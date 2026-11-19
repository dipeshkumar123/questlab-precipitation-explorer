# Current state / Known issues / Next

## Current state

- Stage 0 complete: AIFS `tp` probe confirmed real GRIB content; commit `c1ab13f4ba577a3d6e6ff67ae265b6f587f213ec`.
- Stage 1.1 complete: same AIFS and IFS run (`2026-11-18 18Z`), four steps, exact `stepRange` and accumulation semantics verified; commit `b95836e419e0177c3aef701a99d9ce966ec8ad3d`.
- Stage 1.2 complete: two clean AIFS retrievals were byte-identical (306,290 bytes, SHA-256 `a4e8282c…1f225fba`). Retrieval times in one comparison were 2.242 s and 0.855 s; first default cfgrib opens were 0.678 s and 0.015 s, but the second is confounded by warm caches. Default open repeated the incompatible-index warning; one message, CCSDS packing. A dedicated writable cache keyed by model/run/raw file removes the warning. Full timings and trade-off are in `DECISIONS.md`.
- Stage 1.3 complete: `scripts/inspect_field.py` rendered and the session visually inspected the real AIFS step-24 cumulative and 18–24 h interval fields. Image: `artifacts/field-inspection-aifs-single-2026-11-18-t18-step24.png`. Coordinate orientation and top-five local maxima were printed. The 0.25° grid reveals global/regional structure but is too coarse for city-scale decisions.
- Stage 1.4 complete: `DECISIONS.md` records the ingest/process/serve boundaries, retention and latency targets, failure behavior, freshness shape, and API contract before any endpoint work.
- Stage 1.5 complete: `questlab-ingest` retrieved and processed the pinned run for both AIFS and IFS. Each reloads as four steps on a 721×1440 grid, with `tp_cumulative_mm` and `tp_interval_mm` in mm. The sum of intervals matches step-24 cumulative at every grid point; measured maximum absolute error is 0.0 mm for each model. Matching explicit reruns skip work. A `--date latest` run resolved to 2026-11-18 18Z and reused the existing verified AIFS artifact.
- Processed paths: `data/processed/aifs-single/20261118T18Z/tp.nc` and `data/processed/ifs/20261118T18Z/tp.nc`; local GRIB and NetCDF files are ignored by Git.

## What changed during Stage 1

- Inspection showed IFS GRIB uses metres while AIFS uses kg m⁻²; normalization to mm is model-specific.
- A first serialization attempt exposed missing `h5py` for the h5netcdf backend. Added the explicit dependency and confirmed compressed NetCDF write/reload.
- Using only the basename `tp` as a cfgrib cache key caused an IFS/AIFS cache collision. The final pipeline uses a cache directory containing the model, run, and raw-file stem; the warning disappeared on the verified final runs.
- The ECMWF client defaults to 500 retries and 120-second backoff. One `latest` attempt timed out; a later attempt succeeded. The pipeline now bounds retries to three with 3-second backoff. That initial timeout was stopped before a complete error-path run.

## Known issues

- `--date latest` succeeded once and selected the same run already processed; freshness behavior will be implemented in Stage 2.
- Pipeline currently defaults to a four-step, 24-hour horizon. Longer IFS horizons may not provide every 6-hour step; missing-step handling is explicit but those horizons were not verified.
- At Stage 1 signoff, no back end, front end, deployment, or Stage 4 failure-mode test had started.
- Session rollout path is still to be added to README during handover.

## Stage 2.0 complete (2026-11-19)

- Re-read DECISIONS.md and these notes before beginning Stage 2.
- ecCodes packing probe: `grib_get` CLI is absent on Windows; `scripts/probe_packing.py` reads the same message keys through the installed ecCodes library. Every AIFS and IFS message has 12-bit `grid_ccsds`; none of 8.3 million model-step values is at or within one quantization increment of its theoretical ceiling. AIFS has one step-24 maximum at 243.4375 mm, 12.5 mm below ceiling; IFS has one value >500 mm and no value at its 999.75586 mm step-24 ceiling. The tail difference is not clipping and is recorded as model-output divergence.
- API negative interval decision: clip negative interval values to zero at the API boundary and report clipping counts/flags. Preserve raw signed interval fields and cumulative fields in NetCDF; the public contract warns that clipped interval totals may not telescope exactly.
- Bounded region contract: one model, step, and field; max 20° latitude ×30° longitude, 81×121=9,801 source cells (10,000 guard), 1 MiB JSON response maximum. One field step/request, point-series ≤64 steps/model.
- Cold fresh-data-dir ingest benchmark: AIFS 7.294 s, IFS 5.590 s, including download, decode, NetCDF write/reload, and mass-balance verification; both below the 120 s budget. Script/report: `scripts/benchmark_ingest.py` and `artifacts/ingest-latency-stage2-0.json`.
- NetCDF axes reloaded and JSON-list round-tripped as latitude 90→−90 and longitude −180→179.75, array order `[step_hours, latitude, longitude]`. Live API returned latitude `[20 … 0]`, longitude `[70 … 100]`, shape 81×121 and `[latitude,longitude]` ordering.

## Next

## Stage 2 backend complete (2026-11-19)

- Stage 2.0 data decisions committed as `6815c3c15a75dbdb7cf2bfc1227d0d1831462baa`.
- Chose synchronous FastAPI handlers over Flask/async: local NetCDF snapshots, bounded slicing, schema validation/OpenAPI, and no asynchronous upstream work. Artifacts load read-only from `latest.json` at startup.
- Implemented `/api/v1/health`, `/api/v1/point`, and `/api/v1/field` with common JSON errors, 12-hour stale metadata, clipping flags, 20°×30°/10,000-cell/1 MiB bounds, and the verified longitude order.
- Pipeline attempts atomically write `ingest-status.json`; API reports latest-attempt state while continuing to serve a prior validated artifact. The status/error is safe for clients and omits internal exception text.
- `scripts/test_api.py --failure-scenarios` passed on the live API and isolated real Uvicorn servers: healthy responses, no artifact (503), stale 36-hour artifact (still 200, stale true), failed ingest with last good artifact (still 200 and failed attempt reported), unavailable step (404), malformed request/bounds (400), coordinate order, clipping, payload bounds.
- Latest HTTP timings: health 0.0226 s; first/repeat point 0.0056/0.0251 s; max-size region 0.0087 s and 54,330 bytes (9,801 cells). All are under 500 ms point and 1 s region budgets; loopback measurements on current Windows host.
- `DECISIONS.md` now records observed failure modes and reconciles ingest status, response size, coordinates, and latency with the implementation.

## Known issues

- API service currently snapshots latest artifacts at startup; restart it after new pipeline output.
- Front end and deployment remain unstarted. Do not begin Stage 3 before reporting Stage 2.

## Next

Commit the failure evidence/status tracking and final contract/latency reconciliation. Report Stage 2 and stop before Stage 3.
