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
- No back end, front end, deployment, or Stage 4 failure-mode test has started.
- Session rollout path is still to be added to README during handover.

## Next

Commit Stage 1.5 after a final repository review. Then stop and report Stage 1 findings and commit hash; do not start Stage 2 until the user has reviewed that report.
