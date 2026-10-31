"""Read-only replay of an actual failed run; generated outputs are TEST_ONLY.

No test opens COM7, sends commands to hardware or edits the source evidence.
"""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

from test_pc_experiment_console import FakeClock
from experiment_console.core import Engine, Journal, danger, important
from experiment_console.messages import classify, parse_log
from experiment_console.console import ConsoleUI, MessageLexer
from experiment_console.archive import inspect

REPO = Path(__file__).resolve().parents[3]
SOURCE = Path(os.environ.get('NODE01_REAL_SESSION', str(REPO / 'docs/test_records/NODE-01/sandbox-experiment-archive/console-runs/console-session-20261031-103550-47bcdf1ea20d')))


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = (SOURCE/'serial.bin').read_bytes()
        cls.lines = (SOURCE/'device.txt').read_text(encoding='utf-8').splitlines()
        cls.events = [json.loads(x) for x in (SOURCE/'events.jsonl').read_text(encoding='utf-8').splitlines()]
        cls.source_hashes = {n:hashlib.sha256((SOURCE/n).read_bytes()).hexdigest() for n in ['device.txt','serial.bin','session.json','events.jsonl']}

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='NODE01_TEST_ONLY_REAL_REPLAY_')
        self.addCleanup(self.temp.cleanup)

    def engine(self):
        clock = FakeClock()
        journal = Journal(self.temp.name,clock,'TEST_ONLY_REAL_LOG_REPLAY_NOT_COM7',115200,True)
        engine = Engine(journal,clock,'a'*64)
        self.addCleanup(engine.close)
        return engine

    def event_line(self, event):
        return next(x for x in self.lines if parse_log(x).event == event)

    def rx(self,engine,line):
        engine.receive((line+'\r\n').encode('utf-8'))
        while not engine.messages.empty():
            engine.messages.get_nowait()

    def begin(self,engine):
        self.rx(engine,self.event_line('EXPERIMENT_BEGIN'))

    def test_real_normal_lines_not_errors(self):
        counts=Counter()
        for line in self.lines:
            msg=parse_log(line)
            if msg.event in ['SD_FAILURE','STORAGE_PRESSURE','CAPTURE','SD_IO_IN_FLIGHT','IMU_IRQ_ARM']:
                self.assertFalse(danger(line),line)
                counts[msg.event]+=1
        self.assertTrue(all(counts[name]>0 for name in ['SD_FAILURE','STORAGE_PRESSURE','CAPTURE','SD_IO_IN_FLIGHT','IMU_IRQ_ARM']))

    def test_real_errors_and_history_stats_remain_visible(self):
        counts=Counter()
        for line in self.lines:
            msg=parse_log(line)
            true_error = msg.level=='E' or msg.event=='EXPERIMENT_FINALIZE_FAILED' or (
                msg.event=='SOIL' and msg.fields.get('error')=='1/0/0') or (
                msg.event=='I2C' and msg.fields.get('lock_timeout')=='1') or (
                msg.event=='I2C_DEVICE' and msg.fields.get('addr')=='0x48' and msg.fields.get('err')=='263')
            if true_error:
                self.assertTrue(danger(line),line)
                self.assertTrue(important(line),line)
                counts[msg.event]+=1
        self.assertEqual(counts['SOIL_READ'],1)
        self.assertEqual(counts['I2C_LOCK_TIMEOUT'],1)
        self.assertEqual(counts['EXPERIMENT_FINALIZE_FAILED'],1)
        self.assertGreater(counts['SOIL'],0)
        self.assertGreater(counts['I2C'],0)

    def test_csv_hint_is_not_a_terminal_event(self):
        engine=self.engine(); self.begin(engine)
        self.rx(engine,self.event_line('CAPTURE_CSV_VERIFIED'))
        self.assertEqual(engine.state,'FINALIZING')
        self.assertNotIn('failed',engine.current)
        self.assertNotIn('terminal_event',engine.current)
        self.assertIsNone(engine.last_terminal)
        self.assertFalse(danger(self.event_line('CAPTURE_CSV_VERIFIED')))

    def test_terminal_words_in_prose_never_start_or_finish(self):
        engine=self.engine()
        for line in [
            'I (1) node_runtime: NOTE WAIT EXPERIMENT_BEGIN id=FAKE monotonic_us=1 requested_seconds=30',
            'I (2) node_runtime: NOTE EXPERIMENT_FINALIZED id=FAKE csv_verified=1 metadata_verified=1 within_stop_budget=1 storage_clean=1 sensors_clean=1',
            'I (3) node_runtime: NOTE WAIT EXPERIMENT_FINALIZE_FAILED EXPERIMENT_INIT_FAILED CAPTURE_FINALIZE_BLOCKED',
            'I (4) node_runtime: NOTE docs mention ESP_ERR_TIMEOUT FAILURE STOP blocked',
        ]:
            self.rx(engine,line)
            self.assertEqual(engine.state,'UNKNOWN')
            self.assertFalse(danger(line))
        self.assertEqual(engine.experiments,[])

    def test_failed_result_and_validation_survive_disconnect_late_stop(self):
        engine=self.engine(); self.begin(engine)
        failure=self.event_line('EXPERIMENT_FINALIZE_FAILED')
        self.rx(engine,failure)
        self.assertEqual(engine.current['result'],'FAILED')
        self.assertEqual(engine.current['stop_reason'],'TIME_LIMIT')
        self.assertEqual(engine.current['validation']['csv_verified'],'1')
        self.assertEqual(engine.current['validation']['metadata_verified'],'1')
        self.assertEqual(engine.current['validation']['sensors_clean'],'0')
        engine.send('EXP STOP',lambda data:len(data))
        self.rx(engine,next(x for x in self.lines if parse_log(x).event=='EXP_ACK' and 'command=STOP' in x))
        self.assertEqual(engine.current['device_terminal_line'],failure)
        engine.disconnected(OSError("ClearCommError failed (PermissionError(13, '拒绝访问。', None, 5))"))
        engine.close()
        saved=json.loads((engine.journal.directory/'session.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['connection_status'],'DISCONNECTED')
        self.assertEqual(saved['device_progress_state'],'FAILED')
        self.assertEqual(saved['experiment_result'],'FAILED')
        self.assertEqual(saved['last_device_terminal']['line'],failure)
        self.assertFalse(saved['capture_complete'])
        self.assertFalse(saved['experiments'][0]['device_finalized'])

    def test_failed_terminal_survives_status_csv_duplicate_and_restart(self):
        engine=self.engine(); self.begin(engine)
        self.rx(engine,self.event_line('EXPERIMENT_FINALIZE_FAILED'))
        first=dict(engine.last_terminal)
        for line in [self.event_line('CAPTURE_CSV_VERIFIED'),self.event_line('EXPERIMENT_FINALIZE_FAILED'),
                     'I (9) node_runtime: EXP_STATUS state=CAPTURING',
                     'I (9) node_runtime: EXP_ACK command=STOP first=1 state=STOPPING_PRODUCERS']:
            self.rx(engine,line)
            self.assertEqual(engine.state,'FAILED')
            self.assertEqual(engine.last_terminal,first)
        self.rx(engine,'I (1) boot: ESP-IDF v5.5.3')
        self.assertFalse(engine.experiments[0].get('interrupted',False))
        self.assertEqual(engine.experiments[0]['result'],'FAILED')
        self.assertEqual(engine.last_terminal,first)

    def test_identity_observed_vs_mismatch_is_separate(self):
        engine=self.engine()
        self.assertEqual(engine.snapshot()['firmware_identity'],'NOT_OBSERVED')
        self.rx(engine,'I (1) node_runtime: DIAG_V6 app_elf_sha256='+'b'*64)
        self.assertEqual(engine.snapshot()['firmware_identity'],'MISMATCH')
        self.rx(engine,'I (2) node_runtime: DIAG_V6 app_elf_sha256='+'a'*64)
        self.assertEqual(engine.snapshot()['firmware_identity'],'MATCH')
        engine.expected_elf=None
        self.assertEqual(engine.snapshot()['firmware_identity'],'UNKNOWN')

    def test_success_without_matching_begin_not_confirmed(self):
        engine=self.engine()
        self.rx(engine,'W (1) node_runtime: EXPERIMENT_FINALIZED id=OTHER csv_verified=1 metadata_verified=1 within_stop_budget=1 storage_clean=1 sensors_clean=1')
        self.assertEqual(engine.state,'UNKNOWN')
        self.assertIsNone(engine.last_terminal)

    def test_unmatched_failure_does_not_mark_another_experiment_failed(self):
        engine=self.engine();self.begin(engine)
        self.rx(engine,'W (1) node_runtime: EXPERIMENT_FINALIZE_FAILED id=OTHER reason=TIME_LIMIT sensors_clean=0')
        self.assertEqual(engine.state,'UNKNOWN')
        self.assertNotIn('failed',engine.current)
        self.assertIsNone(engine.last_terminal)

    def test_success_cannot_erase_previously_failed_result(self):
        engine=self.engine();self.begin(engine)
        self.rx(engine,self.event_line('EXPERIMENT_FINALIZE_FAILED'))
        first=engine.current['device_terminal_line']
        self.rx(engine,'W (1) node_runtime: EXPERIMENT_FINALIZED id='+engine.current['experiment_id']+' csv_verified=1 metadata_verified=1 within_stop_budget=1 storage_clean=1 sensors_clean=1')
        self.assertEqual(engine.current['result'],'FAILED')
        self.assertEqual(engine.current['device_terminal_line'],first)
        self.assertFalse(engine.current['device_finalized'])
        self.assertEqual(engine.state,'FAILED')
        self.assertTrue(engine.current['conflict'])

    def test_contradictory_success_flag_not_accepted(self):
        engine=self.engine();self.begin(engine)
        self.rx(engine,'W (1) node_runtime: EXPERIMENT_FINALIZED id='+engine.current['experiment_id']+' csv_verified=1 metadata_verified=1 within_stop_budget=1 storage_clean=1 sensors_clean=1 sensors_clean=0')
        self.assertFalse(engine.current['device_finalized'])
        self.assertIsNone(engine.last_terminal)
        self.assertEqual(engine.state,'UNKNOWN')

    def test_numeric_fields_are_event_specific(self):
        normal=['I (1) DOC err=1 timeout=10 expected_error=ESP_ERR_TIMEOUT',
                'I (1) SD_FAILURE write=0 flush=0 verify=0 open=0 recovery=0 unavailable_drop=0',
                'W (1) SD_IO_IN_FLIGHT op=queue_wait age_us=100000',
                'W (1) IMU_IRQ_ARM site=TOP init_ok=1 result=ESP_OK; failed sites stay IRQ-disabled']
        for line in normal:self.assertFalse(danger(line),line)
        abnormal=['I (1) SD_FAILURE write=1 flush=0', 'I (1) STORAGE_PRESSURE drops=1',
                  'I (1) SOIL error=0/1/0', 'I (1) I2C errors=0 lock_timeout=1',
                  'I (1) I2C_LOCK_OWNERSHIP local_timeouts=1', 'I (1) CAPTURE queue_drop=1',
                  'W (1) IMU_IRQ_ARM init_ok=0 result=ESP_ERR_INVALID_STATE']
        for line in abnormal:self.assertTrue(danger(line),line)
        for line in ['W (1) IMU_IRQ_FALLBACK site=TOP init_ok=1','I (1) SD_LONG_EVENT wall_us=170685']:
            self.assertEqual(classify(line).severity,'WARNING')
            self.assertTrue(important(line))

    def test_real_replay_preserves_failed_result_and_all_raw_bytes(self):
        engine=self.engine();sent=[]
        for event in self.events:
            engine.clock.sample=lambda value=event['host_observed']:value
            if event['kind']=='RX_CHUNK':
                offset=event['raw_offset'];data=self.raw[offset:offset+event['bytes']]
                engine.receive(data,event['host_observed'])
            elif event['kind']=='TX_REQUEST':
                engine.send(event['ascii'].strip(),lambda data:sent.append(data) or len(data))
            elif event['kind']=='SERIAL_DISCONNECTED':
                engine.disconnected(OSError(event['error']))
            while not engine.messages.empty():engine.messages.get_nowait()
        engine.close()
        self.assertEqual(engine.state,'DISCONNECTED')
        self.assertEqual(engine.snapshot()['experiment_result'],'FAILED')
        self.assertEqual(engine.current['terminal_event'],'EXPERIMENT_FINALIZE_FAILED')
        self.assertEqual(engine.current['begin_observation']['iso8601'],'2026-10-31T10:37:49.850417+08:00')
        self.assertEqual(sent,[b'EXP HELP\r\n',b'EXP STATUS\r\n',b'EXP START 30\r\n',b'EXP STOP\r\n'])
        self.assertEqual(engine.parse_issues,[])
        self.assertEqual(engine.display_overflow,0)
        self.assertEqual((engine.journal.directory/'serial.bin').read_bytes(),self.raw)
        self.assertEqual((engine.journal.directory/'device.txt').read_bytes(),(SOURCE/'device.txt').read_bytes())
        for name,identity in engine.file_hashes.items():
            data=(engine.journal.directory/name).read_bytes()
            self.assertEqual(identity,{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        self.assertFalse(engine.current['device_finalized'])
        sd=Path(self.temp.name)/'TEST_ONLY_EMPTY_SD';sd.mkdir()
        plan=inspect(sd,engine.journal.directory)
        self.assertEqual(plan['status'],'INCOMPLETE')
        evidence=os.environ.get('NODE01_PC_TEST_EVIDENCE_DIR')
        if evidence:
            import shutil
            destination=Path(evidence)/'TEST_ONLY_REAL_LOG_REPLAY'
            shutil.copytree(engine.journal.directory,destination)
            (destination/'README_TEST_ONLY.txt').write_text('READ-ONLY replay of real failed source, not a new hardware run. All new events are TEST_ONLY. Original source files untouched.\n',encoding='utf-8')

    def test_source_evidence_unchanged(self):
        for name,digest in self.source_hashes.items():
            self.assertEqual(hashlib.sha256((SOURCE/name).read_bytes()).hexdigest(),digest)

    def test_threaded_snapshots_and_queue_are_bounded(self):
        engine=self.engine(); errors=[]
        def snapshots():
            try:
                for _ in range(500):
                    value=engine.snapshot()
                    self.assertIn(value['firmware_identity'],['NOT_OBSERVED','MATCH','MISMATCH','UNKNOWN'])
            except Exception as error:errors.append(error)
        thread=threading.Thread(target=snapshots);thread.start()
        raw=b'I (1) node_runtime: SD_FAILURE write=0 flush=0 verify=0\r\n'*1000
        for i in range(0,len(raw),4096):engine.receive(raw[i:i+4096])
        thread.join(5)
        self.assertFalse(thread.is_alive());self.assertFalse(errors)
        self.assertEqual(engine.journal.offset,len(raw))
        self.assertLessEqual(engine.messages.qsize(),256)
        self.assertEqual(engine.errors, __import__('collections').deque(maxlen=8))

    def test_failed_banner_after_disconnect_not_unknown(self):
        engine=self.engine();self.begin(engine);self.rx(engine,self.event_line('EXPERIMENT_FINALIZE_FAILED'))
        engine.disconnected(OSError('TEST_ONLY disconnection'))
        # No real terminal/COM: same UI methods via an uninitialized shell object.
        ui=object.__new__(ConsoleUI);ui.engine=engine
        text=''.join(x[1] for x in ui.header()+ui.footer())
        self.assertIn('FAILED',text);self.assertIn('DISCONNECTED',text)
        self.assertIn('sensors_clean=0',text)
        self.assertNotIn('UNKNOWN_OR_MISMATCH',text)
        from prompt_toolkit.document import Document
        lexer=MessageLexer()
        self.assertIn('ansiyellow',lexer.lex_document(Document('[ESP告警] IRQ fallback'))(0)[0][0])
        self.assertIn('ansired',lexer.lex_document(Document('[ESP错误] SOIL_READ'))(0)[0][0])


if __name__=='__main__':unittest.main()
