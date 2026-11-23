"""Isolated, serial ACL research inference. Predictions never enter risk fusion."""
from __future__ import annotations

import base64
from collections import OrderedDict, deque
from concurrent.futures import Future, TimeoutError
from datetime import datetime, timezone
import importlib
import json
from queue import Queue, Empty, Full
from threading import Event, RLock, Thread, Timer
import time
from uuid import uuid4

import numpy as np

from .database import Database, utc_now
from .settings import Settings

REASON = "Uncalibrated research model; not eligible for risk fusion. Soil percent approximates VWC; motion units may differ from training."
SHAPES = {"soil": (4, 1), "motion": (8, 6)}


class InferenceError(Exception):
    def __init__(self, status_code, detail):
        self.status_code, self.detail = status_code, detail
        super().__init__(detail)


def checked(ret, operation):
    if ret != 0:
        raise RuntimeError(f"{operation} failed: ACL error {ret}")


class _ACLModel:
    def __init__(self, acl):
        self.acl = acl
        self.model_id = self.desc = self.host_output = None
        self.datasets, self.buffers, self.allocations = [], [], []

    def open(self, path, input_shape, output_shape):
        acl = self.acl
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
        if errors:
            raise RuntimeError("ACL cleanup failed: " + "; ".join(errors))



class InferenceService:
    def __init__(self, db: Database, settings: Settings):
        self.db, self.settings = db, settings
        self._lock = RLock()
        self._queue = Queue(maxsize=64)
        self._stop = Event()
        self._thread = None
        self._job_timeout = 10.0
        self._buffers = OrderedDict()
        self._models = {}
        self._acl = self._context = None
        self._initialized = self._device_set = False
        self._unavailable = settings.acl_mode not in ("auto", "on")
        self._state = "not_connected"
        self._reason = "disabled" if settings.acl_mode == "off" else "invalid_acl_mode" if self._unavailable else "awaiting_first_window"
        self._successes = self._failures = self._dropped = self._consecutive = 0
        self._latency = self._last_at = None

    def status(self):
        with self._lock:
            return {"state": self._state, "reason": self._reason,
                    "loaded": {name: name in self._models for name in SHAPES},
                    "success_count": self._successes, "failure_count": self._failures,
                    "dropped_count": self._dropped, "queue_depth": self._queue.qsize(),
                    "last_latency_ms": self._latency, "last_inference_at": self._last_at}

    def _submit(self, job):
        with self._lock:
            if self._stop.is_set() or self._unavailable or self._state == "degraded":
                self._dropped += 1
                return False
            try:
                self._queue.put_nowait(job)
            except Full:
                self._dropped += 1
                return False
            if self._thread is None:
                self._thread = Thread(target=self._work, name="atlas-acl", daemon=True)
                try:
                    self._thread.start()
                except Exception as exc:
                    self._thread = None
                    self._unavailable = True
                    self._failures += 1
                    self._dropped += 1
                    self._reason = f"worker_start_failed: {exc}"
                    self._queue.get_nowait()
                    self._queue.task_done()
                    return False
            return True

    def observe(self, payload_dict):
        # Intake must remain durable even if adaptation or scheduling fails.
        try:
            with self._lock:
                if self._unavailable or self._stop.is_set() or self._state == "degraded":
                    return
                p = payload_dict
                key = (p["site_id"], p["device_id"])
                provenance = (p["source"], p["scope"], p.get("boot_id"))
                if key not in self._buffers or self._buffers[key][0] != provenance:
                    self._buffers[key] = (provenance, {name: deque(maxlen=shape[0]) for name, shape in SHAPES.items()})
                self._buffers.move_to_end(key)
                # Bound idle device history as well as the work queue.
                if len(self._buffers) > 1024:
                    self._buffers.popitem(last=False)
                buffers = self._buffers[key][1]
                stamp = (datetime.fromtimestamp(p["timestamp_ms"] / 1000, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
                         if p.get("time_synced") and p.get("timestamp_ms") is not None else utc_now())
                soil = p.get("soil", {}).get("avg_pct")
                samples = {"soil": [] if soil is None else [[soil / 100.0]],
                           "motion": [[sample.get(field) for field in ("ax", "ay", "az", "gx", "gy", "gz")]
                                      for sample in p.get("imu", []) if sample.get("valid") is True]}
                for name, values in samples.items():
                    for value in values:
                        if any(v is None for v in value) or not np.isfinite(value).all():
                            continue
                        buffers[name].append((stamp, value))
                        if len(buffers[name]) == SHAPES[name][0]:
                            window = np.asarray([v for _, v in buffers[name]], dtype=np.float32)[None]
                            self._submit(("infer", (name, window, {"site_id": key[0], "device_id": key[1],
                                "source": p["source"], "scope": p["scope"], "window_start_at": buffers[name][0][0],
                                "window_end_at": stamp}), None))
        except Exception:
            with self._lock:
                self._dropped += 1

    def _open(self):
        if self._models:
            return
        try:
            self._acl = importlib.import_module("acl")
        except Exception as exc:
            raise RuntimeError(f"acl_import_failed: {exc}") from exc
        for name in SHAPES:
            if not (self.settings.acl_model_dir / f"{name}_forecaster.om").is_file():
                raise RuntimeError(f"model_missing: {name}")
        acl = self._acl
        checked(acl.init(), "acl_init_failed")
        self._initialized = True
        checked(acl.rt.set_device(0), "set_device")
        self._device_set = True
        self._context, ret = acl.rt.create_context(0)
        checked(ret, "create_context")
        for name, shape in SHAPES.items():
            model = _ACLModel(acl)
            # Track partial allocations for cleanup too.
            self._pending_model = model
            model.open(self.settings.acl_model_dir / f"{name}_forecaster.om", (1, *shape), (1, shape[1]))
            with self._lock:
                self._models[name] = model
            self._pending_model = None

    def _timeout(self):
        with self._lock:
            if self._stop.is_set() or self._state == "degraded":
                return
            self._state, self._reason = "degraded", "acl_timeout: restart required"
            self._failures += 1

    def _infer(self, name, window):
        output, latency = self._models[name].infer(window)
        if output.shape != (SHAPES[name][1],) or not np.isfinite(output).all():
            raise RuntimeError("invalid_prediction_shape_or_values")
        if not np.isfinite(latency) or latency < 0:
            raise RuntimeError("invalid_inference_latency")
        return output, latency

    def _work(self):
        try:
            while not self._stop.is_set():
                try:
                    kind, data, future = self._queue.get(timeout=0.1)
                except Empty:
                    continue
                timer = None
                try:
                    with self._lock:
                        blocked = self._unavailable or self._state == "degraded"
                    if blocked:
                        with self._lock:
                            self._dropped += 1
                        if future:
                            future.set_result({"available": False, **self.status()})
                        continue
                    try:
                        self._open()
                    except Exception as exc:
                        with self._lock:
                            self._unavailable = True
                            self._reason = str(exc)
                        raise
                    timer = Timer(self._job_timeout, self._timeout)
                    timer.daemon = True
                    timer.start()
                    if kind == "check":
                        result = self._check()
                    else:
                        name, window, metadata = data
                        output, latency = self._infer(name, window)
                        if self.status()["state"] == "degraded" or self._stop.is_set():
                            continue
                        result = {"id": str(uuid4()), **metadata, "model": name,
                                  "predicted_delta": output.tolist(), "latency_ms": latency, "created_at": utc_now(),
                                  "fusion_eligible": False, "calibration": "uncalibrated_research", "reason": REASON}
                        with self.db.connection() as c:
                            c.execute("""INSERT INTO inference_results
                                (id,site_id,device_id,source,scope,model,window_start_at,window_end_at,predicted_delta,
                                 latency_ms,created_at,fusion_eligible,calibration,reason) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                                tuple(json.dumps(result[k], allow_nan=False) if k == "predicted_delta" else result[k] for k in ("id", "site_id", "device_id", "source", "scope", "model", "window_start_at", "window_end_at", "predicted_delta", "latency_ms", "created_at", "fusion_eligible", "calibration", "reason")))
                        with self._lock:
                            self._latency, self._last_at = latency, result["created_at"]
                    with self._lock:
                        if self._state != "degraded":
                            self._successes += 2 if kind == "check" else 1
                            self._consecutive = 0
                            self._state, self._reason = "connected", "real_npu_inference_succeeded"
                    if future:
                        future.set_result(result)
                except Exception as exc:
                    with self._lock:
                        self._failures += 1
                        self._consecutive += 1
                        self._reason = str(exc)
                        if self._consecutive >= 3 or (kind == "check" and not self._unavailable):
                            self._state = "degraded"
                    if future:
                        future.set_result({"available": False, **self.status()})
                finally:
                    if timer:
                        timer.cancel()
                    self._queue.task_done()
        finally:
            self._cleanup()

    def _check(self):
        results = {}
        for name in SHAPES:
            with np.load(self.settings.acl_model_dir / "golden" / f"{name}_golden.npz", allow_pickle=False) as golden:
                window = np.asarray(golden["inputs"][:1], dtype=np.float32)
                expected = np.asarray(golden["expected_delta"][0], dtype=np.float64)
            output, latency = self._infer(name, window)
            delta = output.astype(np.float64) - expected
            absolute = float(np.max(np.abs(delta)))
            relative = absolute / max(float(np.max(np.abs(expected))), 1e-12)
            correlation = None
            if name == "motion" and np.std(output) > 0 and np.std(expected) > 0:
                correlation = float(np.corrcoef(output, expected)[0, 1])
            passed = (absolute <= 5e-5 if name == "soil" else
                      relative <= 1e-3 and correlation is not None and correlation >= 0.99999)
            results[name] = {"max_abs_diff": absolute, "scale_relative_error": relative,
                             "correlation": correlation, "latency_ms": latency, "passed": bool(passed)}
            with self._lock:
                self._latency, self._last_at = latency, utc_now()
        if not all(item["passed"] for item in results.values()):
            with self._lock:
                self._state, self._reason = "degraded", "golden_self_check_failed"
                self._failures += 1
        return {"available": True, "passed": all(item["passed"] for item in results.values()), "models": results}

    def self_check(self):
        future = Future()
        if not self._submit(("check", None, future)):
            return {"available": False, **self.status()}
        try:
            return future.result(timeout=15)
        except TimeoutError:
            self._timeout()
            return {"available": False, **self.status()}

    def results(self, *, site_id=None, device_id=None, limit=100, cursor=None):
        filters = [site_id, device_id]
        conditions, args = [], []
        for field, value in zip(("site_id", "device_id"), filters):
            if value is not None:
                conditions.append(f"{field}=?")
                args.append(value)
        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        with self.db.connection() as c:
            total = c.execute("SELECT count(*) FROM inference_results" + where, args).fetchone()[0]
            if cursor:
                try:
                    stamp, identifier, saved_filters = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                    if saved_filters != filters or not isinstance(stamp, str) or not isinstance(identifier, str):
                        raise ValueError()
                except Exception as exc:
                    raise InferenceError(422, "Invalid inference results cursor") from exc
                conditions.append("(created_at,id)<(?,?)")
                args.extend((stamp, identifier))
            where = " WHERE " + " AND ".join(conditions) if conditions else ""
            rows = c.execute("SELECT * FROM inference_results" + where + " ORDER BY created_at DESC,id DESC LIMIT ?", (*args, limit + 1)).fetchall()
        items = []
        for row in rows[:limit]:
            item = dict(row)
            item["predicted_delta"] = json.loads(item["predicted_delta"])
            item["fusion_eligible"] = False
            items.append(item)
        token = None
        if len(rows) > limit:
            token = base64.urlsafe_b64encode(json.dumps([items[-1]["created_at"], items[-1]["id"], filters]).encode()).decode().rstrip("=")
        return {"items": items, "next_cursor": token, "total": total}

    def _cleanup(self):
        models = list(self._models.values())
        if getattr(self, "_pending_model", None) is not None:
            models.append(self._pending_model)
        for model in reversed(models):
            try:
                model.close()
            except Exception:
                pass
        if self._acl is not None:
            actions = []
            if self._context is not None:
                actions.append((self._acl.rt.destroy_context, (self._context,)))
            if self._device_set:
                actions.append((self._acl.rt.reset_device, (0,)))
            if self._initialized:
                actions.append((self._acl.finalize, ()))
            for function, args in actions:
                try:
                    function(*args)
                except Exception:
                    pass
        with self._lock:
            self._models.clear()

    def close(self):
        self._stop.set()
        if self._thread:
            # A wedged vendor call cannot be cancelled safely; daemon thread
            # owns its resources until it returns, with no further DB writes.
            self._thread.join(timeout=1)
