"""Audit and run the existing TinyQuake CNN; no training/conversion/pickle loading.

Usage: python desktop_baseline.py --repo ../TinyQuake --output results
The four pure NumPy preprocessing functions are extracted from the pinned source
AST, preserving its max (not maxabs) normalization and int16 intermediate.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
import csv
from datetime import datetime
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
import numpy as np
import tensorflow as tf
from tensorflow.lite.python import schema_py_generated as schema
from sklearn.metrics import classification_report, confusion_matrix

COMMIT = "fce74a7027129e721dafe56a5521d1d57b9835f9"
MODEL = "CNN/models/model_17_16_32_32.tflite"
MODEL_SHA256 = "0e1eb00a920ae3daaec7cf142ef8a54373fe1b93b472350e7048b8ae0c1ff1f1"
DATA_SHA256 = "34abb38e09818421a07e4fed307d77386d54b082453d631b13e1212f27976ebd"
CLASSES = ["P-wave", "S-wave", "Noise"]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def serial(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, type):
        return np.dtype(value).name
    raise TypeError(type(value).__name__)


def preprocess(repo, x, y):
    tree = ast.parse((repo / "src/dataprep.py").read_text())
    names = {"remove_small_amplitude", "remove_large_amplitude", "normalize", "quantize"}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert {node.name for node in functions} == names
    context = {"np": np}
    exec(compile(ast.Module(body=functions, type_ignores=[]), "upstream_numpy_preprocessing", "exec"), context)
    # Track original NPZ indexes with the same two selection functions.
    original_indexes = np.arange(len(x))
    x, original_indexes = context["remove_small_amplitude"](x.copy(), original_indexes)
    after_small = len(x)
    x, original_indexes = context["remove_large_amplitude"](x, original_indexes)
    x = context["normalize"](x)
    x = context["quantize"](x)
    x = context["normalize"](x.astype(np.float32))
    assert np.isfinite(x).all()
    return np.ascontiguousarray(x), y[original_indexes], original_indexes, after_small


def inspect_model(path):
    model = schema.Model.GetRootAsModel(path.read_bytes(), 0)
    graph = model.Subgraphs(0)
    enums = {v: k for k, v in vars(schema.BuiltinOperator).items() if isinstance(v, int)}
    tensor_types = {v: k for k, v in vars(schema.TensorType).items() if isinstance(v, int)}
    tensors, constant_buffers = [], {}
    for idx in range(graph.TensorsLength()):
        t = graph.Tensors(idx)
        shape = [t.Shape(k) for k in range(t.ShapeLength())]
        q = t.Quantization()
        size = model.Buffers(t.Buffer()).DataLength()
        if size:
            constant_buffers[t.Buffer()] = size
        tensors.append({"index": idx, "name": t.Name().decode(), "shape": shape,
                        "type": tensor_types[t.Type()], "constant_buffer_bytes": size,
                        "scale": q.ScaleAsNumpy().tolist() if q and q.ScaleLength() else [],
                        "zero_point": q.ZeroPointAsNumpy().tolist() if q and q.ZeroPointLength() else []})
    ops = []
    macs = 0
    for idx in range(graph.OperatorsLength()):
        operator = graph.Operators(idx)
        code = model.OperatorCodes(operator.OpcodeIndex())
        name = enums[code.BuiltinCode()]
        inputs = operator.InputsAsNumpy().tolist()
        outputs = operator.OutputsAsNumpy().tolist()
        item = {"index": idx, "name": name, "version": code.Version(), "inputs": inputs,
                "outputs": outputs, "output_shapes": [tensors[k]["shape"] for k in outputs]}
        table = operator.BuiltinOptions()
        if name == "CONV_2D":
            options = schema.Conv2DOptions()
            options.Init(table.Bytes, table.Pos)
            item["options"] = {"padding": options.Padding(), "stride_h": options.StrideH(),
                               "stride_w": options.StrideW(), "dilation_h": options.DilationHFactor(),
                               "dilation_w": options.DilationWFactor(), "fused_activation": options.FusedActivationFunction()}
            weights = tensors[inputs[1]]["shape"]
            item["macs"] = int(np.prod(tensors[outputs[0]]["shape"]) * np.prod(weights[1:]))
            macs += item["macs"]
        elif name == "MAX_POOL_2D":
            options = schema.Pool2DOptions()
            options.Init(table.Bytes, table.Pos)
            item["options"] = {"padding": options.Padding(), "stride_h": options.StrideH(),
                               "stride_w": options.StrideW(), "filter_h": options.FilterHeight(),
                               "filter_w": options.FilterWidth(), "fused_activation": options.FusedActivationFunction()}
        elif name == "FULLY_CONNECTED":
            options = schema.FullyConnectedOptions()
            options.Init(table.Bytes, table.Pos)
            item["options"] = {"fused_activation": options.FusedActivationFunction(),
                               "weights_format": options.WeightsFormat(), "keep_num_dims": options.KeepNumDims()}
            item["macs"] = int(np.prod(tensors[inputs[1]]["shape"]))
            macs += item["macs"]
        elif name == "SOFTMAX":
            options = schema.SoftmaxOptions()
            options.Init(table.Bytes, table.Pos)
            item["options"] = {"beta": options.Beta()}
        ops.append(item)
    float_constants = sum(int(np.prod(t["shape"])) for t in tensors if t["constant_buffer_bytes"] and t["type"] == "FLOAT32")
    dynamic_bytes = [int(np.prod(t["shape"])) * 4 for t in tensors if not t["constant_buffer_bytes"] and t["type"] == "FLOAT32"]
    return {"schema_version": model.Version(), "description": model.Description().decode(),
            "operators": ops, "operator_counts": dict(Counter(item["name"] for item in ops)),
            "tensors": tensors, "constant_tensor_buffer_bytes": sum(constant_buffers.values()),
            "float_constant_elements_including_biases": float_constants,
            "logical_nonconstant_float_tensor_bytes_sum": sum(dynamic_bytes),
            "largest_logical_nonconstant_float_tensor_bytes": max(dynamic_bytes),
            "multiply_accumulate_count_conv_dense": macs,
            "memory_note": "Static tensor accounting only, NOT Tensor Arena usage or peak process/device RAM."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    repo, output = args.repo.resolve(), args.output.resolve()
    commit = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    if commit != COMMIT:
        raise SystemExit(f"Expected upstream commit {COMMIT}, found {commit}")
    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True):
        raise SystemExit("Upstream checkout must be clean")
    output.mkdir(parents=True, exist_ok=True)
    path, data_path = repo / MODEL, repo / "data/test.npz"
    if digest(path) != MODEL_SHA256 or digest(data_path) != DATA_SHA256:
        raise SystemExit("Model or reference data does not match the evaluated upstream artifact")
    with np.load(data_path, allow_pickle=False) as data:
        raw, labels = data["Xtest"], data["Ytest"]
    assert raw.ndim == 4 and raw.shape[1:] == (80, 3, 1)
    assert labels.shape == (len(raw), 3)
    assert np.isfinite(raw).all() and np.isfinite(labels).all()
    assert np.all((labels == 0) | (labels == 1)) and np.all(labels.sum(axis=1) == 1)
    x, y, indexes, after_small = preprocess(repo, raw, labels)
    truth = np.argmax(y, axis=1)
    report = {"execution_date_local": datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat(), "upstream_commit": commit,
              "model_path": MODEL, "model_sha256": digest(path), "model_file_bytes": path.stat().st_size,
              "test_npz_sha256": digest(data_path),
              "environment": {"python": sys.version, "platform": platform.platform(),
                              "machine": platform.machine(), "packages": {name: importlib.metadata.version(name) for name in ("tensorflow", "numpy", "scipy", "scikit-learn")}},
              "reference_data": {"origin": "Unmodified upstream data/test.npz; prepared STEAD-derived windows, not ICM measurements", "raw_shape": list(raw.shape), "raw_dtype": str(raw.dtype),
                                 "raw_class_counts": np.bincount(np.argmax(labels, axis=1), minlength=3),
                                 "raw_absolute_amplitude_range": [float(np.min(np.max(np.abs(raw), axis=(1, 2, 3)))), float(np.max(np.abs(raw)))],
                                 "after_small_amplitude_filter": after_small, "retained": len(x),
                                 "retained_class_counts": np.bincount(truth, minlength=3),
                                 "preprocessed_range": [float(x.min()), float(x.max())],
                                 "trace_identifiers_and_station_metadata": "NOT_INCLUDED_IN_UPSTREAM_NPZ"},
              "classes": CLASSES, "model": inspect_model(path)}
    before = time.perf_counter_ns()
    interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=1,
        experimental_op_resolver_type=tf.lite.experimental.OpResolverType.BUILTIN_WITHOUT_DEFAULT_DELEGATES)
    interpreter.allocate_tensors()
    report["desktop_allocate_ms"] = (time.perf_counter_ns() - before) / 1e6
    input_info, output_info = interpreter.get_input_details()[0], interpreter.get_output_details()[0]
    report["input"] = {key: value for key, value in input_info.items() if key != "sparsity_parameters"}
    report["output"] = {key: value for key, value in output_info.items() if key != "sparsity_parameters"}
    assert input_info["shape"].tolist() == [1, 80, 3, 1] and input_info["dtype"] == np.float32
    assert output_info["shape"].tolist() == [1, 3] and output_info["dtype"] == np.float32
    for _ in range(50):
        interpreter.set_tensor(input_info["index"], x[0:1])
        interpreter.invoke()
    preds, invoke_ms, full_ms = np.empty((len(x), 3)), [], []
    for n in range(len(x)):
        start = time.perf_counter_ns()
        interpreter.set_tensor(input_info["index"], x[n:n + 1])
        invoke_start = time.perf_counter_ns()
        interpreter.invoke()
        invoke_end = time.perf_counter_ns()
        preds[n] = interpreter.get_tensor(output_info["index"])[0]
        full_ms.append((time.perf_counter_ns() - start) / 1e6)
        invoke_ms.append((invoke_end - invoke_start) / 1e6)
    assert np.isfinite(preds).all() and np.allclose(preds.sum(axis=1), 1, atol=1e-5)
    predictions = np.argmax(preds, axis=1)
    report["argmax"] = {"confusion_matrix_rows_truth_columns_prediction": confusion_matrix(truth, predictions, labels=[0, 1, 2]),
                        "classification_report": classification_report(truth, predictions, labels=[0, 1, 2], target_names=CLASSES, output_dict=True, zero_division=0)}
    # Fixed descriptive operating point, never optimized on these test labels.
    thresholded = preds.copy()
    thresholded[:, :2][thresholded[:, :2] < .8] = 0
    report["fixed_threshold_0_8_not_calibrated"] = {
        "rule": "Only P/S scores below 0.8 are zeroed; argmax retains original Noise score, matching upstream decision_threshold.",
        "confusion_matrix": confusion_matrix(truth, np.argmax(thresholded, axis=1), labels=[0, 1, 2]),
        "classification_report": classification_report(truth, np.argmax(thresholded, axis=1), labels=[0, 1, 2], target_names=CLASSES, output_dict=True, zero_division=0)}
    report["desktop_latency"] = {"num_threads": 1, "runtime": "TensorFlow Lite builtin kernels, default delegates disabled", "warmup_invocations": 50, "measured_windows": len(x), "note": "Host timing only; not ESP32 latency or TFLM timing."}
    for name, values in (("invoke_ms", invoke_ms), ("set_invoke_get_ms", full_ms)):
        report["desktop_latency"][name] = {"mean": float(np.mean(values)), "p50": float(np.median(values)), "p95": float(np.percentile(values, 95)), "max": float(np.max(values))}
    first = [int(np.flatnonzero(truth == k)[0]) for k in range(3)]
    report["first_reference_window_per_class"] = [{"npz_index": int(indexes[n]), "truth": CLASSES[truth[n]], "prediction": CLASSES[predictions[n]], "probabilities": preds[n].tolist()} for n in first]
    np.savez(output / "golden_vectors.npz", inputs=x[first], outputs=preds[first].astype(np.float32), npz_indexes=indexes[first], truth=truth[first])
    with (output / "predictions.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["npz_index", "truth_index", "argmax_index", "P_wave", "S_wave", "Noise"])
        for idx, label, prediction, probability in zip(indexes, truth, predictions, preds):
            writer.writerow([int(idx), int(label), int(prediction), *[float(p) for p in probability]])
    (output / "baseline_results.json").write_text(json.dumps(report, default=serial, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"model_sha256": report["model_sha256"], "raw_windows": len(raw), "tested_windows": len(x), "class_counts": np.bincount(truth).tolist(), "argmax_accuracy": report["argmax"]["classification_report"]["accuracy"], "confusion": report["argmax"]["confusion_matrix_rows_truth_columns_prediction"].tolist(), "latency": report["desktop_latency"]}, indent=2))


if __name__ == "__main__":
    main()
