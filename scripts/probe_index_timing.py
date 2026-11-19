"""Time two clean AIFS downloads and their GRIB decode/index steps."""

from pathlib import Path
import hashlib
import pickle
from time import perf_counter

import cfgrib
from ecmwf.opendata import Client
from eccodes import codes_get, codes_grib_new_from_file, codes_release

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "raw" / "index-timing-aifs-tp-step-6.grib2"
CFGRIB_INDEX = ROOT / "data" / "cache" / "cfgrib" / "index-timing-aifs-tp-step-6" / "{short_hash}.idx"
RUN_DATE = "2026-11-18"
RUN_TIME = 18


def clear_local_cache() -> None:
    for path in TARGET.parent.glob(TARGET.name + "*"):
        path.unlink(missing_ok=True)


def decode(indexpath: str | None = None) -> None:
    kwargs = {} if indexpath is None else {"indexpath": indexpath}
    for ds in cfgrib.open_datasets(TARGET, **kwargs):
        if "tp" in ds:
            print(f"  decoded tp shape={ds.tp.shape}; units={ds.tp.attrs.get('units')}")
        ds.close()


def message_metadata() -> None:
    messages = []
    with TARGET.open("rb") as stream:
        while (handle := codes_grib_new_from_file(stream)) is not None:
            messages.append({key: codes_get(handle, key) for key in ("stepRange", "stepType", "packingType", "units")})
            codes_release(handle)
    print(f"  GRIB message count={len(messages)} metadata={messages}")


def sidecar_metadata() -> None:
    path = TARGET.with_name(TARGET.name + ".5b7b6.idx")
    if path.exists():
        try:
            with path.open("rb") as stream:
                index = pickle.load(stream)
            print(
                f"  downloaded sidecar bytes={path.stat().st_size}; "
                f"indexType={type(index).__name__}; fieldset={getattr(index, 'fieldset', None)!r}; "
                f"protocol={getattr(index, 'index_protocol_version', None)}"
            )
        except Exception as exc:
            print(f"  downloaded sidecar is not a cfgrib pickle: {type(exc).__name__}: {exc}")
    else:
        print("  no downloaded .5b7b6.idx sidecar found")


def main() -> None:
    client = Client(source="ecmwf", model="aifs-single")
    for trial in (1, 2):
        clear_local_cache()
        start = perf_counter()
        result = client.retrieve(
            date=RUN_DATE,
            time=RUN_TIME,
            stream="oper",
            type="fc",
            param="tp",
            step=6,
            target=str(TARGET),
        )
        retrieval_seconds = perf_counter() - start
        digest = hashlib.sha256(TARGET.read_bytes()).hexdigest()
        print(f"trial {trial}: retrieval={retrieval_seconds:.3f}s run={result.datetime} bytes={TARGET.stat().st_size} sha256={digest}")
        message_metadata()
        sidecar_metadata()
        start = perf_counter()
        decode()
        cold_decode_seconds = perf_counter() - start
        print(f"trial {trial}: first decode/index={cold_decode_seconds:.3f}s")
        start = perf_counter()
        decode()
        warm_decode_seconds = perf_counter() - start
        print(f"trial {trial}: second decode/index={warm_decode_seconds:.3f}s")
        print(f"  sidecars={[p.name for p in TARGET.parent.glob(TARGET.name + '*') if p != TARGET]}")

    CFGRIB_INDEX.parent.mkdir(parents=True, exist_ok=True)
    for p in CFGRIB_INDEX.parent.glob("*.idx"):
        p.unlink()
    for label in ("custom-index cold", "custom-index warm"):
        start = perf_counter()
        decode(str(CFGRIB_INDEX))
        print(f"{label}: {perf_counter() - start:.3f}s")
    print(f"custom index files: {[p.name for p in CFGRIB_INDEX.parent.glob('*.idx')]}")


if __name__ == "__main__":
    main()
