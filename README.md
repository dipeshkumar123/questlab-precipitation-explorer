# QUEST precipitation explorer

Early-stage project for exploring ECMWF Open Data precipitation forecasts.

## Stage 0 status

The initial probe uses AIFS deterministic forecasts and total precipitation (`tp`). See [scripts/probe_ecmwf.py](scripts/probe_ecmwf.py) for the exact request. Verified run: `2026-11-18 18:00 UTC`, step 6, field shape `(721, 1440)`, global 0.25° grid, GRIB units `kg m**-2`, values 0–79.875 (mean 0.6158). The parameter database documents `tp` in metres, while this forecast GRIB encodes it as mass per area, numerically equivalent to millimetres of water depth. `tp` is accumulated precipitation; its period semantics need confirmation before converting forecast steps into interval amounts. ECMWF open data is retained for only a limited recent window, so the final app will report the forecast initialization time and freshness.

## Setup

Python 3.11 or newer is recommended. Create an environment and install dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Probe

```powershell
python scripts/probe_ecmwf.py
```

The probe downloads a real ECMWF field and requires network access. Output is written under `data/raw/`.

## Session log

Codex rollout: to be recorded at handover. Expected location: `C:\Users\panji\.codex\sessions\YYYY\MM\DD\rollout-*.jsonl`.
