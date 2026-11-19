# Decisions

## 2026-11-19 — Stage 0 parameter and probe

ECMWF's parameter database identifies `tp` (parameter 228) as total precipitation; its documented unit is metres of accumulated liquid and frozen water. The app will use AIFS Single (`model="aifs-single"`) as the initial model because it provides a single deterministic field and keeps the first end-to-end ingest small. `ifs` remains a viable alternative if AIFS does not expose `tp` through the open-data service; a live one-step retrieval is the deciding check.

The exact probe request is in `scripts/probe_ecmwf.py`. The live AIFS request succeeded for run `2026-11-18 18:00 UTC`, step 6. cfgrib decoded a `tp` field with shape `(721, 1440)` over latitude `[-90, 90]` and longitude `[-180, 179.75]`, i.e. a global 0.25-degree grid including both poles. The actual GRIB metadata says `kg m**-2`, not metres as in the generic parameter database; for water density this is numerically equivalent to millimetres of water depth. Values ranged from 0 to 79.875 with mean 0.616 kg m-2. This confirms precipitation is present and the AIFS choice is viable.

The returned field is an accumulation, not an instantaneous rate. A single step-6 snapshot does not establish whether its period is from forecast start or the preceding output; that must be investigated before interpreting interval totals in the product. The probe also exposed an incompatible stale GRIB index warning; cfgrib still decoded the GRIB successfully, but generated `.idx` files should be removed or disabled during repeatable processing.
