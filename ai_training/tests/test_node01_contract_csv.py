"""TEST_ONLY synthetic triplets; optional read-only real experiment verification."""
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zlib

import pytest

from ai_training.real_intake.node01_contract_csv import COLUMNS, HEADER, ConversionError, convert, main

REPO = Path(__file__).resolve().parents[2]
ELF = "a" * 64
IDENTITY = "TEST_ONLY-device-N0000001.CSV"


def observation(kind, channel, time, *, valid=True, raw="0"):
    r = dict.fromkeys(COLUMNS, "")
    r.update(kind=kind, channel=str(channel), attempted_uptime_us=str(time - 1),
             acquired_uptime_us=str(time) if valid else "", time_synced="false",
             validity="Valid" if valid else "Error", error="0" if valid else "259")
    if valid:
        if kind == "imu":
            r.update({k: "1.230000e-02" for k in COLUMNS[15:21]})
        else:
            r["soil_raw"] = raw
    return r


def triplet(tmp_path, rows=None, *, suffix=""):
    folder = tmp_path / "TEST_ONLY"
    folder.mkdir()
    p = folder / "N0000001.CSV"
    rows = rows if rows is not None else [observation("imu", 0, 10000), observation("imu", 1, 12000)]
    f = io.StringIO(newline="")
    f.write(f"# TEST_ONLY; app_elf_sha256={ELF}\n# firmware=TEST_ONLY; device=NODE-01; boot_id=unavailable\n")
    w = csv.DictWriter(f, COLUMNS, lineterminator="\n")
    w.writeheader()
    for i, r in enumerate(rows):
        r["acquisition_index"] = str(i)
        w.writerow(r)
    p.write_bytes(f.getvalue().encode())
    common = {"experiment_id": IDENTITY, "elf_sha256": ELF, "csv": "/sdcard/" + p.name}
    beg = p.with_name(p.stem + suffix + ".BEG")
    beg.write_text(json.dumps(dict(common, record_type="START_INTENT")))
    end = dict(common, record_type="END", accepted=len(rows), verified_rows=len(rows),
               csv_bytes=p.stat().st_size, csv_crc32=f"{zlib.crc32(p.read_bytes()):08x}",
               top_valid=sum(r["kind"] == "imu" and r["channel"] == "0" and r["validity"] == "Valid" for r in rows),
               toe_valid=sum(r["kind"] == "imu" and r["channel"] == "1" and r["validity"] == "Valid" for r in rows),
               soil_valid=[sum(r["kind"] == "soil" and r["channel"] == str(c) and r["validity"] == "Valid" for r in rows) for c in range(3)])
    p.with_suffix(".END").write_text(json.dumps(end))
    return p


def read_csv(p):
    with p.open(newline="") as f:
        return list(csv.DictReader(f))


def fingerprints(folder):
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir() if p.is_file()}


def contract(out):
    return read_csv(next(out.glob("*.contract.csv")))


def test_alignment_text_identity_and_determinism(tmp_path):
    p = triplet(tmp_path)
    before = fingerprints(p.parent)
    a, b = tmp_path / "a", tmp_path / "b"
    result = convert(p, a)
    convert(p, b)
    assert fingerprints(a) == fingerprints(b)
    assert fingerprints(p.parent) == before
    r = contract(a)
    assert tuple(r[0]) == HEADER
    assert len(r) == 1 and r[0]["top_ax"] == r[0]["toe_ax"] == "1.230000e-02"
    assert r[0]["run_id"] == IDENTITY
    assert all(r[0][k] == "" for k in ("timestamp_ms", "flow_lpm", "rain_level", "label"))
    assert read_csv(a / "timing.csv")[0]["toe_minus_top_us"] == "2000"
    assert result["source_data_rows"] == 2
    h = json.loads((a / "handoff.json").read_text())
    template = json.loads((REPO / 'algorithm/B_revised/data_intake/A_RUN_HANDOFF_DRAFT.json').read_text())
    assert set(h) == set(template) and set(h["sidecars"]) == set(template["sidecars"])
    assert h["firmware_version"] == "TEST_ONLY" and h["source"] == "REAL"
    assert h["identity"]["boot_id"] is None
    for ref in (h["csv"], h["sidecars"]["timing"], h["sidecars"]["validity"]):
        assert fingerprints(a)[ref["path"]] == ref["sha256"]


def test_nearest_unused_and_unmatched_low_rate(tmp_path):
    rows = [observation("imu", 0, t) for t in (10000, 20000, 30000, 40000)]
    rows += [observation("imu", 1, t) for t in (12000, 18000, 70000)]
    p = triplet(tmp_path, rows)
    out = tmp_path / "out"
    convert(p, out)
    r = contract(out)
    assert len(r) == 5
    assert sum(bool(x["top_ax"]) for x in r) == 4
    assert sum(bool(x["toe_ax"]) for x in r) == 3
    t = read_csv(out / "timing.csv")
    assert [x["toe_minus_top_us"] for x in t] == ["2000", "-2000", "", "", ""]
    assert r[-1]["top_ax"] == "" and r[-1]["toe_ax"]


def test_pair_tolerance_boundary_ties_and_source_order(tmp_path):
    rows = [observation("imu", 0, t) for t in (10000, 11000, 12000)]
    # Input order need not follow device time. Equal-distance candidates prefer
    # the earlier time; identical times prefer the smaller acquisition index.
    rows += [observation("imu", 1, t) for t in (15000, 5000, 5000, 40000)]
    p = triplet(tmp_path, rows)
    out = tmp_path / "out"
    convert(p, out)
    timing = read_csv(out / "timing.csv")
    paired = {r["top_acquisition_index"]: r["toe_acquisition_index"]
              for r in timing if r["top_acquisition_index"]}
    assert paired == {"0": "4", "1": "3", "2": ""}
    assert [int(r["anchor_uptime_us"]) for r in timing] == [5000, 10000, 11000, 12000, 40000]
    assert sorted(r["toe_acquisition_index"] for r in timing if r["toe_acquisition_index"]) == ["3", "4", "5", "6"]


def test_error_rows_and_soil_causality_zero(tmp_path):
    rows = [observation("imu", 0, 10000), observation("imu", 1, 12000, valid=False),
            observation("soil", 0, 11000, raw="0"), observation("soil", 1, 15000, raw="-12"),
            observation("soil", 2, 20000, raw="27"), observation("imu", 0, 20000, valid=False),
            observation("imu", 1, 30000), observation("soil", 0, 25000, valid=False)]
    p = triplet(tmp_path, rows)
    out = tmp_path / "out"
    convert(p, out)
    r = contract(out)
    assert len(r) == 3 and r[0]["toe_ax"] == "" and r[1]["top_ax"] == ""
    assert [x["soil_top_raw"] for x in r] == ["", "0", ""]
    assert [x["soil_middle_raw"] for x in r] == ["", "-12", ""]
    assert [x["soil_toe_raw"] for x in r] == ["", "", "27"]  # Error TOP anchored at attempted=19999
    v = read_csv(out / "validity.csv")
    assert [x["row_index"] for x in v] == ["0", "1", "2"]
    assert all(x["error"] == "259" for x in v)
    t = read_csv(out / "timing.csv")
    assert t[1]["soil_ch0_to_anchor_us"] == "8999"
    assert t[2]["soil_ch2_to_anchor_us"] == "10000"
    blank = tmp_path / "blank"
    meta = convert(p, blank, blank_ain2=True)
    assert all(x["soil_toe_raw"] == "" for x in contract(blank))
    assert meta["blank_ain2"] and meta["AIN2_DIAGNOSTIC_ONLY"]
    assert meta["nonempty_cells"]["soil_toe_raw"] == 0


@pytest.mark.parametrize("field,value,reason", [
    ("csv_bytes", 0, "CSV_BYTES_MISMATCH"), ("csv_crc32", "00000000", "CSV_CRC32_MISMATCH"),
    ("accepted", 3, "ACCEPTED_COUNT_MISMATCH"), ("verified_rows", 3, "VERIFIED_ROWS_MISMATCH"),
    ("top_valid", 0, "VALID_COUNT_MISMATCH"), ("toe_valid", 0, "VALID_COUNT_MISMATCH"),
    ("soil_valid", [1, 0, 0], "VALID_COUNT_MISMATCH"),
    ("experiment_id", "OTHER-N0000001.CSV", "EXPERIMENT_ID_MISMATCH"),
    ("elf_sha256", "b" * 64, "ELF_SHA256_MISMATCH"),
])
def test_integrity_refusal(tmp_path, field, value, reason):
    p = triplet(tmp_path)
    e = json.loads(p.with_suffix(".END").read_text())
    e[field] = value
    p.with_suffix(".END").write_text(json.dumps(e))
    out = tmp_path / "out"
    with pytest.raises(ConversionError, match=reason):
        convert(p, out)
    assert not out.exists()
    assert not list(tmp_path.glob(".node01-*"))


@pytest.mark.parametrize("mutation,reason", [("header", "HEADER_MISMATCH"), ("index", "DISCONTINUITY"),
                                           ("firmware", "CSV_ELF"), ("number", "INVALID_MEASUREMENT")])
def test_payload_refusal_after_valid_crc(tmp_path, mutation, reason):
    p = triplet(tmp_path)
    data = p.read_text()
    data = {"header": lambda: data.replace("kind,channel,", "type,channel,"),
            "index": lambda: data.replace("imu,0,0,", "imu,0,9,"),
            "firmware": lambda: data.replace(ELF, "b" * 64),
            "number": lambda: data.replace("1.230000e-02", "NaN")}[mutation]()
    p.write_text(data)
    e = json.loads(p.with_suffix(".END").read_text())
    e.update(csv_bytes=p.stat().st_size, csv_crc32=f"{zlib.crc32(p.read_bytes()):08x}")
    p.with_suffix(".END").write_text(json.dumps(e))
    with pytest.raises(ConversionError, match=reason):
        convert(p, tmp_path / "out")
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("missing", [".BEG", ".END"])
def test_empty_and_missing_sidecars(tmp_path, missing):
    p = triplet(tmp_path, [])
    with pytest.raises(ConversionError, match="NO_DATA_ROWS"):
        convert(p, tmp_path / "out")
    p.with_suffix(missing).unlink()
    with pytest.raises(ConversionError, match="SIDECAR_NOT_UNIQUE"):
        convert(p, tmp_path / "out")


def test_suffixed_explicit_ambiguous_sidecars_and_override(tmp_path):
    p = triplet(tmp_path, suffix="I2C报错")
    convert(p, tmp_path / "a")
    beg = p.with_name(p.stem + "I2C报错.BEG")
    p.with_suffix(".BEG").write_bytes(beg.read_bytes())
    with pytest.raises(ConversionError, match="SIDECAR_NOT_UNIQUE"):
        convert(p, tmp_path / "b")
    convert(p, tmp_path / "b", beg=beg, end=p.with_suffix(".END"), run_id="TEST_ONLY-override")
    assert contract(tmp_path / "b")[0]["run_id"] == "TEST_ONLY-override"


def test_output_guard_and_cli_json(tmp_path, capsys):
    p = triplet(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    convert(p, out)
    before = fingerprints(out)
    assert main([str(p), "--output-dir", str(out)]) == 2
    assert json.loads(capsys.readouterr().err)["status"] == "REFUSED"
    assert fingerprints(out) == before
    with pytest.raises(ConversionError, match="OUTPUT_MUST_BE"):
        convert(p, REPO / "ai_training/TEST_ONLY-forbidden-output")
    with pytest.raises(ConversionError, match="OUTPUT_INSIDE_SOURCE"):
        convert(p, p.parent / "out")
    for run_id in ("../bad", "", "a/b", "a\nb"):
        with pytest.raises(ConversionError, match="RUN_ID"):
            convert(p, tmp_path / "other", run_id=run_id)
    with pytest.raises(ConversionError, match="PAIR_TOLERANCE"):
        convert(p, tmp_path / "other", pair_tolerance_us=-1)


def test_session_full_identity_selection(tmp_path):
    p = triplet(tmp_path)
    s = p.parent / "session.json"
    s.write_text(json.dumps({"firmware_identity": "NOT_OBSERVED", "experiments": [
        {"experiment_id": "OTHER-N0000001.CSV", "begin_observation": {"iso8601": "wrong"}},
        {"experiment_id": IDENTITY, "begin_observation": {"iso8601": "TEST_ONLY"},
         "terminal_observation": {"iso8601": "TEST_ONLY_FINAL"}, "device_time_sync": "NOT_SYNCHRONIZED"}]}))
    result = convert(p, tmp_path / "out")
    assert result["session"]["begin_observation"]["iso8601"] == "TEST_ONLY"
    s.write_text('{"experiments": []}')
    with pytest.raises(ConversionError, match="SESSION_EXPERIMENT_ID"):
        convert(p, tmp_path / "other")


@pytest.mark.parametrize("soil_times,reason", [([40000], "SOIL_AFTER_LAST_ANCHOR"),
                                             ([11000, 12000], "SOIL_COLLISION")])
def test_unrepresentable_soil_is_refused_without_loss(tmp_path, soil_times, reason):
    rows = [observation("imu", 0, t) for t in (10000, 30000)]
    rows += [observation("soil", 0, t) for t in soil_times]
    p = triplet(tmp_path, rows)
    with pytest.raises(ConversionError, match=reason):
        convert(p, tmp_path / "out")
    assert not (tmp_path / "out").exists()


SAMPLES = [
    ("AIR-1", "标定土壤传感器/AIR-1/N0000010.CSV", 6159, 2998, 2981, [60]*3),
    ("WATER-1", "标定土壤传感器/WATER-1/N0000021.CSV", 6160, 2998, 2982, [60]*3),
    ("N0000023", "标定土壤传感器/测试ANI2异常数据/N0000023.CSV", 5074, 2992, 1890, [60]*3),
    ("plus-Z", "标定IMU/IMU +Z朝上/10轮测试数据/N0000002.CSV", 5347, 2993, 2174, [60]*3),
    ("300s", "标定IMU/300秒静态零偏标定IMU/第二轮测试数据/N0000002.CSV", 61632, 29998, 29834, [600]*3),
]


def real_root():
    value = os.environ.get("ICT_NODE01_DATA_ROOT")
    if not value:
        pytest.skip("ICT_NODE01_DATA_ROOT not set")
    root = Path(value)
    assert root.is_dir(), f"Real data root missing: {root}"
    return root


@pytest.mark.parametrize("name,rel,total,top,toe,soil", SAMPLES, ids=[x[0] for x in SAMPLES])
def test_real_data(name, rel, total, top, toe, soil):
    p = real_root() / rel
    assert p.is_file(), f"Required real sample missing: {p}"
    paths = [p, *p.parent.glob(p.stem + "*.BEG"), p.with_suffix(".END")]
    if (p.parent / "session.json").exists():
        paths.append(p.parent / "session.json")
    before = {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in paths}
    root = REPO / "work/node01_contract"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-" + name + "-", dir=root) as temp:
        out = Path(temp) / "converted"
        result = convert(p, out)
        rows = contract(out)
        assert result["source_data_rows"] == total
        for field, count in [(f, top) for f in HEADER[2:8]] + [(f, toe) for f in HEADER[8:14]]:
            assert sum(bool(r[field]) for r in rows) == count
            assert result["nonempty_cells"][field] == count
        for field, count in zip(HEADER[14:17], soil):
            assert sum(bool(r[field]) for r in rows) == count
        if name == "AIR-1":
            assert result["sources"]["csv"]["bytes"] == 844004
            assert result["end"]["csv_crc32"] == "19f9044b"
        if name == "N0000023":
            invalid = read_csv(out / "validity.csv")
            assert len(invalid) == 12
            assert all(r["kind"] == "imu" and r["channel"] == "1" and r["error"] == "259" for r in invalid)
            assert result["end"]["i2c_errors"] == result["end"]["sensor_errors"] == 12
            assert any(r["top_ax"] and not r["toe_ax"] for r in rows[-100:])
        if name == "plus-Z":
            assert 72 < toe / (result["end"]["actual_duration_us"] / 1e6) < 73
            assert sum(bool(r["top_ax"]) and not r["toe_ax"] for r in rows) > 800
        checked = subprocess.run([sys.executable, str(REPO / "algorithm/B_revised/data_intake/check_experiment_csv.py"),
                                  str(next(out.glob("*.contract.csv"))), "--output", str(Path(temp) / "report.json")],
                                 capture_output=True, text=True)
        assert checked.returncode == 0, checked.stdout + checked.stderr
        assert json.loads((Path(temp) / "report.json").read_text())["status"] == "CSV_CHECKED"
        again = Path(temp) / "again"
        convert(p, again)
        assert fingerprints(out) == fingerprints(again)
    assert {str(f): hashlib.sha256(f.read_bytes()).hexdigest() for f in paths} == before


def test_real_header_only_refused():
    p = real_root() / "标定土壤传感器/测试ANI2异常数据/N0000027.CSV"
    assert p.is_file()
    root = REPO / "work/node01_contract"
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="test-header-only-", dir=root) as temp:
        with pytest.raises(ConversionError):
            convert(p, Path(temp) / "out")
        assert not (Path(temp) / "out").exists()
