"""Compile the exported MCU arithmetic and compare it with the Python model."""

from copy import deepcopy
import ctypes
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from ai_training.multimodal.embedded import render_soil_header
from ai_training.multimodal.forecast import RidgeForecaster


AI_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = AI_ROOT / "pretrained/public_sensor_v1/soil_model.json"
FLOAT_PTR = ctypes.POINTER(ctypes.c_float)


@pytest.fixture(scope="module", params=[("cc", "c99", ".c"), ("c++", "c++17", ".cpp")])
def compiled(request, tmp_path_factory):
    compiler, standard, suffix = request.param
    executable = shutil.which(compiler)
    if executable is None:
        pytest.skip(f"{compiler} required for native C export parity tests")
    model = RidgeForecaster.load(MODEL_PATH)
    root = tmp_path_factory.mktemp("soil_native")
    (root / "soil_baseline.h").write_text(render_soil_header(model))
    source = root / ("wrapper" + suffix)
    source.write_text('''#include "soil_baseline.h"
#ifdef __cplusplus
extern "C" {
#endif
int predict(const float *h, size_t n, float *p) { return soil_model_predict_vwc(h, n, p); }
void reset(soil_model_state *s) { soil_model_reset(s); }
int push(soil_model_state *s, float v, int valid, float *p) {
    return soil_model_push_vwc(s, v, valid, p);
}
#ifdef __cplusplus
}
#endif
''')
    library_path = root / "soil.so"
    subprocess.run([executable, f"-std={standard}", "-O2", "-Wall", "-Wextra", "-Werror",
                    "-pedantic", "-shared", "-fPIC", str(source), "-lm", "-o", str(library_path)],
                   check=True, capture_output=True, text=True)
    library = ctypes.CDLL(str(library_path))

    class State(ctypes.Structure):
        _fields_ = [("history", ctypes.c_float * model.history_length), ("count", ctypes.c_uint)]

    library.predict.argtypes = [FLOAT_PTR, ctypes.c_size_t, FLOAT_PTR]
    library.predict.restype = ctypes.c_int
    library.reset.argtypes = [ctypes.POINTER(State)]
    library.reset.restype = None
    library.push.argtypes = [ctypes.POINTER(State), ctypes.c_float, ctypes.c_int, FLOAT_PTR]
    library.push.restype = ctypes.c_int
    return model, library, State


def reference(model, history):
    return model.predict(np.asarray(history, dtype=np.float64)[:, :, None],
                         channel_names=model.channel_names, units=model.units,
                         time_unit=model.time_unit)[:, 0]


def test_c_and_cpp_match_python_for_float32_inputs(compiled):
    model, library, _ = compiled
    # Deterministic TEST_ONLY boundary and randomized software vectors.
    histories = np.random.default_rng(19).uniform(0, 1, (1024, 4)).astype(np.float32)
    histories = np.vstack([histories, np.zeros(4, dtype=np.float32), np.ones(4, dtype=np.float32)])
    expected = reference(model, histories)
    for history, target in zip(histories, expected):
        output = ctypes.c_float(-999)
        status = library.predict(history.ctypes.data_as(FLOAT_PTR), 4, ctypes.byref(output))
        if 0 <= target <= 1:
            assert status == 0
            assert abs(output.value - target) < 5e-7
        else:
            assert status == -2
            assert output.value == -999  # reject extrapolation; do not clip silently


@pytest.mark.parametrize("value,status", [(float("nan"), -1), (float("inf"), -1),
                                         (-0.1, -2), (32.0, -2)])
def test_nonfinite_and_wrong_unit_scale_are_rejected(compiled, value, status):
    _, library, _ = compiled
    history = (ctypes.c_float * 4)(.2, value, .2, .2)
    output = ctypes.c_float(-999)
    assert library.predict(history, 4, ctypes.byref(output)) == status
    assert output.value == -999


def test_invalid_pointer_or_window_length_rejected(compiled):
    _, library, _ = compiled
    history = (ctypes.c_float * 4)(.2, .2, .2, .2)
    output = ctypes.c_float(-999)
    assert library.predict(None, 4, ctypes.byref(output)) == -1
    assert library.predict(history, 3, ctypes.byref(output)) == -1
    assert library.predict(history, 4, None) == -1
    assert output.value == -999


def test_stream_warmup_reset_and_sensor_isolation(compiled):
    model, library, State = compiled
    top, toe = State(), State()
    library.reset(ctypes.byref(top))
    library.reset(ctypes.byref(toe))
    output = ctypes.c_float(-999)
    values = np.asarray([.20, .21, .23, .25, .26], dtype=np.float32)
    for index, value in enumerate(values):
        status = library.push(ctypes.byref(top), value, 1, ctypes.byref(output))
        if index < 3:
            assert status == 1 and output.value == -999
        else:
            assert status == 0
            assert abs(output.value - reference(model, values[index-3:index+1][None])[0]) < 5e-7
    assert toe.count == 0
    assert library.push(ctypes.byref(top), .3, 0, ctypes.byref(output)) == -1
    assert top.count == 0
    assert library.push(ctypes.byref(top), .3, 1, ctypes.byref(output)) == 1
    assert library.push(ctypes.byref(top), 32, 1, ctypes.byref(output)) == -2
    assert top.count == 0


@pytest.mark.parametrize("field,value", [("modality", "motion"), ("units", ("ADC_raw",)),
                                        ("channel_names", ("soil_pct",)), ("time_unit", "seconds")])
def test_export_does_not_silently_rename_sensor_units(field, value):
    model = deepcopy(RidgeForecaster.load(MODEL_PATH))
    setattr(model, field, value)
    with pytest.raises(ValueError, match="single VWC"):
        render_soil_header(model)


def test_checked_in_header_matches_current_model():
    model = RidgeForecaster.load(MODEL_PATH)
    assert (AI_ROOT / "embedded/soil_baseline/include/soil_baseline.h").read_text() == render_soil_header(model)


def test_board_self_test_arithmetic_runs_on_host(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler required")
    embedded = AI_ROOT / "embedded/soil_baseline"
    # Verify the board example's actual app_main body without pretending to run ESP-IDF.
    entry = tmp_path / "host_entry.c"
    entry.write_text("void app_main(void); int main(void) { app_main(); return 0; }\n")
    executable = tmp_path / "board_arithmetic_on_host"
    subprocess.run([compiler, "-std=c99", "-O2", "-Wall", "-Wextra", "-Werror", "-pedantic",
                    "-I", str(embedded / "include"),
                    str(embedded / "examples/esp_idf/main/app_main.c"), str(entry), "-lm",
                    "-o", str(executable)], check=True, capture_output=True, text=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    assert "SOIL_BASELINE_SELF_TEST PASS" in result.stdout
