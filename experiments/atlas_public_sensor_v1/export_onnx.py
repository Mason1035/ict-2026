"""Export raw history -> predicted delta, static batch 1, ONNX opset 13."""
from pathlib import Path
import argparse
import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper
from reference import HERE, MODEL_DIR, load_model


def export(path, destination):
    model = load_model(path)
    t, c = model.history_length, model.channels
    constants = []
    nodes = []

    def const(name, value, dtype):
        constants.append(numpy_helper.from_array(np.asarray(value, dtype=dtype), name))
        return name

    # Gather keeps the time axis for increments; scalar index removes it for level.
    const("last_index", t-1, np.int64)
    const("later_indices", list(range(1, t)), np.int64)
    const("earlier_indices", list(range(t-1)), np.int64)
    const("flat_shape", [1, (t-1)*c], np.int64)
    for name in ("mean", "scale", "coefficients", "delta_mean"):
        const(name, getattr(model, name), np.float32)
    nodes.extend([
        helper.make_node("Gather", ["history", "last_index"], ["level"], axis=1),
        helper.make_node("Gather", ["history", "later_indices"], ["later"], axis=1),
        helper.make_node("Gather", ["history", "earlier_indices"], ["earlier"], axis=1),
        helper.make_node("Sub", ["later", "earlier"], ["increments"]),
        helper.make_node("Reshape", ["increments", "flat_shape"], ["flat_increments"]),
        helper.make_node("Concat", ["level", "flat_increments"], ["features"], axis=1),
        helper.make_node("Sub", ["features", "mean"], ["centered"]),
        helper.make_node("Div", ["centered", "scale"], ["standardized"]),
        helper.make_node("MatMul", ["standardized", "coefficients"], ["linear_delta"]),
        helper.make_node("Add", ["linear_delta", "delta_mean"], ["predicted_delta"]),
    ])
    graph = helper.make_graph(nodes, f"{model.modality}_research_delta_forecaster",
                              [helper.make_tensor_value_info("history", TensorProto.FLOAT, [1, t, c])],
                              [helper.make_tensor_value_info("predicted_delta", TensorProto.FLOAT, [1, c])],
                              initializer=constants)
    output = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 13)],
                               producer_name="atlas_public_sensor_v1", ir_version=7)
    output.doc_string = "PUBLIC_DATA_RESEARCH; predicted next-recorded-observation delta; deployment_ready=false"
    onnx.checker.check_model(output, full_check=True)
    onnx.save_model(output, destination)
    print(f"PASS checker: {destination} input=(1,{t},{c}) output=(1,{c})")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    args = parser.parse_args()
    for branch in ("soil", "motion"):
        export(args.model_dir / f"{branch}_model.json", HERE / f"{branch}_forecaster.onnx")


if __name__ == "__main__":
    main()
