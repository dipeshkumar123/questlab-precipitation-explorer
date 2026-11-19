"""Retrieve and inspect one real AIFS total-precipitation forecast field."""

from pathlib import Path

import cfgrib
import numpy as np
from ecmwf.opendata import Client


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "data" / "raw" / "aifs-tp-step-6.grib2"


def main() -> None:
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    client = Client(source="ecmwf", model="aifs-single")
    result = client.retrieve(
        stream="oper",
        type="fc",
        param="tp",
        step=6,
        target=str(TARGET),
    )
    print(f"retrieval run datetime: {result.datetime}")
    datasets = cfgrib.open_datasets(TARGET)
    if not datasets:
        raise RuntimeError("GRIB file contained no decodable datasets")
    for index, dataset in enumerate(datasets):
        print(f"dataset {index}: variables={list(dataset.data_vars)}")
        for name, field in dataset.data_vars.items():
            values = np.asarray(field.values)
            finite = values[np.isfinite(values)]
            print(f"  field={name} shape={field.shape} dims={field.dims}")
            print(f"  coordinates={list(dataset.coords)}")
            for coord_name in ("latitude", "longitude"):
                if coord_name in dataset.coords:
                    coord = np.asarray(dataset.coords[coord_name].values)
                    print(f"  {coord_name}_range=({coord.min()}, {coord.max()})")
            print(f"  units={field.attrs.get('units', 'unknown')}")
            print(
                "  finite summary: "
                f"count={finite.size} min={finite.min():.8g} "
                f"mean={finite.mean():.8g} max={finite.max():.8g}"
            )
        dataset.close()
    print(f"saved GRIB2: {TARGET}")


if __name__ == "__main__":
    main()
