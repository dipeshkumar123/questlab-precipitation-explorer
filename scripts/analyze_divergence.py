"""Exhaustively compare decoded step-24 model maxima and upper-tail occupancy."""

from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
RUN = "20261118T18Z"
BIN_WIDTH_MM = 1.0
TAIL_START_MM = 100.0


def analyze(model: str) -> dict:
    path = ROOT / "data" / "processed" / model / RUN / "tp.nc"
    with xr.open_dataset(path, engine="h5netcdf") as dataset:
        values = np.asarray(dataset.tp_cumulative_mm.sel(step_hours=24).values, dtype=np.float64)
        latitude = np.asarray(dataset.latitude.values, dtype=np.float64)
        longitude = np.asarray(dataset.longitude.values, dtype=np.float64)
    finite = np.isfinite(values)
    maximum = float(np.max(values[finite]))
    max_indices = np.argwhere(finite & (values == maximum))
    max_cells = [
        {"latitude": float(latitude[row]), "longitude": float(longitude[col])}
        for row, col in max_indices
    ]
    tail_values = values[finite & (values >= TAIL_START_MM)]
    bin_edges = np.arange(TAIL_START_MM, math.ceil(maximum) + BIN_WIDTH_MM + 1e-9, BIN_WIDTH_MM)
    histogram, edges = np.histogram(tail_values, bins=bin_edges)
    bins = [
        {"fromMm": float(edges[index]), "toMmExclusive": float(edges[index + 1]), "count": int(count)}
        for index, count in enumerate(histogram)
    ]
    exact_counts = Counter(tail_values.tolist())
    most_common_exact = sorted(exact_counts.items(), key=lambda item: (-item[1], -item[0]))[:10]
    occupied_bins = [item for item in bins if item["count"]]
    coarse_histogram = []
    for start in np.arange(TAIL_START_MM, math.ceil(maximum / 10) * 10, 10.0):
        end = start + 10.0
        coarse_histogram.append(
            {
                "fromMm": float(start),
                "toMmExclusive": float(end),
                "count": int(np.count_nonzero((tail_values >= start) & (tail_values < end))),
            }
        )
    row, col = (int(value) for value in max_indices[0])
    return {
        "model": model,
        "sourceFile": str(path.relative_to(ROOT)),
        "gridShape": list(values.shape),
        "finitePointCount": int(np.count_nonzero(finite)),
        "tailStartMm": TAIL_START_MM,
        "tailPointCount": int(tail_values.size),
        "maximumMm": maximum,
        "maximumCellCount": len(max_cells),
        "maximumCells": max_cells,
        "maximumGridIndex": [row, col],
        "exactValueMaxMultiplicityInTail": max(exact_counts.values()),
        "mostCommonExactTailValues": [{"valueMm": float(value), "count": int(count)} for value, count in most_common_exact],
        "mostOccupiedOneMmBin": max(occupied_bins, key=lambda item: item["count"]),
        "histogramOneMmBins": bins,
        "histogramTenMmSummary": coarse_histogram,
    }


def main() -> None:
    results = [analyze(model) for model in ("aifs-single", "ifs")]
    same_max_cell = results[0]["maximumGridIndex"] == results[1]["maximumGridIndex"]
    report = {
        "measuredAtUtc": datetime.now(timezone.utc).isoformat(),
        "run": "2026-11-18T18:00:00Z",
        "variable": "tp_cumulative_mm at step_hours=24",
        "binWidthMm": BIN_WIDTH_MM,
        "tailStartMmInclusive": TAIL_START_MM,
        "sameMaximumGridCell": same_max_cell,
        "models": results,
    }
    output = ROOT / "artifacts" / "model-tail-stage3-0.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for result in results:
        print(
            f"{result['model']}: n={result['finitePointCount']} tail>=100={result['tailPointCount']} "
            f"max={result['maximumMm']:.6f}mm cells={result['maximumCellCount']} "
            f"coords={result['maximumCells']} exactTailMultiplicity={result['exactValueMaxMultiplicityInTail']} "
            f"max1mmBin={result['mostOccupiedOneMmBin']}"
        )
        print("10mm tail bins:", result["histogramTenMmSummary"])
    print(f"same_maximum_grid_cell={same_max_cell}")
    print(f"full one-mm histogram={output}")


if __name__ == "__main__":
    main()
