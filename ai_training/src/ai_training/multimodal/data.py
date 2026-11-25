"""Source-native observed sequences, independent of the formal B dataset contract."""

from copy import deepcopy
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SensorSeries:
    source_id: str
    run_id: str
    group_id: str
    modality: str
    values: np.ndarray
    times: np.ndarray
    channel_names: tuple[str, ...]
    units: tuple[str, ...]
    time_unit: str
    provenance: dict

    def __post_init__(self):
        for name in ("source_id", "run_id", "group_id", "time_unit"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be an explicit nonempty string")
        if self.modality not in ("soil", "motion"):
            raise ValueError("modality must be soil or motion")
        for name, rank in (("values", 2), ("times", 1)):
            array = np.asarray(getattr(self, name))
            if array.ndim != rank or array.dtype.kind not in "iuf":
                raise ValueError(f"{name} must be a rank-{rank} real numeric array")
            if not np.isfinite(array).all():
                raise ValueError(f"{name} must contain only finite observations")
            array = np.array(array, dtype=np.float64, copy=True)
            array.setflags(write=False)
            object.__setattr__(self, name, array)
        rows, columns = self.values.shape
        if rows == 0 or columns == 0 or self.times.shape != (rows,):
            raise ValueError("values/times must have matching nonempty observation dimensions")
        if not np.all(np.diff(self.times) > 0):
            raise ValueError("source observation times must strictly increase")
        for name in ("channel_names", "units"):
            names = getattr(self, name)
            if (not isinstance(names, tuple) or len(names) != columns
                    or any(not isinstance(value, str) or not value.strip() for value in names)):
                raise ValueError(f"{name} must identify every observed channel")
        if len(set(self.channel_names)) != columns:
            raise ValueError("channel names must be unique")
        if not isinstance(self.provenance, dict):
            raise ValueError("provenance must be a separate dictionary")
        object.__setattr__(self, "provenance", deepcopy(self.provenance))
