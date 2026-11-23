"""TEST_ONLY projection boundary, NOT Zhang Pengfei's algorithm or Missing Policy."""

from mock_loader import payload_hash, plain


def receive_validated(payload, *, context):
    """Future integration seam: preserve inputs, do not score or invent calibration.

    payload is the same read-only mapping passed independently to Edge Handoff.
    context['sampling_snapshot'] is TEST_ONLY sidecar, not a v2 field or fix for G03.
    The projection is local handoff evidence, NOT an approved algorithm input model.
    """
    projection = {
        "identity": {key: payload[key] for key in ("device_id", "boot_id", "seq")},
        "time": {key: payload[key] for key in ("uptime_ms", "timestamp_ms", "time_synced")},
        "imu": plain(payload["imu"]),
        "soil": plain(payload["soil"]),
        "risk": plain(payload["risk"]),
        "system": plain(payload["system"]),
    }
    return {
        "status": "ACCEPTED", "scope": "TEST_ONLY_PROJECTION_NOT_FORMAL_RISK_INPUT",
        "source": context["source"], "payload_sha256": payload_hash(payload),
        "projection": projection,
        "test_only_sidecar": {"scope": "TEST_ONLY_NOT_PRODUCTION_INTERFACE",
                              "sampling_snapshot": plain(context["sampling_snapshot"])},
        "risk_execution": {"status": "BLOCKED", "integration": "NOT_INTEGRATED",
                           "reason": "No reviewed v2 adapter/calibrated formal Risk entry integrated; no scoring performed."},
        "open_interface_gaps": ["G%02d" % i for i in range(1, 10)],
    }
