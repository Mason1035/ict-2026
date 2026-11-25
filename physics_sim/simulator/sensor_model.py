"""Causal synthetic observations of physics; never controls the physics layer."""

import math

import numpy as np

from .config import IMU_SITES, SOIL_SITES, grid_steps


class SensorModel:
    def __init__(self, parameters, initial_moisture, dt_s, rng: np.random.Generator):
        self.parameters = parameters
        self.initial_moisture = initial_moisture
        self.dt_s = dt_s
        # The caller owns the only Generator; never seed or create one here.
        self.rng = rng
        self.moisture_history = []
        self.previous_tilt = {}
        self.delays = {site: grid_steps(parameters["soil_sites"][site]["delay_s"], dt_s, site) for site in SOIL_SITES}

    def observe(self, physics):
        self.moisture_history.append(physics.moisture)
        n = len(self.moisture_history) - 1
        result = {}
        for site in SOIL_SITES:
            p = self.parameters["soil_sites"][site]
            # Delayed response to CHANGE from M0, with M0 as constant prehistory.
            # This gives distinct top/middle/toe responses without using future
            # moisture. SIMULATION_ONLY spatial surrogate, not water transport.
            # TODO_CALIBRATION: site gains/delays from controlled experiments.
            delayed = self.moisture_history[max(0, n - self.delays[site])]
            value = self.initial_moisture + p["response_coefficient"] * (delayed - self.initial_moisture)
            value += self.rng.normal(0, self.parameters["soil_noise_std"])
            if not math.isfinite(value):
                raise ValueError(f"sensor.soil_{site}: non-finite observation")
            result[f"soil_{site}"] = float(np.clip(value, 0, 1))
        for site in IMU_SITES:
            p = self.parameters["imu_sites"][site]
            # Linear D->tilt maps synthetic metres to degrees; this is not a
            # geometric instrument model. Difference the noisy current/past tilt,
            # so tilt-rate noise depends on dt. At the first point there is no
            # previous observation: the rate is unknown, not a physical zero.
            tilt = p["base_tilt_deg"] + p["tilt_gain_deg_per_m"] * physics.displacement
            tilt += self.rng.normal(0, self.parameters["imu_noise_std"])
            rate_valid = site in self.previous_tilt
            tilt_rate = (tilt - self.previous_tilt[site]) / self.dt_s if rate_valid else None
            self.previous_tilt[site] = tilt
            # Velocity (m/s) times gain (1/s) produces an acceleration-amplitude
            # proxy (m/s^2). State affects it through velocity. This is a synthetic
            # RMS-like channel, not RMS computed from an accelerometer waveform.
            vibration = p["vibration_base_mps2"] + p["vibration_gain_per_s"] * abs(physics.velocity)
            vibration += self.rng.normal(0, self.parameters["vibration_noise_std"])
            if not all(math.isfinite(v) for v in (tilt, vibration)) or (rate_valid and not math.isfinite(tilt_rate)):
                raise ValueError(f"sensor.imu_{site}: non-finite observation")
            result.update({
                f"imu_{site}_tilt_deg": float(tilt),
                f"imu_{site}_tilt_rate_dps": float(tilt_rate) if rate_valid else None,
                f"imu_{site}_tilt_rate_valid": rate_valid,
                f"imu_{site}_vibration_rms": float(max(0, vibration)),
            })
        return result
