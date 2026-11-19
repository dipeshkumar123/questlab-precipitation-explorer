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

Pairwise non-decreasing grid fractions at raw decoded precision are AIFS `6→12: 98.262%` (18,040 negative cells, minimum delta −0.03125 mm), `12→18: 100%`, `18→24: 99.880%` (1,241 negative cells, −0.0625 mm); IFS `6→12: 97.222%` (28,839 cells, −0.06104 mm), `12→18: 99.921%` (824 cells, −0.12207 mm), `18→24: 94.534%` (56,754 cells, −0.12207 mm). ecCodes confirmed the message-level `stepRange` values are exactly `0-6`, `0-12`, `0-18`, and `0-24` for both models, with `stepType=accum`. The fields are therefore cumulative from forecast initialization, not independent 6-hour totals. Their maxima and means also increase at every step. The small local decreases (maximum absolute 0.0625 mm AIFS, 0.1221 mm IFS) match the CCSDS packing quantization: AIFS binary scale factors are −5/−4, IFS are −14/−13/−13/−12 with IFS units metres. Preserve these source-derived differences for conservation.

**Pipeline consequence:** difference consecutive cumulative fields to form 6-hour totals, retaining the raw differences so they telescope exactly back to step 24. Do not silently clip small negative differences: doing so would break that conservation check. Expose a presentation-side floor at zero for visualization if needed, while keeping source-derived numeric values in the data artefact. Verify mass balance after serialization.

## 2026-11-19 — Stage 1.2 retrieval and cfgrib index timing

Ran the same pinned AIFS `tp` step-6 request twice, deleting the local GRIB and sidecar before each trial. Retrieval took 2.242 s then 0.855 s; the 306,290-byte GRIB had the same SHA-256 both times (`a4e8282c…1f225fba`). First default cfgrib open took 0.678 s on trial one and 0.015 s on trial two; a second open took 0.013 s and 0.012 s. The lower second-trial latency is confounded by the warm OS/network cache and is not a reliable ingest benchmark.

The default open emitted “Ignoring index file … incompatible with GRIB file” on repeated opens. ecCodes finds exactly one message (`stepRange=0-6`, `stepType=accum`, `packingType=grid_ccsds`, units `kg m**-2`); repeat retrievals are byte-identical, so there is no evidence of repacking on this request. cfgrib's source confirms that an incompatible index is ignored and the GRIB field index is rebuilt from the fieldset. A dedicated writable index path (`{short_hash}.idx`) successfully writes a 1,346-byte usable index and opens without the warning; warmed local opens were ~0.01 s. The warning is repeatable but not a dominant cost for this one-message field. Pipeline decision: store indexes under `data/cache/cfgrib/<model>/<run>/<raw-file-stem>/` so neither ECMWF download sidecars nor other model/run indexes collide with cfgrib's cache.

## What the field actually looks like

Inspected `artifacts/field-inspection-aifs-single-2026-11-18-t18-step24.png`, rendered from the real 0.25° field with north-to-south latitude order verified. The cumulative view shows coherent broad tropical rain belts and curved mid-latitude frontal/cyclone bands, with finer patchy convection embedded in them; the 18–24 h increment keeps those structures but makes the newer precipitation bands easier to distinguish. The Stage 0 peak grows into a broad coherent southwest-Pacific feature: the global maximum is 243.438 mm at (−11.50°, −162.75°) at step 24, and the step-6 maximum already has 56 cells above 50 mm. The five spatially separated 3×3 local maxima at step 24 are `243.438 mm @ (−11.50°, −162.75°)`, `163.375 @ (−11.00°, 89.25°)`, `136.812 @ (18.25°, 85.25°)`, `130.375 @ (60.00°, −149.75°)`, and `126.562 @ (−13.75°, −147.25°)`. The 0.25° grid is adequate for global/synoptic structure and broad regional planning, but its roughly 25 km spacing cannot resolve a city block or a small catchment; the image has no local context or impacts. A hydrologist needs a catchment total over an explicit period, a farmer needs local timing/thresholds, and a city planner needs neighborhood-scale exceedance and lead time. Those require location/region queries and interval accumulation, not interpreting a global color field alone. The log scale (0.1 mm floor) reveals light structure hidden by a linear 0–250 mm scale; colors compare the same numeric scale across the two panels.

## 2026-11-19 — Stage 1.4 pipeline and API contract

### Pipeline boundary and trade-offs

**Ingest:** one model + one initialization run + `tp`, requested as a contiguous sequence of six-hour steps beginning at step 6. `--date latest` omits date/time so ECMWF Open Data selects its latest matching run; explicit `--date YYYY-MM-DD --time HH` pins reproducible runs. AIFS and IFS are separate artifacts because their metadata and units differ. Keep downloaded GRIB2 under `data/raw/<model>/<run>/tp-through-<max-step>h.grib2`, plus the source retrieval time and checksum. The local cache is retained for reproducibility and is not checked into Git; ECMWF source retention remains limited, so a new retrieval cannot promise a historical run after the upstream window closes. The processed run is immutable and retained locally until manually pruned.

**Process:** decode and validate all requested steps before publishing any output. Normalize `kg m**-2` to mm by identity and `m` to mm by ×1000, derive each interval as `tp(step) - tp(step-6)` (step 0 is a zero field), and keep the unmodified cumulative fields alongside interval fields. Preserve negative sub-mm decoded differences for conservation; consumers may clamp only the visual color value to zero. No spatial downsampling at ingest: retain the verified 0.25° full globe so point selection and regional subsetting can remain accurate to the source grid. This resolution still is not urban/catchment-scale.

**Serve artefact:** one compressed NetCDF4 file per model/run under `data/processed/<model>/<run>/tp.nc`, plus `manifest.json`. NetCDF stores named coordinates and the two `[step, latitude, longitude]` variables without expanding a million grid cells into JSON text. It can be read by Python/xarray in the backend and sliced by requested region before JSON serialization. A dedicated writable cfgrib cache is keyed by GRIB stem to avoid the incompatible ECMWF sidecar. Write to temporary files and atomically replace only after validation; a matching manifest makes reruns idempotent. Raw source runs are kept locally for reproducibility; processed artifacts are retained until manually pruned (no automated archive or cloud mirror in this local-first deliverable).

**Latency budget (design targets, not yet measured end-to-end):** ingest one model's four-step 24-hour product in ≤120 seconds on ordinary broadband, excluding a provider outage; point-series API response ≤500 ms; bounded regional field response ≤1 s. Network retrieval dominates the current local decode, so all unit conversion and interval differencing is precomputed at ingest. `tp.nc` will compress the full grid; regional API requests may apply a stride to cap returned cells at 50,000.

**Freshness and failure contract:** `/api/v1/health` returns `status` (`ok`, `stale`, `degraded`, `unavailable`), `latestRun`, `retrievedAtUtc`, `ageSeconds`, `fresh` (fresh means run age ≤12 h, two expected six-hour cycles), `lastIngestSucceeded`, and an optional `lastError`. If ECMWF is unavailable, ingest exits nonzero and keeps the last valid artifact; the app shows that artifact with a degraded/stale banner and age. A forecast older than 12 h remains viewable with an explicit stale state. An unavailable model/step is a 404 with the available steps; malformed artefacts return a controlled service error and never a Python traceback.

### API contract (written before endpoint implementation)

- `GET /api/v1/point?lat=<deg>&lon=<deg>&model=aifs-single|ifs|all` samples the nearest source-grid cell (no interpolation). Latitude is degrees north; longitude input and output use `[-180, 180)`. The response includes requested and selected coordinates, model/run metadata, grid spacing, units, and a series of `{stepHours, validTimeUtc, intervalMm, cumulativeMm}` records. `model=all` returns one series per available model.
- `GET /api/v1/field?model=<model>&stepHours=<n>&kind=interval|cumulative&bbox=<west,south,east,north>&stride=<positive integer>` returns one region as `{run, validTimeUtc, units:"mm", arrayOrder:"[latitude,longitude]", latitudeOrder:"north-to-south", longitudeConvention:"[-180,180)", latitude:[], longitude:[], values:[[]]}`. Bbox uses west/south/east/north degrees; dateline-crossing boxes (`west > east`) are rejected with 400 in v1. Stride is applied after bbox selection; requests above 50,000 cells are rejected with a clear 400 suggesting a larger stride or smaller bbox. Coordinates identify grid-cell centers.
- `GET /api/v1/health` follows the freshness shape above and returns HTTP 200 when usable data exists (including stale/degraded), 503 only when no valid forecast artifact is available.
- Missing grid cells serialize as JSON `null`; no silent zero fill. An unavailable step returns HTTP 404 with `availableSteps`; invalid coordinates, model, bbox, or stride return HTTP 400 with a concise error code/message.

## 2026-11-19 — Stage 2.0 data-layer flags closed

### 2.0.1 Packing and AIFS/IFS tail discrepancy

`grib_get` is not installed or on PATH on this Windows machine. I used the ECMWF ecCodes Python bindings (the installed package ships the ecCodes binary library) to read the exact requested keys directly from each message; the reproducible probe is `scripts/probe_packing.py`. The output-equivalent tuple below is `packingType, bitsPerValue, binaryScaleFactor, decimalScaleFactor, numberOfValues`; all messages have `referenceValue=0`.

| Model | Step | ecCodes key tuple | Decoded max / count | Representable ceiling / count at ceiling |
|---|---:|---|---:|---:|
| AIFS | 6 | `grid_ccsds, 12, -5, 0, 1038240` | 79.875 mm / 1 | 127.96875 mm / 0 |
| AIFS | 12 | `grid_ccsds, 12, -4, 0, 1038240` | 145.9375 mm / 1 | 255.9375 mm / 0 |
| AIFS | 18 | `grid_ccsds, 12, -4, 0, 1038240` | 195.75 mm / 1 | 255.9375 mm / 0 |
| AIFS | 24 | `grid_ccsds, 12, -4, 0, 1038240` | 243.4375 mm / 1 | 255.9375 mm / 0 |
| IFS | 6 | `grid_ccsds, 12, -14, 0, 1038240` | 193.66455 mm / 1 | 249.93896 mm / 0 |
| IFS | 12 | `grid_ccsds, 12, -13, 0, 1038240` | 361.93848 mm / 1 | 499.87793 mm / 0 |
| IFS | 18 | `grid_ccsds, 12, -13, 0, 1038240` | 475.09766 mm / 1 | 499.87793 mm / 0 |
| IFS | 24 | `grid_ccsds, 12, -12, 0, 1038240` | 574.70703 mm / 1 | 999.75586 mm / 0 |

No values equal the theoretical packing ceiling, and no values are within one quantization increment of it. AIFS step-24's maximum is 12.5 mm below its 255.9375 mm ceiling (200 quantization increments); IFS step-24's maximum is 425.0488 mm below its ceiling. There is no evidence of ceiling clipping in these fields; changing `bitsPerValue` is unnecessary. The AIFS max of 243.4375 mm is one grid cell; IFS has one point above 500 mm, 14 above 250 mm, and 31 above 200 mm, versus 0, 0, and 13 in AIFS. A 3×3 neighborhood around the IFS 574.707 mm point contains 574.7, 280.0, and 256.8 mm cells; the corresponding AIFS neighborhood ranges 96.5–126.6 mm. The same-grid forecasts therefore show a localized heavier IFS tail, not a packing ceiling. The similar global means do not refute this: a localized set of 31 cells above 200 mm has little weight in a 1,038,240-cell global mean. Record this as real model-output divergence for the Stage 3 model-agreement UX; do not imply either model is verified as more accurate.

### 2.0.2 Negative interval policy

The processed NetCDF retains signed raw interval differences so they conserve the cumulative values exactly. At the API boundary, clip negative interval values to `0 mm` because the observed negatives are at the CCSDS quantization scale (≤0.1221 mm) and negative precipitation is not useful to a viewer. Do not hide the change: each model result includes `negativeIntervalPolicy:"clip-to-zero"`, a count of clipped values (`clippedIntervalCount` for a point; `clippedCellCount` for a region), and a boolean indicating whether any value was clipped. Cumulative fields remain unchanged and authoritative; clipped public intervals may not sum exactly to cumulative values at affected cells. The client contract and implementation must carry these fields.

### 2.0.3 Enforced response bounds

The region endpoint returns exactly one model, one step, and one field per request. Accept at most 20° latitude span × 30° longitude span; on this 0.25° grid that is at most 81×121 = 9,801 cells. Enforce a second cap of 10,000 cells after selection/stride. Each request can contain one forecast step; point-series responses return at most 64 steps per model (the longest configured AIFS horizon is 61 six-hour steps). Serialize coordinates and float32 field values as JSON numbers, with missing values as `null`, and reject any response above 1,048,576 bytes with HTTP 413. This bounded JSON format is simple for a static frontend and remains below the 1 MiB cap at the specified cell count; the measured largest region response will be recorded after endpoint implementation.

The API intentionally serves only each model's `latest.json` run. Historical processed directories remain on disk for manual reproducibility but are not discoverable or requestable through v1; adding a run-list endpoint is deferred.

### 2.0.4 Cold ingest timing

Measured with `scripts/benchmark_ingest.py` on 2026-11-19 for the pinned 2026-11-18 18Z run. Each model used a new empty data directory, so retrieval, GRIB decoding, cfgrib index creation, NetCDF write, reload, and conservation verification were all included. AIFS completed in **7.294 s**, IFS in **5.590 s**, against the 120 s design budget. Both finished with zero mass-balance error. These are single-run wall-clock observations over the current connection, not a guarantee under a slow network or an ECMWF outage. The JSON measurements are in `artifacts/ingest-latency-stage2-0.json`.

### 2.0.5 Longitude convention and round-trip

The processed NetCDF for both models reloads with latitude `90.0 → −90.0` (north-to-south) and longitude `−180.0 → 179.75` (ascending, convention `[-180, 180)`). The values remain ordered `[step_hours, latitude, longitude]`. `scripts/verify_longitude.py` round-tripped both full axis arrays through the same JSON list representation planned for `/api/v1/field` and verified neither axis flips. The API must return these axes directly, with `arrayOrder:"[latitude,longitude]"`; the live HTTP response will be asserted by the Stage 2 client test before this task is finally considered closed.

### Updated v1 contract requirements

- Stale data remains servable; point and field responses include `stale` and `ageSeconds`. Freshness is based on run age ≤12 hours.
- Health reports `sourceRunUtc`, `retrievedAtUtc`, `stepsHours`, `processingVersion`, `ageSeconds`, `stale`, and `lastIngestSucceeded` per available model. No valid latest artifact means HTTP 503.
- The field and point shapes carry the negative-interval clipping metadata above. Cumulative values are never clipped.
- Region bounds, response field count, step count, byte cap, JSON error shape, and longitude/array conventions follow Tasks 2.0.2–2.0.5. Every error is `{"error":{"code":"...","message":"...","details":{...}}}`; `details` may be empty.

## 2026-11-19 — Stage 2 service framework and concrete contract (before implementation)

**Framework:** FastAPI with synchronous `def` handlers. The endpoints read already-processed local NetCDF arrays and do bounded in-memory slicing/JSON serialization; they make no network call. Async would add no useful I/O concurrency here. FastAPI runs normal path handlers in a worker thread pool, keeping disk/serialization work off the event loop; built-in query documentation, validation, and OpenAPI are useful for the next frontend stage. Flask was rejected because it would require more hand-written request validation/schema work for these three typed endpoints. Deployment is one `uvicorn` process for this team-of-one local-first service; the loaded read-only arrays are shared in memory and bounded by the two current model artifacts (~66 MB uncompressed). This fits the 500 ms point and 1 s 9,801-cell region design budgets; cold-start artifact loading is outside request latency. Source: [FastAPI sync/async guidance](https://fastapi.tiangolo.com/async/) and [custom error handling](https://fastapi.tiangolo.com/tutorial/handling-errors/).

**Serving/reload boundary:** at startup, read only each model's `latest.json`, manifest, and referenced NetCDF, validate metadata/coordinates, and load the arrays into an immutable snapshot. The API never retrieves GRIB or reprocesses NetCDF. A successful new pipeline run becomes visible after restarting the API process. v1 serves only those per-model latest pointers; historical directories are retained on disk but not exposed through an endpoint.

**Concrete response shapes:**

- `GET /api/v1/point?lat=12.97&lon=77.59&model=all` returns `{"units":"mm","requested":{"latitude":12.97,"longitude":77.59},"models":{"aifs-single":{"nearestCell":{"latitude":13.0,"longitude":77.5},"sourceRunUtc":"…","retrievedAtUtc":"…","ageSeconds":0,"stale":false,"negativeIntervalPolicy":"clip-to-zero","clippedIntervalCount":0,"series":[{"stepHours":6,"validTimeUtc":"…","intervalMm":0.0,"intervalClipped":false,"cumulativeMm":0.0}]}}}`. Each model gets its own nearest cell and metadata. `model=all` includes available models and names any unavailable ones in `unavailableModels`; explicit unavailable model returns 503. At most 64 steps/model. A negative raw interval is published as `0.0`, with `intervalClipped:true`; cumulative values remain unmodified.
- `GET /api/v1/field?model=aifs-single&stepHours=24&kind=interval&bbox=70,0,100,20&stride=1` returns `{model,kind,stepHours,sourceRunUtc,retrievedAtUtc,validTimeUtc,ageSeconds,stale,units:"mm",negativeIntervalPolicy,negativeIntervalsClipped,clippedCellCount,arrayOrder:"[latitude,longitude]",latitudeOrder:"north-to-south",longitudeConvention:"[-180,180)",latitude:[],longitude:[],shape:[nLat,nLon],values:[[]]}`. Bbox is west,south,east,north; extents may not exceed 30° longitude or 20° latitude; east must be greater than west (no dateline crossing). One model, one step, ≤10,000 cells, and ≤1,048,576 serialized bytes. One negative interval is clipped to zero and counted; missing cells are JSON `null`.
- `GET /api/v1/health` returns HTTP 200 with `{"available":true,"models":{"ifs":{"sourceRunUtc":"…","retrievedAtUtc":"…","stepsHours":[6,12,18,24],"processingVersion":"0.1.0","ageSeconds":0,"stale":false,"lastIngestSucceeded":true}}}` when at least one valid latest artifact loads. A per-model missing/broken pointer reports `lastIngestSucceeded:false` and a safe error code; if neither model is usable, return HTTP 503.
- All errors are `{"error":{"code":"...","message":"...","details":{...}}}`. Invalid query values are 400; invalid model names 400; missing step is 404 with `details.availableSteps`; region extent/cell excess is 400; response byte excess is 413; unavailable model or no valid artifacts is 503. Server exceptions are logged locally and returned as generic 500 `internal_error`, never with a stack trace.
- Point and field responses remain available when stale and include `stale` plus `ageSeconds`. The health response is the source of truth for all model states. No `/runs` endpoint exists because v1 intentionally serves latest only.

The live HTTP client test later confirmed the field response preserves these axes: for `bbox=70,0,100,20`, latitude is `[20.0 … 0.0]` descending, longitude `[70.0 … 100.0]` ascending, shape `[81,121]`, and `arrayOrder` is `[latitude,longitude]`. All longitudes remain inside `[-180,180)`. This closes the NetCDF-to-JSON round-trip check from Task 2.0.5.
