# Decisions

## 2026-11-19 — Stage 0 parameter and probe

ECMWF's parameter database identifies `tp` (parameter 228) as total precipitation; its documented unit is metres of accumulated liquid and frozen water. The app will use AIFS Single (`model="aifs-single"`) as the initial model because it provides a single deterministic field and keeps the first end-to-end ingest small. `ifs` remains a viable alternative if AIFS does not expose `tp` through the open-data service; a live one-step retrieval is the deciding check.

The exact probe request is in `scripts/probe_ecmwf.py`. The live AIFS request succeeded for run `2026-11-18 18:00 UTC`, step 6. cfgrib decoded a `tp` field with shape `(721, 1440)` over latitude `[-90, 90]` and longitude `[-180, 179.75]`, i.e. a global 0.25-degree grid including both poles. The actual GRIB metadata says `kg m**-2`, not metres as in the generic parameter database; for water density this is numerically equivalent to millimetres of water depth. Values ranged from 0 to 79.875 with mean 0.616 kg m-2. This confirms precipitation is present and the AIFS choice is viable.

The returned field is an accumulation, not an instantaneous rate. A single step-6 snapshot does not establish whether its period is from forecast start or the preceding output; that must be investigated before interpreting interval totals in the product. The probe also exposed an incompatible stale GRIB index warning; cfgrib still decoded the GRIB successfully, but generated `.idx` files should be removed or disabled during repeatable processing.

## 2026-11-19 — Stage 1.1 accumulation semantics (same run, four steps)

Retrieved `tp` at steps 6, 12, 18, and 24 for both `aifs-single` and `ifs`, pinned to `2026-11-18 18:00 UTC`. `scripts/probe_accumulation.py` is the reproducible probe. Both GRIBs have `stepType=accum`, 721×1440 points, 0.25° spacing, latitude ordered north-to-south (90° to −90°), and longitude −180° to 179.75°. AIFS units are `kg m**-2`; IFS units are `m`; reported values below are both converted to mm.

| Model | Step (h) | Min (mm) | Max (mm) | Mean (mm) | Grid fraction >0.1 mm |
|---|---:|---:|---:|---:|---:|
| AIFS | 6 | 0 | 79.875 | 0.615798 | 0.435667 |
| AIFS | 12 | 0 | 145.9375 | 1.211850 | 0.563810 |
| AIFS | 18 | 0 | 195.75 | 1.843001 | 0.639563 |
| AIFS | 24 | 0 | 243.4375 | 2.486011 | 0.685694 |
| IFS | 6 | 0 | 193.664551 | 0.624251 | 0.416196 |
| IFS | 12 | 0 | 361.938477 | 1.224000 | 0.593341 |
| IFS | 18 | 0 | 475.097656 | 1.848381 | 0.670252 |
| IFS | 24 | 0 | 574.707031 | 2.495348 | 0.667220 |

The global maxima and counts above 50 mm for AIFS steps 6/12/18/24 are respectively `79.875 @ (−11.25°, −163.5°), 56`; `145.9375 @ (−11.25°, −163.5°), 361`; `195.75 @ (−11.25°, −163.0°), 822`; and `243.4375 @ (−11.5°, −162.75°), 1676`. Thus the Stage 0 maximum is not a single-point spike: 56 points exceed 50 mm at step 6, around a nearby, stable maximum location. The spatial shape still needs visual inspection before calling it coherent.

Pairwise non-decreasing grid fractions at raw decoded precision are AIFS `6→12: 98.262%` (18,040 negative cells, minimum delta −0.03125 mm), `12→18: 100%`, `18→24: 99.880%` (1,241 negative cells, −0.0625 mm); IFS `6→12: 97.222%` (28,839 cells, −0.06104 mm), `12→18: 99.921%` (824 cells, −0.12207 mm), `18→24: 94.534%` (56,754 cells, −0.12207 mm). Both models' maxima and means rise at each step, and more than 94.5% of grid cells are non-decreasing in every pair; the remaining decreases are small in absolute magnitude relative to the field maxima. Together with GRIB `stepType=accum`, this supports treating each step as a cumulative forecast from initialization for both models, with small local negative excursions that may be related to packing/rounding. This does not support treating the fields as independent 6-hour interval totals.

**Pipeline consequence:** difference consecutive cumulative fields to form 6-hour totals, retaining the raw differences so they telescope exactly back to step 24. Do not silently clip small negative differences: doing so would break that conservation check. Expose a presentation-side floor at zero for visualization if needed, while keeping source-derived numeric values in the data artefact. Verify mass balance after serialization.
