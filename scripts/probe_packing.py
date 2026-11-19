"""Inspect packing limits and decoded tail occupancy with ecCodes bindings."""

from pathlib import Path

import numpy as np
from eccodes import codes_get, codes_get_values, codes_grib_new_from_file, codes_release

ROOT = Path(__file__).resolve().parents[1]
RUN = "20261118T18Z"


def main() -> None:
    for model in ("aifs-single", "ifs"):
        path = ROOT / "data" / "raw" / model / RUN / "tp-through-024h.grib2"
        print(f"model={model} file={path}")
        with path.open("rb") as stream:
            while (handle := codes_grib_new_from_file(stream)) is not None:
                try:
                    keys = {
                        name: codes_get(handle, name)
                        for name in (
                            "stepRange",
                            "packingType",
                            "bitsPerValue",
                            "binaryScaleFactor",
                            "decimalScaleFactor",
                            "numberOfValues",
                            "referenceValue",
                            "units",
                        )
                    }
                    values = np.asarray(codes_get_values(handle), dtype=np.float64)
                    decimal_multiplier = 10.0 ** (-keys["decimalScaleFactor"])
                    ceiling = (
                        keys["referenceValue"]
                        + (2**keys["bitsPerValue"] - 1) * 2.0**keys["binaryScaleFactor"]
                    ) * decimal_multiplier
                    scale_to_mm = 1000.0 if keys["units"] == "m" else 1.0
                    maximum = float(values.max())
                    quantization = 2.0**keys["binaryScaleFactor"] * decimal_multiplier
                    at_ceiling = int(np.count_nonzero(np.isclose(values, ceiling, rtol=0.0, atol=1e-10)))
                    within_one_quantum = int(np.count_nonzero(values >= ceiling - quantization - 1e-10))
                    print(
                        "  grib_get -p packingType,bitsPerValue,binaryScaleFactor,"
                        "decimalScaleFactor,numberOfValues equivalent: "
                        f"{keys['packingType']} {keys['bitsPerValue']} {keys['binaryScaleFactor']} "
                        f"{keys['decimalScaleFactor']} {keys['numberOfValues']}"
                    )
                    print(
                        f"  stepRange={keys['stepRange']} units={keys['units']} reference={keys['referenceValue']} "
                        f"max={maximum * scale_to_mm:.8g} mm max_count={np.count_nonzero(values == maximum)} "
                        f"ceiling={ceiling * scale_to_mm:.8g} mm ceiling_count={at_ceiling} "
                        f"within_one_quantum_of_ceiling={within_one_quantum}"
                    )
                    if keys["stepRange"] == "0-24":
                        for threshold in (50, 100, 200, 250, 500):
                            print(
                                f"  count_above_{threshold}mm="
                                f"{int(np.count_nonzero(values * scale_to_mm > threshold))}"
                            )
                finally:
                    codes_release(handle)


if __name__ == "__main__":
    main()
