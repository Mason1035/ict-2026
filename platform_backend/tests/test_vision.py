from contextlib import contextmanager
import io
import sqlite3

import cv2
import numpy as np
from PIL import Image
import pytest

from geohazard_platform import vision
from geohazard_platform.vision import VisionError, VisionService


class LocalDatabase:
    """Exercise real SQLite transactions independently of unrelated tables."""

    def __init__(self, path):
        self.path = path

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()


@pytest.fixture
def service(tmp_path):
    return VisionService(LocalDatabase(tmp_path / "platform.sqlite3"), tmp_path / "media")


def encoded(array, image_format="PNG", **options):
    output = io.BytesIO()
    Image.fromarray(array).save(output, format=image_format, **options)
    return output.getvalue()


def textured(size=160):
    random = np.random.default_rng(31).integers(0, 256, (size, size), dtype=np.uint8)
    return cv2.GaussianBlur(random, (3, 3), 0.6)


def upload(service, array, **kwargs):
    return service.upload(encoded(array), "frame.png", site_id=kwargs.pop("site_id", "SLOPE-01"), **kwargs)


def test_actual_content_validation_and_bounded_bytes(service, tmp_path):
    for bad in (b"not a PNG", b"<svg><script>not an image</script></svg>", b"\x89PNG\r\n\x1a\n"):
        with pytest.raises(VisionError) as error:
            service.upload(bad, "looks-valid.png", site_id="SLOPE-01")
        assert error.value.status_code == 415
    with pytest.raises(VisionError) as error:
        service.upload(b"", "empty.png", site_id="SLOPE-01")
    assert error.value.status_code == 422
    limited = VisionService(service.db, tmp_path / "limited", max_upload_bytes=10)
    with pytest.raises(VisionError) as error:
        limited.upload(b"x" * 11, "big.png", site_id="SLOPE-01")
    assert error.value.status_code == 413
    # An executable-looking name does not change real image content or stored suffix.
    evidence = service.upload(encoded(textured()), "image.exe", site_id="SLOPE-01")
    assert evidence["content_type"] == "image/png"
    assert service.file_path(evidence["id"]).suffix == ".png"


def test_dimension_gate_runs_before_opencv_decode(service, monkeypatch):
    monkeypatch.setattr(vision, "MAX_IMAGE_PIXELS", 1000)
    with pytest.raises(VisionError) as error:
        upload(service, np.zeros((40, 40), np.uint8))
    assert error.value.status_code == 413
    assert service.list_evidence() == []


def test_filename_cannot_choose_storage_path_and_lookup_rejects_traversal(service):
    evidence = service.upload(encoded(textured()), "../../escape.png", site_id="SLOPE-01")
    assert evidence["filename"] == "escape.png"
    assert service.file_path(evidence["id"]).parent == service.media_dir / "evidence"
    assert service.file_path(evidence["id"]).stem == evidence["id"]
    for invalid in ("../../etc/passwd", "/etc/passwd", evidence["id"] + ".png"):
        with pytest.raises(VisionError) as error:
            service.file_path(invalid)
        assert error.value.status_code == 404
    # Even corrupted database metadata cannot expose a file outside media_dir.
    with service.db.connection() as connection:
        connection.execute("UPDATE vision_evidence SET path = ? WHERE id = ?", ("../../outside.png", evidence["id"]))
    with pytest.raises(VisionError):
        service.file_path(evidence["id"])


def test_jpeg_exif_orientation_applied_and_metadata_stripped(service):
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Do not retain this author"
    content = encoded(np.zeros((30, 20, 3), np.uint8), "JPEG", exif=exif)
    evidence = service.upload(content, "camera.jpg", site_id="SLOPE-01")
    assert (evidence["width"], evidence["height"]) == (30, 20)
    with Image.open(service.file_path(evidence["id"])) as restored:
        assert restored.getexif() == {}
        assert restored.size == (30, 20)


def test_no_reference_reports_quality_without_risk(service):
    evidence = upload(service, np.zeros((64, 64), np.uint8))
    result = service.analyze(evidence["id"])
    assert result["vision_score"] is None
    assert result["model_version"] is None
    assert result["algorithm_mode"] == "opencv_baseline"
    assert not result["baseline_valid"] and not result["fusion_eligible"]
    assert result["metrics"] is None and result["overlay_url"] is None
    assert set(result["quality"]["current"]["flags"]) == {"blur", "dark", "low_contrast"}
    assert "reference_unavailable" in result["reasons"]
    assert "capture_time_unknown" in result["reasons"]
    with pytest.raises(VisionError) as error:
        service.result_overlay_path(result["id"])
    assert error.value.status_code == 404


def test_identical_images_have_zero_change_and_quality_not_risk(service):
    array = textured()
    reference = upload(service, array, capture_time="2026-10-16T10:00:00+08:00")
    current = upload(service, array, capture_time="2026-10-16T10:00:01+08:00")
    result = service.analyze(current["id"], reference["id"])
    assert result["metrics"]["changed_area_ratio"] == 0
    assert result["metrics"]["mean_absolute_difference"] == 0
    assert result["metrics"]["ssim"] == 1
    assert result["metrics"]["optical_flow_median_px_per_frame"] < 0.02
    assert result["baseline_valid"]
    assert result["vision_score"] is None and not result["fusion_eligible"]
    assert current["capture_time"] == "2026-10-16T02:00:01Z"
    overlay = cv2.imread(str(service.result_overlay_path(result["id"])), cv2.IMREAD_GRAYSCALE)
    assert np.array_equal(overlay, array)


def test_translation_detects_change_and_generates_overlay(service):
    reference_array = textured()
    current_array = cv2.warpAffine(reference_array, np.float32([[1, 0, 4], [0, 1, 0]]),
                                   (160, 160), borderMode=cv2.BORDER_REFLECT)
    reference = upload(service, reference_array)
    current = upload(service, current_array)
    result = service.analyze(current["id"], reference["id"])
    assert result["metrics"]["changed_area_ratio"] > 0.1
    assert result["metrics"]["ssim"] < 0.9
    assert 2.5 < result["metrics"]["optical_flow_median_px_per_frame"] < 5.5
    assert service.result_overlay_path(result["id"]).is_file()
    assert result["vision_score"] is None


@pytest.mark.parametrize("roi", [
    {"x": -1, "y": 0, "width": 10, "height": 10},
    {"x": 0, "y": 0, "width": 161, "height": 10},
    {"x": 0, "y": 0, "width": 0, "height": 10},
    {"x": 0.0, "y": 0, "width": 10, "height": 10},
    {"x": True, "y": 0, "width": 10, "height": 10},
    {"x": 0, "y": 0, "width": 10},
])
def test_invalid_roi_is_rejected(service, roi):
    evidence = upload(service, textured())
    with pytest.raises(VisionError) as error:
        service.analyze(evidence["id"], roi=roi)
    assert error.value.status_code == 422


def test_roi_limits_pixel_comparison(service):
    reference_array = textured()
    current_array = reference_array.copy()
    current_array[80:, 80:] = 255
    reference = upload(service, reference_array)
    current = upload(service, current_array)
    roi = {"x": 0, "y": 0, "width": 60, "height": 60}
    result = service.analyze(current["id"], reference["id"], roi=roi)
    assert result["metrics"]["changed_area_ratio"] == 0
    assert result["roi"] == roi


@pytest.mark.parametrize("different", [
    {"site_id": "OTHER-SITE"}, {"camera_id": "OTHER-CAMERA"},
    {"source": "REAL"}, {"scope": "OPERATIONAL"},
])
def test_incompatible_reference_metadata_is_rejected(service, different):
    reference = upload(service, textured(), **different)
    current = upload(service, textured())
    with pytest.raises(VisionError) as error:
        service.analyze(current["id"], reference["id"])
    assert error.value.status_code == 422


def test_size_mismatch_and_same_evidence_rejected(service):
    reference = upload(service, textured(120))
    current = upload(service, textured(160))
    with pytest.raises(VisionError, match="width"):
        service.analyze(current["id"], reference["id"])
    with pytest.raises(VisionError, match="different"):
        service.analyze(current["id"], current["id"])


def test_persists_evidence_results_and_files_across_service_recreation(service):
    reference = upload(service, textured())
    current = upload(service, textured())
    result = service.analyze(current["id"], reference["id"])
    reopened = VisionService(service.db, service.media_dir)
    assert reopened.get_evidence(current["id"]) == current
    assert reopened.get_result(result["id"]) == result
    assert reopened.list_results("SLOPE-01") == [result]
    assert len(reopened.list_evidence("SLOPE-01")) == 2
    assert reopened.list_evidence("NO-SUCH-SITE") == []
    assert reopened.result_overlay_path(result["id"]).is_file()


def test_database_failure_cleans_new_file(service):
    with service.db.connection() as connection:
        connection.execute("""CREATE TRIGGER reject_evidence BEFORE INSERT ON vision_evidence
                              BEGIN SELECT RAISE(FAIL, 'simulated database error'); END""")
    with pytest.raises(sqlite3.IntegrityError):
        upload(service, textured())
    assert list((service.media_dir / "evidence").iterdir()) == []
    assert service.list_evidence() == []


def test_bad_scope_source_timestamp_and_limits_rejected(service):
    for kwargs in ({"source": "UNKNOWN"}, {"scope": "guess"},
                   {"capture_time": "2026-10-16T12:00:00"}, {"site_id": ""}):
        with pytest.raises(VisionError) as error:
            upload(service, textured(), **kwargs)
        assert error.value.status_code == 422
    with pytest.raises(VisionError):
        service.list_evidence(limit=1000)
