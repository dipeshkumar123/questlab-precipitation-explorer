"""Build the static UI and start the full local app on one origin."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    environment = os.environ.copy()
    environment["QUEST_API_BASE_URL"] = ""
    environment["QUEST_DATA_DIR"] = str(ROOT / "data")
    environment["QUEST_STATIC_DIR"] = str(ROOT / "dist")
    environment.setdefault("QUEST_API_HOST", "127.0.0.1")
    environment.setdefault("PORT", environment.get("QUEST_API_PORT", "8000"))
    subprocess.run([sys.executable, "scripts/build_frontend.py"], cwd=ROOT, env=environment, check=True)
    os.execvpe(
        sys.executable,
        [sys.executable, "-m", "uvicorn", "questlab.api:app", "--host", environment["QUEST_API_HOST"], "--port", environment["PORT"], "--workers", "1"],
        environment,
    )


if __name__ == "__main__":
    main()
