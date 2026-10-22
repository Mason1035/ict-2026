"""Board-only synchronous pyACL runner for one static float32 history window.

API pattern: Ascend/ACLLite python/acllite_model.py and CANN Python model
execution samples. No ONNX, training package, or model JSON needed on board.
"""
import argparse
from pathlib import Path
import sys
import time

import numpy as np


def checked(ret, operation):
    if ret != 0:
        raise RuntimeError(f"{operation} failed: ACL error {ret}")


class Runner:
    def __init__(self, acl, device):
        self.acl, self.device = acl, device
        self.initialized = self.device_set = False
        self.context = self.model_id = self.desc = self.host_output = None
        self.datasets, self.buffers, self.allocations = [], [], []

    def open(self, path, input_shape, output_shape):
        acl = self.acl
        checked(acl.init(), "acl.init")
        self.initialized = True
        checked(acl.rt.set_device(self.device), "set_device")
        self.device_set = True
        self.context, ret = acl.rt.create_context(self.device)
        checked(ret, "create_context")
        mode, ret = acl.rt.get_run_mode()
        checked(ret, "get_run_mode")
        # get_run_mode: ACL_HOST=0, ACL_DEVICE=1. The Atlas 200I DK A2 runs
        # apps on the device-side CPU and reports ACL_DEVICE (1). The H2D/D2H
        # memcpy pattern below is valid in both modes.
        if mode not in (0, 1):
            raise RuntimeError(f"unexpected ACL run mode {mode}")
        self.run_mode = mode
        self.model_id, ret = acl.mdl.load_from_file(str(path))
        checked(ret, "load_from_file")
        self.desc = acl.mdl.create_desc()
        if self.desc is None:
            raise RuntimeError("create_desc returned None")
        checked(acl.mdl.get_desc(self.desc, self.model_id), "get_desc")
        if acl.mdl.get_num_inputs(self.desc) != 1 or acl.mdl.get_num_outputs(self.desc) != 1:
            raise ValueError("OM must have exactly one input and one output")
        for direction, shape in (("input", input_shape), ("output", output_shape)):
            # ACL_FLOAT=0. Dimensions and byte count must match the static graph.
            if getattr(acl.mdl, f"get_{direction}_data_type")(self.desc, 0) != 0:
                raise ValueError(f"OM {direction} is not float32")
            dims, ret = getattr(acl.mdl, f"get_{direction}_dims")(self.desc, 0)
            checked(ret, f"get_{direction}_dims")
            if tuple(dims["dims"]) != tuple(shape):
                raise ValueError(f"OM {direction} dims {dims['dims']} != {shape}")
            size = getattr(acl.mdl, f"get_{direction}_size_by_index")(self.desc, 0)
            if size != int(np.prod(shape)) * 4:
                raise ValueError(f"unexpected OM {direction} byte count {size}")
            dataset = acl.mdl.create_dataset()
            if dataset is None:
                raise RuntimeError("create_dataset returned None")
            self.datasets.append(dataset)
            ptr, ret = acl.rt.malloc(size, 2)  # ACL_MEM_MALLOC_NORMAL_ONLY
            checked(ret, "malloc")
            self.allocations.append((ptr, size))
            buffer = acl.create_data_buffer(ptr, size)
            if buffer is None:
                raise RuntimeError("create_data_buffer returned None")
            self.buffers.append(buffer)
            _, ret = acl.mdl.add_dataset_buffer(dataset, buffer)
            checked(ret, "add_dataset_buffer")
        self.host_output, ret = acl.rt.malloc_host(self.allocations[1][1])
        checked(ret, "malloc_host")

    def infer(self, window):
        acl = self.acl
        array = np.ascontiguousarray(window, dtype=np.float32)
        payload = array.tobytes(order="C")  # Keep bytes alive throughout synchronous copy.
        ptr = acl.util.bytes_to_ptr(payload)
        device_input, input_bytes = self.allocations[0]
        if len(payload) != input_bytes:
            raise ValueError("input byte count differs from OM")
        checked(acl.rt.memcpy(device_input, input_bytes, ptr, input_bytes, 1), "memcpy H2D")
        start = time.perf_counter_ns()
        checked(acl.mdl.execute(self.model_id, self.datasets[0], self.datasets[1]), "execute")
        latency_ms = (time.perf_counter_ns() - start) / 1e6
        device_output, output_bytes = self.allocations[1]
        checked(acl.rt.memcpy(self.host_output, output_bytes, device_output, output_bytes, 2),
                "memcpy D2H")
        raw = acl.util.ptr_to_bytes(self.host_output, output_bytes)
        return np.frombuffer(raw, dtype=np.float32).copy(), latency_ms

    def close(self):
        # Best-effort cleanup of every acquired resource, including partial setup.
        acl = self.acl
        errors = []

        def release(operation, function, *args):
            try:
                checked(function(*args), operation)
            except Exception as exc:
                errors.append(str(exc))

        for buffer in reversed(self.buffers):
            release("destroy_data_buffer", acl.destroy_data_buffer, buffer)
        for dataset in reversed(self.datasets):
            release("destroy_dataset", acl.mdl.destroy_dataset, dataset)
        for ptr, _ in reversed(self.allocations):
            release("free", acl.rt.free, ptr)
        if self.host_output is not None:
            release("free_host", acl.rt.free_host, self.host_output)
        if self.model_id is not None:
            release("unload", acl.mdl.unload, self.model_id)
        if self.desc is not None:
            release("destroy_desc", acl.mdl.destroy_desc, self.desc)
        if self.context is not None:
            release("destroy_context", acl.rt.destroy_context, self.context)
        if self.device_set:
            release("reset_device", acl.rt.reset_device, self.device)
        if self.initialized:
            release("finalize", acl.finalize)
        if errors:
            raise RuntimeError("ACL cleanup failed: " + "; ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--golden", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--atol", type=float, default=1e-5)
    args = parser.parse_args()
    if not np.isfinite(args.atol) or args.atol < 0:
        parser.error("--atol must be finite and nonnegative")
    if args.output.resolve() in (args.model.resolve(), args.golden.resolve()):
        parser.error("output must differ from model and golden paths")
    with np.load(args.golden, allow_pickle=False) as data:
        inputs = np.ascontiguousarray(data["inputs"], dtype=np.float32)
        expected = np.asarray(data["expected_delta"], dtype=np.float32)
    if (inputs.ndim != 3 or len(inputs) == 0 or inputs.shape[1:] not in ((4, 1), (8, 6))
            or expected.shape != (len(inputs), inputs.shape[2])
            or not np.isfinite(inputs).all() or not np.isfinite(expected).all()):
        raise ValueError("invalid golden shapes or non-finite values")
    import acl  # Available only with the matching board Python ABI and Ascend environment.
    runner = Runner(acl, args.device)
    outputs, latency = [], []
    try:
        runner.open(args.model, (1, *inputs.shape[1:]), (1, inputs.shape[2]))
        for window in inputs:
            result, elapsed = runner.infer(window[None])
            outputs.append(result)
            latency.append(elapsed)
    finally:
        # Preserve an inference/setup exception while still reporting cleanup errors.
        active_error = sys.exc_info()[0] is not None
        try:
            runner.close()
        except Exception as exc:
            if not active_error:
                raise
            print(str(exc), file=sys.stderr)
    outputs = np.asarray(outputs, dtype=np.float32)
    diff = float(np.max(np.abs(outputs.astype(np.float64) - expected.astype(np.float64))))
    passed = bool(np.isfinite(outputs).all() and diff <= args.atol)
    np.savez(args.output, outputs=outputs, expected_delta=expected,
             latency_ms=np.asarray(latency), max_abs_diff=diff, passed=passed)
    print(f"{'PASS' if passed else 'FAIL'} predicted_delta: max_abs_diff={diff:.12g} "
          f"atol={args.atol:g}; mean execute latency={np.mean(latency):.6f} ms; N={len(inputs)}")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
