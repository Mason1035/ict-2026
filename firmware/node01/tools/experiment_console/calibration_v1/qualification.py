"""One-use qualification for the frozen N0000043 candidate."""

import hashlib
import json
import os
from pathlib import Path

from ..core import Engine, wire_command
from .common import require, unchanged
from .identity import IdentityGate, LOG, MAX_READY_AGE_NS, is_boot_marker
from .manifest_schema_adapter import CANDIDATE, require_start_approval


AUTHORIZATION = Path(
    r'C:\Users\LQY\Documents\Codex\ICT2026_INTEGRATION\QUALIFICATION_TESTS'
    r'\N0000043_STAGE_1_4_PREFLIGHT_20261118_195351_661\qualification-authorization.json'
)
AUTHORIZATION_SHA = 'f6b20cbfaf903ab8fecff8a86fd0b0edcd046bff04a184bb81aa398d2043895b'
START = b'EXP START 30\r\n'
STATUS = b'EXP STATUS\r\n'
STARTUP_PHASES = ('IMU_TOP', 'IMU_TOE', 'ADS', 'SD_MOUNT', 'SD_OPEN')
FINAL_FLAGS = ('csv_verified', 'metadata_verified', 'storage_clean', 'sensors_clean', 'within_stop_budget')
TERMINAL_ERROR_EVENTS = ('EXPERIMENT_INIT_FAILED', 'EXPERIMENT_FINALIZE_FAILED',
                         'CAPTURE_START_BLOCKED', 'CAPTURE_FINALIZE_BLOCKED')


class QualificationAuthorization:
    def __init__(self, profile, path):
        self.path = Path(path).resolve()
        require(self.path == AUTHORIZATION.resolve(), '资格授权必须使用原始固定路径')
        self.profile = profile
        self.claim_path = self.path.with_name('qualification-start-consumed.v1.json')
        self.check()

    def check(self):
        raw = self.path.read_bytes()
        require(hashlib.sha256(raw).hexdigest() == AUTHORIZATION_SHA, '原资格授权 SHA-256 不匹配')
        approval = json.loads(raw)
        require(self.profile['firmware_id'] == CANDIDATE and
                self.profile['approval_status'] == 'CANDIDATE_REVIEW_ONLY' and
                approval['schema'] == 'NODE01_SINGLE_QUALIFICATION_AUTHORIZATION_V1' and
                approval['purpose'] == 'qualification' and approval['max_experiments'] == 1 and
                approval['duration_s'] == 30 and approval['auto_start'] is False and
                approval['consumed'] is False and approval['start_attempts'] == 0,
                '资格授权的候选、用途或额度不符')
        for name in ('firmware_id', 'bin_sha256', 'elf_sha256', 'manifest_sha256',
                     'bootloader_sha256', 'partition_table_sha256'):
            require(approval[name] == self.profile[name], f'资格授权身份不符：{name}')
        require_start_approval(dict(self.profile, approval_status=approval['approval_status'],
                                    approval_record=approval), 'qualification')
        require(not self.claim_path.exists(), '一次性资格额度已领取，不可重试')

    def claim(self, session, gate):
        # File presence consumes the authorization, including empty or damaged receipts.
        # Exclusive creation, fixed path, flush and fsync all precede the only UART write.
        receipt = {'authorization_sha256': AUTHORIZATION_SHA, 'session_directory': str(session.resolve()),
                   'command': 'EXP START 30', 'ready_id': gate.ready_id, 'boot_generation': gate.generation,
                   'consumed': True}
        try:
            with self.claim_path.open('x', encoding='utf-8') as stream:
                json.dump(receipt, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as error:
            raise ValueError('一次性资格额度已领取，不可重试') from error


class QualificationGate(IdentityGate):
    def __init__(self, expected_elf):
        self.start_transmission_attempted = False
        super().__init__(expected_elf)

    def invalidate(self):
        super().invalidate()
        self.phases = set()
        self.initialized = set()
        self.queue_ready = False
        self.status_sent = False
        self.status_endpoint = None
        self.ack = False
        self.arms = {}
        self.accepted_begin = None
        self.terminal_pass = False
        self.terminal_seen = False
        self.failure = 'START后启动关联中断' if self.start_transmission_attempted else None

    def reject(self, reason):
        if not self.failure:
            self.failure = reason

    def preflight(self, sample):
        age = None if self.ready_ns is None else sample['monotonic_ns'] - self.ready_ns
        require(not self.failure and not self.poisoned and self.actual_elf == self.expected_elf and
                self.ready_id and not self.start_id and age is not None and 0 <= age <= MAX_READY_AGE_NS,
                '资格启动阻断：缺少有效同 boot ELF MATCH / READY，或启动已失败')
        require(self.initialized == {'TOP', 'TOE', 'ADS'} and self.queue_ready and
                self.phases == set(STARTUP_PHASES), '资格启动阻断：缺少双 IMU、ADS、SD 或队列初始化证据')

    def start(self, sample):
        self.preflight(sample)
        require(self.status_endpoint is not None, '资格启动阻断：缺少本次 EXP STATUS 的 READY 回复')
        return super().start(sample)

    def receive(self, line, sample):
        super().receive(line, sample)
        match = LOG.fullmatch(line)
        if self.boot_ms is None or not match or match[2] != 'node_runtime':
            return
        tokens = match[3].split(';', 1)[0].split()
        if not tokens:
            return
        event = tokens[0]
        pairs = [word.split('=', 1) for word in tokens[1:] if '=' in word]
        fields = dict(pairs)
        if event in ('EXP_STATUS', 'EXP_ACK', 'IMU_IRQ_ARM', 'EXPERIMENT_BEGIN', 'EXPERIMENT_FINALIZED'):
            if len(fields) != len(pairs):
                self.reject('资格关键事件存在重复字段：' + event)
                return
        if event in TERMINAL_ERROR_EVENTS:
            self.terminal_seen = True
            self.reject(match[3])
        elif event in ('IMU_TOP_INIT', 'IMU_TOE_INIT', 'ADS1115_INIT'):
            site = {'IMU_TOP_INIT': 'TOP', 'IMU_TOE_INIT': 'TOE', 'ADS1115_INIT': 'ADS'}[event]
            address = {'TOP': '0x68', 'TOE': '0x69'}
            if tokens[1:2] == ['ESP_OK'] and (site == 'ADS' or fields.get('addr') == address[site]):
                self.initialized.add(site)
            else:
                self.reject(match[3])
        elif event == 'STARTUP_PHASE' and fields.get('name') in STARTUP_PHASES:
            name = fields['name']
            first_begin = fields.get('first_begin_us', '')
            first_end = fields.get('first_end_us', '')
            if (fields.get('result') == '0' and first_begin.isdecimal() and first_end.isdecimal()
                    and 0 < int(first_begin) <= int(first_end)):
                self.phases.add(name)
            else:
                self.reject(match[3])
        elif event == 'STORAGE_QUEUE_ALLOC':
            rows = fields.get('rows', '')
            self.queue_ready = fields.get('allocated') == '1' and rows.isdecimal() and int(rows) > 0
            if not self.queue_ready:
                self.reject(match[3])
        elif event == 'EXP_STATUS' and self.status_sent and not self.start_transmission_attempted:
            endpoint = fields.get('endpoint')
            if (self.status_endpoint is None and endpoint in ('0', '1') and fields.get('state') == 'READY'
                    and fields.get('start_us') == fields.get('stop_us') == fields.get('q') == '0'):
                self.status_endpoint = endpoint
            else:
                self.reject('EXP STATUS 未确认空队列 READY 或出现重复回复')
        elif event == 'EXP_ACK' and fields.get('command') == 'START':
            if (self.start_transmission_attempted and not self.ack and fields.get('accepted') == '1'
                    and fields.get('seconds') == '30' and fields.get('state') == 'START_PENDING'
                    and fields.get('endpoint') == self.status_endpoint):
                self.ack = True
            else:
                self.reject('START ACK 无法与唯一资格请求关联：' + match[3])
        elif event == 'IMU_IRQ_ARM':
            site = fields.get('site')
            if not self.ack or self.accepted_begin or site not in ('TOP', 'TOE') or site in self.arms:
                self.reject('DRDY ARM 时序或设备不符：' + match[3])
            else:
                self.arms[site] = (fields.get('init_ok') == '1' and fields.get('result') == 'ESP_OK'
                                   and fields.get('startup_status_seen') == '1')
                if not self.arms[site]:
                    self.reject(match[3])
        elif event == 'EXPERIMENT_BEGIN':
            if (self.failure or not self.ack or self.poisoned or self.arms != {'TOP': True, 'TOE': True}
                    or not self.begin_id or fields.get('requested_seconds') != '30'):
                self.reject('BEGIN 缺少同 boot 唯一 START ACK 或两路成功 ARM')
            else:
                self.accepted_begin = self.begin_id
        elif event == 'EXPERIMENT_FINALIZED':
            self.terminal_seen = True
            duration = fields.get('actual_duration_us', '')
            self.terminal_pass = bool(not self.failure and not self.poisoned and self.finalized and
                                      self.accepted_begin and fields.get('reason') == 'TIME_LIMIT' and
                                      fields.get('requested_s') == '30' and duration.isdecimal() and
                                      int(duration) >= 30_000_000 and
                                      all(fields.get(key) == '1' for key in FINAL_FLAGS))
            if not self.terminal_pass:
                self.reject('最终状态未满足 30 秒 TIME_LIMIT 及全项验证：' + match[3])

    def qualification_evidence(self):
        return {'failure': self.failure, 'startup_phases': sorted(self.phases),
                'initialized': sorted(self.initialized), 'queue_ready': self.queue_ready,
                'status_sent': self.status_sent, 'status_endpoint': self.status_endpoint,
                'start_attempted': self.start_transmission_attempted, 'start_ack': self.ack,
                'irq_arm': dict(self.arms), 'experiment_id': self.accepted_begin,
                'terminal_seen': self.terminal_seen, 'terminal_pass': self.terminal_pass and not self.failure}


class QualificationEngine(Engine):
    def __init__(self, journal, clock, profile, authorization):
        self.authorization = authorization
        self.first_boot_seen = False
        self.pre_boot_parse_issues = []
        super().__init__(journal, clock, profile['expected_elf'],
                         identity_gate=QualificationGate(profile['expected_elf']), start_guard=self.check_inputs)

    def check_inputs(self):
        unchanged(self.authorization.profile['inputs'])
        self.authorization.check()

    def snapshot(self):
        with self.lock:
            return dict(super().snapshot(), qualification=self.identity_gate.qualification_evidence(),
                        qualification_pre_boot_parse_issues=list(self.pre_boot_parse_issues))

    def _line(self, line, sample):
        before = self.identity_gate.qualification_evidence()
        match = LOG.fullmatch(line)
        first_boot = not self.first_boot_seen and match is not None and is_boot_marker(match[2], match[3])
        if first_boot:
            self.first_boot_seen = True
            if 'ENCODING_DAMAGE' in self.parse_issues:
                self.pre_boot_parse_issues.append('ENCODING_DAMAGE')
                self.parse_issues.remove('ENCODING_DAMAGE')
                self.journal.event('QUALIFICATION_PRE_BOOT_ENCODING_DAMAGE', sample)
        super()._line(line, sample)
        if first_boot or before != self.identity_gate.qualification_evidence() or (
                'EXPERIMENT_READY ' in line or ' DIAG_V6 ' in line):
            self._save()

    def send(self, text, writer):
        with self.lock:
            data = wire_command(text)
            gate = self.identity_gate
            if data == STATUS:
                gate.preflight(self.clock.sample())
                require(not gate.status_sent, '资格流程只允许一次 EXP STATUS')
            else:
                require(data == START, '资格流程只允许 EXP STATUS 和 EXP START 30')
                require(not gate.start_transmission_attempted, '拒绝重复 START')

            def write(payload):
                self.journal.sync(True)
                if payload == START:
                    self.authorization.claim(self.journal.directory, gate)
                    gate.start_transmission_attempted = True
                else:
                    gate.status_sent = True
                return writer(payload)

            try:
                return super().send(text, write)
            finally:
                self._save()


def verify_sensor_counts(rows):
    from collections import Counter
    valid = Counter((row['kind'], row['channel']) for row in rows if row['validity'] == 'Valid')
    require(all(valid['imu', site] > 0 for site in range(2)), '缺少双 IMU 的实际有效样本')
    require(all(valid['soil', channel] == 60 for channel in range(3)), '三路 Soil 未全部达到各 60 个有效转换')
    require(not any(row['validity'] == 'Error' for row in rows), '采集存在实际传感器 Error 行')
    return valid
