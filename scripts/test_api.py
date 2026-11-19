"""Exercise the HTTP API as a client; optionally run real-stack failure scenarios."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter

import requests
import xarray as xr

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
MODELS = ("aifs-single", "ifs")


def assert_error(response: requests.Response, status: int) -> dict:
    assert response.status_code == status, (response.status_code, response.text)
    payload = response.json()
    assert set(payload) == {"error"}, payload
    error = payload["error"]
    assert isinstance(error.get("code"), str) and error["code"], error
    assert isinstance(error.get("message"), str) and error["message"], error
    assert isinstance(error.get("details"), dict), error
    return error


def assert_valid_health(base_url: str) -> tuple[dict, float]:
    started = perf_counter()
    response = requests.get(f"{base_url}/api/v1/health", timeout=15)
    elapsed = perf_counter() - started
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["available"] is True
    assert set(MODELS).issubset(payload["models"])
    for model in MODELS:
        state = payload["models"][model]
        for field in ("sourceRunUtc", "retrievedAtUtc", "stepsHours", "processingVersion", "ageSeconds", "stale", "lastIngestSucceeded"):
            assert field in state, (model, field, state)
        assert state["lastIngestSucceeded"] is True
        assert state["stepsHours"] == [6, 12, 18, 24]
        assert isinstance(state["stale"], bool)
    return payload, elapsed


def test_healthy_api(base_url: str) -> dict:
    health, health_seconds = assert_valid_health(base_url)

    point_times = []
    point_payload = None
    for _ in range(2):
        started = perf_counter()
        response = requests.get(
            f"{base_url}/api/v1/point",
            params={"lat": 12.9716, "lon": 77.5946, "model": "all"},
            timeout=15,
        )
        point_times.append(perf_counter() - started)
        assert response.status_code == 200, response.text
        point_payload = response.json()
    assert point_payload["units"] == "mm"
    assert set(point_payload["models"]) == set(MODELS)
    for model, result in point_payload["models"].items():
        cell = result["nearestCell"]
        assert -90 <= cell["latitude"] <= 90
        assert -180 <= cell["longitude"] < 180
        assert result["negativeIntervalPolicy"] == "clip-to-zero"
        assert isinstance(result["clippedIntervalCount"], int)
        assert len(result["series"]) == 4
        assert all(record["intervalMm"] is None or record["intervalMm"] >= 0 for record in result["series"])
        assert all(isinstance(record["intervalClipped"], bool) for record in result["series"])
        assert result["stale"] == health["models"][model]["stale"]

    region_started = perf_counter()
    region_response = requests.get(
        f"{base_url}/api/v1/field",
        params={"model": "aifs-single", "stepHours": 24, "kind": "interval", "bbox": "70,0,100,20", "stride": 1},
        timeout=15,
    )
    region_seconds = perf_counter() - region_started
    assert region_response.status_code == 200, region_response.text[:1000]
    region = region_response.json()
    assert region["units"] == "mm"
    assert region["arrayOrder"] == "[latitude,longitude]"
    assert region["latitudeOrder"] == "north-to-south"
    assert region["longitudeConvention"] == "[-180,180)"
    assert region["latitude"][0] > region["latitude"][-1]
    assert region["longitude"][0] < region["longitude"][-1]
    assert region["latitude"][0] == 20.0 and region["latitude"][-1] == 0.0
    assert region["longitude"][0] == 70.0 and region["longitude"][-1] == 100.0
    assert -180.0 <= region["longitude"][0] < 180.0
    assert -180.0 <= region["longitude"][-1] < 180.0
    assert region["shape"] == [len(region["latitude"]), len(region["longitude"])]
    assert region["shape"] == [81, 121], region["shape"]
    assert len(region["values"]) == region["shape"][0]
    assert all(len(row) == region["shape"][1] for row in region["values"])
    assert region["negativeIntervalPolicy"] == "clip-to-zero"
    assert region["clippedCellCount"] > 0
    assert region["negativeIntervalsClipped"] is (region["clippedCellCount"] > 0)
    assert len(region_response.content) <= 1_048_576
    assert len(region_response.content) > 0

    missing_step = requests.get(
        f"{base_url}/api/v1/field",
        params={"model": "aifs-single", "stepHours": 48, "kind": "interval", "bbox": "70,0,80,10", "stride": 1},
        timeout=15,
    )
    missing_error = assert_error(missing_step, 404)
    assert missing_error["code"] == "step_unavailable"
    assert missing_error["details"]["availableSteps"] == [6, 12, 18, 24]

    too_wide = requests.get(
        f"{base_url}/api/v1/field",
        params={"model": "aifs-single", "stepHours": 24, "kind": "interval", "bbox": "0,0,31,10", "stride": 1},
        timeout=15,
    )
    assert_error(too_wide, 400)
    bad_coordinate = requests.get(
        f"{base_url}/api/v1/point", params={"lat": 91, "lon": 0, "model": "ifs"}, timeout=15
    )
    assert_error(bad_coordinate, 400)

    print(
        "healthy API: health={:.4f}s point_cold={:.4f}s point_warm={:.4f}s "
        "max_region={:.4f}s bytes={} cells={}x{}; error shapes passed".format(
            health_seconds,
            point_times[0],
            point_times[1],
            region_seconds,
            len(region_response.content),
            region["shape"][0],
            region["shape"][1],
        )
    )
    return {
        "healthSeconds": round(health_seconds, 6),
        "pointColdSeconds": round(point_times[0], 6),
        "pointWarmSeconds": round(point_times[1], 6),
        "regionMaxSeconds": round(region_seconds, 6),
        "regionBytes": len(region_response.content),
        "regionCells": region["shape"][0] * region["shape"][1],
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@contextmanager
def running_server(data_dir: Path):
    port = _free_port()
    env = os.environ.copy()
    env["QUEST_DATA_DIR"] = str(data_dir)
    env["QUEST_API_HOST"] = "127.0.0.1"
    env["QUEST_API_PORT"] = str(port)
    old_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(ROOT / "src") + (os.pathsep + old_path if old_path else "")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "questlab.api:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(120):
            if process.poll() is not None:
                raise RuntimeError(f"uvicorn exited during startup with {process.returncode}")
            try:
                requests.get(f"{base_url}/api/v1/health", timeout=0.3)
                break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            raise RuntimeError("uvicorn did not become ready within 12 seconds")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_fixture(root: Path, stale: bool, failed_ingest: bool = False) -> None:
    source_root = ROOT / "data"
    for model in MODELS:
        source_model = source_root / "processed" / model
        target_model = root / "processed" / model
        shutil.copytree(source_model, target_model)
        pointer_path = target_model / "latest.json"
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        manifest_path = root / pointer["manifest"]
        artifact_path = root / pointer["artifact"]
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if stale:
            source_run = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(hours=36)
            retrieved_at = source_run + timedelta(minutes=10)
            with xr.open_dataset(artifact_path, engine="h5netcdf") as original:
                dataset = original.load()
            dataset.attrs["source_run_utc"] = source_run.isoformat()
            valid_times = [np_datetime64(source_run + timedelta(hours=int(step))) for step in dataset.step_hours.values]
            dataset["valid_time_utc"] = (("step_hours",), valid_times)
            temporary = artifact_path.with_name("tp.stale-fixture.nc")
            encoding = {
                name: {"zlib": True, "complevel": 2, "dtype": "float32", "_FillValue": float("nan")}
                for name in ("tp_cumulative_mm", "tp_interval_mm")
            }
            dataset.to_netcdf(temporary, engine="h5netcdf", encoding=encoding)
            dataset.close()
            os.replace(temporary, artifact_path)
            manifest["sourceRunUtc"] = source_run.isoformat()
            manifest["retrievedAtUtc"] = retrieved_at.isoformat()
            manifest["artifactSha256"] = _sha256(artifact_path)
            pointer["sourceRunUtc"] = source_run.isoformat()
            pointer["updatedAtUtc"] = retrieved_at.isoformat()
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
            pointer_path.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
        if failed_ingest:
            (target_model / "ingest-status.json").write_text(
                json.dumps({"model": model, "attemptedAtUtc": "2026-11-19T08:00:00+00:00", "lastIngestSucceeded": False, "state": "failed", "lastErrorMessage": "private detail"}) + "\n",
                encoding="utf-8",
            )


def np_datetime64(value: datetime):
    import numpy as np

    return np.datetime64(value.replace(tzinfo=None), "ns")


def test_failure_scenarios() -> None:
    with tempfile.TemporaryDirectory(prefix="quest-api-missing-") as missing_dir:
        with running_server(Path(missing_dir)) as base_url:
            health = requests.get(f"{base_url}/api/v1/health", timeout=15)
            assert assert_error(health, 503)["code"] == "forecast_unavailable"
            point = requests.get(f"{base_url}/api/v1/point", params={"lat": 0, "lon": 0, "model": "all"}, timeout=15)
            assert_error(point, 503)
            field = requests.get(
                f"{base_url}/api/v1/field",
                params={"model": "ifs", "stepHours": 24, "kind": "interval", "bbox": "0,0,10,10"},
                timeout=15,
            )
            assert_error(field, 503)
            print("upstream unavailable / no manifest: health, point, and field return consistent 503 JSON errors")

    with tempfile.TemporaryDirectory(prefix="quest-api-stale-") as stale_dir:
        fixture = Path(stale_dir)
        make_fixture(fixture, stale=True)
        with running_server(fixture) as base_url:
            health = requests.get(f"{base_url}/api/v1/health", timeout=15)
            assert health.status_code == 200, health.text
            health_model = health.json()["models"]["aifs-single"]
            assert health_model["stale"] is True and health_model["ageSeconds"] > 12 * 3600
            point = requests.get(
                f"{base_url}/api/v1/point", params={"lat": 12.97, "lon": 77.59, "model": "aifs-single"}, timeout=15
            )
            assert point.status_code == 200, point.text
            point_model = point.json()["models"]["aifs-single"]
            assert point_model["stale"] is True and point_model["ageSeconds"] > 12 * 3600
            field = requests.get(
                f"{base_url}/api/v1/field",
                params={"model": "aifs-single", "stepHours": 24, "kind": "interval", "bbox": "70,0,80,10"},
                timeout=15,
            )
            assert field.status_code == 200, field.text
            assert field.json()["stale"] is True and field.json()["ageSeconds"] > 12 * 3600
            print(
                f"stale manifest: health stale=true age={health_model['ageSeconds']}s; "
                "point and field still return 200 with stale=true and ageSeconds"
            )

    with tempfile.TemporaryDirectory(prefix="quest-api-failed-ingest-") as failed_dir:
        fixture = Path(failed_dir)
        make_fixture(fixture, stale=False, failed_ingest=True)
        with running_server(fixture) as base_url:
            health = requests.get(f"{base_url}/api/v1/health", timeout=15)
            assert health.status_code == 200, health.text
            state = health.json()["models"]["aifs-single"]
            assert state["available"] is True and state["lastIngestSucceeded"] is False
            assert state["lastIngestAttemptedAtUtc"] == "2026-11-19T08:00:00Z"
            assert state["lastError"]["code"] == "ingest_failed"
            assert "private detail" not in health.text
            point = requests.get(f"{base_url}/api/v1/point", params={"lat": 12, "lon": 77, "model": "aifs-single"}, timeout=15)
            assert point.status_code == 200 and point.json()["models"]["aifs-single"]["lastIngestSucceeded"] is False
            field = requests.get(f"{base_url}/api/v1/field", params={"model": "aifs-single", "stepHours": 24, "kind": "interval", "bbox": "70,0,80,10"}, timeout=15)
            assert field.status_code == 200 and field.json()["lastIngestSucceeded"] is False
            print("failed latest ingest: health reports failure and safe error; prior verified point/field remain available")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="URL of an already-running questlab-api instance")
    parser.add_argument("--failure-scenarios", action="store_true", help="also launch real uvicorn instances for missing/stale data scenarios")
    args = parser.parse_args()
    measurements = test_healthy_api(args.base_url.rstrip("/"))
    output = ROOT / "artifacts" / "api-latency-stage2.json"
    output.write_text(json.dumps({"measuredAtUtc": datetime.now(timezone.utc).isoformat(), **measurements}, indent=2) + "\n", encoding="utf-8")
    print(f"latency report={output}")
    if args.failure_scenarios:
        test_failure_scenarios()


if __name__ == "__main__":
    main()
