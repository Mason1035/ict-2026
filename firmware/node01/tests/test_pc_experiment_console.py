"""TEST_ONLY/SYNTHETIC. No test opens COM ports, alters clocks or samples hardware."""
import asyncio
import codecs
import csv
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import zlib

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from experiment_console.archive import copy_verified, inspect, file_info
from experiment_console.clock import HostClock, ClockGuard
from experiment_console.console import ConsoleUI, default_manifest
from experiment_console.core import Engine, Journal, Lines, danger, important, wire_command
from experiment_console.transport import Receiver, open_port


class FakeClock(HostClock):
    def __init__(self, zone=None, offset='+08:00', confirmed=True):
        super().__init__(zone, None if zone else offset, confirmed)
        self.utc = datetime(2026, 10, 30, 13, 30, 15, tzinfo=timezone.utc)
        self.mono = 1000000000

    def sample(self):
        return self.at(self.utc, self.mono)

    def advance(self, seconds, wall_seconds=None):
        self.mono += int(seconds * 1e9)
        self.utc += timedelta(seconds=seconds if wall_seconds is None else wall_seconds)


class Fixture:
    """Firmware-shaped wire fixtures for ORIGINAL validator. Explicit TEST_ONLY outer scope.

    The old validator requires wire metadata source=REAL_SENSOR. That payload is
    simulated, not a real observation: CSV header, session, ID and extra metadata
    all mark TEST_ONLY/SYNTHETIC, and output never counts as hardware validation.
    """
    def __init__(self, root, identifier='TEST_ONLY_SYNTHETIC_A', clock=None, finish=True):
        self.root = Path(root)
        self.sd = self.root / 'SYNTHETIC_SD'
        self.sd.mkdir(parents=True)
        self.clock = clock or FakeClock()
        self.manifest = default_manifest()
        self.elf = json.loads(self.manifest.read_text())['files']['zhishao_node01.elf']['sha256']
        self.journal = Journal(self.root / 'TEST_ONLY_RUNS', self.clock, 'SIMULATED_NOT_COM7', 115200, True)
        self.engine = Engine(self.journal, self.clock, self.elf)
        self.id = identifier
        self.csv = self.sd / 'N0000001.CSV'
        self.begin = self.csv.with_suffix('.BEG')
        self.end = self.csv.with_suffix('.END')
        fields = 'kind channel acquisition_index attempted_uptime_us acquired_uptime_us timestamp_ms time_synced validity error ax_raw ay_raw az_raw gx_raw gy_raw gz_raw ax_mps2 ay_mps2 az_mps2 gx_dps gy_dps gz_dps soil_raw'.split()
        with self.csv.open('w', encoding='utf-8', newline='') as stream:
            stream.write('# TEST_ONLY SYNTHETIC fixture; not sensor observations or hardware results\n')
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
            writer.writeheader()
            for index, (kind, channel) in enumerate([('imu', 0), ('imu', 1), ('soil', 0), ('soil', 1), ('soil', 2)]):
                row = dict.fromkeys(fields, '')
                row.update(kind=kind, channel=channel, acquisition_index=index,
                           attempted_uptime_us=1000001 + index * 10, acquired_uptime_us=1000002 + index * 10,
                           time_synced='false', validity='Valid', error=0)
                if kind == 'imu':
                    row.update(dict.fromkeys(fields[9:21], 0))
                else:
                    row['soil_raw'] = 1234
                writer.writerow(row)
        self.raw_csv = self.csv.read_bytes()
        self.crc = f'{zlib.crc32(self.raw_csv):08x}'
        begin = {'_test_only': 'SYNTHETIC_NOT_HARDWARE', 'record_type': 'START_INTENT',
                 'experiment_id': self.id, 'elf_sha256': self.elf, 'source': 'REAL_SENSOR',
                 'mode': 'SANDBOX_EXPERIMENT_CAPTURE', 'calibration_status': 'NOT_READY',
                 'requested_seconds': 30, 'start_us': 0, 'csv': '/sdcard/N0000001.CSV'}
        end = {**begin, 'record_type': 'END', 'start_us': 1000000, 'stop_us': 2500000,
               'last_producer_ack_us': 2501000, 'actual_duration_us': 1500000, 'stop_reason': 'USER_STOP',
               'produced': 5, 'enqueued': 5, 'dequeued': 5, 'accepted': 5, 'verified_rows': 5,
               'queue_drop': 0, 'internal_drop': 0, 'errors': 0, 'uncertain': 0, 'replay': 0,
               'i2c_errors': 0, 'lock_timeouts': 0, 'sensor_errors': 0,
               'top_valid': 1, 'toe_valid': 1, 'soil_valid': [1, 1, 1],
               'storage_clean': True, 'csv_verified': True, 'csv_bytes': len(self.raw_csv), 'csv_crc32': self.crc}
        self.begin.write_text(json.dumps(begin) + '\n', encoding='utf-8')
        self.end.write_text(json.dumps(end) + '\n', encoding='utf-8')
        self.rx('I (1) boot: ESP-IDF v5.5.3\r\n')
        self.rx('I (2) node_runtime: STARTUP_EXPERIMENT plan=B_IMU_FIRST probes=0 duration_s=120\r\n')
        self.rx('I (3) node_runtime: DIAG_V6 app_elf_sha256=' + self.elf + '\r\n')
        self.rx('W (4) node_runtime: EXPERIMENT_READY id=' + self.id + ' csv=/sdcard/N0000001.CSV range_s=30..300\r\n')
        self.rx(f'I (5) node_runtime: EXPERIMENT_METADATA_VERIFIED stage=START_INTENT path=/sdcard/N0000001.BEG bytes={self.begin.stat().st_size} crc32={zlib.crc32(self.begin.read_bytes()):08x}\r\n')
        self.rx(f'W (6) node_runtime: EXPERIMENT_BEGIN id={self.id} monotonic_us=1000000 requested_seconds=30 calibration=NOT_READY\r\n')
        if finish:
            self.finish()

    def rx(self, text):
        self.engine.receive(text.encode('utf-8'))

    def finish(self):
        self.rx('W (7) node_runtime: EXPERIMENT_STOP_REQUEST actual_us=2500000 reason=USER_STOP\r\n')
        self.rx('W (8) node_runtime: CAPTURE_CSV_VERIFIED storage_quality=NO_RECORDED_STORAGE_LOSS\r\n')
        self.rx(f'I (9) node_runtime: SD_READBACK verified path=/sdcard/N0000001.CSV rows=5 bytes={len(self.raw_csv)} crc32={self.crc} checks=length,actual_rows,crc,eof\r\n')
        self.rx(f'W (10) node_runtime: EXPERIMENT_FINALIZED id={self.id} reason=USER_STOP requested_s=30 actual_duration_us=1500000 last_producer_ack_us=2501000 csv_verified=1 metadata_verified=1 metadata_path=/sdcard/N0000001.END metadata_error=0 metadata_bytes={self.end.stat().st_size} metadata_crc32={zlib.crc32(self.end.read_bytes()):08x} within_stop_budget=1 storage_clean=1 sensors_clean=1\r\n')
        self.engine.close()

    def plan(self):
        return inspect(self.sd, self.journal.directory, self.manifest)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='NODE01_TEST_ONLY_')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def engine(self, clock=None):
        clock = clock or FakeClock()
        journal = Journal(self.root, clock, 'FAKE_DEVICE_NOT_COM7', 115200, True)
        engine = Engine(journal, clock)
        self.addCleanup(engine.close)
        return engine

    def test_protocol_exact_bytes_and_invalid_not_forwarded(self):
        for text, expected in [('EXP STATUS', b'EXP STATUS\r\n'), (' EXP START 030 ', b'EXP START 30\r\n'), ('EXP STOP', b'EXP STOP\r\n'), ('EXP START', b'EXP START\r\n')]:
            self.assertEqual(wire_command(text), expected)
        for text in [':quit', 'EXP START 301', 'EXP START 29', 'EXP START -30', 'SECRET_PASSWORD', 'EXP STATUS\nEXP START 30', 'X' * 48, 'EXP MARK RAIN_START', 'EXP STOP\x00']:
            with self.assertRaises(ValueError):
                wire_command(text)

    def test_raw_exact_hidden_utf8_ansi_crlf_and_partial(self):
        engine = self.engine()
        raw = '\x1b[32mI (1) IMU_IRQ error=0 测试\x1b[0m\r\n'.encode() + b'partial\xff'
        for byte in raw:
            engine.receive(bytes([byte]))
        engine.close()
        self.assertEqual((engine.journal.directory / 'serial.bin').read_bytes(), raw)
        self.assertEqual((engine.journal.directory / 'device.txt').read_bytes().decode('utf-8'), raw.decode('utf-8', errors='backslashreplace'))
        self.assertGreater(engine.suppressed, 0)
        self.assertIn('PARTIAL_LINE_AT_CLOSE', engine.parse_issues)

    def test_filter_keeps_errors_not_ordinary_long_tail(self):
        for line in ['I (2) I2C_DEVICE err=2', 'I (3) SOIL error=0/0/1', 'I (4) FLOW queue_drop=1', 'E (5) sdk CRC mismatch', 'I (6) EXPERIMENT_FINALIZE_FAILED reason=X', 'I (7) I2C_LOCK_OWNERSHIP metadata_errors=1']:
            self.assertTrue(important(line), line)
            self.assertTrue(danger(line), line)
        for line in ['I (1) IMU_IRQ error=0', 'I (2) SD_LONG_EVENT wall_us=700000', 'I (3) STACK_HWM_BYTES health=1744', 'I (4) SD_PHASE fail=0']:
            self.assertFalse(danger(line), line)

    def test_ack_begin_finalization_separate_timeout_and_duplicates(self):
        engine = self.engine()
        sent = []
        writer = lambda data: sent.append(data) or len(data)
        with self.assertRaises(ValueError):
            engine.send('EXP START 30', writer)
        engine.receive(b'I (1) EXP_STATUS endpoint=0 state=READY\n')
        engine.send('EXP START 30', writer)
        self.assertEqual(engine.state, 'READY')
        self.assertFalse(engine.experiments)
        engine.receive(b'I (2) EXP_ACK endpoint=0 command=START accepted=1 seconds=30 state=START_PENDING\n')
        self.assertEqual(engine.state, 'START_PENDING')
        engine.receive(b'W (3) EXPERIMENT_BEGIN id=TEST_ONLY monotonic_us=12 requested_seconds=30\n')
        self.assertEqual(engine.state, 'RUNNING')
        engine.receive(b'I (2) EXP_ACK endpoint=0 command=START accepted=1 seconds=30 state=START_PENDING\n')
        self.assertEqual(engine.state, 'RUNNING')
        engine.send('EXP STOP', writer)
        engine.clock.advance(6)
        engine.tick()
        self.assertIsNone(engine.pending)
        self.assertEqual(len(sent), 2)
        engine.receive(b'I (3) CAPTURE_CSV_VERIFIED rows=5\n')
        self.assertEqual(engine.state, 'FINALIZING')
        engine.receive(b'W (4) EXPERIMENT_FINALIZED id=TEST_ONLY csv_verified=1 metadata_verified=1 within_stop_budget=1 storage_clean=1 sensors_clean=1\n')
        self.assertEqual(engine.state, 'FINALIZED')
        self.assertEqual(engine.snapshot()['host_files'], 'HOST_FILES_NOT_VERIFIED')

    def test_reboot_disconnect_partial_and_no_auto_transmit(self):
        engine = self.engine()
        engine.receive(b'W (1) EXPERIMENT_BEGIN id=TEST_ONLY monotonic_us=1 requested_seconds=30\n')
        engine.receive(b'I (2) boot: ESP-IDF v5.5.3\n')
        self.assertTrue(engine.experiments[0]['interrupted'])
        self.assertEqual(engine.state, 'INITIALIZING')
        engine.disconnected(OSError('TEST_ONLY USB removed'))
        self.assertEqual(engine.state, 'DISCONNECTED')
        self.assertFalse(engine.capture_complete)
        engine.close()
        self.assertNotIn('TX_SENT_LOCAL', (engine.journal.directory / 'events.jsonl').read_text())
        other = self.engine()
        other.receive(b'I (1) EXP_STATUS state=CAPTURING\n')
        self.assertEqual(other.state, 'UNKNOWN')
        other.receive(b'EXPERIMENT_FINALIZED id=TEST_ONLY')
        other.close()
        self.assertNotEqual(other.state, 'FINALIZED')

    def test_stale_ready_incomplete_final_claim_and_begin_timeout(self):
        engine = self.engine()
        engine.receive(b'W (1) EXPERIMENT_READY id=TEST_ONLY csv=/sdcard/N0000001.CSV\n')
        engine.send('EXP START 30', lambda data: len(data))
        engine.receive(b'I (2) EXP_ACK endpoint=0 command=START accepted=1 state=START_PENDING\n')
        engine.clock.advance(16)
        engine.tick()
        self.assertIsNone(engine.begin_deadline_ns)
        self.assertEqual(engine.state, 'START_PENDING')
        engine.receive(b'W (3) EXPERIMENT_BEGIN id=TEST_ONLY monotonic_us=12 requested_seconds=30\n')
        engine.receive(b'W (1) EXPERIMENT_READY id=TEST_ONLY csv=/sdcard/N0000001.CSV\n')
        self.assertEqual(engine.state, 'RUNNING')
        engine.receive(b'I (4) EXP_STATUS state=READY\n')
        self.assertEqual(engine.state, 'UNKNOWN')
        engine.receive(b'W (5) EXPERIMENT_FINALIZED id=TEST_ONLY metadata_verified=0\n')
        self.assertNotEqual(engine.state, 'FINALIZED')
        self.assertFalse(engine.current['device_finalized'])

    def test_early_elf_before_startup_marker_is_not_erased(self):
        engine = self.engine()
        identity = 'a' * 64
        engine.receive(('I (1) app_elf_sha256=' + identity + '\n').encode())
        engine.receive(b'I (2) STARTUP_EXPERIMENT plan=B_IMU_FIRST\n')
        self.assertEqual(engine.actual_elf, identity)

    def test_rejected_start_terminal_ack_does_not_leave_false_ready(self):
        engine = self.engine()
        engine.receive(b'I (1) EXP_STATUS state=READY\n')
        engine.send('EXP START 30', lambda data: len(data))
        engine.receive(b'I (2) EXP_ACK endpoint=0 command=START accepted=0 seconds=30 state=FINALIZED\n')
        self.assertEqual(engine.state, 'UNKNOWN')
        self.assertTrue(engine.errors)
        with self.assertRaises(ValueError):
            engine.send('EXP START 30', lambda data: len(data))

    def test_stream_memory_limits_and_critical_overflow_visible(self):
        engine = self.engine()
        data = b'I (1) IMU_IRQ error=0\n' * 3000
        for start in range(0, len(data), 4096):
            engine.receive(data[start:start + 4096])
        self.assertEqual(engine.journal.offset, len(data))
        self.assertLessEqual(engine.messages.qsize(), 256)
        engine.receive(b'X' * 9000 + b'\n')
        self.assertIn('LINE_TOO_LONG', engine.parse_issues)
        for _ in range(300):
            engine.message('TEST_ONLY danger', True)
        self.assertGreater(engine.display_overflow, 0)
        self.assertTrue(engine.errors)
        with self.assertRaises(RuntimeError):
            engine.send('EXP STATUS', lambda data: len(data))

    def test_disk_full_and_short_write_block_commands(self):
        for short in [False, True]:
            engine = self.engine()
            real = engine.journal.raw
            class Faulty:
                def write(self, data):
                    if short:
                        return real.write(data[:2])
                    raise OSError(28, 'TEST_ONLY No space left on device')
                def __getattr__(self, name):
                    return getattr(real, name)
            engine.journal.raw = Faulty()
            engine.receive(b'I (1) EXP_STATUS state=READY\n')
            self.assertTrue(engine.fatal)
            self.assertFalse(engine.capture_complete)
            with self.assertRaises(RuntimeError):
                engine.send('EXP STATUS', lambda data: len(data))
            engine.close()

    def test_port_config_no_explicit_reset_or_open_until_preconfigured(self):
        order = []
        class Fake:
            def __init__(self, **kwargs):
                self.asserted = kwargs
                order.append(('constructor', kwargs['port']))
            def __setattr__(self, name, value):
                order.append((name, value))
                object.__setattr__(self, name, value)
            def open(self):
                order.append(('open', self.dtr, self.rts))
        with patch('experiment_console.transport.serial.Serial', Fake):
            open_port('COM7', 115200)
        self.assertEqual(order[-1], ('open', False, False))
        self.assertNotIn('write', [item[0] for item in order])

    def test_real_pyserial_loop_only_receiver(self):
        import serial
        device = serial.serial_for_url('loop://', timeout=0.05, write_timeout=1)
        engine = self.engine()
        receiver = Receiver(device, engine)
        receiver.start()
        raw = b'I (1) EXP_STATUS endpoint=0 state=READY\r\n'
        device.write(raw)
        due = time.monotonic() + 2
        while engine.state != 'READY' and time.monotonic() < due:
            time.sleep(0.01)
        receiver.stop()
        engine.close()
        self.assertEqual(engine.state, 'READY')
        self.assertEqual((engine.journal.directory / 'serial.bin').read_bytes(), raw)

    def test_receiver_exception_and_new_session_do_not_reuse_begin(self):
        class Broken:
            in_waiting = 1
            def read(self, count):
                raise OSError('TEST_ONLY disconnected during RX')
            def close(self):
                pass
        engine = self.engine()
        receiver = Receiver(Broken(), engine)
        receiver.start()
        due = time.monotonic() + 2
        while engine.state != 'DISCONNECTED' and time.monotonic() < due:
            time.sleep(0.01)
        receiver.stop()
        self.assertEqual(engine.state, 'DISCONNECTED')
        self.assertFalse(engine.capture_complete)
        reopened = self.engine()
        self.assertEqual(reopened.state, 'UNKNOWN')
        self.assertFalse(reopened.experiments)


class TimeTests(unittest.TestCase):
    def test_midnight_offset_and_dst(self):
        clock = HostClock(utc_offset='+08:00', confirmed=True)
        before = clock.at(datetime(2026, 10, 30, 15, 59, 59, tzinfo=timezone.utc), 0)
        after = clock.at(datetime(2026, 10, 30, 16, 0, 1, tzinfo=timezone.utc), 2000000000)
        self.assertTrue(before['iso8601'].startswith('2026-10-30T23:59:59'))
        self.assertTrue(after['iso8601'].startswith('2026-10-31T00:00:01'))
        toronto = HostClock(timezone_name='America/Toronto', confirmed=True)
        a = toronto.at(datetime(2026, 11, 1, 5, 59, 59, tzinfo=timezone.utc), 0)
        b = toronto.at(datetime(2026, 11, 1, 6, 0, 1, tzinfo=timezone.utc), 2000000000)
        self.assertEqual(a['utc_offset'], '-04:00')
        self.assertEqual(b['utc_offset'], '-05:00')
        guard = ClockGuard()
        guard.observe(a)
        self.assertFalse(guard.observe(b))

    def test_jump_and_system_timezone_change(self):
        clock = FakeClock()
        guard = ClockGuard()
        guard.observe(clock.sample())
        clock.advance(1, 30)
        self.assertIn('HOST_CLOCK_JUMP', guard.observe(clock.sample()))
        sample = clock.sample()
        sample.update(timezone_kind='WINDOWS_SYSTEM_LOCAL', utc_offset='-05:00')
        self.assertIn('HOST_TIMEZONE_OR_SYSTEM_OFFSET_CHANGED', guard.observe(sample))


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='NODE01_SYNTHETIC_ARCHIVE_')
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_original_validator_then_copy_same_sha_and_source_unchanged(self):
        fixture = Fixture(self.root)
        before = {p.name: file_info(p) for p in fixture.sd.iterdir()}
        plan = fixture.plan()
        self.assertEqual(plan['status'], 'HOST_FILES_VERIFIED', plan)
        self.assertTrue(plan['test_only'])
        self.assertEqual(plan['verification_scope'], 'TEST_ONLY_SIMULATION')
        self.assertTrue(plan['suggested_stem'].startswith('20261030_213015_NODE01_TEST_ONLY'))
        output = self.root / 'PC_OUTPUT'
        self.assertFalse(output.exists())
        result = copy_verified(plan, output)
        for key in ['CSV', 'BEG', 'END']:
            entry = result['archive_files'][key]
            self.assertEqual(file_info(Path(entry['source'])), file_info(Path(entry['destination'])))
        self.assertEqual({p.name: file_info(p) for p in fixture.sd.iterdir()}, before)
        other = copy_verified(plan, output)
        self.assertNotEqual(result['archive_directory'], other['archive_directory'])
        evidence = os.environ.get('NODE01_PC_TEST_EVIDENCE_DIR')
        if evidence:
            destination = Path(evidence) / 'TEST_ONLY_SYNTHETIC_ARCHIVE_FIXTURE'
            shutil.copytree(self.root, destination)
            (destination / 'README_TEST_ONLY.md').write_text('所有数据为软件测试合成，不是COM7/真实传感器。旧校验器要求source=REAL_SENSOR形状字段，所以此处仅模拟该wire shape；CSV、session和元数据均明确TEST_ONLY。路径指向测试时临时目录，检查结果和文件SHA真实生成。\n', encoding='utf-8')

    def test_same_second_experiments_do_not_collide(self):
        a = Fixture(self.root / 'a', 'TEST_ONLY_A')
        b = Fixture(self.root / 'b', 'TEST_ONLY_B')
        first, second = a.plan(), b.plan()
        self.assertEqual(first['status'], second['status'])
        self.assertNotEqual(first['suggested_stem'], second['suggested_stem'])

    def test_archive_date_is_begin_not_stop_across_midnight(self):
        clock = FakeClock()
        clock.utc = datetime(2026, 10, 30, 15, 59, 59, tzinfo=timezone.utc)
        fixture = Fixture(self.root, clock=clock, finish=False)
        clock.advance(2)
        fixture.finish()
        plan = fixture.plan()
        self.assertEqual(plan['status'], 'HOST_FILES_VERIFIED', plan)
        self.assertTrue(plan['suggested_stem'].startswith('20261030_235959_'))

    def test_unknown_clock_missing_begin_historical_mtime_never_used(self):
        fixture = Fixture(self.root, clock=FakeClock(confirmed=False))
        self.assertEqual(fixture.plan()['status'], 'UNKNOWN_TIME')
        preview = inspect(fixture.sd)
        self.assertEqual(preview['status'], 'UNKNOWN_TIME')
        self.assertIsNone(preview['historical_preview'][0]['timestamp_name'])
        with self.assertRaises(ValueError):
            copy_verified(preview, self.root / 'DO_NOT_CREATE')
        self.assertFalse((self.root / 'DO_NOT_CREATE').exists())

    def test_jump_incomplete_missing_corrupt_and_original_index_verification(self):
        for case in ['jump', 'missing_end', 'bad_crc', 'incomplete', 'renumber']:
            with self.subTest(case=case):
                fixture = Fixture(self.root / case, finish=False)
                if case == 'jump':
                    fixture.clock.advance(1, 30)
                    fixture.engine.tick()
                if case == 'incomplete':
                    fixture.engine.close()
                else:
                    if case == 'renumber':
                        fixture.raw_csv = fixture.raw_csv.replace(b'soil,0,2,', b'soil,0,9,')
                        fixture.csv.write_bytes(fixture.raw_csv)
                        fixture.crc = f'{zlib.crc32(fixture.raw_csv):08x}'
                        metadata = json.loads(fixture.end.read_text())
                        metadata['csv_crc32'] = fixture.crc
                        fixture.end.write_text(json.dumps(metadata)+'\n', encoding='utf-8')
                    fixture.finish()
                if case == 'missing_end':
                    fixture.end.unlink()  # TEST_ONLY temporary generated fixture, never user SD.
                elif case == 'bad_crc':
                    fixture.csv.write_bytes(fixture.raw_csv + b'X')
                plan = fixture.plan()
                self.assertNotEqual(plan['status'], 'HOST_FILES_VERIFIED')
                if case == 'renumber':
                    self.assertIn('index', plan['reason'])

    def test_destination_sd_and_toctou_refused(self):
        fixture = Fixture(self.root)
        plan = fixture.plan()
        with self.assertRaises(ValueError):
            copy_verified(plan, fixture.sd / 'OUTPUT_NOT_ALLOWED')
        fixture.csv.write_bytes(fixture.raw_csv + b'X')
        with self.assertRaises(ValueError):
            copy_verified(plan, self.root / 'OUT')

    def test_anchor_summary_and_event_mapping_cannot_silently_disagree(self):
        fixture = Fixture(self.root)
        path = fixture.journal.directory / 'session.json'
        summary = json.loads(path.read_text())
        summary['experiments'][0]['begin_observation']['iso8601'] = '2030-01-01T00:00:00+08:00'
        path.write_text(json.dumps(summary), encoding='utf-8')
        self.assertNotEqual(fixture.plan()['status'], 'HOST_FILES_VERIFIED')

    def test_source_changes_during_actual_validator_are_rejected(self):
        fixture = Fixture(self.root)
        from experiment_console import archive
        real = archive.original_check
        def altered(*args):
            result = real(*args)
            fixture.csv.write_bytes(fixture.raw_csv + b'X')
            return result
        with patch.object(archive, 'original_check', altered):
            self.assertNotEqual(fixture.plan()['status'], 'HOST_FILES_VERIFIED')

    def test_optimized_python_cannot_disable_original_checks(self):
        fixture = Fixture(self.root)
        result = subprocess.run([sys.executable, '-O', '-B', '-m', 'experiment_console.archive', '--sd-dir', str(fixture.sd), '--session', str(fixture.journal.directory), '--manifest', str(fixture.manifest)], cwd=TOOLS, capture_output=True, text=True, encoding='utf-8')
        self.assertEqual(result.returncode, 2)
        self.assertIn('PYTHONOPTIMIZE', result.stdout)


class UITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='NODE01_TEST_ONLY_UI_')
        self.addCleanup(self.temp.cleanup)
        clock = FakeClock()
        self.engine = Engine(Journal(self.temp.name, clock, 'FAKE_UI_NOT_COM7', 115200, True), clock)
        self.addCleanup(self.engine.close)

    async def test_windows_pipe_renderer_editing_with_async_flood(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output.vt100 import Vt100_Output
        from prompt_toolkit.data_structures import Size
        rendered = io.StringIO()
        output = Vt100_Output(rendered, lambda: Size(rows=24, columns=100), enable_cpr=False)
        sent = []
        with create_pipe_input() as pipe:
            ui = ConsoleUI(self.engine, lambda data: sent.append(data) or len(data), input=pipe, output=output)
            running = asyncio.create_task(ui.run())
            await asyncio.sleep(0.1)
            pipe.send_text('EXP STATUX')
            await asyncio.sleep(0.1)
            for _ in range(30):
                self.engine.receive(b'I (1) IMU_IRQ error=0\n' * 100)
                await asyncio.sleep(0)
            # Backspace, then S: full input text remains separate from 3000 RX lines.
            pipe.send_text('\x7fS')
            await asyncio.sleep(0.2)
            self.assertEqual(ui.input.buffer.text, 'EXP STATUS')
            pipe.send_text('\x1b[D\x1b[C')  # edit cursor left/right
            await asyncio.sleep(0.1)
            self.assertEqual(ui.input.buffer.text, 'EXP STATUS')
            pipe.send_text('\r')
            await asyncio.sleep(0.2)
            self.assertEqual(sent, [b'EXP STATUS\r\n'])
            self.assertIn('NODE-01 >', rendered.getvalue())
            self.assertIn('EXP STATU', rendered.getvalue())
            self.assertEqual((self.engine.journal.directory / 'serial.bin').stat().st_size, len(b'I (1) IMU_IRQ error=0\n') * 3000)
            pipe.send_text(':quit confirm\r')
            result = await asyncio.wait_for(running, 3)
            self.assertEqual(result, 0)
            self.assertEqual(sent, [b'EXP STATUS\r\n'])  # No automatic STOP or RESET.
            evidence = os.environ.get('NODE01_PC_TEST_EVIDENCE_DIR')
            if evidence:
                directory = Path(evidence)
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'TEST_ONLY_terminal_render.vt100.txt').write_text(rendered.getvalue(), encoding='utf-8')
                (directory / 'TEST_ONLY_ui-result.json').write_text(json.dumps({'platform':sys.platform,'input_backend':type(pipe).__module__+'.'+type(pipe).__name__,'output':'Vt100_Output captured renderer','edited_command':'EXP STATUS','tx_hex':sent[0].hex(),'rx_normal_lines':3000,'actual_terminal_human_visual_acceptance':'NOT_RUN','hardware':'HARDWARE_NOT_RUN'},indent=2),encoding='utf-8')

    async def test_local_commands_and_quit_warning_never_go_to_serial(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        sent = []
        with create_pipe_input() as pipe:
            ui = ConsoleUI(self.engine, lambda data: sent.append(data) or len(data), input=pipe, output=DummyOutput(), port_provider=lambda: [])
            running = asyncio.create_task(ui.run())
            await asyncio.sleep(0.05)
            for command in [':status', ':help', ':verbose on', ':verbose off', ':ports']:
                await ui.command(command)
            await ui.command(':quit')
            self.assertFalse(running.done())
            self.assertTrue(ui.quit_warning)
            await ui.command(':quit confirm')
            await asyncio.wait_for(running, 3)
            self.assertEqual(sent, [])

    async def test_ctrl_c_warns_then_exits_without_sending_stop(self):
        from prompt_toolkit.input import create_pipe_input
        from prompt_toolkit.output import DummyOutput
        sent = []
        with create_pipe_input() as pipe:
            ui = ConsoleUI(self.engine, lambda data: sent.append(data) or len(data), input=pipe, output=DummyOutput())
            running = asyncio.create_task(ui.run())
            await asyncio.sleep(0.05)
            self.engine.receive(b'I (1) IMU_IRQ error=0\n'*30)
            pipe.send_text('\x03')
            await asyncio.sleep(0.1)
            self.assertTrue(ui.quit_warning)
            self.assertFalse(running.done())
            pipe.send_text('\x03')
            await asyncio.wait_for(running, 3)
            self.assertEqual(sent, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
