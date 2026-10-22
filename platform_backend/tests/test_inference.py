"""Research inference windows, bounded execution and provenance contracts."""
from threading import Event, get_ident
import time

import numpy as np
import pytest

from geohazard_platform.database import Database
from geohazard_platform.inference import InferenceService
from geohazard_platform.settings import Settings


@pytest.fixture
def service(tmp_path):
    db = Database(tmp_path / 'inference.sqlite3')
    instance = InferenceService(db, Settings(data_dir=tmp_path))
    yield instance
    instance.close()
    db.close()


def observation(device='NODE', soil=25, valid=True):
    return {'site_id': 'SITE', 'device_id': device, 'boot_id': 1,
            'source': 'MOCK', 'scope': 'TEST_ONLY', 'timestamp_ms': 1760000000000,
            'time_synced': True, 'soil': {'avg_pct': soil},
            'imu': [dict(zip(('ax', 'ay', 'az', 'gx', 'gy', 'gz'), range(6)), valid=valid)]}


def wait_until(predicate):
    deadline = time.monotonic() + 3
    while not predicate():
        assert time.monotonic() < deadline, 'inference worker did not finish'
        time.sleep(.005)


def test_windows_are_raw_float32_and_isolated_by_device(service, monkeypatch):
    jobs = []
    monkeypatch.setattr(service, '_submit', jobs.append)
    for index in range(3):
        service.observe(observation(soil=10 * (index + 1)))
    service.observe(observation('OTHER'))
    assert not jobs
    service.observe(observation(soil=40))
    assert len(jobs) == 1
    name, window, metadata = jobs[0][1]
    assert name == 'soil' and window.shape == (1, 4, 1) and window.dtype == np.float32
    np.testing.assert_allclose(window.ravel(), [.1, .2, .3, .4])
    assert metadata['source'] == 'MOCK' and metadata['scope'] == 'TEST_ONLY'
    assert metadata['window_start_at'] == metadata['window_end_at'] == '2025-10-09T08:53:20.000Z'


def test_motion_requires_eight_valid_samples_and_skips_missing(service, monkeypatch):
    jobs = []
    monkeypatch.setattr(service, '_submit', jobs.append)
    for _ in range(7):
        service.observe(observation(soil=None))
    for _ in range(5):
        service.observe(observation(soil=None, valid=False))
    missing = observation(soil=None)
    missing['imu'][0]['gz'] = None
    service.observe(missing)
    assert not jobs
    service.observe(observation(soil=None))
    assert len(jobs) == 1
    name, window, _ = jobs[0][1]
    assert name == 'motion' and window.shape == (1, 8, 6)
    np.testing.assert_array_equal(window[0], np.tile(np.arange(6), (8, 1)))


def test_boot_and_provenance_changes_reset_partial_windows(service, monkeypatch):
    jobs = []
    monkeypatch.setattr(service, '_submit', jobs.append)
    for _ in range(3):
        service.observe(observation())
    changed = observation()
    changed.update(boot_id=2, source='REAL', scope='DEVICE_INTAKE')
    service.observe(changed)
    assert not jobs
    for _ in range(3):
        service.observe(changed)
    assert jobs[0][1][2]['source'] == 'REAL'


def fake_runtime(service, monkeypatch, *, fail=False):
    calls = []

    class Model:
        def infer(self, window):
            calls.append(get_ident())
            if fail:
                raise RuntimeError('execute failed')
            return np.ones(window.shape[-1], dtype=np.float32), .25

        def close(self):
            pass

    def load():
        service._models.update({name: Model() for name in ('soil', 'motion')})

    monkeypatch.setattr(service, '_open', load)
    return calls


def test_worker_serializes_and_persists_only_research_results(service, monkeypatch):
    calls = fake_runtime(service, monkeypatch)
    assert service.status()['state'] == 'not_connected'
    for _ in range(4):
        service.observe(observation())
    wait_until(lambda: service.status()['success_count'] == 1)
    assert calls and calls[0] != get_ident()
    assert service.status()['state'] == 'connected'
    result = service.results()['items'][0]
    assert result['model'] == 'soil' and result['predicted_delta'] == [1.0]
    assert result['latency_ms'] == .25
    assert result['source'] == 'MOCK' and result['scope'] == 'TEST_ONLY'
    assert result['fusion_eligible'] is False and result['calibration'] == 'uncalibrated_research'
    assert 'risk fusion' in result['reason']
    assert not any('risk' in key for key in result)
    assert service.results(device_id='OTHER')['total'] == 0


def test_three_execute_failures_latch_degraded(service, monkeypatch):
    calls = fake_runtime(service, monkeypatch, fail=True)
    for _ in range(8):
        service.observe(observation())
    wait_until(lambda: service.status()['state'] == 'degraded')
    assert len(calls) == 3 and service.status()['failure_count'] == 3
    service.observe(observation())
    assert service.self_check()['available'] is False
    assert len(calls) == 3 and service.results()['items'] == []


def test_missing_acl_is_lazy_and_never_escapes_observe(service, monkeypatch):
    def absent(name):
        raise ImportError('no ACL in test environment')

    monkeypatch.setattr('geohazard_platform.inference.importlib.import_module', absent)
    assert service._thread is None
    for _ in range(4):
        service.observe(observation())
    wait_until(lambda: service.status()['failure_count'] == 1)
    status = service.status()
    assert status['state'] == 'not_connected' and 'acl_import_failed' in status['reason']
    assert status['loaded'] == {'soil': False, 'motion': False}
    assert service.self_check()['available'] is False


def test_queue_is_bounded_and_full_queue_drops_without_waiting(service, monkeypatch):
    entered, release = Event(), Event()

    def blocked_open():
        entered.set()
        release.wait(3)
        raise RuntimeError('test initialization failure')

    monkeypatch.setattr(service, '_open', blocked_open)
    try:
        for _ in range(4):
            service.observe(observation())
        assert entered.wait(1)
        for _ in range(100):
            service.observe(observation())
        assert service.status()['queue_depth'] == 64
        assert service.status()['dropped_count'] > 0
    finally:
        release.set()


def test_disabled_never_imports_or_starts_worker(tmp_path):
    db = Database(':memory:')
    service = InferenceService(db, Settings(data_dir=tmp_path, acl_mode='off'))
    for _ in range(8):
        service.observe(observation())
    assert service.status()['reason'] == 'disabled'
    assert service.self_check()['available'] is False
    assert service._thread is None
    service.close()
    db.close()


def test_self_check_runs_golden_first_windows_on_worker(service, monkeypatch):
    expected = {}
    for name, shape in {'soil': (4, 1), 'motion': (8, 6)}.items():
        directory = service.settings.acl_model_dir
        with np.load(directory / 'golden' / f'{name}_golden.npz') as golden:
            expected[name] = (golden['inputs'][:1].copy(), golden['expected_delta'][0].copy())
    calls = []

    class Model:
        def __init__(self, name):
            self.name = name

        def infer(self, window):
            np.testing.assert_array_equal(window, expected[self.name][0])
            calls.append(get_ident())
            return expected[self.name][1], .5

        def close(self):
            pass

    monkeypatch.setattr(service, '_open', lambda: service._models.update({name: Model(name) for name in expected}))
    checked = service.self_check()
    assert checked['available'] and checked['passed']
    assert all(item['max_abs_diff'] == 0 for item in checked['models'].values())
    assert len(set(calls)) == 1 and calls[0] != get_ident()
    assert service.status()['state'] == 'connected'
    assert service.results()['total'] == 0  # golden vectors are never telemetry


def test_timeout_latches_and_discards_late_output(service, monkeypatch):
    entered, release = Event(), Event()

    class Model:
        def infer(self, window):
            entered.set()
            release.wait(3)
            return np.ones(1, dtype=np.float32), .5

        def close(self):
            pass

    monkeypatch.setattr(service, '_open', lambda: service._models.update(soil=Model()))
    try:
        for _ in range(4):
            service.observe(observation())
        assert entered.wait(1)
        service._timeout()
        assert service.status()['state'] == 'degraded'
        release.set()
        wait_until(lambda: service._queue.unfinished_tasks == 0)
        assert service.results()['total'] == 0
        assert service.status()['success_count'] == 0
    finally:
        release.set()


def test_failed_golden_check_cannot_report_connected(service, monkeypatch):
    class Model:
        def infer(self, window):
            return np.zeros(window.shape[-1], dtype=np.float32), .25

        def close(self):
            pass

    monkeypatch.setattr(service, '_open', lambda: service._models.update({name: Model() for name in ('soil', 'motion')}))
    result = service.self_check()
    assert result['available'] and not result['passed']
    assert service.status()['state'] == 'degraded'
    assert service.status()['reason'] == 'golden_self_check_failed'
    assert service.status()['failure_count'] == 1
    assert service.self_check()['available'] is False
    # Even constant motion output must remain JSON serializable.
    import json
    json.dumps(result, allow_nan=False)


def test_unreadable_golden_check_cannot_leave_connected(service, monkeypatch, tmp_path):
    fake_runtime(service, monkeypatch)
    for _ in range(4):
        service.observe(observation())
    wait_until(lambda: service.status()['state'] == 'connected')
    service.settings.acl_model_dir = tmp_path / 'missing-golden'
    result = service.self_check()
    assert result['available'] is False
    assert service.status()['state'] == 'degraded'
