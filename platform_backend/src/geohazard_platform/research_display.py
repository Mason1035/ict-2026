"""Read-only WP2/WP3 presentation adapter; no platform DB or ingestion imports."""
from __future__ import annotations

from contextlib import closing
import json
from pathlib import Path
import sqlite3

from .sd_replay import ADAPTER_VERSION, SENSORS, parse_sd_session
from .research_sessions import to_analysis_session, AnalysisSession
from .research_rules import run_rules
from .research_rule_config import validate_config


FROZEN_CONFIG = Path(__file__).resolve().parents[2] / "config/research_rules/provisional-v1-r4.json"
LABELS = {"rain_50": ("R1", "50 档降雨试验"), "rain_70": ("R2", "70 档降雨试验"),
          "rain_100": ("R3", "100 档降雨试验"),
          "post_rain_static": ("R4", "雨后静置，非干土基线")}
BOUNDARY = {"scope": "RESEARCH", "uncalibrated": True, "production_alarm_eligible": False,
            "risk_eligible": False, "fusion_eligible": False}
REASON_LABELS = {"ORIENTATION_IMU_TOP": "TOP 相对方向角变化", "ORIENTATION_IMU_TOE": "TOE 相对方向角变化",
                 "SOIL_TOP": "AIN0 原始 ADC 码相对变化", "SOIL_MIDDLE": "AIN1 原始 ADC 码相对变化",
                 "SOIL_TOE": "AIN2 原始 ADC 码相对变化", "VIBRATION_IMU_TOP": "TOP 振动候选",
                 "VIBRATION_IMU_TOE": "TOE 振动候选"}


class ResearchDisplayError(ValueError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


def downsample(points, metric, limit, max_gap_us):
    """Min/max buckets, original times only. Segment IDs prevent bridging hidden gaps.

    This is a display reduction AFTER full-resolution rule evaluation. It does not
    feed the rules. Missing values stay null; raw ADC spikes remain eligible extrema.
    """
    if not 16 <= limit <= 2000:
        raise ValueError("max_points must be between 16 and 2000")
    data, segment, previous_time = [], 0, None
    for point in points:
        t, value = point["time_us"], point["values"].get(metric)
        if t is None:
            segment += 1
            continue
        if (value is None or point["quality_flags"] or previous_time is None
                or t <= previous_time or t - previous_time > max_gap_us):
            segment += 1
        data.append({"time_us": t, "value": value, "segment": segment})
        if value is None or point["quality_flags"]:
            segment += 1
        previous_time = t
    indices = set(range(len(data)))
    if len(data) > limit:
        indices = {0, len(data) - 1}
        buckets = (limit - 2) // 2
        for bucket in range(buckets):
            start = 1 + (len(data) - 2) * bucket // buckets
            stop = 1 + (len(data) - 2) * (bucket + 1) // buckets
            finite = [i for i in range(start, stop) if data[i]["value"] is not None]
            if finite:
                indices.update((min(finite, key=lambda i: data[i]["value"]),
                                max(finite, key=lambda i: data[i]["value"])))
            else:
                indices.update((start, stop - 1))
    reduced, previous_segment = [], None
    for i in sorted(indices):
        point = data[i]
        reduced.append({"time_us": point["time_us"], "value": point["value"],
                        "break_before": point["segment"] != previous_segment})
        previous_segment = point["segment"]
    return {"metric": metric, "input_points": len(points), "points": reduced}


class ResearchDisplay:
    def __init__(self, registry_path: Path, production_path: Path):
        self.registry_path = Path(registry_path).expanduser().resolve()
        self.production_path = Path(production_path).expanduser().resolve()

    def _rows(self, experiment_id=None):
        path = self.registry_path
        if path == self.production_path or (path.exists() and self.production_path.exists()
                                           and path.samefile(self.production_path)):
            raise ResearchDisplayError(503, "研究登记库必须独立于平台数据库")
        if not path.is_file():
            raise ResearchDisplayError(503, "研究登记库尚未配置；请离线使用 WP2 CLI 登记会话")
        try:
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only=ON")
                tables = {r[0] for r in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
                if tables != {"research_sd_sessions", "research_sd_attempts"}:
                    raise ResearchDisplayError(503, "仅允许读取专用 WP2 研究登记库")
                query = "SELECT * FROM research_sd_sessions WHERE adapter_version=?"
                args = [ADAPTER_VERSION]
                if experiment_id is not None:
                    query += " AND experiment_id=?"
                    args.append(experiment_id)
                rows = connection.execute(query + " ORDER BY experiment_id", args).fetchall()
                return [dict(row) for row in rows]
        except sqlite3.Error as exc:
            raise ResearchDisplayError(503, "研究登记库不可读或结构不兼容") from exc

    def _metadata(self, row):
        m = json.loads(row["metadata_json"])
        if (m["experiment_id"] != row["experiment_id"] or m["replay_id"] != row["replay_id"]
                or m["adapter_version"] != ADAPTER_VERSION or m["scope"] != "TEST_ONLY"
                or m["source"] != "REAL" or m["transport"] != "sd_replay"
                or m["session_type"] not in LABELS or m["risk_eligible"] or m["fusion_eligible"]
                or m["integrity"]["file_sha256"] != json.loads(row["fingerprints_json"])):
            raise ResearchDisplayError(409, "研究登记元数据不一致")
        return m

    def _summary(self, m):
        label, title = LABELS[m["session_type"]]
        return {**BOUNDARY, "experiment_id": m["experiment_id"], "replay_id": m["replay_id"],
                "source": m["source"], "input_scope": m["scope"], "transport": m["transport"],
                "session_type": m["session_type"], "label": label, "type_label": title,
                "duration_s": (m["capture_stop_uptime_us"] - m["time_origin_uptime_us"]) / 1e6,
                "firmware_sha256": m["firmware_sha256"],
                "firmware_identity_status": m["firmware_identity_status"],
                "quality_flags": m["quality_flags"],
                "channels": {sensor: {"valid_count": m["valid_counts"][sensor],
                                      "invalid_count": m["invalid_counts"][sensor]}
                             for sensor in SENSORS.values()}}

    def sessions(self):
        items = [self._summary(self._metadata(row)) for row in self._rows()]
        return {**BOUNDARY, "items": sorted(items, key=lambda item: (item["label"], item["experiment_id"]))}

    def _session(self, experiment_id):
        rows = self._rows(experiment_id)
        if not rows:
            raise ResearchDisplayError(404, "研究会话未登记")
        m = self._metadata(rows[0])
        parsed = parse_sd_session(m["source_directory"], m["csv_name"])
        if (parsed.experiment_id != experiment_id
                or parsed.integrity.file_sha256 != json.loads(rows[0]["fingerprints_json"])):
            raise ResearchDisplayError(409, "原件与登记指纹不一致，拒绝展示")
        fresh = to_analysis_session(parsed, m["session_type"], replay_id=rows[0]["replay_id"])
        if fresh.metadata != m:
            raise ResearchDisplayError(409, "原件与登记元数据不一致，拒绝展示")
        return AnalysisSession(metadata=m, channels=fresh.channels)

    def _evaluate(self, experiment_id):
        session = self._session(experiment_id)
        config = json.loads(FROZEN_CONFIG.read_text(encoding="utf-8"))
        validate_config(config)
        result = run_rules(session, config, include_features=True)
        provenance = {key: config[key] for key in (
            "method_version", "rule_version", "reference_version", "generated_at", "config_sha256",
            "source", "reason_definition_version", "reason_bits")}
        return session, config, result, {**BOUNDARY, **provenance}

    def detail(self, experiment_id, max_points=600):
        session, config, result, provenance = self._evaluate(experiment_id)
        channels = {}
        for series in session.channels:
            metrics = ({"direction_angle_deg": "°", "vibration_rms_mps2": "m/s²", "sta_lta": "ratio"}
                       if series.kind == "imu" else
                       {"raw_adc_code": "ADC code", "relative_change_fraction": "fraction"})
            gap = config["parameters"]["imu_max_gap_us" if series.kind == "imu" else "soil_max_gap_us"]
            if series.kind == "imu":
                gap += config["parameters"]["evaluation_step_us"]
            channels[series.sensor_id] = {
                "statistics": series.statistics(), "rule_summary": result["channels"][series.sensor_id],
                "curves": [{**downsample(result["features"][series.sensor_id], metric, max_points, gap),
                            "unit": unit} for metric, unit in metrics.items()]}
        return {**BOUNDARY, "session": self._summary(session.metadata), "channels": channels,
                "max_points": max_points, "provenance": provenance, "time_basis": result["time_basis"]}

    def rules(self, experiment_id):
        _, _, result, provenance = self._evaluate(experiment_id)
        result.pop("features")
        result["provenance"] = provenance
        result["reason_decode"] = [{"code": code, "mask": mask, "label": REASON_LABELS[code]}
                                   for code, mask in result["reason_bits"].items()]
        return result
