"""PC display semantics, not a device protocol/schema extension.

Only the first event token after an ESP-IDF level/timestamp/tag is an event.
Words in explanatory prose never create another event or a terminal state.
"""
from dataclasses import dataclass
import re

PREFIX = re.compile(r'^(?P<level>[EWIDV])\s*\(\d+\)\s*(?:[\w.-]+:\s*)?')
TOKEN = re.compile(r'(?P<event>[A-Za-z_][A-Za-z_0-9]*)\b(?P<body>.*)$')
FIELD = re.compile(r'\b([A-Za-z_]\w*)=([^\s;]+)')
NUMBER = re.compile(r'-?\d+(?:/-?\d+)*\Z')


@dataclass(frozen=True)
class LogMessage:
    level: str
    event: str
    body: str
    fields: dict


def parse_log(line):
    prefix = PREFIX.match(line)
    payload = line[prefix.end():] if prefix else line
    token = TOKEN.fullmatch(payload)
    body = token['body'] if token else payload
    return LogMessage(prefix['level'] if prefix else '', token['event'] if token else '',
                      body, dict(FIELD.findall(body)))


@dataclass(frozen=True)
class Classification:
    severity: str
    event: str
    reason: str


FAILURE_EVENTS = {
    'SOIL_READ', 'I2C_LOCK_TIMEOUT', 'EXPERIMENT_FINALIZE_FAILED', 'EXPERIMENT_INIT_FAILED',
    'CAPTURE_FINALIZE_BLOCKED', 'CAPTURE_START_BLOCKED', 'EXPERIMENT_START_BLOCKED',
    'STORAGE_QUEUE_OVERFLOW', 'EXPERIMENT_ABORTED',
}
MILESTONES = {
    'EXPERIMENT_READY', 'EXPERIMENT_BEGIN', 'EXPERIMENT_STOP_REQUEST',
    'EXPERIMENT_FINALIZED', 'CAPTURE_BEGIN', 'CAPTURE_CSV_VERIFIED', 'CAPTURE_FINALIZED',
    'CAPTURE_PRODUCER_STOP', 'EXP_ACK', 'EXP_STATUS', 'EXP_HELP', 'STARTUP_EXPERIMENT',
    'IMU_TOP_INIT', 'IMU_TOE_INIT', 'ADS1115_INIT', 'SD_READBACK',
    'EXPERIMENT_METADATA_VERIFIED',
}
# Always abnormal counters; do not treat age, wait, duration, or arbitrary err
# fields from unrelated events as an error. Slashed values are channel counters.
COMMON_COUNTERS = {
    'queue_drop', 'queue_overflows', 'internal_drop', 'unavailable_drop',
    'index_exhausted', 'write_failure', 'flush_failure', 'verify_failure', 'crc_errors',
}
EVENT_COUNTERS = {
    'SD_FAILURE': {'write', 'flush', 'verify', 'open', 'recovery', 'unavailable_drop'},
    'STORAGE_PRESSURE': {'drops'}, 'SOIL': {'error'}, 'IMU_TOP': {'error'}, 'IMU_TOE': {'error'},
    'I2C': {'errors', 'lock_timeout'},
    'I2C_DEVICE': {'err', 'timeout', 'state'},
    'I2C_CAUSE': {'sdk_err', 'local_err', 'sdk_state', 'local_state', 'probe_error'},
    'I2C_LOCK_OWNERSHIP': {'local_timeouts', 'give_failures', 'metadata_errors'},
    'SD': {'errors', 'uncertain', 'replay'}, 'SD_PHASE': {'fail'},
    'CAPTURE': {'queue_drop', 'internal_drop'},
    'CAPTURE_CSV_VERIFIED': {'errors', 'uncertain', 'replay'},
}


def classify(line):
    msg = parse_log(line)
    def result(severity, reason):
        return Classification(severity, msg.event, reason)
    if msg.level == 'E':
        return result('ERROR', 'ESP_ERROR_LEVEL')
    if msg.event in FAILURE_EVENTS:
        return result('ERROR', 'FAILURE_EVENT')
    for key in COMMON_COUNTERS | EVENT_COUNTERS.get(msg.event, set()):
        value = msg.fields.get(key, '')
        if NUMBER.fullmatch(value) and any(int(n) != 0 for n in value.split('/')):
            return result('ERROR', 'NONZERO_COUNTER:' + key)
    if any(msg.fields.get(key, '').startswith('ESP_ERR_') for key in ['error', 'result', 'init_cause', 'bank_restore']):
        return result('ERROR', 'EXPLICIT_ERROR_RESULT')
    if msg.body.strip().split(' ', 1)[0].startswith('ESP_ERR_'):
        return result('ERROR', 'EXPLICIT_OPERATION_ERROR')
    if msg.event == 'IMU_IRQ_ARM':
        return result('MILESTONE' if msg.fields.get('result') == 'ESP_OK' and msg.fields.get('init_ok') == '1' else 'ERROR', 'IRQ_ARM_RESULT')
    if msg.event == 'EXP_REJECT' or (msg.event == 'EXP_ACK' and msg.fields.get('accepted') == '0'):
        return result('WARNING', 'COMMAND_REJECTED')
    if msg.event in MILESTONES or 'app_elf_sha256' in msg.fields:
        return result('MILESTONE', 'EXACT_EVENT')
    if msg.event == 'SD_IO_IN_FLIGHT' and msg.fields.get('op') == 'queue_wait':
        return result('DIAGNOSTIC', 'NORMAL_QUEUE_WAIT')
    if msg.event in ['SD_LONG_EVENT', 'IMU_IRQ_FALLBACK'] or msg.level == 'W':
        return result('WARNING', 'DEVICE_WARNING')
    return result('DIAGNOSTIC', 'NORMAL_INFORMATION')
