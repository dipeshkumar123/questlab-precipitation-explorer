"""Measure fresh-cache retrieval-through-NetCDF pipeline wall time."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    measured_at = datetime.now(timezone.utc)
    stamp = measured_at.strftime("%Y%m%dT%H%M%SZ")
    run_root = ROOT / "data" / "benchmark" / f"cold-{stamp}"
    results = []
    for model in ("aifs-single", "ifs"):
        data_dir = run_root / model
        command = [
            sys.executable,
            "-m",
            "questlab.pipeline",
            "--model",
            model,
            "--date",
            "2026-11-18",
            "--time",
            "18",
            "--max-step",
            "24",
            "--data-dir",
            str(data_dir),
        ]
        started = time.perf_counter()
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        elapsed = time.perf_counter() - started
        print(f"{model}: returncode={completed.returncode} wall_seconds={elapsed:.3f}")
        print(completed.stdout.strip())
        if completed.stderr.strip():
            print("stderr:", completed.stderr.strip())
        if completed.returncode:
            raise SystemExit(completed.returncode)
        results.append(
            {
                "model": model,
                "command": command,
                "wallSeconds": round(elapsed, 3),
                "exitCode": completed.returncode,
                "cache": "fresh data-dir with no GRIB, NetCDF, or cfgrib index files",
            }
        )
    report = {"measuredAtUtc": measured_at.isoformat(), "run": "2026-11-18T18:00:00Z", "results": results}
    output = ROOT / "artifacts" / "ingest-latency-stage2-0.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"report={output}")


if __name__ == "__main__":
    main()
