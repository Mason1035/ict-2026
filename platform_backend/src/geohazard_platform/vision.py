"""Persisted image evidence and an explicitly uncalibrated OpenCV baseline.

The numerical thresholds below are *image processing heuristics*. They diagnose
image quality and describe pixel changes; they do not predict geological risk.
Only PNG/JPEG still images are accepted and re-encoded without input metadata.
"""
from __future__ import annotations

import base64
import binascii
import io
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import UUID, uuid4
import warnings

import cv2
import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError


MAX_IMAGE_PIXELS = 12_000_000
ANALYSIS_MAX_EDGE = 1024
QUALITY_THRESHOLDS = {
    "blur_laplacian_variance_min": 40.0,
    "dark_mean_gray_below": 30.0,
    "bright_mean_gray_above": 225.0,
    "low_contrast_std_below": 8.0,
    "absolute_difference_threshold": 25,
}


class _Database(Protocol):
    def connection(self) -> Any: ...


class VisionError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _label(value: str, name: str, max_length: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > max_length:
        raise VisionError(422, f"{name} must contain 1–{max_length} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise VisionError(422, f"{name} contains control characters")
    return value.strip()


def _capture_time(value: str | None) -> str | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("timezone required")
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (ValueError, TypeError, AttributeError) as exc:
        raise VisionError(422, "capture_time must be an ISO 8601 timestamp with timezone") from exc


def _identifier(value: str) -> str:
    try:
        parsed = str(UUID(value))
        if parsed != value:
            raise ValueError("canonical UUID required")
        return parsed
    except (ValueError, TypeError, AttributeError) as exc:
        raise VisionError(404, "Image evidence or analysis result was not found") from exc


def _sample(gray: np.ndarray) -> np.ndarray:
    height, width = gray.shape[:2]
    scale = min(1.0, ANALYSIS_MAX_EDGE / max(height, width))
    if scale == 1.0:
        return gray
    return cv2.resize(gray, (max(1, round(width * scale)), max(1, round(height * scale))),
                      interpolation=cv2.INTER_AREA)


def _quality(gray: np.ndarray) -> dict[str, Any]:
    sampled = _sample(gray)
    mean, std = float(sampled.mean()), float(sampled.std())
    laplacian = float(cv2.Laplacian(sampled, cv2.CV_64F).var())
    flags = []
    if laplacian < QUALITY_THRESHOLDS["blur_laplacian_variance_min"]:
        flags.append("blur")
    if mean < QUALITY_THRESHOLDS["dark_mean_gray_below"]:
        flags.append("dark")
    if mean > QUALITY_THRESHOLDS["bright_mean_gray_above"]:
        flags.append("overexposed")
    if std < QUALITY_THRESHOLDS["low_contrast_std_below"]:
        flags.append("low_contrast")
    return {
        "mean_gray": round(mean, 4),
        "gray_std": round(std, 4),
        "laplacian_variance": round(laplacian, 4),
        "flags": flags,
        "acceptable": not flags,
        "thresholds": dict(QUALITY_THRESHOLDS),
        "interpretation": "Technical image-quality heuristics; not calibrated geological thresholds",
    }


def _ssim(current: np.ndarray, reference: np.ndarray) -> float:
    """Windowed grayscale SSIM, 11px Gaussian window (sigma 1.5), range 255."""
    a, b = current.astype(np.float32), reference.astype(np.float32)
    mu_a = cv2.GaussianBlur(a, (11, 11), 1.5)
    mu_b = cv2.GaussianBlur(b, (11, 11), 1.5)
    var_a = np.maximum(cv2.GaussianBlur(a * a, (11, 11), 1.5) - mu_a * mu_a, 0)
    var_b = np.maximum(cv2.GaussianBlur(b * b, (11, 11), 1.5) - mu_b * mu_b, 0)
    covariance = cv2.GaussianBlur(a * b, (11, 11), 1.5) - mu_a * mu_b
    c1, c2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    values = ((2 * mu_a * mu_b + c1) * (2 * covariance + c2)) / (
        (mu_a * mu_a + mu_b * mu_b + c1) * (var_a + var_b + c2))
    return float(np.clip(values.mean(), -1, 1))


class VisionService:
    """Local evidence storage. Database must expose a transactional connection()."""

    def __init__(self, db: _Database, media_dir: str | Path,
                 max_upload_bytes: int = 12 * 1024 * 1024):
        if max_upload_bytes <= 0:
            raise ValueError("max_upload_bytes must be positive")
        self.db = db
        self.media_dir = Path(media_dir).resolve()
        self.max_upload_bytes = max_upload_bytes
        self.media_dir.mkdir(parents=True, exist_ok=True)
        for folder in ("evidence", "overlays"):
            location = self.media_dir / folder
            location.mkdir(exist_ok=True)
            if location.is_symlink() or not location.resolve().is_relative_to(self.media_dir):
                raise ValueError("Media subdirectories must remain inside media_dir")
        with self.db.connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS vision_evidence (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL,
                    camera_id TEXT NOT NULL, source TEXT NOT NULL, scope TEXT NOT NULL,
                    arrival_time TEXT NOT NULL, path TEXT NOT NULL, data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_vision_evidence_site_time
                    ON vision_evidence(site_id, arrival_time DESC);
                CREATE INDEX IF NOT EXISTS ix_vision_evidence_stream_time
                    ON vision_evidence(site_id, source, json_extract(data_json, '$.device_id'),
                                       arrival_time DESC, id DESC);
                CREATE TABLE IF NOT EXISTS vision_results (
                    id TEXT PRIMARY KEY, site_id TEXT NOT NULL,
                    evidence_id TEXT NOT NULL REFERENCES vision_evidence(id),
                    reference_id TEXT REFERENCES vision_evidence(id),
                    created_at TEXT NOT NULL, overlay_path TEXT, data_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS ix_vision_results_site_time
                    ON vision_results(site_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS ix_vision_results_evidence_time
                    ON vision_results(evidence_id, created_at DESC, id DESC);
            """)

    def _safe_path(self, stored: str) -> Path:
        path = (self.media_dir / stored).resolve()
        if not path.is_relative_to(self.media_dir) or not path.is_file():
            raise VisionError(404, "Stored image file was not found")
        return path

    def _atomic_write(self, path: Path, content: bytes) -> None:
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".upload-", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def upload(self, content: bytes, filename: str, *, site_id: str,
               device_id: str | None = None, camera_id: str = "UPLOAD-01",
               source: str = "MOCK", scope: str = "TEST_ONLY",
               capture_time: str | None = None) -> dict[str, Any]:
        if not isinstance(content, bytes) or not content:
            raise VisionError(422, "Image content is empty")
        if len(content) > self.max_upload_bytes:
            raise VisionError(413, "Image exceeds the configured upload byte limit")
        site_id, camera_id = _label(site_id, "site_id"), _label(camera_id, "camera_id")
        source, scope = _label(source, "source", 64), _label(scope, "scope", 64)
        if source not in {"REAL", "MOCK", "SYNTHETIC"}:
            raise VisionError(422, "source must be REAL, MOCK or SYNTHETIC")
        if scope not in {"OPERATIONAL", "TEST_ONLY"}:
            raise VisionError(422, "scope must be OPERATIONAL or TEST_ONLY")
        if device_id is not None:
            device_id = _label(device_id, "device_id")
        capture_time = _capture_time(capture_time)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as candidate:
                    image_format = candidate.format
                    if image_format not in {"PNG", "JPEG"}:
                        raise VisionError(415, "Only actual PNG or JPEG still-image content is accepted")
                    if candidate.width * candidate.height > MAX_IMAGE_PIXELS:
                        raise VisionError(413, "Image exceeds the 12 million pixel limit")
                    if getattr(candidate, "n_frames", 1) != 1:
                        raise VisionError(415, "Animated images are not supported")
                    candidate.verify()
                with Image.open(io.BytesIO(content)) as candidate:
                    image = ImageOps.exif_transpose(candidate).convert("RGB")
                    image.load()
        except VisionError:
            raise
        except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
            raise VisionError(413, "Image exceeds safe decoder dimensions") from exc
        except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
            raise VisionError(415, "Image content cannot be decoded as a valid PNG or JPEG") from exc

        encoded = io.BytesIO()
        # Re-encoding strips EXIF, GPS, ICC and text metadata from uploaded files.
        clean_image = Image.fromarray(np.asarray(image))
        if image_format == "JPEG":
            clean_image.save(encoded, format="JPEG", quality=92)
            extension, content_type = ".jpg", "image/jpeg"
        else:
            clean_image.save(encoded, format="PNG")
            extension, content_type = ".png", "image/png"
        evidence_id = str(uuid4())
        stored = f"evidence/{evidence_id}{extension}"
        path = self.media_dir / stored
        basename = str(filename or "image").replace("\\", "/").rsplit("/", 1)[-1]
        basename = re.sub(r"[\x00-\x1f\x7f]", "", basename).strip()[:200] or f"image{extension}"
        evidence = {
            "id": evidence_id, "site_id": site_id, "device_id": device_id,
            "camera_id": camera_id, "source": source, "scope": scope,
            "capture_time": capture_time, "arrival_time": _utc_now(), "filename": basename,
            "content_type": content_type, "width": image.width, "height": image.height,
            "byte_size": len(encoded.getvalue()), "file_url": f"/api/v1/evidence/{evidence_id}/file",
        }
        try:
            self._atomic_write(path, encoded.getvalue())
            with self.db.connection() as connection:
                connection.execute("""INSERT INTO vision_evidence
                    (id, site_id, camera_id, source, scope, arrival_time, path, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", (
                    evidence_id, site_id, camera_id, source, scope, evidence["arrival_time"],
                    stored, json.dumps(evidence, ensure_ascii=False, allow_nan=False)))
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return evidence

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute("SELECT data_json FROM vision_evidence WHERE id = ?",
                                     (_identifier(evidence_id),)).fetchone()
        if row is None:
            raise VisionError(404, "Image evidence was not found")
        return json.loads(row["data_json"])

    def file_path(self, evidence_id: str) -> Path:
        with self.db.connection() as connection:
            row = connection.execute("SELECT path FROM vision_evidence WHERE id = ?",
                                     (_identifier(evidence_id),)).fetchone()
        if row is None:
            raise VisionError(404, "Image evidence was not found")
        return self._safe_path(row["path"])

    def list_evidence(self, site_id: str | None = None, limit: int = 50, *,
                      device_id: str | None = None, source: str | None = None,
                      camera_id: str | None = None) -> list[dict[str, Any]]:
        """Compatibility list; filtered before limiting, like evidence_page."""
        return self.evidence_page(site_id, limit, device_id=device_id, source=source,
                                  camera_id=camera_id)["items"]

    def list_results(self, site_id: str | None = None, limit: int = 50, *,
                     device_id: str | None = None, source: str | None = None,
                     camera_id: str | None = None) -> list[dict[str, Any]]:
        return self.results_page(site_id, limit, device_id=device_id, source=source,
                                 camera_id=camera_id)["items"]

    def evidence_page(self, site_id: str | None = None, limit: int = 50, *,
                      device_id: str | None = None, source: str | None = None,
                      camera_id: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        return self._page("evidence", site_id, limit, device_id, source, camera_id, cursor)

    def results_page(self, site_id: str | None = None, limit: int = 50, *,
                     device_id: str | None = None, source: str | None = None,
                     camera_id: str | None = None, cursor: str | None = None) -> dict[str, Any]:
        return self._page("results", site_id, limit, device_id, source, camera_id, cursor)

    @staticmethod
    def _read_cursor(cursor: str, kind: str, filters: list[str | None]) -> tuple[str, str]:
        try:
            if not isinstance(cursor, str) or not 1 <= len(cursor) <= 4096:
                raise ValueError("invalid cursor length")
            padded = cursor + "=" * (-len(cursor) % 4)
            values = json.loads(base64.b64decode(padded, altchars=b"-_", validate=True).decode("utf-8"))
            if not isinstance(values, list) or len(values) != 4:
                raise ValueError("invalid cursor structure")
            cursor_kind, stamp, identifier, cursor_filters = values
            if cursor_kind != kind or cursor_filters != filters or not isinstance(stamp, str):
                raise ValueError("cursor does not belong to this filtered list")
            if _capture_time(stamp) is None:
                raise ValueError("missing cursor time")
            return stamp, _identifier(identifier)
        except (ValueError, TypeError, UnicodeError, binascii.Error, RecursionError, VisionError) as exc:
            raise VisionError(422, "Invalid vision cursor; restart pagination for the selected filters") from exc

    def _page(self, kind: str, site_id: str | None, limit: int,
              device_id: str | None, source: str | None, camera_id: str | None,
              cursor: str | None) -> dict[str, Any]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 200:
            raise VisionError(422, "limit must be an integer between 1 and 200")
        site_id = _label(site_id, "site_id") if site_id is not None else None
        device_id = _label(device_id, "device_id") if device_id is not None else None
        camera_id = _label(camera_id, "camera_id") if camera_id is not None else None
        if source is not None and (not isinstance(source, str) or source not in {"REAL", "MOCK", "SYNTHETIC"}):
            raise VisionError(422, "source must be REAL, MOCK or SYNTHETIC")
        filters = [site_id, device_id, source, camera_id]
        is_result = kind == "results"
        # Evidence remains the identity source of truth for pre-existing result
        # JSON without device_id. No migration guesses an owner for null IDs.
        from_clause = ("vision_results r JOIN vision_evidence e ON e.id = r.evidence_id"
                       if is_result else "vision_evidence e")
        alias, time_column = ("r", "created_at") if is_result else ("e", "arrival_time")
        conditions: list[str] = []
        parameters: list[Any] = []
        for column, value in (("e.site_id", site_id), ("json_extract(e.data_json, '$.device_id')", device_id),
                              ("e.source", source), ("e.camera_id", camera_id)):
            if value is not None:
                conditions.append(f"{column} = ?")
                parameters.append(value)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        page_conditions, page_parameters = list(conditions), list(parameters)
        if cursor is not None:
            stamp, identifier = self._read_cursor(cursor, kind, filters)
            page_conditions.append(f"({alias}.{time_column}, {alias}.id) < (?, ?)")
            page_parameters.extend((stamp, identifier))
        page_where = " WHERE " + " AND ".join(page_conditions) if page_conditions else ""
        query = (f"SELECT {alias}.id AS row_id, {alias}.{time_column} AS row_time, {alias}.data_json, "
                 f"json_extract(e.data_json, '$.device_id') AS evidence_device_id FROM {from_clause}{page_where} "
                 f"ORDER BY {alias}.{time_column} DESC, {alias}.id DESC LIMIT ?")
        with self.db.connection() as connection:
            total = connection.execute(f"SELECT count(*) FROM {from_clause}{where}", parameters).fetchone()[0]
            rows = connection.execute(query, (*page_parameters, limit + 1)).fetchall()
        visible = rows[:limit]
        items = [self._result_row(row) if is_result else json.loads(row["data_json"]) for row in visible]
        next_cursor = None
        if len(rows) > limit:
            last = visible[-1]
            token = json.dumps([kind, last["row_time"], last["row_id"], filters],
                               separators=(",", ":"), ensure_ascii=False)
            next_cursor = base64.urlsafe_b64encode(token.encode()).decode().rstrip("=")
        return {"items": items, "next_cursor": next_cursor, "total": total}

    @staticmethod
    def _result_row(row: Any) -> dict[str, Any]:
        data = json.loads(row["data_json"])
        data["device_id"] = row["evidence_device_id"]
        return data

    def get_result(self, result_id: str) -> dict[str, Any]:
        with self.db.connection() as connection:
            row = connection.execute("""SELECT r.data_json,
                json_extract(e.data_json, '$.device_id') AS evidence_device_id
                FROM vision_results r JOIN vision_evidence e ON e.id = r.evidence_id WHERE r.id = ?""",
                                     (_identifier(result_id),)).fetchone()
        if row is None:
            raise VisionError(404, "Vision analysis result was not found")
        return self._result_row(row)

    def result_overlay_path(self, result_id: str) -> Path:
        with self.db.connection() as connection:
            row = connection.execute("SELECT overlay_path FROM vision_results WHERE id = ?",
                                     (_identifier(result_id),)).fetchone()
        if row is None or row["overlay_path"] is None:
            raise VisionError(404, "No change overlay is available for this result")
        return self._safe_path(row["overlay_path"])

    @staticmethod
    def _roi(roi: dict[str, Any] | None, width: int, height: int) -> dict[str, int]:
        if roi is None:
            return {"x": 0, "y": 0, "width": width, "height": height}
        fields = {"x", "y", "width", "height"}
        if not isinstance(roi, dict) or set(roi) != fields:
            raise VisionError(422, "roi must contain exactly integer x, y, width, height")
        if any(isinstance(roi[key], bool) or not isinstance(roi[key], int) for key in fields):
            raise VisionError(422, "roi coordinates must be integers")
        x, y, w, h = (roi[key] for key in ("x", "y", "width", "height"))
        if x < 0 or y < 0 or w < 1 or h < 1 or x + w > width or y + h > height:
            raise VisionError(422, "roi lies outside image bounds")
        return dict(roi)

    def analyze(self, evidence_id: str, reference_id: str | None = None,
                roi: dict[str, Any] | None = None) -> dict[str, Any]:
        evidence = self.get_evidence(evidence_id)
        current = cv2.imread(str(self.file_path(evidence_id)), cv2.IMREAD_COLOR)
        if current is None:
            raise VisionError(422, "Stored image could not be decoded")
        height, width = current.shape[:2]
        region = self._roi(roi, width, height)
        x, y, w, h = (region[key] for key in ("x", "y", "width", "height"))
        current_gray = cv2.cvtColor(current[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
        quality: dict[str, Any] = {"current": _quality(current_gray), "reference": None}
        reasons = ["uncalibrated_vision_score"]
        if evidence["capture_time"] is None:
            reasons.append("capture_time_unknown")
        reasons.extend(f"current_{flag}" for flag in quality["current"]["flags"])
        metrics: dict[str, Any] | None = None
        overlay: np.ndarray | None = None
        reference: dict[str, Any] | None = None
        if reference_id is None:
            reasons.append("reference_unavailable")
        else:
            if reference_id == evidence_id:
                raise VisionError(422, "A reference must be a different evidence image")
            reference = self.get_evidence(reference_id)
            for key in ("site_id", "device_id", "camera_id", "source", "scope", "width", "height"):
                if reference.get(key) != evidence.get(key):
                    raise VisionError(422, f"Reference and current image must have matching {key}")
            prior = cv2.imread(str(self.file_path(reference_id)), cv2.IMREAD_COLOR)
            if prior is None or prior.shape != current.shape:
                raise VisionError(422, "Reference image could not be decoded with matching dimensions")
            reference_gray = cv2.cvtColor(prior[y:y + h, x:x + w], cv2.COLOR_BGR2GRAY)
            quality["reference"] = _quality(reference_gray)
            reasons.extend(f"reference_{flag}" for flag in quality["reference"]["flags"])
            if reference["capture_time"] is None:
                reasons.append("reference_capture_time_unknown")
            a, b = _sample(current_gray), _sample(reference_gray)
            difference = cv2.absdiff(a, b)
            threshold = QUALITY_THRESHOLDS["absolute_difference_threshold"]
            scale_x, scale_y = a.shape[1] / w, a.shape[0] / h
            metrics = {
                "mean_absolute_difference": round(float(difference.mean()), 6),
                "changed_area_ratio": round(float(np.mean(difference > threshold)), 6),
                "absolute_difference_threshold": threshold,
                "ssim": round(_ssim(a, b), 6),
                "analysis_width": a.shape[1], "analysis_height": a.shape[0],
                "analysis_scale_x": scale_x, "analysis_scale_y": scale_y,
                "optical_flow_median_px_per_frame": None,
                "optical_flow_p95_px_per_frame": None,
                "optical_flow_unit": "original_image_pixels_per_frame_pair",
                "interpretation": "Pixel differences can also reflect lighting or camera movement; no physical displacement or risk inference",
            }
            if min(a.shape) >= 8:
                flow = cv2.calcOpticalFlowFarneback(b, a, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                magnitude = np.hypot(flow[:, :, 0] / scale_x, flow[:, :, 1] / scale_y)
                metrics["optical_flow_median_px_per_frame"] = round(float(np.median(magnitude)), 6)
                metrics["optical_flow_p95_px_per_frame"] = round(float(np.percentile(magnitude, 95)), 6)
            else:
                reasons.append("roi_too_small_for_optical_flow")
            # Colorize only changed pixels so identical images do not imply damage.
            changed = cv2.resize(difference, (w, h), interpolation=cv2.INTER_NEAREST)
            heatmap = cv2.applyColorMap(changed, cv2.COLORMAP_JET)
            original_roi = current[y:y + h, x:x + w]
            blended = cv2.addWeighted(original_roi, 0.55, heatmap, 0.45, 0)
            overlay = current.copy()
            overlay[y:y + h, x:x + w] = np.where((changed > threshold)[:, :, None], blended, original_roi)
            if region != {"x": 0, "y": 0, "width": width, "height": height}:
                cv2.rectangle(overlay, (x, y), (x + w - 1, y + h - 1), (255, 220, 0), 1)

        result_id, created_at = str(uuid4()), _utc_now()
        overlay_stored = f"overlays/{result_id}.png" if overlay is not None else None
        result = {
            "id": result_id, "evidence_id": evidence_id, "reference_id": reference_id,
            "site_id": evidence["site_id"], "device_id": evidence.get("device_id"),
            "camera_id": evidence["camera_id"],
            "source": evidence["source"], "scope": evidence["scope"],
            "capture_time": evidence["capture_time"], "created_at": created_at,
            "algorithm_mode": "opencv_baseline", "model_version": None,
            "vision_score": None, "calibration_status": "uncalibrated",
            "quality": quality, "metrics": metrics, "roi": region,
            "baseline_valid": bool(reference is not None and quality["current"]["acceptable"]
                                   and quality["reference"]["acceptable"]),
            "fusion_eligible": False, "reasons": reasons,
            "overlay_url": f"/api/v1/vision/results/{result_id}/overlay" if overlay_stored else None,
            "risk_interpretation": "Uncalibrated technical baseline only; vision_score is unavailable and this result must not trigger geological danger alerts",
        }
        overlay_path = self.media_dir / overlay_stored if overlay_stored else None
        try:
            if overlay_path is not None:
                success, encoded = cv2.imencode(".png", overlay)
                if not success:
                    raise VisionError(500, "Could not encode the change overlay")
                self._atomic_write(overlay_path, encoded.tobytes())
            with self.db.connection() as connection:
                connection.execute("""INSERT INTO vision_results
                    (id, site_id, evidence_id, reference_id, created_at, overlay_path, data_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    result_id, evidence["site_id"], evidence_id, reference_id, created_at,
                    overlay_stored, json.dumps(result, ensure_ascii=False, allow_nan=False)))
        except BaseException:
            if overlay_path is not None:
                overlay_path.unlink(missing_ok=True)
            raise
        return result
