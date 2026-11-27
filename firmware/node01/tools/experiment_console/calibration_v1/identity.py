"""Fail-closed sequence check for the candidate, live and in offline replay."""
import re

from .common import require

LOG = re.compile(r'^[IWEVD]\s+\(\s*(\d+)\)\s+([^:]+):\s+(.*)$')
ROM = re.compile(r'^(?:ESP-ROM:|rst:0x|Rebooting|Guru Meditation)')
SHA = re.compile(r'^DIAG_V6 app_elf_sha256=([0-9a-f]{64});')
EXPERIMENT = re.compile(r'^NODE01-[0-9a-f]{16}-N\d{7}\.CSV$')
MAX_READY_AGE_NS = 120_000_000_000


def is_boot_marker(tag, body):
    return tag == 'boot' and body.startswith('ESP-IDF ') and '2nd stage bootloader' in body


class IdentityGate:
    def __init__(self, expected_elf):
        self.expected_elf = expected_elf
        self.generation = 0
        self.invalidate()

    def invalidate(self):
        self.generation += 1
        self.boot_ms = self.last_ms = self.ready_ns = None
        self.actual_elf = self.observation = self.ready_id = self.start_id = self.begin_id = None
        self.finalized = self.poisoned = self.startup_seen = False

    def receive(self, line, sample):
        if ROM.match(line):
            self.invalidate()
            return
        match = LOG.fullmatch(line)
        if not match:
            return
        ticks, tag, body = match.groups()
        tick = int(ticks)
        if is_boot_marker(tag, body):
            self.invalidate()
            self.boot_ms = self.last_ms = tick
            return
        # A gross uptime reversal is an ambiguous boot boundary. Small UART
        # interleaving across FreeRTOS tasks is not a fresh identity anchor.
        if self.last_ms is not None and tick + 1000 < self.last_ms:
            self.invalidate()
            return
        if self.boot_ms is None:
            return
        self.last_ms = max(tick, self.last_ms)
        marker = SHA.match(body) if tag == 'NODE-01' else None
        if marker:
            if self.actual_elf or self.ready_id or self.start_id:
                self.poisoned = True
            self.actual_elf = marker[1]
            self.observation = sample
        words = body.split()
        if tag != 'node_runtime' or not words:
            return
        event = words[0]
        pairs = [word.split('=', 1) for word in words[1:] if '=' in word]
        fields = dict(pairs)
        if event in ('EXPERIMENT_READY','EXPERIMENT_BEGIN','EXPERIMENT_FINALIZED') and len(fields) != len(pairs):
            self.poisoned = True
            return
        if event == 'STARTUP_EXPERIMENT':
            if self.startup_seen or self.ready_id or self.start_id:
                self.invalidate()
            self.startup_seen = True
            return
        if event == 'EXPERIMENT_READY':
            eid = fields.get('id', '')
            if (self.ready_id or self.start_id or self.actual_elf != self.expected_elf or not EXPERIMENT.fullmatch(eid)
                    or fields.get('csv') != '/sdcard/' + eid.rsplit('-',1)[-1]):
                self.poisoned = True
            else:
                self.ready_id, self.ready_ns = eid, sample['monotonic_ns']
        elif event == 'EXP_STATUS' and fields.get('state') != 'READY' and not self.start_id:
            self.poisoned = True
        elif event == 'EXPERIMENT_BEGIN':
            eid = fields.get('id')
            if self.poisoned or not self.start_id or self.begin_id or eid != self.start_id:
                self.poisoned = True
            else:
                self.begin_id = eid
        elif event == 'EXPERIMENT_FINALIZED':
            if not self.begin_id or self.finalized or fields.get('id') != self.begin_id:
                self.poisoned = True
            else:
                self.finalized = True
        elif event in ('EXPERIMENT_FINALIZE_FAILED','EXPERIMENT_INIT_FAILED','CAPTURE_START_BLOCKED','CAPTURE_FINALIZE_BLOCKED'):
            self.poisoned = True

    def start(self, sample):
        age = None if self.ready_ns is None else sample['monotonic_ns'] - self.ready_ns
        require(not self.poisoned and self.actual_elf == self.expected_elf and self.ready_id and not self.start_id
                and age is not None and 0 <= age <= MAX_READY_AGE_NS,
                'CALIBRATION_START_BLOCKED：缺少当前同 boot 完整 ELF MATCH、有效 READY 或已有 START')
        self.start_id = self.ready_id
        return self.evidence()

    def evidence(self):
        return {'boot_generation':self.generation, 'expected_elf':self.expected_elf,
                'actual_device_elf':self.actual_elf, 'ready_id':self.ready_id, 'start_id':self.start_id,
                'identity_observation_source':'UART_BOOT_APP_DESCRIPTOR' if self.observation else None,
                'identity_observation_time':self.observation, 'begin_id':self.begin_id,
                'identity_match':self.actual_elf == self.expected_elf if self.actual_elf else None,
                'same_boot':bool(self.finalized and self.begin_id and not self.poisoned)}
