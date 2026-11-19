"""Render a cumulative field beside its 6-hour increment from a GRIB2 file."""

from __future__ import annotations

import argparse
from pathlib import Path

import cfgrib
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import LogNorm

ROOT = Path(__file__).resolve().parents[1]


def load_fields(path: Path) -> tuple[dict[int, np.ndarray], np.ndarray, np.ndarray, str]:
    cache_key = path.relative_to(ROOT / "data" / "raw").with_suffix("")
    cache = ROOT / "data" / "cache" / "cfgrib" / cache_key / "{short_hash}.idx"
    cache.parent.mkdir(parents=True, exist_ok=True)
    datasets = cfgrib.open_datasets(path, indexpath=str(cache))
    result: dict[int, np.ndarray] = {}
    latitude = longitude = None
    units = ""
    for ds in datasets:
        if "tp" not in ds:
            ds.close()
            continue
        units = ds.tp.attrs.get("units", "")
        latitude, longitude = np.asarray(ds.latitude.values), np.asarray(ds.longitude.values)
        values = np.asarray(ds.tp.values, dtype=np.float64)
        if units == "m":
            values *= 1000.0
        elif units not in ("kg m**-2", "kg m-2"):
            raise ValueError(f"Unsupported precipitation units {units!r}")
        for i, step in enumerate(np.asarray(ds.step.values)):
            hours = int(step / np.timedelta64(1, "h"))
            result[hours] = values[i]
        ds.close()
    if latitude is None or longitude is None or not result:
        raise ValueError(f"No total precipitation field found in {path}")
    return result, latitude, longitude, units


def local_maxima(field: np.ndarray, latitude: np.ndarray, longitude: np.ndarray, count: int = 5):
    valid = np.isfinite(field)
    neighborhood = field.copy()
    for dy in (-1, 0, 1):
        rows = np.clip(np.arange(field.shape[0]) + dy, 0, field.shape[0] - 1)
        for dx in (-1, 0, 1):
            shifted = np.roll(field[rows, :], dx, axis=1)
            neighborhood = np.maximum(neighborhood, shifted)
    candidates = np.argwhere(valid & (field >= 0.1) & (field == neighborhood))
    candidates = sorted(candidates, key=lambda rc: field[rc[0], rc[1]], reverse=True)
    selected = []
    for row, col in candidates:
        if all(max(abs(row - r), min(abs(col - c), field.shape[1] - abs(col - c))) >= 8
               for r, c in selected):
            selected.append((int(row), int(col)))
            if len(selected) == count:
                break
    return [(float(field[r, c]), float(latitude[r]), float(longitude[c])) for r, c in selected]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", choices=("aifs-single", "ifs"), default="aifs-single")
    parser.add_argument("--run-date", default="2026-11-18")
    parser.add_argument("--time", type=int, default=18)
    parser.add_argument("--step", type=int, default=24)
    parser.add_argument("--max-step", type=int, default=24, help="max step used when retrieving the GRIB")
    args = parser.parse_args()
    stamp = f"{args.run_date.replace('-', '')}T{args.time:02d}Z"
    path = ROOT / "data" / "raw" / args.model / stamp / f"tp-through-{args.max_step:03d}h.grib2"
    if not path.exists():
        # Also accept the flat probe files created by scripts/probe_accumulation.py.
        path = ROOT / "data" / "raw" / f"{args.model}-{args.run_date}-t{args.time:02d}-tp.grib2"
    if not path.exists():
        raise FileNotFoundError(f"Retrieve the run first: {path}")
    fields, latitude, longitude, units = load_fields(path)
    prior_step = args.step - 6
    if args.step not in fields or prior_step not in fields:
        raise ValueError(f"Need both steps {prior_step} and {args.step}; available: {sorted(fields)}")
    accumulated = fields[args.step]
    interval = accumulated - fields[prior_step]
    max_row, max_col = np.unravel_index(np.nanargmax(accumulated), accumulated.shape)
    print(f"model={args.model}, run={args.run_date} {args.time:02d}:00 UTC, source_units={units}")
    print(f"latitude order={latitude[0]} to {latitude[-1]} ({'north-to-south' if latitude[0] > latitude[-1] else 'south-to-north'}), "
          f"longitude order={longitude[0]} to {longitude[-1]}")
    print(f"global max: {accumulated[max_row,max_col]:.6g} mm at ({latitude[max_row]:.2f}, {longitude[max_col]:.2f})")
    print("top five spatially separated 3x3 local maxima (mm, lat, lon):")
    for value, lat, lon in local_maxima(accumulated, latitude, longitude):
        print(f"  {value:.6g}, {lat:.2f}, {lon:.2f}")
    print(f"interval negative cells from packing/rounding: {np.count_nonzero(interval < 0)}; "
          f"minimum={np.nanmin(interval):.6g} mm")

    vmax = max(float(np.nanmax(accumulated)), float(np.nanmax(interval)), 0.1)
    norm = LogNorm(vmin=0.1, vmax=max(vmax, 0.1001))
    fig, axes = plt.subplots(2, 1, figsize=(15, 8), constrained_layout=True)
    fig.suptitle(f"{args.model}: total precipitation · {args.run_date} {args.time:02d}Z", fontsize=15)
    panels = [
        (axes[0], accumulated, f"Cumulative from initialization · step {args.step} h"),
        (axes[1], interval, f"6-hour increment · step {prior_step}–{args.step} h"),
    ]
    mesh = None
    for ax, values, title in panels:
        ax.set_facecolor("#eef1f4")
        shown = np.ma.masked_where(~np.isfinite(values) | (values < 0.1), values)
        mesh = ax.pcolormesh(longitude, latitude, shown, cmap="YlGnBu", norm=norm, shading="auto", rasterized=True)
        ax.set_xlim(-180, 180)
        ax.set_ylim(-90, 90)
        ax.set_ylabel("Latitude (°)")
        ax.set_title(title, loc="left", fontsize=11)
        ax.set_xticks(np.arange(-180, 181, 60))
        ax.set_yticks(np.arange(-60, 91, 30))
        ax.grid(color="#77808a", linewidth=0.25, alpha=0.35)
    axes[1].set_xlabel("Longitude (°; −180 to 180)")
    colorbar = fig.colorbar(mesh, ax=axes, shrink=0.92, pad=0.02)
    colorbar.set_label("Precipitation depth (mm; logarithmic, <0.1 mm masked)")
    output = ROOT / "artifacts" / f"field-inspection-{args.model}-{args.run_date}-t{args.time:02d}-step{args.step}.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=150)
    plt.close(fig)
    print(f"image: {output}")


if __name__ == "__main__":
    main()
