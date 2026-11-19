"""Normalize host-native path separators in model latest pointers for Linux."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/processed")
    for model in ("aifs-single", "ifs"):
        pointer_path = root / model / "latest.json"
        if not pointer_path.is_file():
            continue
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        for key in ("artifact", "manifest"):
            pointer[key] = pointer[key].replace("\\", "/")
            target = root.parent / pointer[key]
            if not target.is_file():
                raise SystemExit(f"{key} referenced by {pointer_path} is missing: {target}")
        pointer_path.write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
