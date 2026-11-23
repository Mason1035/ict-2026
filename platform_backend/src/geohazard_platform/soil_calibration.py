"""Versioned display adapter; never writes Telemetry VWC or risk."""
from algorithm.B_revised.data_intake.air_water_adapter import load_parameters, evaluate_observation

CHANNELS = {"top": 0, "middle": 1, "toe": 2}

def evaluate(soil, context=None):
    context = context or {}
    parameters = load_parameters()
    firmware = context.get("firmware_elf_sha256")
    values = {}
    flags = []
    for name, channel in CHANNELS.items():
        result = evaluate_observation(channel=channel, raw=soil[name + "_raw"],
            valid=True, firmware_sha256=firmware, parameters=parameters)
        values[name] = result["w_rel_pct"]
        flags.extend(f"soil.{name}:{flag}" for flag in result["quality_flags"])
    return values, flags, {"version": parameters["version"], "unit": parameters["unit"],
        "firmware_elf_sha256": firmware, "applicable": firmware == parameters["firmware_elf_sha256"],
        "evidence": context.get("firmware_evidence", "not_provided"),
        "vwc_calibrated": False, "risk_eligible": False, "fusion_eligible": False}
