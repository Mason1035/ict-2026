"""Readers preserve actual source semantics and reject unsafe/malformed inputs."""

import csv
from dataclasses import FrozenInstanceError
import struct
import zlib

import numpy as np
import pytest

from ai_training.multimodal.data import SensorSeries
from ai_training.multimodal.public_data import load_lisa, load_smartstone


def test_sensor_series_validates_native_observations_and_copies_arrays():
    values = np.array([[.1], [.2]])
    series = SensorSeries("source", "run", "group", "soil", values, np.array([1, 2]),
                          ("vwc",), ("1",), "source_relative_time", {})
    values[0, 0] = .9
    assert series.values[0, 0] == .1
    with pytest.raises(ValueError):
        series.values[0, 0] = .4
    with pytest.raises(FrozenInstanceError):
        series.modality = "motion"
    for times in ([1, 1], [2, 1], [1, np.nan]):
        with pytest.raises(ValueError):
            SensorSeries("s", "r", "g", "soil", values, np.asarray(times), ("vwc",), ("1",), "unknown", {})
    with pytest.raises(ValueError):
        SensorSeries("s", "r", "g", "soil", values, np.array([1, 2]), ("vwc",), (), "unknown", {})


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream, delimiter=";").writerows(rows)


def test_lisa_preserves_vwc_and_groups_dates_and_documented_continuations(tmp_path):
    experiments = [
        [str(key), date + " 00:00:00", "1", "1", "Rainfall 50 mm/h", "16:00", "17:00", "", "No failure"]
        for key, date in ((1, "1/6/2021"), (2, "1/6/2021"), (18, "9/6/2021"), (22, "10/6/2021"))
    ]
    _write_csv(tmp_path / "Experiments.csv", experiments)
    for filename in ("centre_slope", "upslope", "downslope"):
        _write_csv(tmp_path / f"TDR_{filename}_measurements.csv", [
            ["1", "1", "2", "0,2"], ["2", "1", "0", "0,1"],
            ["3", "1", "10\n10", "0,9"], ["4", "1", "2", "0,8"],
            ["5", "1", "4", "nan"], ["6", "2", "0", "0,3"],
            ["7", "18", "0", "0,2"], ["8", "22", "0", "0,25"],
        ])
    series = load_lisa(tmp_path)
    assert len(series) == 12
    runs = {}
    for item in series:
        runs.setdefault(item.run_id, set()).add(item.group_id)
        assert item.modality == "soil" and item.units == ("1",)
        assert item.time_unit == "source_relative_time"
        assert item.provenance["target"] == "next_observation"
        assert not hasattr(item, "labels")
        assert "soil_top_raw" not in item.channel_names
    assert runs["LISA:1"] == runs["LISA:2"]
    assert runs["LISA:18"] == runs["LISA:22"]
    first = next(item for item in series if item.run_id == "LISA:1")
    np.testing.assert_array_equal(first.times, [0, 2])
    np.testing.assert_array_equal(first.values[:, 0], [.1, .2])
    assert first.provenance["exclusions"] == {
        "invalid_time": 1, "invalid_value": 1, "invalid_value_range": 0, "duplicate_time": 1,
    }
    assert first.provenance["event_metadata"]["first_visible_fracture_raw"] == "No failure"


def test_lisa_quarantines_whole_sensor_sequence_with_ambiguous_fraction_units(tmp_path):
    _write_csv(tmp_path / "Experiments.csv", [
        [str(key), "1/6/2021 00:00:00", "1", "1", "rain", "16:00", "17:00", "", "unknown"]
        for key in (1, 2, 3)
    ])
    _write_csv(tmp_path / "TDR_centre_slope_measurements.csv", [
        ["1", "1", "0", "0"], ["2", "1", "1", "1"],
        ["3", "2", "0", "0,2"], ["4", "2", "1", "10,30"],
        ["5", "3", "0", "-0,01"],
    ])
    series = load_lisa(tmp_path)
    assert len(series) == 1 and series[0].run_id == "LISA:1"
    np.testing.assert_array_equal(series[0].values[:, 0], [0, 1])
    audit = series[0].provenance
    assert audit["table_exclusions"]["invalid_value_range"] == 2
    assert audit["table_exclusions"]["unit_ambiguity_records"] == 3
    assert [item["experiment_id"] for item in audit["quarantined_sequences"]] == ["2", "3"]
    assert audit["quarantined_sequences"][0]["out_of_range_records"][0]["source_value"] == 10.30


def _element(kind, payload):
    return struct.pack("<II", kind, len(payload)) + payload + b"\0" * (-len(payload) % 8)


def _matrix(name, array, *, array_class=6):
    array = np.asarray(array, dtype="<f8")
    payload = _element(6, struct.pack("<II", array_class, 0))
    payload += _element(5, struct.pack("<ii", *array.shape))
    # Exercise the v5 small-data-element tag used by the source's acc/gyr names.
    encoded = name.encode("ascii")
    payload += (struct.pack("<HH", 1, len(encoded)) + encoded.ljust(4, b"\0")
                if len(encoded) <= 4 else _element(1, encoded))
    payload += _element(9, array.tobytes(order="F"))
    return _element(14, payload)


def _mat_file(path, arrays, *, array_class=6):
    header = b"MATLAB 5.0 MAT-file test fixture".ljust(116, b" ") + b"\0" * 8 + b"\0\1IM"
    chunks = []
    for name, array in arrays.items():
        compressed = zlib.compress(_matrix(name, array, array_class=array_class))
        # miCOMPRESSED streams in these source files do not have trailing padding.
        chunks.append(struct.pack("<II", 15, len(compressed)) + compressed)
    path.write_bytes(header + b"".join(chunks))


def test_smartstone_numeric_mat_v5_preserves_six_axes_and_single_group(tmp_path):
    for stone in (1, 2):
        _mat_file(tmp_path / f"ProbeData_{stone}.mat", {
            "acc": np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9], [np.nan, 0, 0]]),
            "gyr": np.arange(12).reshape(4, 3), "time": np.array([[20], [10], [20], [30]]),
        })
    series = load_smartstone(tmp_path)
    assert len(series) == 2 and len({item.group_id for item in series}) == 1
    item = series[0]
    np.testing.assert_array_equal(item.times, [10, 20])
    np.testing.assert_array_equal(item.values[0], [4, 5, 6, 3, 4, 5])
    assert item.units == ("source_native_acc",) * 3 + ("source_native_gyr",) * 3
    assert item.time_unit == "source_native_timecode"
    assert not item.provenance["timecode_is_utc"]
    assert not item.provenance["cross_probe_sync_confirmed"]
    assert item.provenance["exclusions"] == {"invalid_time": 0, "invalid_value": 1, "duplicate_time": 1}
    assert not any("top" in name or "toe" in name for name in item.channel_names)
    assert not hasattr(item, "labels")


def test_smartstone_rejects_non_numeric_or_truncated_mat(tmp_path):
    path = tmp_path / "ProbeData_1.mat"
    _mat_file(path, {"acc": np.zeros((2, 3))}, array_class=2)  # mxSTRUCT_CLASS
    with pytest.raises(ValueError, match="numeric"):
        load_smartstone(tmp_path)
    path.write_bytes(path.read_bytes()[:-5])
    with pytest.raises(ValueError, match="truncated"):
        load_smartstone(tmp_path)
