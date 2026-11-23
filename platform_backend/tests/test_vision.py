from contextlib import contextmanager
import io
import json
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


def test_filtered_pages_find_device_before_limit_and_count_all_matching_rows(service):
    frame = np.full((16, 16), 100, np.uint8)
    expected_evidence, expected_results = [], []
    for _ in range(3):
        evidence = upload(service, frame, device_id="NODE-A", source="REAL", camera_id="CAM-A")
        expected_evidence.append(evidence["id"])
        expected_results.append(service.analyze(evidence["id"])["id"])
    # Newer same-site records from a different device/source must not crowd the
    # selected stream out of the default 50-row list or its result history.
    for _ in range(53):
        evidence = upload(service, frame, device_id="NODE-B", source="MOCK", camera_id="CAM-B")
        service.analyze(evidence["id"])
    evidence_page = service.evidence_page("SLOPE-01", 2, device_id="NODE-A", source="REAL")
    results_page = service.results_page("SLOPE-01", 2, device_id="NODE-A", source="REAL")
    assert evidence_page["total"] == results_page["total"] == 3
    assert len(evidence_page["items"]) == len(results_page["items"]) == 2
    assert evidence_page["next_cursor"] and results_page["next_cursor"]
    assert set(e["id"] for e in service.list_evidence("SLOPE-01", device_id="NODE-A", source="REAL")) == set(expected_evidence)
    assert set(r["id"] for r in service.list_results("SLOPE-01", device_id="NODE-A", source="REAL")) == set(expected_results)
    assert all(r["device_id"] == "NODE-A" for r in results_page["items"])
    assert service.evidence_page("SLOPE-01", source="MOCK")["total"] == 53
    assert service.results_page("SLOPE-01", source="REAL")["total"] == 3
    assert service.evidence_page("SLOPE-01", device_id="NODE-A", source="MOCK")["items"] == []
    assert service.results_page("SLOPE-01", device_id="NODE-A", camera_id="CAM-B")["total"] == 0
    assert service.evidence_page("OTHER-SITE", source="REAL")["total"] == 0


@pytest.mark.parametrize("kind", ["evidence", "results"])
def test_cursor_pages_equal_timestamps_without_skips_and_with_newer_arrivals(service, kind):
    stamp = "2000-01-01T09:00:00.000000Z"
    frames = [upload(service, np.full((16, 16), i, np.uint8), device_id="NODE-A") for i in range(5)]
    analyses = [service.analyze(frame["id"]) for frame in frames]
    table, column = (("vision_evidence", "arrival_time") if kind == "evidence"
                     else ("vision_results", "created_at"))
    expected = {item["id"] for item in (frames if kind == "evidence" else analyses)}
    with service.db.connection() as connection:
        connection.execute(f"UPDATE {table} SET {column} = ?", (stamp,))
    get_page = service.evidence_page if kind == "evidence" else service.results_page
    first = get_page("SLOPE-01", 2, device_id="NODE-A", source="MOCK")
    assert first["total"] == 5 and first["next_cursor"]
    # A new image/result arriving after page 1 belongs on a refreshed first
    # page; it must not make the current continuation repeat or omit old rows.
    recent = upload(service, np.full((16, 16), 200, np.uint8), device_id="NODE-A")
    service.analyze(recent["id"])
    rows = list(first["items"])
    cursor = first["next_cursor"]
    while cursor:
        page = get_page("SLOPE-01", 2, device_id="NODE-A", source="MOCK", cursor=cursor)
        assert page["total"] == 6
        rows.extend(page["items"])
        cursor = page["next_cursor"]
    assert len(rows) == 5 and {row["id"] for row in rows} == expected
    assert get_page("SLOPE-01", 1, device_id="NODE-A", source="MOCK")["items"][0]["id"] not in expected


@pytest.mark.parametrize("kind", ["evidence", "results"])
def test_cursor_is_rejected_when_malformed_or_from_another_list(service, kind):
    for _ in range(2):
        evidence = upload(service, np.full((16, 16), 100, np.uint8), device_id="NODE-A")
        service.analyze(evidence["id"])
    get_page = service.evidence_page if kind == "evidence" else service.results_page
    other_page = service.results_page if kind == "evidence" else service.evidence_page
    cursor = get_page("SLOPE-01", 1, device_id="NODE-A")["next_cursor"]
    for wrong in ("not-base64", "☃", "x" * 5000, "W10"):
        with pytest.raises(VisionError) as error:
            get_page("SLOPE-01", cursor=wrong)
        assert error.value.status_code == 422
    with pytest.raises(VisionError) as error:
        get_page("SLOPE-01", device_id="NODE-B", cursor=cursor)
    assert error.value.status_code == 422
    with pytest.raises(VisionError):
        other_page("SLOPE-01", device_id="NODE-A", cursor=cursor)


@pytest.mark.parametrize("reference_device,current_device", [
    ("NODE-A", "NODE-B"), (None, "NODE-A"), ("NODE-A", None),
])
def test_reference_requires_same_device_even_when_camera_id_is_shared(service, reference_device, current_device):
    frame = textured(32)
    reference = upload(service, frame, device_id=reference_device)
    current = upload(service, frame, device_id=current_device)
    with pytest.raises(VisionError, match="device_id") as error:
        service.analyze(current["id"], reference["id"])
    assert error.value.status_code == 422
    assert service.list_results() == []


def test_legacy_site_evidence_remains_comparable_but_is_not_assigned_to_a_device(service):
    frame = textured(32)
    reference = upload(service, frame)
    current = upload(service, frame)
    result = service.analyze(current["id"], reference["id"])
    assert result["device_id"] is None
    assert service.get_result(result["id"])["device_id"] is None
    assert service.results_page("SLOPE-01")["total"] == 1
    assert service.results_page("SLOPE-01", device_id="NODE-A")["total"] == 0


def test_existing_result_json_without_device_id_is_projected_from_original_evidence(service):
    evidence = upload(service, textured(32), device_id="NODE-A")
    result = service.analyze(evidence["id"])
    assert result["device_id"] == "NODE-A"
    legacy = {key: value for key, value in result.items() if key != "device_id"}
    with service.db.connection() as connection:
        connection.execute("UPDATE vision_results SET data_json = ? WHERE id = ?",
                           (json.dumps(legacy), result["id"]))
    reopened = VisionService(service.db, service.media_dir)
    assert reopened.get_result(result["id"])["device_id"] == "NODE-A"
    page = reopened.results_page("SLOPE-01", device_id="NODE-A", source="MOCK")
    assert page["total"] == 1 and page["items"][0]["device_id"] == "NODE-A"
    # Projection does not rewrite historical analysis records.
    with reopened.db.connection() as connection:
        stored = connection.execute("SELECT data_json FROM vision_results WHERE id = ?", (result["id"],)).fetchone()[0]
    assert "device_id" not in json.loads(stored)
