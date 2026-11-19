"""Build the dependency-free static front end into dist/."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "frontend"
OUTPUT = ROOT / "dist"


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "styles.css", "app.js"):
        shutil.copy2(SOURCE / name, OUTPUT / name)
    api_base_url = os.environ.get("QUEST_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    (OUTPUT / "config.js").write_text(
        f"window.QUEST_API_BASE_URL = {json.dumps(api_base_url)};\n",
        encoding="utf-8",
    )
    print(f"Built static frontend: {OUTPUT}")
    print(f"API base URL: {api_base_url or '(same origin; proxy /api to FastAPI)'}")


if __name__ == "__main__":
    main()
