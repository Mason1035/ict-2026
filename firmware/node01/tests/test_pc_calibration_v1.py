"""Offline regression using immutable real replays and TEST_ONLY simulated boot."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import zlib

FW = Path(__file__).resolve().parents[1]
CODEX = Path('C:/Users/LQY/Documents/Codex')
B = CODEX/'NODE01_BASELINE_ARCHIVE/N0000043_20261118'
A = FW.parents[1]/'docs/test_records/NODE-01/sandbox-01-stable-capture-v1'
BM = B/'firmware/manifest-experiment.json'
AM = A/'firmware/manifest-original.json'
sys.path.insert(0, str(FW/'tools'))

from experiment_console.calibration_v1 import manifest_schema_adapter as adapter
from experiment_console.calibration_v1.common import Rejected
from experiment_console.calibration_v1.identity import IdentityGate, MAX_READY_AGE_NS
from experiment_console.calibration_v1.replay import replay
from experiment_console.calibration_v1.verify_espidf_run import verify_run
from experiment_console import archive, console
from experiment_console.clock import HostClock
from experiment_console.core import Engine, Journal

ELF = 'c920e629a61e61c7f845c619dbe1df635005dd455f970212389902830d681b42'
SIM_ID = 'NODE01-0000000000000000-N0000001.CSV'
BOOT = 'I (25) boot: ESP-IDF v5.5.3 2nd stage bootloader'
IDENTITY = f'I (801) NODE-01: DIAG_V6 app_elf_sha256={ELF}; descriptor'
READY = f'W (2100) node_runtime: EXPERIMENT_READY id={SIM_ID} csv=/sdcard/N0000001.CSV'
BEGIN = f'W (2300) node_runtime: EXPERIMENT_BEGIN id={SIM_ID} monotonic_us=2300000 requested_seconds=30'
FINAL = f'W (33100) node_runtime: EXPERIMENT_FINALIZED id={SIM_ID}'


def spec(directory, name):
    p = directory/name
    return {'experiment_id':json.loads(p.with_suffix('.END').read_bytes())['experiment_id'],
            'begin':str(p.with_suffix('.BEG')), 'csv':str(p), 'end':str(p.with_suffix('.END')),
            'session':str(directory/'session.json')}


class ManifestTests(unittest.TestCase):
    def test_A_and_B_fixed_manifest(self):
        self.assertEqual(adapter.verify_manifest(AM)['firmware_id'], 'OLD_STABLE')
        b = adapter.verify_manifest(BM)
        self.assertEqual(b['approval_status'], 'CANDIDATE_REVIEW_ONLY')
        self.assertEqual(b['expected_elf'], ELF)
        for manifest in (AM, BM):
            self.assertEqual(adapter.verify_manifest(manifest)['auto_start']['manifest_presence'], 'NOT_PRESENT_IN_MANIFEST')

    def test_B_requires_approval_for_both_purposes_and_never_opens_port(self):
        for purpose in ('calibration','qualification'):
            with self.subTest(purpose=purpose), patch.object(console,'open_port',side_effect=AssertionError('FORBIDDEN')), \
                    self.assertRaises(SystemExit):
                console.main(['--manifest', str(BM), '--calibration-purpose', purpose])

    def test_A_manifest_with_B_bin_rejected(self):
        original = adapter.legacy_manifest.info
        def mixed(path):
            value = Path(path)
            return original(B/'firmware/zhishao_node01.bin') if value.name == 'zhishao_node01.bin' else original(value)
        with patch.object(adapter.legacy_manifest,'info',side_effect=mixed), self.assertRaisesRegex(Rejected,'产物大小/SHA'):
            adapter.verify_manifest(AM)

    def test_B_wrong_products_and_A_mixed_bin_rejected(self):
        with tempfile.TemporaryDirectory(prefix='NODE01_STAGE13_TEST_ONLY_') as temp:
            root=Path(temp)/'firmware'
            shutil.copytree(B/'firmware', root)
            for name in ('zhishao_node01.bin','zhishao_node01.elf','config/sdkconfig.json','sdkconfig.local',
                         'bootloader/bootloader.bin','partition_table/partition-table.bin'):
                with self.subTest(name=name):
                    path=root/name
                    raw=path.read_bytes()
                    replacement=bytearray(raw)
                    replacement[-1]^=1
                    path.write_bytes(replacement)
                    with self.assertRaisesRegex(Rejected,'产物大小/SHA'):
                        adapter.verify_manifest(root/BM.name)
                    path.write_bytes(raw)
            shutil.copyfile(A/'firmware/zhishao_node01.bin',root/'zhishao_node01.bin')
            with self.assertRaisesRegex(Rejected,'产物大小/SHA'):
                adapter.verify_manifest(root/BM.name)

    def test_explicit_start_missing_or_wrong_proof(self):
        with tempfile.TemporaryDirectory() as temp:
            bad=Path(temp)/'proof.json'
            for p in (AM,BM):
                with self.assertRaisesRegex(Rejected,'不存在'):
                    adapter.verify_manifest(p,bad)
            bad.write_text('{}')
            for p in (AM,BM):
                with self.assertRaisesRegex(Rejected,'来源证据 SHA'):
                    adapter.verify_manifest(p,bad)

    def test_explicit_false_and_reject_true_or_wrong_type(self):
        self.assertEqual(adapter.auto_start_presence({'auto_start':False}),'PRESENT_AND_VERIFIED')
        for value in (True,0,'false',None):
            with self.subTest(value=value), self.assertRaises(Rejected):
                adapter.auto_start_presence({'auto_start':value})

    def test_diagnostic_relabel_and_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            m=Path(temp)/'manifest.json'
            value=json.loads(BM.read_bytes())
            value['mode']='ACQUISITION_DIAGNOSTIC'
            m.write_text(json.dumps(value))
            with self.assertRaisesRegex(Rejected,'不在受审'):
                adapter.verify_manifest(m)
            # Exercise the mode check independently of the digest gate.
            profile=adapter.profiles()[adapter.CANDIDATE]
            with patch.object(adapter,'profile_for_sha',return_value=profile), self.assertRaisesRegex(Rejected,'Diagnostic'):
                adapter.verify_manifest(m)
        with self.assertRaises(Rejected):
            adapter.verify_manifest(None)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.gate = IdentityGate(ELF)
        self.sample = {'monotonic_ns':1_000_000_000}

    def feed(self,*lines):
        for line in lines:
            self.gate.receive(line,self.sample)

    def denied(self):
        with self.assertRaisesRegex(Rejected,'CALIBRATION_START_BLOCKED'):
            self.gate.start(self.sample)

    def test_same_boot_order_and_one_start(self):
        self.feed(BOOT,IDENTITY,READY)
        self.assertTrue(self.gate.start(self.sample)['identity_match'])
        self.denied()
        self.feed(BEGIN,FINAL)
        self.assertTrue(self.gate.evidence()['same_boot'])

    def test_bad_identity_variants(self):
        for value in (IDENTITY.replace(ELF,'f'*64),IDENTITY.replace(ELF,ELF[:16]),
                      IDENTITY[:-34],f'I (801) other: DIAG_V6 app_elf_sha256={ELF};',
                      IDENTITY.replace(';','0;'), IDENTITY.split(';')[0]):
            with self.subTest(value=value):
                self.gate.invalidate()
                self.feed(BOOT,value,READY)
                self.denied()

    def test_late_and_ready_before_identity(self):
        self.feed(IDENTITY,READY)
        self.denied()
        self.assertIsNone(self.gate.actual_elf)
        self.feed(BOOT,READY,IDENTITY)
        self.denied()

    def test_multiple_boots_no_stale_identity(self):
        self.feed(BOOT,IDENTITY,READY,BOOT,READY)
        self.denied()
        self.assertIsNone(self.gate.actual_elf)
        self.feed(BOOT,IDENTITY,READY)
        self.assertEqual(self.gate.start(self.sample)['start_id'], SIM_ID)

    def test_restart_and_second_begin_invalidate_completed_flow(self):
        self.feed(BOOT,IDENTITY,READY)
        self.gate.start(self.sample)
        self.feed(BEGIN,FINAL,BEGIN)
        self.assertFalse(self.gate.evidence()['same_boot'])
        self.feed('ESP-ROM:esp32s3')
        self.assertIsNone(self.gate.actual_elf)
        self.denied()

    def test_expired_ready_blocks(self):
        self.feed(BOOT,IDENTITY,READY)
        self.sample={'monotonic_ns':self.sample['monotonic_ns']+MAX_READY_AGE_NS+1}
        self.denied()

    def test_second_startup_without_boot_marker_invalidates_cached_ready(self):
        startup = 'W (1200) node_runtime: STARTUP_EXPERIMENT plan=B_IMU_FIRST probes=0 duration_s=120'
        self.feed(BOOT,IDENTITY,startup,READY,'W (2200) node_runtime: STARTUP_EXPERIMENT plan=B_IMU_FIRST probes=0 duration_s=120')
        self.assertIsNone(self.gate.actual_elf)
        self.denied()

    def test_real_Engine_gate_mock_writer_and_raw_replay(self):
        with tempfile.TemporaryDirectory(prefix='NODE01_STAGE13_TEST_ONLY_') as temp:
            clock=HostClock(None,'+08:00')
            clock.confirmed=True
            j=Journal(temp,clock,'TEST_ONLY',115200,test_only=True)
            profile=adapter.verify_manifest(BM)
            j.event('CALIBRATION_PROFILE_V1',clock.sample(),firmware_id=profile['firmware_id'],
                    manifest_sha256=profile['manifest_sha256'],purpose='qualification')
            e=Engine(j,clock,ELF,identity_gate=IdentityGate(ELF),start_guard=lambda:None)
            sent=[]
            def mock_writer(raw):
                sent.append(raw)
                return len(raw)
            with self.assertRaises(ValueError):
                e.send('EXP START 30',mock_writer)
            e.receive((BOOT+'\r\n'+IDENTITY+'\r\n'+READY+'\r\n').encode())
            e.send('EXP START 30',mock_writer)
            e.receive((BEGIN+'\r\n'+FINAL+'\r\n').encode())
            # Raw replay tests the chain itself. This intentionally does not
            # assert a valid device terminal or host file result for mock data.
            e.close()
            self.assertEqual(sent,[b'EXP START 30\r\n'])
            self.assertEqual(replay(j.directory/'session.json',SIM_ID,profile)['status'],'SAME_BOOT_IDENTITY_VERIFIED')
            self.assertTrue(json.loads((j.directory/'session.json').read_bytes())['test_only'])

    def test_disconnect_resets_gate_and_prevents_writer(self):
        with tempfile.TemporaryDirectory() as temp:
            clock=HostClock(None,'+08:00')
            j=Journal(temp,clock,'TEST_ONLY',115200,test_only=True)
            e=Engine(j,clock,ELF,identity_gate=IdentityGate(ELF),start_guard=lambda:None)
            e.receive(('\n'.join((BOOT,IDENTITY,READY))+'\n').encode())
            e.disconnected(OSError('TEST_ONLY'))
            self.assertIsNone(e.actual_elf)
            with self.assertRaises(RuntimeError):
                e.send('EXP START 30',lambda _:self.fail('串口写入不允许'))
            e.close()


class FileTests(unittest.TestCase):
    def test_real_A_positive_B_only_byte_integrity(self):
        a=verify_run(spec(A/'hardware-evidence/300s','N0000014.CSV'),adapter.verify_manifest(AM))
        self.assertEqual(a['status'],'FILES_AND_UART_VERIFIED',a['reasons'])
        b=verify_run(spec(B/'raw','N0000043.CSV'),adapter.verify_manifest(BM))
        self.assertEqual(b['host_byte_integrity'],'HOST_FILES_BYTES_VERIFIED',b['reasons'])
        self.assertEqual(b['device_sd_readback'],'DEVICE_SD_READBACK_VERIFIED')
        self.assertEqual(b['runtime_identity']['status'],'HISTORICAL_IDENTITY_NOT_OBSERVED')
        self.assertEqual(b['status'],'FAILED_OR_INCOMPLETE')
        self.assertIsNone(b['runtime_identity']['actual_device_elf'])

    def test_versioned_archive_only_marks_copy_after_independent_recheck(self):
        source = A/'hardware-evidence/300s'
        plan = archive.inspect(source,source/'session.json',AM)
        self.assertEqual(plan['status'],'HOST_FILES_VERIFIED',plan.get('reason'))
        with tempfile.TemporaryDirectory(prefix='NODE01_STAGE13_TEST_ONLY_') as output:
            result = archive.copy_verified(plan,output)
            self.assertEqual(result['host_file_copy'],'HOST_FILE_COPY_VERIFIED')
            self.assertEqual(result['original_verifier']['result']['power_loss_safety'],'NOT_VERIFIED')

    def test_bad_file_groups_crc_size_rows_eof_duplicate_gap_and_mixed(self):
        profile=adapter.verify_manifest(BM)
        for case, reason in (
                ('missing_BEG','不存在'),('missing_END','不存在'),('bad_CRC','CRC不匹配'),
                ('bad_size','字节数或CRC'),('bad_count','行数'),('EOF','EOF'),
                ('duplicate','重复index'),('gap','索引缺行'),('mixed_ID','BEG/END字段'),
                ('mixed_ELF','BEG/END字段')):
            with self.subTest(case=case), tempfile.TemporaryDirectory(prefix='NODE01_STAGE13_TEST_ONLY_') as temp:
                raw=Path(temp)/'raw'
                shutil.copytree(B/'raw',raw)
                s=spec(raw,'N0000043.CSV')
                ep,cp,bp=(Path(s[k]) for k in ('end','csv','begin'))
                end=json.loads(ep.read_bytes())
                binary=cp.read_bytes()
                if case in ('missing_BEG','missing_END'):
                    (bp if case=='missing_BEG' else ep).unlink()
                elif case in ('mixed_ID','mixed_ELF'):
                    beg=json.loads(bp.read_bytes())
                    field='experiment_id' if case=='mixed_ID' else 'elf_sha256'
                    beg[field]='not-the-same'
                    bp.write_text(json.dumps(beg))
                else:
                    if case=='bad_CRC':
                        end['csv_crc32']='00000000'
                    if case=='bad_size':
                        end['csv_bytes']+=1
                    if case=='bad_count':
                        end['verified_rows']-=1
                    if case in ('EOF','duplicate','gap'):
                        if case=='EOF':
                            binary=binary[:-1]
                        else:
                            lines=binary.splitlines(keepends=True)
                            fields=lines[-1].split(b',')
                            fields[2]=b'6157' if case=='duplicate' else b'7000'
                            lines[-1]=b','.join(fields)
                            binary=b''.join(lines)
                        cp.write_bytes(binary)
                        end.update(csv_bytes=len(binary),csv_crc32=f'{zlib.crc32(binary):08x}')
                    ep.write_text(json.dumps(end))
                result=verify_run(s,profile)
                self.assertEqual(result['host_byte_integrity'],'HOST_FILES_INCOMPLETE')
                self.assertIn(reason,result['reasons'][0])
