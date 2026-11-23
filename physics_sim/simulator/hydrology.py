"""Bounded normalized storage; NOT Richards equation or calibrated hydrology."""

import math


def update_moisture(moisture, rainfall, dt_s, infiltration_rate, drainage_rate):
    values = (moisture, rainfall, dt_s, infiltration_rate, drainage_rate)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("hydrology: non-finite input")
    if not 0 <= moisture <= 1 or rainfall < 0 or dt_s <= 0 or min(infiltration_rate, drainage_rate) < 0:
        raise ValueError("hydrology: invalid moisture/rainfall/dt/rate")
    # ------------------------------------------------------------------
    # Physics-inspired normalized storage: dM/dt = a*(1-M) - b*M,
    # a = infiltration_rate * R, b = drainage_rate. R is in mm/h, while
    # infiltration_rate is (mm/h)^-1 s^-1; hence a and b are both s^-1.
    # Exact integration under constant rainfall over this interval preserves
    # bounds even for large dt, unlike unclamped explicit Euler. expm1 avoids
    # cancellation for small rates. This is SIMULATION_ONLY, not a validated
    # soil-water model. TODO_CALIBRATION: storage, infiltration and drainage.
    # ------------------------------------------------------------------
    a = infiltration_rate * rainfall
    rate = a + drainage_rate
    if not math.isfinite(rate) or not math.isfinite(rate * dt_s):
        raise ValueError("hydrology: rate or rate*dt overflow")
    if rate == 0:
        return moisture
    equilibrium = a / rate
    result = moisture + (equilibrium - moisture) * (-math.expm1(-rate * dt_s))
    if not math.isfinite(result):
        raise ValueError("hydrology: non-finite moisture")
    # Only roundoff protection: bounded analytical evolution precedes clipping.
    return min(1.0, max(0.0, result))
