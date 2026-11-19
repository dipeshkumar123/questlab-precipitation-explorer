# Current state / Known issues / Next

## Current state

- Stage 0 underway: repository initialized, README stub and reproducible ECMWF retrieval probe created.
- Installed Python 3.13 environment dependencies: `ecmwf-opendata`, `xarray`, `cfgrib`/ecCodes, NumPy, and Matplotlib.
- ECMWF parameter database confirms `tp` is total precipitation (parameter 228), documented in metres.

## Known issues

- Live retrieval succeeded for AIFS Single run `2026-11-18 18:00 UTC`, forecast step 6. cfgrib decoded `tp` as `(721, 1440)` on latitude `[-90,90]` and longitude `[-180,179.75]`; GRIB units are `kg m**-2`; summary finite min/mean/max `0 / 0.61579847 / 79.875`.
- The parameter database reports metres while this GRIB reports `kg m**-2` (equivalent numerically to mm water depth). Step 6's accumulation window still needs verification before product semantics are chosen.
- cfgrib warned that a `.idx` file was incompatible, then successfully decoded the field. Avoid reusing stale indices.
- No frontend or pipeline decisions have been made.

## Next

Stage 0 verification is complete. Commit this checkpoint, then Stage 1 should model the accumulated-field semantics and implement the independent pipeline CLI. Create the required plotted inspection harness before selecting the UX.
