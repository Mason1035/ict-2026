"""Offline Stage 1.4-R qualification regression."""

import json
from pathlib import Path
import tempfile
from concurrent.futures import ThreadPoolExecutor
import unittest
from unittest.mock import patch

from ...clock import HostClock
from ...core import Journal
from .. import qualification as q
from ..common import Rejected
from ..manifest_schema_adapter import profiles, CANDIDATE

ELF = 'c920e629a61e61c7f845c619dbe1df635005dd455f970212389902830d681b42'
EID = 'NODE01-0000000000000001-N0000001.CSV'
BOOT = 'ESP-IDF v5.5.3 2nd stage bootloader'
READY = f'EXPERIMENT_READY id={EID} csv=/sdcard/N0000001.CSV'
ACK = 'EXP_ACK endpoint=0 command=START accepted=1 seconds=30 state=START_PENDING'
STATUS = 'EXP_STATUS endpoint=0 state=READY requested_seconds=120 start_us=0 stop_us=0 reason=NONE q=0'
BEGIN = f'EXPERIMENT_BEGIN id={EID} monotonic_us=2000000 requested_seconds=30'
FINAL = (f'EXPERIMENT_FINALIZED id={EID} reason=TIME_LIMIT requested_s=30 actual_duration_us=30000000 '
         'csv_verified=1 metadata_verified=1 storage_clean=1 sensors_clean=1 within_stop_budget=1')


def arm(site, ok=True):
    result = 'ESP_OK' if ok else 'ESP_FAIL'
    return f'IMU_IRQ_ARM site={site} init_ok=1 result={result} startup_status_seen=1 status=0x39'


class QualificationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.profile = dict(profiles()[CANDIDATE], expected_elf=ELF, inputs={})
        self.path = root/'qualification-authorization.json'
        self.path.write_bytes(q.AUTHORIZATION.read_bytes())
        patcher = patch.object(q, 'AUTHORIZATION', self.path)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.auth = q.QualificationAuthorization(self.profile, self.path)
        clock = HostClock(utc_offset='+08:00')
        clock.confirmed = True
        self.engine = q.QualificationEngine(Journal(root, clock, 'COM7', 115200, test_only=True),
                                            clock, self.profile, self.auth)
        self.addCleanup(self.engine.close)
        self.gate = self.engine.identity_gate
        self.writes = []
        self.tick = 24

    def send(self, command):
        self.engine.send(command, lambda data: self.writes.append(data) or len(data))

    def feed(self, body, tag='node_runtime'):
        self.tick += 1
        self.engine.receive(f'I ({self.tick}) {tag}: {body}\r\n'.encode('ascii'))

    def boot(self, elf=ELF, boot_marker=True, ready=True, failed=None):
        if boot_marker:
            self.feed(BOOT, 'boot')
        if elf:
            self.feed(f'DIAG_V6 app_elf_sha256={elf}; descriptor', 'NODE-01')
        self.feed('STORAGE_QUEUE_ALLOC rows=512 allocated=1')
        for site, address in [('TOP','0x68'), ('TOE','0x69')]:
            result = 'ESP_FAIL' if failed == site else 'ESP_OK'
            self.feed(f'IMU_{site}_INIT {result} addr={address}')
        self.feed('ADS1115_INIT ESP_OK')
        for phase in q.STARTUP_PHASES:
            self.feed(f'STARTUP_PHASE name={phase} first_begin_us=100 first_end_us=202 result=0')
        if ready:
            self.feed(READY)

    def status(self):
        self.send('EXP STATUS')
        self.feed(STATUS)

    def start(self):
        self.boot()
        self.status()
        self.send('EXP START 30')
        self.feed(ACK)

    def arms(self):
        self.feed(arm('TOP'))
        self.feed(arm('TOE'))

    def start_blocked(self):
        with self.assertRaises(ValueError):
            self.send('EXP START 30')
        self.assertFalse(self.auth.claim_path.exists())

    def test_matching_elf_and_start_without_arm(self):
        self.start()
        self.assertEqual(self.gate.actual_elf, ELF)
        self.assertEqual(self.gate.arms, {})
        self.assertEqual(self.writes, [q.STATUS, q.START])

    def test_wrong_elf(self):
        self.boot(elf='1'*64)
        self.start_blocked()

    def test_missing_elf(self):
        self.boot(elf=None)
        self.start_blocked()

    def test_missing_ready(self):
        self.boot(ready=False)
        self.start_blocked()

    def test_imu_init_failure(self):
        self.boot(failed='TOE')
        self.start_blocked()

    def test_top_arm(self):
        self.start()
        self.feed(arm('TOP'))
        self.assertEqual(self.gate.arms, {'TOP': True})

    def test_toe_arm(self):
        self.start()
        self.feed(arm('TOE'))
        self.assertEqual(self.gate.arms, {'TOE': True})

    def arm_failure(self, site):
        self.start()
        self.feed(arm('TOP', site != 'TOP'))
        self.feed(arm('TOE', site != 'TOE'))
        self.feed(BEGIN)
        self.feed(FINAL)
        self.assertTrue(self.gate.failure)
        self.assertFalse(self.gate.terminal_pass)

    def test_top_arm_failure(self):
        self.arm_failure('TOP')

    def test_toe_arm_failure(self):
        self.arm_failure('TOE')

    def test_missing_arm(self):
        self.start()
        self.feed(arm('TOP'))
        self.feed(BEGIN)
        self.assertIsNone(self.gate.accepted_begin)

    def test_early_begin(self):
        self.start()
        self.feed(BEGIN)
        self.arms()
        self.feed(FINAL)
        self.assertFalse(self.gate.terminal_pass)

    @staticmethod
    def rows():
        return [{'kind': 'imu', 'channel': i, 'validity': 'Valid'} for i in range(2)] + [
            {'kind': 'soil', 'channel': c, 'validity': 'Valid'} for c in range(3) for _ in range(60)]

    def test_soil_valid(self):
        self.assertEqual(q.verify_sensor_counts(self.rows())['soil', 2], 60)

    def test_soil_timeout(self):
        rows = self.rows()
        rows[-1]['validity'] = 'Error'
        with self.assertRaises(Rejected):
            q.verify_sensor_counts(rows)
        with self.assertRaises(Rejected):
            q.verify_sensor_counts(rows[:-1])

    def test_duplicate_start(self):
        self.start()
        with self.assertRaises(Rejected):
            self.send('EXP START 30')
        self.assertEqual(self.writes.count(q.START), 1)

    def test_uncertain_write_consumes_quota(self):
        self.boot()
        self.status()
        def fails(data):
            self.assertTrue(json.loads(self.auth.claim_path.read_text(encoding='utf-8'))['consumed'])
            raise OSError('mock uncertain write')
        with self.assertRaises(OSError):
            self.engine.send('EXP START 30', fails)
        with self.assertRaises(Rejected):
            q.QualificationAuthorization(self.profile, self.path)

    def test_exclusive_claim(self):
        def claim(_):
            try:
                self.auth.claim(self.engine.journal.directory, self.gate)
            except ValueError:
                return 'blocked'
            return 'claimed'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertCountEqual(list(pool.map(claim, range(2))), ['claimed','blocked'])

    def test_consumed_even_with_damaged_receipt(self):
        self.auth.claim_path.write_bytes(b'')
        with self.assertRaises(Rejected):
            q.QualificationAuthorization(self.profile, self.path)

    def test_mixed_boot(self):
        self.boot()
        self.status()
        self.feed(BOOT, 'boot')
        self.start_blocked()

    def test_late_uart(self):
        self.boot(boot_marker=False)
        self.start_blocked()

    def test_disconnect_mid_capture(self):
        self.start()
        self.arms()
        self.feed(BEGIN)
        self.engine.disconnected(OSError('mock disconnect'))
        self.assertTrue(self.gate.failure)
        self.assertFalse(self.gate.terminal_pass)

    def test_no_finalized(self):
        self.start()
        self.arms()
        self.feed(BEGIN)
        self.assertEqual(self.gate.accepted_begin, EID)
        self.assertFalse(self.gate.terminal_pass)

    def test_full_order(self):
        self.start()
        self.arms()
        self.feed(BEGIN)
        self.feed(FINAL)
        self.assertTrue(self.gate.evidence()['same_boot'])
        self.assertTrue(self.gate.terminal_pass)

    def test_no_status(self):
        self.boot()
        self.start_blocked()

    def test_duration_and_approval_digest(self):
        self.boot()
        self.status()
        with self.assertRaises(Rejected):
            self.send('EXP START 60')
        self.path.write_bytes(b'changed')
        self.start_blocked()

    def test_no_second_status(self):
        self.boot()
        self.status()
        with self.assertRaises(Rejected):
            self.send('EXP STATUS')
        self.assertEqual(self.writes, [q.STATUS])

    def test_ack_from_wrong_endpoint(self):
        self.boot()
        self.status()
        self.send('EXP START 30')
        self.feed(ACK.replace('endpoint=0','endpoint=1'))
        self.assertTrue(self.gate.failure)


    def log_qualification_binding(self):
        self.engine.journal.event('CALIBRATION_PROFILE_V1', self.engine.clock.sample(),
                                  firmware_id=self.profile['firmware_id'], manifest_sha256=self.profile['manifest_sha256'],
                                  purpose='qualification', qualification_authorization_sha256=q.AUTHORIZATION_SHA)

    def test_reset_framing_damage_is_scoped_and_replayed(self):
        from ..replay import replay

        self.log_qualification_binding()
        self.engine.receive(b'previous output truncated\xcbESP-ROM:esp32s3\r\n')
        self.start()
        self.arms()
        self.feed(BEGIN)
        self.feed(FINAL)
        self.engine.close()
        self.assertEqual(self.engine.snapshot()['qualification_pre_boot_parse_issues'], ['ENCODING_DAMAGE'])
        self.assertEqual(self.engine.snapshot()['parse_issues'], [])
        result = replay(self.engine.journal.directory/'session.json', EID, self.profile)
        self.assertEqual(result['status'], 'SAME_BOOT_IDENTITY_VERIFIED')
        self.assertTrue(result['qualification']['terminal_pass'])

    def test_post_boot_damage_blocks_start_and_does_not_consume(self):
        self.boot()
        self.status()
        self.engine.receive(b'corrupt\xcb\r\n')
        self.start_blocked()
        self.assertEqual(self.engine.snapshot()['parse_issues'], ['ENCODING_DAMAGE'])

    def test_replay_does_not_clear_encoding_damage_after_begin(self):
        from ..replay import replay

        self.log_qualification_binding()
        self.start()
        self.arms()
        self.feed(BEGIN)
        self.engine.receive(b'corrupt\xcb\r\n')
        self.feed(FINAL)
        self.engine.close()
        with self.assertRaisesRegex(Rejected, '原串口解析损坏'):
            replay(self.engine.journal.directory/'session.json', EID, self.profile)

    def test_replay_requires_two_arms_even_when_final_log_is_clean(self):
        from ..replay import replay

        self.log_qualification_binding()
        self.start()
        self.feed(arm('TOP'))
        self.feed(BEGIN)
        self.feed(FINAL)
        self.engine.close()
        with self.assertRaisesRegex(Rejected, '两路 ARM'):
            replay(self.engine.journal.directory/'session.json', EID, self.profile)

