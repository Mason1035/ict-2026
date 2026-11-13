"""Causal, uncalibrated SD → telemetry v2 projection and localhost MQTT replay."""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time
from threading import Event
from uuid import uuid4

from .sd_replay import ParsedSDSession, parse_sd_session
from .telemetry import IMU_NUMBERS, MAX_INTEGER, SOIL_NUMBERS, validate_telemetry


@dataclass(frozen=True)
class ReplayOptions:
    site_id: str = "REPLAY-LAB"
    device_id: str = "REPLAY-NODE01"
    speed: float = 1.0
    frame_hz: float = 2.0
    imu_max_age_ms: float = 50
    soil_max_age_ms: float = 1000
    include_ain2: bool = False
    derive_display: bool = False
    baseline_s: float = 5
    rain_level: int | None = None

    def __post_init__(self):
        for value in (self.site_id, self.device_id):
            if (not isinstance(value, str) or not value.strip() or len(value) > 128
                    or any(c in value for c in "/+#\0") or value.startswith(("MOCK-", "DEMO-"))):
                raise ValueError("site/device must be a single non-MOCK-/DEMO- MQTT segment")
            value.encode("utf-8")
        for name, low, high in (("speed", .1, 50), ("frame_hz", .5, 10),
                                ("imu_max_age_ms", 0, MAX_INTEGER),
                                ("soil_max_age_ms", 0, MAX_INTEGER), ("baseline_s", 0.000001, MAX_INTEGER)):
            value = getattr(self, name)
            if not math.isfinite(value) or not low <= value <= high:
                raise ValueError(f"{name} must be {low}..{high}")
        if self.rain_level is not None and (type(self.rain_level) is not int or not 0 <= self.rain_level <= 3):
            raise ValueError("rain_level must be 0..3")

    @property
    def topic(self):
        return f"zhifang/v2/{self.site_id}/{self.device_id}/telemetry"


def deterministic_boot(session: ParsedSDSession) -> int:
    match = re.search(r"(?:^|-)([0-9a-fA-F]{16})(?:-|$)", session.experiment_id)
    if not match:
        raise ValueError("experiment_id must contain a 16-digit hexadecimal segment for deterministic boot")
    return int(match[1], 16) & MAX_INTEGER


def frames(session: ParsedSDSession, boot_id: int, options: ReplayOptions = ReplayOptions()):
    """Anchor at the first acquired observation at/after each sampling deadline.

    No interpolation: all lookups use only Valid, complete observations at or
    before the anchor. RMS uses (previous anchor, anchor], first window includes
    observations from session start. Baseline accumulates only historical samples
    in the first baseline_s of this session, then freezes.
    """
    if type(boot_id) is not int or not 0 <= boot_id <= MAX_INTEGER:
        raise ValueError("boot_id outside telemetry integer range")
    end = json.loads((session.directory / session.csv_name).with_suffix(".END").read_bytes())
    degraded = any(session.integrity.invalid_counts.values()) or end.get("i2c_errors", 0) > 0
    rows = sorted((r for r in session.rows if r.acquired_uptime_us is not None),
                  key=lambda r: (r.acquired_uptime_us, r.acquisition_index))
    latest = {}
    baseline = {i: [0., 0., 0., 0] for i in range(2)}
    window = defaultdict(list)
    step = 1_000_000 / options.frame_hz
    deadline = rows[0].acquired_uptime_us if rows else 0
    position = seq = 0
    while position < len(rows):
        anchor = rows[position].acquired_uptime_us
        while position < len(rows) and rows[position].acquired_uptime_us <= anchor:
            row = rows[position]
            position += 1
            if row.validity != "Valid" or row.missing_value:
                continue
            latest[(row.kind, row.channel)] = row
            if row.kind == "imu":
                a = row.acceleration_mps2
                window[row.channel].append(math.sqrt(sum(v*v for v in a)))
                if row.acquired_uptime_us <= session.start_uptime_us + options.baseline_s * 1e6:
                    b = baseline[row.channel]
                    for i in range(3):
                        b[i] += a[i]
                    b[3] += 1
        if anchor < deadline:
            continue
        seq += 1
        imus = []
        for channel, name in enumerate(("top", "toe")):
            imu = {"id": name, "valid": False, **dict.fromkeys(IMU_NUMBERS)}
            row = latest.get(("imu", channel))
            if row and anchor - row.acquired_uptime_us <= options.imu_max_age_ms * 1000:
                imu.update(valid=True, **dict(zip(("ax", "ay", "az", "gx", "gy", "gz"),
                                                  row.acceleration_mps2 + row.angular_velocity_dps)))
                if options.derive_display:
                    a = row.acceleration_mps2
                    b = baseline[channel]
                    norm = math.sqrt(sum(v*v for v in a) * sum(v*v for v in b[:3]))
                    if b[3] and norm:
                        imu["tilt_deg"] = math.degrees(math.acos(max(-1., min(1., sum(a[i]*b[i] for i in range(3))/norm))))
                    values = window[channel]
                    if values:
                        mean = sum(values)/len(values)
                        imu["vibration_rms"] = math.sqrt(sum((v-mean)**2 for v in values)/len(values))
            imus.append(imu)
        soil = dict.fromkeys(SOIL_NUMBERS | {"top_raw", "middle_raw", "toe_raw"})
        for channel, field in enumerate(("top_raw", "middle_raw", "toe_raw")):
            row = latest.get(("soil", channel))
            if (channel != 2 or options.include_ain2) and row and anchor-row.acquired_uptime_us <= options.soil_max_age_ms*1000:
                soil[field] = row.soil_raw
        yield {"schema": "zhifang.telemetry.v2", "site_id": options.site_id,
               "device_id": options.device_id, "boot_id": boot_id, "seq": seq,
               "timestamp_ms": None, "uptime_ms": anchor//1000, "time_synced": False,
               "imu": imus, "soil": soil,
               "experiment": {"run_id": "REAL_REPLAY|UNCALIBRATED|"+session.experiment_id, "rain_level": options.rain_level},
               "risk": {"sensor_score": None, "level": None, "reason_mask": None},
               "system": {"wifi_up": False, "mqtt_up": True, "lora_ready": False,
                          "edge_online": False, "sd_ok": end.get("storage_clean") is True,
                          "sensor_degraded": bool(degraded)}}
        window.clear()
        deadline += (math.floor((anchor-deadline)/step)+1)*step


def replay(session, boot_id, options, *, publish=None, dry_run=False, max_frames=None,
           monotonic=time.monotonic, sleep=time.sleep, output=None, summary=None, stop=None):
    """Validate before send; publish is a Paho-compatible callable. Injectable clock."""
    summary = summary if summary is not None else {}
    summary.update(experiment_id=session.experiment_id, boot_id=boot_id, frames=0, published=0,
                   rejected=0, null_frames=dict.fromkeys(("imu_top", "imu_toe", "soil_top", "soil_middle", "soil_toe"), 0),
                   file_sha256=session.integrity.file_sha256)
    start = monotonic()
    first = None
    failures = 0
    try:
        for payload in frames(session, boot_id, options):
            if (stop is not None and stop.is_set()) or (max_frames is not None and summary["frames"] >= max_frames):
                break
            summary["frames"] += 1
            for name, missing in zip(summary["null_frames"], [not i["valid"] for i in payload["imu"]] +
                                     [payload["soil"][f] is None for f in ("top_raw", "middle_raw", "toe_raw")]):
                summary["null_frames"][name] += int(missing)
            first = payload["uptime_ms"] if first is None else first
            if not dry_run:
                delay = start + (payload["uptime_ms"]-first)/1000/options.speed-monotonic()
                if delay > 0:
                    sleep(delay)
                if stop is not None and stop.is_set():
                    break
            errors = validate_telemetry(payload, topic=options.topic)
            if errors:
                summary["rejected"] += 1
                failures += 1
                if failures >= 10:
                    raise ValueError(f"10 consecutive locally rejected frames: {errors}")
                continue
            failures = 0
            data = json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if dry_run:
                print(data, file=output or sys.stdout)
            else:
                result = publish(options.topic, data, qos=0, retain=False)
                if result is not None:
                    result.wait_for_publish(timeout=10)
                    if not result.is_published():
                        raise RuntimeError("MQTT publish did not complete")
                summary["published"] += 1
    finally:
        for kind, suffix in (("csv", ".CSV"), ("beg", ".BEG"), ("end", ".END")):
            path = (session.directory/session.csv_name).with_suffix(suffix)
            if hashlib.sha256(path.read_bytes()).hexdigest() != session.integrity.file_sha256[kind]:
                raise ValueError("source fingerprint changed during replay")
    return summary


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("session_dirs", metavar="SESSION_DIR", nargs="+")
    p.add_argument("--csv")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=18883)
    p.add_argument("--username", help="remote broker username")
    p.add_argument("--password", default=os.environ.get("GEOHAZARD_MQTT_PASSWORD"),
                   help="broker password; prefer GEOHAZARD_MQTT_PASSWORD to avoid shell history/process args")
    p.add_argument("--embedded-broker", action="store_true")
    for name in ("site-id", "device-id"):
        p.add_argument("--"+name, default=getattr(ReplayOptions(), name.replace("-", "_")))
    for name in ("speed", "frame-hz", "imu-max-age-ms", "soil-max-age-ms", "baseline-s"):
        p.add_argument("--"+name, type=float, default=getattr(ReplayOptions(), name.replace("-", "_")))
    for name in ("include-ain2", "derive-display", "loop", "dry-run"):
        p.add_argument("--"+name, action="store_true")
    identity = p.add_mutually_exclusive_group()
    identity.add_argument("--boot-id", type=int)
    identity.add_argument("--deterministic-boot", action="store_true")
    p.add_argument("--rain-level", type=int, choices=range(4))
    p.add_argument("--max-frames", type=int)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    try:
        options = ReplayOptions(**{key: getattr(args, key) for key in ReplayOptions.__dataclass_fields__})
        if not 1 <= args.port <= 65535 or (args.max_frames is not None and args.max_frames < 1):
            raise ValueError("invalid port or max-frames")
        if args.boot_id is not None and not 0 <= args.boot_id <= MAX_INTEGER:
            raise ValueError("boot-id outside telemetry integer range")
        # No implicit public destinations. A supplied --host is an explicit broker choice.
        if args.embedded_broker and args.host != "127.0.0.1":
            raise ValueError("embedded broker requires --host 127.0.0.1")
        if args.password is not None and not args.username:
            raise ValueError("--password requires --username")
        if args.embedded_broker and (args.username or args.password is not None):
            raise ValueError("embedded broker does not support credentials; use an external Mosquitto")
        sessions = [parse_sd_session(directory, args.csv) for directory in args.session_dirs]
        if args.deterministic_boot:
            for session in sessions:
                deterministic_boot(session)
    except ValueError as exc:
        p.error(str(exc))
    log_dir = Path(__file__).resolve().parents[3]/"work/replay"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir/f"mqtt-{time.time_ns()}-{uuid4().hex[:8]}.json"
    log = {"options": {**vars(args), "password": "<redacted>" if args.password is not None else None}, "sessions": []}

    stop = Event()

    def run():
        client = None
        used = set()
        try:
            if not args.dry_run:
                import paho.mqtt.client as mqtt
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
                if args.username:
                    client.username_pw_set(args.username, args.password)
                client.connect(args.host, args.port, keepalive=30)
                client.loop_start()
            remaining = args.max_frames
            while not stop.is_set():
                for session in sessions:
                    if stop.is_set():
                        return
                    boot = (args.boot_id if args.boot_id is not None else
                            deterministic_boot(session) if args.deterministic_boot else int(time.time()*1000))
                    while boot in used:
                        boot = (boot+1) & MAX_INTEGER
                    used.add(boot)
                    summary = {"experiment_id": session.experiment_id, "boot_id": boot}
                    log["sessions"].append(summary)
                    log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
                    try:
                        replay(session, boot, options, publish=client.publish if client else None,
                               dry_run=args.dry_run, max_frames=remaining, summary=summary, stop=stop, sleep=stop.wait)
                    finally:
                        log_path.write_text(json.dumps(log, ensure_ascii=False, indent=2))
                        print(json.dumps(summary, ensure_ascii=False), file=sys.stderr)
                    if remaining is not None:
                        remaining -= summary["frames"]
                        if remaining <= 0:
                            return
                if not args.loop:
                    return
        finally:
            if client:
                client.disconnect()
                client.loop_stop()
            print(f"Replay log: {log_path}", file=sys.stderr)

    try:
        if args.embedded_broker and not args.dry_run:
            import asyncio
            from amqtt.broker import Broker

            async def embedded():
                broker = Broker({"listeners": {"default": {"type": "tcp", "bind": f"127.0.0.1:{args.port}"}},
                                 "plugins": {"amqtt.plugins.authentication.AnonymousAuthPlugin": {"allow_anonymous": True}}, "sys_interval": 0})
                await broker.start()
                print(f"Replay Broker 127.0.0.1:{args.port}; REAL / TEST_ONLY; Ctrl+C stops", file=sys.stderr)
                task = asyncio.create_task(asyncio.to_thread(run))
                try:
                    await asyncio.shield(task)
                finally:
                    stop.set()
                    try:
                        await task
                    finally:
                        await broker.shutdown()
            asyncio.run(embedded())
        else:
            run()
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        print(f"Replay failed: {exc}", file=sys.stderr)
        return 1
    return 0
