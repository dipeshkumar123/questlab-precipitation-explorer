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

- `--date latest` succeeded once and selected the same run already processed; API freshness behavior is implemented in Stage 2.
- Pipeline currently defaults to a four-step, 24-hour horizon. Longer IFS horizons may not provide every 6-hour step; missing-step handling is explicit but those horizons were not verified.
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
- Deployment remains unstarted and requires the same-origin `/api` reverse proxy described in README.

## Next

## Stage 3.0 complete (2026-11-19)

- Cold/warm ingest benchmark rerun: AIFS 7.948/2.950 s; IFS 6.879/3.014 s, all below the 120 s budget. Warm is forced reprocessing from cached GRIB plus cfgrib index, without retrieval. Report: `artifacts/ingest-latency-stage2-0.json`.
- Exhaustive step-24 tail analysis read 1,038,240 points per model and wrote full 1 mm histogram at/above 100 mm to `artifacts/model-tail-stage3-0.json`. AIFS tail count 200, max exact-value multiplicity 3, largest 1-mm bin count 9; IFS tail count 309, exact multiplicity 6, largest 1-mm bin count 12. No ceiling-style repeated-value spike.
- AIFS unique max 243.4375 mm at (−11.50, −162.75); IFS unique max 574.707031 mm at (−13.75, −147.00). Different cells. Verdict recorded: “model divergence confirmed.”
- UX rationale/framework/rejected alternatives were written to DECISIONS.md before frontend implementation. Chosen experience: bounded point-anchored side-by-side regional fields plus a clicked-cell full forecast fingerprint across models; no global map request.

## Next

## Stage 3 front end complete (2026-11-19)

- Built a static, point-anchored forecast explorer. The two side-by-side fields are bounded to the API's 20°×30° / 9,801-cell maximum and share a log colour scale; clicking a cell loads the four-step AIFS/IFS fingerprint.
- Browser loaded real Uvicorn API and NetCDF-backed artifacts. Visual review confirms north-to-south latitude, west-to-east longitude, and the Stage 1 YlGnBu-style log palette with values under 0.1 mm masked.
- Interval view surfaces clipping counts (AIFS 0, IFS 211 on the tested field); point view carries both interval and cumulative values.
- Browser failure results: stopped Uvicorn showed API unavailable with no stuck loader; current real artifact showed stale age >12 h while still rendering; step 48 showed available steps `[6,12,18,24]`.
- Build: `python scripts/build_frontend.py`; static output in `dist/`; `QUEST_API_BASE_URL` is injected into `dist/config.js`. Deployment assumes same-origin reverse proxy `/api` to FastAPI; local preview uses port 5173 with the API on 8000.

## Next

Report Stage 3. Do not begin Stage 4 (deployment) until user review.

## Stage 4 packaging complete; public deployment blocked (2026-11-19)

- Re-read `DECISIONS.md`, `SESSION_NOTES.md`, and the Stage 4 request before work. Recorded Railway topology and baked-artifact policy, then committed the decision as `fb3ce43` before deployment code.
- Added Docker packaging, `scripts/prepare_deploy.py` for an isolated context with normalized Linux pointer paths, `scripts/run_local.py` for one-command local startup, and the Docker-time frontend build. Final context size was 11,917,772 bytes and contained the two NetCDF snapshots (11,868,882 bytes combined), manifests, pointers, and app only; raw GRIB and cache were excluded.
- Local same-origin root, health, and point requests returned HTTP 200; missing step 48 returned HTTP 404. Health showed the real pinned 2026-11-18 18Z artifact at age ~46,060 seconds and stale=true. Frontend build and Python compileall completed. Initial packaging commit: `259e848`.
- Reviewed Railway Free plan docs: $0/month, $1 monthly usage credits, 0.5 GB RAM, 1 GB ephemeral storage, 4 GB image limit, service sleep after 5–10 idle minutes. The account's trial has expired. `railway up .deploy/context --path-as-root --no-gitignore --new --name quest-lab --yes --detach` stopped before project creation with `Your trial has expired. Please select a plan to continue using Railway.` No plan was selected and no project/service/URL was created. A Free plan selection in the account is the remaining prerequisite; no paid tier was authorized.
- Updated the deployment design to use nginx + one supervised Uvicorn worker in the same container so the static page remains served if the API process stops; this preserves the failure-test requirement and same origin. This new Docker container has not been built or run because the local Docker daemon is unavailable and Railway blocked deployment.
- Topology follow-up changed the Dockerfile to run nginx and Uvicorn under supervisord, added the dynamic `${PORT}` nginx proxy config, and included those files in the isolated staging context. Local context/compile checks pass; the container runtime behavior still needs a successful Docker/Railway build.
- Deployed URL, first paint/data render measurements, interaction checks in a second browser, deployed failure cases, and HTTPS/CORS results remain **not verified**. Stage 4.2/4.3 are not complete. No Stage 5 work started.
- Exact Codex session rollout: `C:\Users\panji\.codex\sessions\2026\11\19\rollout-2026-11-19T10-07-26-01a1f218-5ff0-73b3-9394-e61118a92b59.jsonl`.
