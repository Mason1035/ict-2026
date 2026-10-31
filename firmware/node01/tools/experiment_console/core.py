import codecs
from collections import deque
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import threading
import time
import uuid

from .clock import ClockGuard
from .messages import classify, parse_log

ANSI = re.compile(r'\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07\x1b]*(?:\x07|\x1b\\))')
STATES = {'INITIALIZING': 'INITIALIZING', 'READY': 'READY', 'START_PENDING': 'START_PENDING',
          'STOPPING_PRODUCERS': 'FINALIZING', 'DRAINING_CLOSING_VERIFYING': 'FINALIZING',
          'FINALIZE_FAILED': 'FAILED'}


def clean_line(text):
    return ''.join(c if c.isprintable() or c == '\t' else f'\\x{ord(c):02x}' for c in ANSI.sub('', text))


def danger(line):
    return classify(line).severity == 'ERROR'


def important(line):
    return classify(line).severity != 'DIAGNOSTIC'


def wire_command(text):
    # Reject arbitrary text/passwords, multiline paste and invented protocols.
    if '\n' in text or '\r' in text or len(text) > 47 or not text.isascii():
        raise ValueError('仅允许单行ASCII，最长47字节；请用EXP HELP')
    tokens = text.split()
    if tokens in [['EXP', 'HELP'], ['EXP', 'STATUS'], ['EXP', 'STOP'], ['EXP', 'START']]:
        return (' '.join(tokens) + '\r\n').encode('ascii')
    if len(tokens) == 3 and tokens[:2] == ['EXP', 'START'] and re.fullmatch(r'\d{1,3}', tokens[2]) and 30 <= int(tokens[2]) <= 300:
        return f'EXP START {int(tokens[2])}\r\n'.encode('ascii')
    raise ValueError('不支持此设备命令；本地命令以冒号开头，设备命令用EXP HELP')


class Lines:
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.buffer = []
        self.discard = False

    def feed(self, data):
        events = []
        for ch in self.decoder.decode(data):
            if ch in '\r\n':
                if self.buffer and not self.discard:
                    text = ''.join(self.buffer)
                    events.append(('ENCODING_DAMAGE', '') if '\ufffd' in text else ('LINE', clean_line(text)))
                self.buffer.clear()
                self.discard = False
            elif not self.discard:
                self.buffer.append(ch)
                if len(self.buffer) > 8192:
                    self.buffer.clear()
                    self.discard = True
                    events.append(('LINE_TOO_LONG', ''))
        return events

    def finish(self):
        tail = self.decoder.decode(b'', final=True)
        return bool(self.buffer or self.discard or tail)


class Journal:
    """RX bytes only in serial.bin; PC messages are confined to events.jsonl."""
    def __init__(self, root, clock, port, baud, test_only=False):
        self.directory = Path(root) / ('console-session-' + datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:12])
        self.directory.mkdir(parents=True, exist_ok=False)
        opened = []
        try:
            self.raw = open(self.directory / 'serial.bin', 'xb', buffering=0)
            opened.append(self.raw)
            self.text = open(self.directory / 'device.txt', 'x', encoding='utf-8', newline='')
            opened.append(self.text)
            self.events = open(self.directory / 'events.jsonl', 'x', encoding='utf-8', newline='\n')
            opened.append(self.events)
        except Exception:
            for stream in opened:
                stream.close()
            raise
        self.decoder = codecs.getincrementaldecoder('utf-8')('backslashreplace')
        self.offset = 0
        self.port, self.baud, self.test_only = port, baud, test_only
        self.last_sync = time.monotonic()
        self.failed = None
        self.event('SESSION_OPEN', clock.sample(), port=port, baud=baud, test_only=test_only,
                   reset_commands='NONE', time_source='HOST_OBSERVED_EXPERIMENT_BEGIN_ONLY')

    def event(self, kind, sample, **fields):
        self.events.write(json.dumps({'kind': kind, 'host_observed': sample, **fields}, ensure_ascii=False) + '\n')
        self.events.flush()

    def receive(self, data, sample):
        start = self.offset
        n = self.raw.write(data)
        self.offset += n
        if n != len(data):
            raise OSError(f'原始字节写盘不完整 accepted={n} expected={len(data)}')
        self.text.write(self.decoder.decode(data))
        self.text.flush()
        self.event('RX_CHUNK', sample, raw_offset=start, bytes=n)
        self.sync(False)

    def sync(self, force=False):
        if force or time.monotonic() - self.last_sync >= 1:
            for file in [self.raw, self.text, self.events]:
                file.flush()
                os.fsync(file.fileno())
            self.last_sync = time.monotonic()

    def summary(self, value):
        temp = self.directory / 'session.next.json'
        with open(temp, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, self.directory / 'session.json')

    def close(self):
        errors = []
        try:
            self.text.write(self.decoder.decode(b'', final=True))
            self.sync(True)
        except Exception as error:
            errors.append(repr(error))
        for file in [self.raw, self.text, self.events]:
            try:
                file.close()
            except Exception as error:
                errors.append(repr(error))
        return errors


class Engine:
    def __init__(self, journal, clock, expected_elf=None):
        self.journal, self.clock, self.expected_elf = journal, clock, expected_elf
        self.lock = threading.RLock()
        self.lines, self.guard = Lines(), ClockGuard()
        self.state = 'UNKNOWN'
        self.connection_status = 'UNKNOWN'
        self.device_state_before_disconnect = 'UNKNOWN'
        self.last_terminal = None
        self.verbose = False
        self.pending = None
        self.actual_elf = None
        self.experiments = []
        self.current = None
        self.begin_deadline_ns = None
        self.errors = deque(maxlen=8)
        self.messages = queue.Queue(maxsize=256)
        self.suppressed = 0
        self.display_overflow = 0
        self.parse_issues = []
        self.fatal = None
        self.closed = False
        self.capture_complete = True
        self.boot_await_startup = False
        self.startup_seen = False
        self.ready_id = None
        self.file_hashes = {}
        self._save()

    def _save(self):
        self.journal.summary(self.snapshot())

    def snapshot(self):
        with self.lock:
            return {'format': 'NODE01_PC_SESSION_V1', 'closed': self.closed,
                    'capture_complete': self.capture_complete and not self.fatal,
                    'test_only': self.journal.test_only, 'port': self.journal.port, 'baud': self.journal.baud,
                    'state': self.state, 'connection_status': self.connection_status,
                    'device_progress_state': self.device_state_before_disconnect if self.state == 'DISCONNECTED' else self.state,
                    'last_device_terminal': self.last_terminal,
                    'experiment_result': self.current.get('result', 'UNKNOWN') if self.current else 'UNKNOWN',
                    'actual_device_elf': self.actual_elf, 'expected_elf': self.expected_elf,
                    'firmware_identity': ('NOT_OBSERVED' if not self.actual_elf else
                                          'UNKNOWN' if not self.expected_elf else
                                          'MATCH' if self.actual_elf == self.expected_elf else 'MISMATCH'),
                    'host_files': 'HOST_FILES_NOT_VERIFIED', 'clock_confirmed': self.clock.confirmed,
                    'begin_confirmation_pending': self.begin_deadline_ns is not None,
                    'recent_warnings': list(self.errors),
                    'clock_issues': list(self.guard.issues), 'parse_issues': list(self.parse_issues),
                    'experiments': self.experiments, 'pending': self.pending,
                    'raw_file': 'serial.bin', 'readable_device_log': 'device.txt', 'event_file': 'events.jsonl',
                    'raw_bytes': self.journal.offset, 'display_suppressed': self.suppressed,
                    'evidence_files': self.file_hashes,
                    'display_overflow': self.display_overflow, 'fatal': self.fatal,
                    'calibration': 'UNCALIBRATED', 'integration': 'INTEGRATION_NOT_READY',
                    'time_accuracy': 'Host observation only; NOT synchronized device UTC or subsecond accuracy guarantee'}

    def message(self, text, critical=False, origin='ESP回复', severity=None):
        item = {'text': text[:1200], 'critical': critical, 'origin': origin,
                'severity': severity or ('ERROR' if critical else 'INFO')}
        try:
            self.messages.put_nowait(item)
        except queue.Full:
            if critical:
                self.display_overflow += 1
                self.errors.append('屏幕错误队列过载；完整RX仍在日志，暂停发送，请退出后查原始证据。' + text[:200])
            else:
                self.suppressed += 1

    def _fault(self, error):
        self.fatal = repr(error)
        self.capture_complete = False
        self.errors.append('证据保存/读取失败：' + self.fatal)
        self.message('证据不完整；禁止继续发送。关闭工具不会STOP设备。' + self.fatal, True, '本机错误')

    def _observe_clock(self, sample):
        for reason in self.guard.observe(sample):
            self.journal.event('TIME_INTEGRITY_WARNING', sample, reason=reason)
            self.errors.append(reason + '：日期命名锚标为UNKNOWN_TIME')
            self.message(reason + '，保留原时间观测，不生成可信日期名', True, '时间警告')

    def receive(self, data, sample=None):
        with self.lock:
            if self.closed or self.fatal:
                return
            try:
                sample = sample or self.clock.sample()
                self.journal.receive(data, sample)  # Never parse/display before preserving RX bytes.
                self.connection_status = 'CONNECTED'
                self._observe_clock(sample)
                for kind, line in self.lines.feed(data):
                    if kind != 'LINE':
                        if kind not in self.parse_issues:
                            self.parse_issues.append(kind)
                        self.state = 'UNKNOWN'
                        self.journal.event('RX_PARSE_LIMIT', sample, reason=kind)
                        self.message(kind + '：raw字节仍保存，协议状态/时间需人工查证', True, '本机警告')
                    else:
                        self.journal.event('RX_LINE', sample, line=line)
                        self._line(line, sample)
                        category = classify(line)
                        if category.severity == 'ERROR':
                            self.errors.append(line[:512])
                        if self.verbose or category.severity != 'DIAGNOSTIC':
                            self.message(line, category.severity == 'ERROR', severity=category.severity)
                        else:
                            self.suppressed += 1
            except Exception as error:
                self._fault(error)

    def _new_boot(self, sample):
        if self.current and not self.current.get('device_finalized') and not self.current.get('terminal_event'):
            self.current['interrupted'] = True
        self.current = None
        self.pending = None
        self.begin_deadline_ns = None
        self.actual_elf = None
        self.ready_id = None
        self.state = 'INITIALIZING'
        self.journal.event('DEVICE_BOOT_OBSERVED', sample)
        self.message('设备启动/重启：旧请求不再关联，未完成实验保留为INCOMPLETE', True, '设备状态')

    def _line(self, line, sample):
        msg = parse_log(line)
        if re.search(r'\bboot: ESP-IDF', line):
            self._new_boot(sample)
            self.boot_await_startup = True
            self.startup_seen = False
        elif msg.event == 'STARTUP_EXPERIMENT':
            if not self.boot_await_startup and (self.startup_seen or self.current or self.pending):
                self._new_boot(sample)
            elif not self.boot_await_startup:
                self.state = 'INITIALIZING'
            self.boot_await_startup = False
            self.startup_seen = True
        elf = re.search(r'\bapp_elf_sha256=([0-9a-fA-F]{64})\b', line)
        if elf:
            self.actual_elf = elf[1].lower()
            if self.expected_elf and self.actual_elf != self.expected_elf:
                self.errors.append('设备ELF与所选Manifest不一致')
                self.message('设备ELF身份不匹配，禁止START，请先确认固件版本', True, '设备身份')
        ready = re.search(r'\bEXPERIMENT_READY id=(\S+)', line) if msg.event == 'EXPERIMENT_READY' else None
        if ready:
            if self.current and self.current['experiment_id'] == ready[1]:
                self.journal.event('STALE_READY_IGNORED', sample, experiment_id=ready[1])
                return
            if self.ready_id and self.ready_id != ready[1]:
                self._new_boot(sample)
            if self.current and not self.current.get('device_finalized') and not self.current.get('terminal_event'):
                self.current['interrupted'] = True
                self.current = None
            self.state = 'READY'
            self.ready_id = ready[1]
        begin = re.search(r'\bEXPERIMENT_BEGIN id=(\S+) monotonic_us=(\d+) requested_seconds=(\d+)', line) if msg.event == 'EXPERIMENT_BEGIN' else None
        if begin:
            previous = next((item for item in self.experiments if item['experiment_id'] == begin[1]), None)
            if previous:
                if previous['device_monotonic_us'] != int(begin[2]):
                    previous['conflict'] = True
                    self.errors.append('相同实验ID出现不同BEGIN，拒绝时间归档')
                self.journal.event('DUPLICATE_OR_CONFLICT_BEGIN', sample, experiment_id=begin[1])
            else:
                if len(self.experiments) >= 16:
                    raise RuntimeError('单会话超过16场/重启，停止本机记录；请新开控制台，未自动STOP设备')
                if self.current and not self.current.get('device_finalized') and not self.current.get('terminal_event'):
                    self.current['interrupted'] = True
                previous = {'experiment_id': begin[1], 'device_monotonic_us': int(begin[2]),
                            'requested_seconds': int(begin[3]), 'begin_observation': sample,
                            'time_source': 'HOST_OBSERVED_EXPERIMENT_BEGIN',
                            'device_time_sync': 'NOT_SYNCHRONIZED', 'device_finalized': False,
                            'result': 'UNKNOWN',
                            'host_files': 'HOST_FILES_NOT_VERIFIED'}
                self.experiments.append(previous)
                self.journal.event('HOST_OBSERVED_EXPERIMENT_BEGIN', sample, experiment_id=begin[1], device_monotonic_us=int(begin[2]))
                self.message('BEGIN时间锚 ' + sample['iso8601'] + '；主机收到时刻，不是设备UTC精确开始', False, '时间锚')
            self.current = previous
            self.begin_deadline_ns = None
            if previous.get('conflict'):
                self.state = 'UNKNOWN'
            elif not previous.get('device_finalized'):
                self.state = 'RUNNING'
            self.journal.sync(True)
            self._save()
        if msg.event in ['EXPERIMENT_STOP_REQUEST', 'CAPTURE_CSV_VERIFIED'] and not (self.current and self.current.get('terminal_event')):
            self.state = 'FINALIZING'
        finalized = re.search(r'\bEXPERIMENT_FINALIZED id=(\S+)', line) if msg.event == 'EXPERIMENT_FINALIZED' else None
        if finalized:
            if not all(msg.fields.get(key) == '1' for key in ['csv_verified','metadata_verified','within_stop_budget','storage_clean','sensors_clean']):
                self.state = 'UNKNOWN'
                self.errors.append('最终消息缺少/矛盾的校验标记，未确认安全收尾')
                self.journal.event('INCONSISTENT_FINALIZATION_CLAIM', sample, line=line)
                if self.current:
                    self.current['failed'] = True
                self._save()
                return
            if self.current and self.current['experiment_id'] == finalized[1] and self._record_terminal(msg, sample, line, 'SUCCEEDED'):
                self.state = 'FINALIZED'
                self.message('DEVICE_FINALIZED / HOST_FILES_NOT_VERIFIED；一启动一场，下一场需手动RESET', False, '设备状态')
            else:
                self.state = 'UNKNOWN'
                self.errors.append('成功终态没有匹配的BEGIN或与既有终态冲突；不确认设备成功')
            self.journal.sync(True)
            self._save()
        if msg.event in ['EXPERIMENT_FINALIZE_FAILED', 'EXPERIMENT_INIT_FAILED', 'CAPTURE_FINALIZE_BLOCKED', 'CAPTURE_START_BLOCKED']:
            recorded = self._record_terminal(msg, sample, line, 'FAILED')
            self.state = 'FAILED' if recorded or (self.current and self.current.get('failed')) else 'UNKNOWN'
            self.begin_deadline_ns = None
            self.journal.sync(True)
            self._save()
        # Single pending command only. Protocol has no message ID: ACK correlation is heuristic.
        response = None
        if msg.event == 'EXP_STATUS':
            response = 'STATUS'
            match = re.search(r'\bstate=(\w+)', line)
            if match:
                reported = match[1]
                if reported == 'READY' and self.current:
                    self.state = 'UNKNOWN'
                    self.errors.append('STATUS回到READY但旧实验仍在记录；缺少新的启动/实验ID，禁止猜测重启')
                elif reported in STATES:
                    self.state = STATES[reported]
                elif reported == 'CAPTURING' and self.current and not self.current.get('device_finalized'):
                    self.state = 'RUNNING'
                elif reported in ['CAPTURING', 'FINALIZED'] and (not self.current or (reported == 'CAPTURING' and self.current.get('device_finalized'))):
                    self.state = 'UNKNOWN'
                    self.message('设备报告' + reported + '，本机缺BEGIN/完整终态证据；时间UNKNOWN_TIME', True, '设备状态')
        elif msg.event == 'EXP_HELP':
            response = 'HELP'
        else:
            ack = re.search(r'\bEXP_ACK .*?command=(START|STOP)\b', line) if msg.event == 'EXP_ACK' else None
            if ack:
                response = ack[1]
                if self.pending and self.pending['command'] == response:
                    reported = re.search(r'\bstate=(\w+)',line)
                    if reported and reported[1] == 'FINALIZED' and not (self.current and self.current.get('device_finalized')):
                        self.state = 'UNKNOWN'
                        self.errors.append('设备ACK报告已结束，但本机缺完整终态；不允许再次START')
                    elif reported and reported[1] in STATES:
                        if not (self.current and self.state in ['RUNNING','FINALIZING','FINALIZED']):
                            self.state = STATES[reported[1]]
                    if response == 'START' and re.search(r'\baccepted=1\b',line) and not self.current:
                        self.state = 'START_PENDING'
                        self.begin_deadline_ns = sample['monotonic_ns'] + 15000000000
                    if response == 'STOP' and re.search(r'\bfirst=1\b',line):
                        self.state = 'FINALIZING'
                    if response == 'STOP' and 'state=START_PENDING' in line:
                        self.message('STOP未取消START_PENDING；等待实际BEGIN后再发STOP', True, '设备状态')
        if response and self.pending and response == self.pending['command']:
            self.journal.event('DEVICE_RESPONSE_OBSERVED', sample, command=response, tx_id=self.pending['tx_id'], correlation='SINGLE_PENDING_NO_DEVICE_MESSAGE_ID')
            self.pending = None
        # Later STATUS/STOP acknowledgements cannot rewrite a recorded outcome.
        if self.current and self.current.get('terminal_event'):
            self.state = 'UNKNOWN' if self.current.get('result') == 'CONFLICT' else 'FAILED' if self.current.get('failed') else 'FINALIZED'

    def _record_terminal(self, msg, sample, line, result):
        identifier = msg.fields.get('id')
        if self.current and identifier and identifier != self.current['experiment_id']:
            self.errors.append('终态ID与当前BEGIN不一致，保留原文但不覆盖当前实验')
            self.journal.event('UNMATCHED_TERMINAL_OBSERVED', sample, line=line)
            return False
        if self.current and self.current.get('terminal_event'):
            if self.current.get('result') != result:
                self.current['conflict'] = True
                self.current['failed'] = True
                self.current['device_finalized'] = False
                if self.current.get('result') != 'FAILED':
                    self.current['result'] = 'CONFLICT'
                    self.last_terminal = {**self.last_terminal, 'result': 'CONFLICT'}
                self.errors.append('同一实验终态冲突；保留第一次终态原文，拒绝合格归档')
            self.journal.event('LATER_TERMINAL_OBSERVED', sample, line=line)
            return False
        validation = {key: msg.fields.get(key) for key in
                      ['csv_verified', 'metadata_verified', 'within_stop_budget', 'storage_clean', 'sensors_clean']}
        terminal = {'event': msg.event, 'experiment_id': identifier or (self.current['experiment_id'] if self.current else None),
                    'result': result, 'stop_reason': msg.fields.get('reason'), 'validation': validation,
                    'host_observed': sample, 'line': line}
        self.last_terminal = terminal
        if self.current:
            self.current.update(result=result, terminal_event=msg.event, terminal_observation=sample,
                                stop_reason=msg.fields.get('reason'), validation=validation,
                                device_terminal_line=line, device_finalized=result == 'SUCCEEDED', failed=result == 'FAILED')
            if result == 'SUCCEEDED':
                self.current['device_final_line'] = line  # Original archive-compatible field.
        self.journal.event('DEVICE_TERMINAL_OBSERVED', sample, terminal=terminal)
        return True

    def tick(self):
        with self.lock:
            if self.fatal or self.closed:
                return
            try:
                sample = self.clock.sample()
                self._observe_clock(sample)
                if self.pending and sample['monotonic_ns'] >= self.pending['deadline_ns']:
                    self.message(self.pending['command'] + '：设备尚未确认/超时；不自动重发，不宣称执行成功', True, '本机警告')
                    self.journal.event('ACK_TIMEOUT', sample, command=self.pending['command'], tx_id=self.pending['tx_id'])
                    self.pending = None
                    self._save()
                if self.begin_deadline_ns is not None and sample['monotonic_ns'] >= self.begin_deadline_ns:
                    self.message('START虽有ACK，但尚未观察到BEGIN；未确认开始，不自动重发/STOP', True, '本机警告')
                    self.journal.event('BEGIN_NOT_OBSERVED_TIMEOUT', sample)
                    self.begin_deadline_ns = None
                    self._save()
            except Exception as error:
                self._fault(error)

    def send(self, text, writer):
        with self.lock:
            if self.fatal or self.closed or self.state == 'DISCONNECTED' or self.display_overflow:
                raise RuntimeError('当前连接/证据状态不可发送；不会自动STOP/复位')
            data = wire_command(text)
            command = data.decode('ascii').split()[1]
            if self.pending:
                raise ValueError('上一条命令尚未确认；等待回复/超时后再决定，不自动排队START')
            if command == 'START' and self.state != 'READY':
                raise ValueError('仅在设备真实报告READY后允许START；先EXP STATUS')
            if command == 'START' and self.expected_elf and self.actual_elf and self.actual_elf != self.expected_elf:
                raise ValueError('已观察到固件身份不匹配，拒绝START')
            sample = self.clock.sample()
            self._observe_clock(sample)
            tx = uuid.uuid4().hex
            # Keep all RX/TX journal mutation serialized. A request is persisted before write.
            try:
                self.journal.event('TX_REQUEST', sample, tx_id=tx, ascii=data.decode('ascii'), wire_hex=data.hex())
                n = writer(data)
                if n != len(data):
                    raise OSError(f'串口部分写入 accepted={n} expected={len(data)}；不自动重发')
                self.pending = {'tx_id': tx, 'command': command, 'deadline_ns': sample['monotonic_ns'] + 5000000000}
                self.journal.event('TX_SENT_LOCAL', self.clock.sample(), tx_id=tx, bytes=n, execution='NOT_CONFIRMED_BY_DEVICE')
                self.message(data.decode().strip() + '（仅本机写入，等待设备回复）', False, 'PC发送')
            except Exception as error:
                self._fault(error)
                raise

    def disconnected(self, error):
        with self.lock:
            self.capture_complete = False
            if self.state != 'DISCONNECTED':
                self.device_state_before_disconnect = self.state
            self.connection_status = 'DISCONNECTED'
            self.state = 'DISCONNECTED'
            self.pending = None
            self.begin_deadline_ns = None
            self.errors.append('串口断开≠实验结束：' + repr(error))
            self.message('串口断开；未自动STOP/重连，保存现有证据后重新选择端口', True, '本机错误')
            try:
                self.journal.event('SERIAL_DISCONNECTED', self.clock.sample(), error=repr(error))
                self._save()
            except Exception as failure:
                self._fault(failure)

    def close(self):
        with self.lock:
            if self.closed:
                return
            try:
                if self.lines.finish():
                    self.parse_issues.append('PARTIAL_LINE_AT_CLOSE')
                self.journal.event('SESSION_CLOSE', self.clock.sample(), device_state=self.state,
                                   warning='Close is not EXP STOP; no automatic reset/stop')
            except Exception as error:
                self._fault(error)
            errors = self.journal.close()
            if errors:
                self._fault(OSError('; '.join(errors)))
            self.closed = True
            try:
                for name in ['serial.bin', 'device.txt', 'events.jsonl']:
                    path = self.journal.directory / name
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    self.file_hashes[name] = {'bytes': path.stat().st_size, 'sha256': digest}
                self._save()
            except Exception as error:
                self._fault(error)
