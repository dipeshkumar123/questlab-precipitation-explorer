"""Create a minimal Railway/Docker context with verified processed snapshots."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ROOT / ".deploy" / "context"
MODELS = ("aifs-single", "ifs")


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.egg-info"))


def main() -> None:
    if CONTEXT.exists():
        shutil.rmtree(CONTEXT)
    CONTEXT.mkdir(parents=True)
    for name in ("Dockerfile", "pyproject.toml", "README.md"):
        shutil.copy2(ROOT / name, CONTEXT / name)
    copy_tree(ROOT / "src", CONTEXT / "src")
    copy_tree(ROOT / "frontend", CONTEXT / "frontend")
    (CONTEXT / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts" / "build_frontend.py", CONTEXT / "scripts" / "build_frontend.py")

    processed = CONTEXT / "data" / "processed"
    for model in MODELS:
        model_source = ROOT / "data" / "processed" / model
        pointer_path = model_source / "latest.json"
        if not pointer_path.is_file():
            raise SystemExit(f"Required latest pointer is missing: {pointer_path}")
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
        # Latest pointers are generated with host-native separators; write portable
        # relative paths because the image runs on Linux.
        for key in ("artifact", "manifest"):
            pointer[key] = pointer[key].replace("\\", "/")
        model_target = processed / model
        model_target.mkdir(parents=True, exist_ok=True)
        (model_target / "latest.json").write_text(json.dumps(pointer, indent=2) + "\n", encoding="utf-8")
        for key in ("artifact", "manifest"):
            source = (ROOT / "data" / pointer[key]).resolve()
            if not source.is_relative_to((ROOT / "data").resolve()) or not source.is_file():
                raise SystemExit(f"Invalid or missing {key} referenced by {pointer_path}")
            relative = source.relative_to(ROOT / "data")
            destination = CONTEXT / "data" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        status = model_source / "ingest-status.json"
        if status.is_file():
            shutil.copy2(status, model_target / status.name)

    total_bytes = sum(path.stat().st_size for path in CONTEXT.rglob("*") if path.is_file())
    print(f"Prepared {CONTEXT} ({total_bytes:,} bytes)")
    print("Included: app source, frontend source, and latest verified artifacts for AIFS/IFS.")
    print("Excluded: raw GRIB, cfgrib cache, benchmarks, and unrelated processed runs.")


if __name__ == "__main__":
    main()
