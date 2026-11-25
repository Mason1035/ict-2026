"""Configurable synthetic instability bands, explicitly not a safety factor."""

from dataclasses import dataclass
import math

from .config import STATES


@dataclass(frozen=True)
class PhysicsState:
    moisture: float
    instability_drive: float
    displacement: float
    velocity: float
    state: str


def evaluate_state(moisture, theta_deg, parameters, previous=None, dt_s=0.0):
    if not math.isfinite(moisture) or not 0 <= moisture <= 1:
        raise ValueError("slope: moisture must be finite in [0, 1]")
    if not math.isfinite(theta_deg) or not 0 <= theta_deg <= 90:
        raise ValueError("slope: theta_deg must be finite in [0, 90]")
    if not math.isfinite(dt_s) or (previous is not None and dt_s <= 0):
        raise ValueError("slope: update requires finite dt_s > 0")
    # SIMULATION_ONLY: dimensionless moisture times a monotone slope-angle
    # factor. It is neither a factor of safety nor a geotechnical failure law.
    # Thresholds apply to I, not directly to moisture. Equality enters the
    # higher band. Recovery is allowed before failure; FAILURE is absorbing.
    drive = moisture * math.sin(math.radians(theta_deg))
    thresholds = [parameters[key] for key in (
        "saturation_threshold", "creep_threshold", "slip_threshold", "failure_threshold"
    )]
    state = STATES[sum(drive >= threshold for threshold in thresholds)]
    if previous is not None and previous.state == "FAILURE":
        state = "FAILURE"
    # State-specific constant speeds are deliberate software coverage knobs,
    # in synthetic m/s, not measured material velocities. No rainfall clock
    # or future failure schedule influences the dynamics.
    velocity = {
        "NORMAL": 0.0, "SATURATION": 0.0,
        "CREEP": parameters["creep_rate"],
        "INCIPIENT_SLIP": parameters["slip_rate"],
        "FAILURE": parameters["failure_rate"],
    }[state]
    # Causal left-endpoint integration: row n reports D_n and v_n, and
    # D_(n+1) = D_n + v_n*dt. Newly observed moisture cannot rewrite the past
    # interval. Initial displacement is zero by definition of the origin.
    displacement = 0.0 if previous is None else previous.displacement + previous.velocity * dt_s
    if not all(math.isfinite(v) for v in (drive, displacement, velocity)):
        raise ValueError("slope: non-finite state or displacement overflow")
    return PhysicsState(moisture, drive, displacement, velocity, state)
