"""Offline research rule executor/CLI. Never imports production ingestion/alarms."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

from .research_features import compute_features
from .research_rule_config import canonical_json, freeze_config, validate_config
from .research_sessions import SESSION_TYPES, register_session


def _periods(points, *, sensor, event_class, metrics, thresholds, dwell_us, parameters,
             reason_key, reason_mask, candidate=False):
    """Causal dwell + hysteresis; never bridge invalid/warmup/guarded observations."""
    periods = []
    pending = None
    active = None
    recovery = None
    peaks = {}
    last_support = None

    def close(reported_at, cause):
        if active is not None:
            periods.append({
                "scope": "RESEARCH", "event_class": event_class, "candidate_only": candidate,
                "triggered": not candidate, "sensor_id": sensor,
                "start_us": pending, "confirmed_at_us": active, "end_us": last_support,
                "reported_closed_at_us": reported_at, "closure": cause,
                "duration_s": (last_support - pending) / 1e6,
                "reason_codes": [reason_key], "reason_mask": reason_mask,
                "contributions": [{"sensor_id": sensor, "peak_values": dict(peaks),
                                   "thresholds": dict(zip(metrics, thresholds))}],
            })

    def decision(point, state):
        # Per-observation decisions are immutable once emitted. Period summaries
        # may later gain an end/peak, while this trace supports exact prefix QA.
        point.setdefault("rule_decisions", {})[event_class] = {
            "scope": "RESEARCH", "state": state,
            "duration_us": (point["time_us"] - pending
                            if pending is not None and point["time_us"] is not None else 0),
            "confirmed_at_us": active,
            "reason_mask": reason_mask if pending is not None else 0,
        }

    for point in points:
        t = point["time_us"]
        values = [point["values"].get(key) for key in metrics]
        if point["state"] != "READY" or point["quality_flags"] or any(v is None for v in values):
            close(t, "QUALITY_INTERRUPTION")
            pending = active = recovery = last_support = None
            peaks = {}
            decision(point, point["state"] if point["state"] != "READY" else "INVALID")
            continue
        enter = all(abs(v) > threshold for v, threshold in zip(values, thresholds))
        support = all(abs(v) > threshold * parameters["recovery_ratio"]
                      for v, threshold in zip(values, thresholds))
        if active is None:
            if not enter:
                pending = None
                peaks = {}
                decision(point, "NO_TRIGGER")
                continue
            if pending is None:
                pending = t
            for key, value in zip(metrics, values):
                peaks[key] = max(peaks.get(key, 0), abs(value))
            if t - pending >= dwell_us:
                active = t
                last_support = t
        elif support:
            recovery = None
            last_support = t
            for key, value in zip(metrics, values):
                peaks[key] = max(peaks.get(key, 0), abs(value))
        else:
            if recovery is None:
                recovery = t
            if t - recovery >= parameters["recovery_dwell_us"]:
                close(t, "RECOVERED")
                pending = active = recovery = last_support = None
                peaks = {}
        decision(point, ("CANDIDATE" if candidate else "TRIGGERED") if active is not None
                 else "PENDING" if pending is not None else "NO_TRIGGER")
    close(None, "SESSION_END")
    return periods


def _coincidences(events):
    """Overlaps use confirmed times, so dwell evidence is never backdated."""
    boundaries = sorted({t for event in events for t in (event["confirmed_at_us"], event["end_us"])})
    overlaps = []
    for start, stop in zip(boundaries, boundaries[1:]):
        matching = [e for e in events if e["confirmed_at_us"] <= start and e["end_us"] >= stop]
        sensors = sorted({e["sensor_id"] for e in matching})
        if len(sensors) < 2:
            continue
        mask = 0
        for e in matching:
            mask |= e["reason_mask"]
        if overlaps and overlaps[-1]["end_us"] == start and overlaps[-1]["channels"] == sensors:
            overlaps[-1]["end_us"] = stop
        else:
            overlaps.append({"scope": "RESEARCH", "event_class": "SIMULTANEOUS_CHANNEL_CHANGE",
                             "start_us": start, "end_us": stop, "channels": sensors, "reason_mask": mask})
    return overlaps


def run_rules(session, config, *, include_features=False):
    """Pure evaluation: copies the config and emits deterministic research results.

    No timestamps/UUIDs are generated here. Registration identity and frozen config
    are inputs. Running a rain session cannot update parameters, thresholds or bits.
    """
    validate_config(config)
    config = deepcopy(config)
    p = config["parameters"]
    features = compute_features(session, p)
    if (session.metadata["experiment_id"] == config["source"]["experiment_id"]
            and session.metadata["integrity"]["file_sha256"] != config["source"]["file_sha256"]):
        raise ValueError("reference experiment bytes differ from frozen source")
    channels = {}
    events, candidates = [], []
    for series in session.channels:
        sensor = series.sensor_id
        points = features[sensor]
        thresholds = config["channels"][sensor]["metrics"]
        ready = [point for point in points if point["state"] == "READY"]
        if series.kind == "imu":
            rules = [("RELATIVE_ORIENTATION_CHANGE", ("direction_angle_deg",), "orientation_dwell_us",
                      "ORIENTATION_" + sensor.upper(), False),
                     ("VIBRATION_CANDIDATE", ("vibration_rms_mps2", "sta_lta"), "vibration_dwell_us",
                      "VIBRATION_" + sensor.upper(), True)]
        else:
            rules = [("SOIL_ADC_RELATIVE_CHANGE", ("relative_change_fraction",), "soil_dwell_us",
                      sensor.upper(), False)]
        channel_events, channel_candidates = [], []
        for event_class, metrics, dwell_key, reason, candidate in rules:
            periods = _periods(points, sensor=sensor, event_class=event_class, metrics=metrics,
                               thresholds=[thresholds[key]["frozen_value"] for key in metrics],
                               dwell_us=p[dwell_key], parameters=p, reason_key=reason,
                               reason_mask=config["reason_bits"][reason], candidate=candidate)
            (channel_candidates if candidate else channel_events).extend(periods)
        events.extend(channel_events)
        candidates.extend(channel_candidates)
        keys = sorted({key for point in ready for key in point["values"]})
        peaks = {}
        for key in keys:
            values = [(abs(point["values"][key]), point["time_us"], point["values"][key])
                      for point in ready if point["values"].get(key) is not None]
            if values:
                peak = max(values, key=lambda v: v[0])
                peaks[key] = {"absolute_peak": peak[0], "time_us": peak[1], "signed_value": peak[2]}
        states = {key: sum(point["state"] == key for point in points)
                  for key in ("WARMUP", "INSUFFICIENT_BASELINE", "INVALID", "READY")}
        state = ("TRIGGERED" if channel_events else "NO_TRIGGER" if ready else
                 "INVALID" if states["INVALID"] else "INSUFFICIENT_BASELINE"
                 if states["INSUFFICIENT_BASELINE"] else "WARMUP")
        channels[sensor] = {
            "state": state, "input_observations": len(series.observations),
            "last_feature_state": points[-1]["state"] if points else "WARMUP",
            "feature_points": len(points), "state_counts": states,
            "quality_flags": list(series.quality_flags),
            "diagnostic_counts": {flag: sum(flag in point["quality_flags"] for point in points)
                                  for flag in sorted({flag for point in points for flag in point["quality_flags"]})},
            "peak_values": peaks, "events": channel_events, "candidates": channel_candidates,
        }
    events.sort(key=lambda e: (e["confirmed_at_us"], e["sensor_id"], e["event_class"]))
    candidates.sort(key=lambda e: (e["confirmed_at_us"], e["sensor_id"]))
    m = session.metadata
    result = {
        "format_version": "research-rule-result-v1", "scope": "RESEARCH", "source": m["source"],
        "input_scope": m["scope"], "transport": m["transport"],
        "experiment_id": m["experiment_id"], "session_type": m["session_type"],
        "replay_id": m["replay_id"], "generated_replay_identity": True,
        "adapter_version": m["adapter_version"], "file_sha256": deepcopy(m["integrity"]["file_sha256"]),
        "time_basis": m["time_basis"], "uncalibrated": True,
        "fusion_eligible": False, "risk_eligible": False, "production_alarm_eligible": False,
        "rule_version": config["rule_version"], "reference_version": config["reference_version"],
        "method_version": config["method_version"], "config_sha256": config["config_sha256"],
        "reason_definition_version": config["reason_definition_version"], "reason_bits": config["reason_bits"],
        "quality_flags": list(m["quality_flags"]), "channels": channels,
        "trigger_count": len(events), "candidate_count": len(candidates),
        "events": events, "candidates": candidates, "coincidences": _coincidences(events),
        "interpretation": "Research observations only; NO_TRIGGER does not establish slope safety. "
                          "ADC codes are uncalibrated; direction of change has no moisture interpretation. "
                          "Vibration is candidate-only. R4 is post-rain static, not a dry baseline.",
    }
    if include_features:
        result["features"] = features
    return result


def _safe_output(path, source):
    path = path.expanduser().resolve()
    source = source.expanduser().resolve()
    if path == source or source in path.parents:
        raise ValueError("output must be outside read-only capture directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="R4-only freeze and offline research rule reports")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "run"):
        command_parser = subparsers.add_parser(command)
        command_parser.add_argument("directory", type=Path)
        command_parser.add_argument("--registry", type=Path, required=True)
        command_parser.add_argument("--csv", dest="csv_name")
        command_parser.add_argument("--output", type=Path, required=True, help="new JSON file; never overwritten")
        if command == "run":
            command_parser.add_argument("--type", dest="session_type", choices=SESSION_TYPES, required=True)
            command_parser.add_argument("--config", type=Path, required=True)
        else:
            command_parser.add_argument("--generated-at", help="optional timezone-aware freeze timestamp")
    args = parser.parse_args(argv)
    try:
        output = _safe_output(args.output, args.directory)
        # Refuse before registry changes, and use exclusive creation again at write.
        if output.exists():
            raise ValueError("output already exists; frozen artifacts cannot be overwritten")
        kind = "post_rain_static" if args.command == "freeze" else args.session_type
        session = register_session(args.directory, kind, args.registry, csv_name=args.csv_name)
        if args.command == "freeze":
            payload = freeze_config(session, generated_at=args.generated_at)
            self_check = run_rules(session, payload)
            if self_check["trigger_count"] or self_check["candidate_count"]:
                raise ValueError("R4 zero-trigger/candidate self-check failed; config not written")
        else:
            payload = run_rules(session, json.loads(args.config.read_text()))
        with output.open("x", encoding="utf-8") as stream:
            stream.write(canonical_json(payload))
        print(canonical_json({"status": "written", "scope": "RESEARCH", "output": str(output)}), end="")
        return 0
    except (ValueError, OSError, sqlite3.Error) as exc:
        print(canonical_json({"status": "rejected", "error": str(exc)}), file=sys.stderr, end="")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
