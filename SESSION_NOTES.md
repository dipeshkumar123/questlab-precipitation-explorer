# Current state / Known issues / Next

## Current state

- Stage 0 complete and committed as `c1ab13f`.
- Stage 1.1 semantic probe complete for AIFS Single and IFS at 2026-11-18 18:00 UTC, steps 6, 12, 18, and 24. Both have GRIB `stepType=accum`; means/maxima rise across steps and at least 94.5% of cells are non-decreasing for every pair.
- Units differ: AIFS `kg m**-2`; IFS `m`. Probe normalizes to mm for comparison. Both share a 721×1440 0.25° grid, latitude north-to-south, longitude −180° to 179.75°.
- Detailed statistics and the differencing decision are in `DECISIONS.md`.

## Known issues

- Some cells decrease slightly between cumulative steps: maximum observed decrease is 0.0625 mm for AIFS and 0.1221 mm for IFS. Preserve raw differences for conservation; investigate magnitude/packing during the index timing task.
- The Stage 0 cfgrib index incompatibility warning has not yet been timed or explained.
- No front end has been chosen. Data inspection and pipeline work remain.

## Next

Commit the Stage 1.1 semantic finding. Then measure repeat retrieval/decode timings, build and inspect the field visualization, record the pipeline/API design, and implement the independent ingest-process-serve CLI.
