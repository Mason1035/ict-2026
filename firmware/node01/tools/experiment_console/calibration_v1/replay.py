"""Reconstruct strict device identity using consensus with the recorded raw RX."""
import json
from pathlib import Path

from ..core import Lines
from .common import require
from .identity import IdentityGate, LOG, is_boot_marker
from .qualification import AUTHORIZATION_SHA, START, STATUS, QualificationGate


def replay(session_path, experiment_id, profile):
    directory = Path(session_path).resolve().parent
    raw = (directory/'serial.bin').read_bytes()
    gate = IdentityGate(profile['expected_elf'])
    parser = Lines()
    pending = None
    offset = 0
    scope = None
    starts = 0
    last_ns = None
    status_request = None
    first_boot_seen = False
    pre_boot_encoding_damage = False
    pre_boot_event_seen = False
    with (directory/'events.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            event = json.loads(line)
            kind, sample = event['kind'], event['host_observed']
            now = sample['monotonic_ns']
            require(type(now) is int and (last_ns is None or now >= last_ns), '会话事件时序反转')
            last_ns = now
            if kind == 'CALIBRATION_PROFILE_V1':
                require(scope is None and offset == 0 and all(event[k] == profile[k] for k in
                        ('manifest_sha256','firmware_id')) and event['purpose'] in ('qualification','calibration'),
                        '会话未绑定明确受审版本')
                scope = event['purpose']
                if 'qualification_authorization_sha256' in event:
                    require(scope == 'qualification' and
                            event['qualification_authorization_sha256'] == AUTHORIZATION_SHA,
                            '资格会话授权绑定不符')
                    gate = QualificationGate(profile['expected_elf'])
            elif kind == 'RX_CHUNK':
                count = event['bytes']
                require(type(count) is int and count > 0 and event['raw_offset'] == offset
                        and offset + count <= len(raw), '原串口分块不完整')
                for status, decoded in parser.feed(raw[offset:offset+count]):
                    if isinstance(gate, QualificationGate):
                        if status == 'ENCODING_DAMAGE' and not first_boot_seen:
                            pre_boot_encoding_damage = True
                            gate.invalidate()
                            continue
                        match = LOG.fullmatch(decoded)
                        if match and is_boot_marker(match[2], match[3]):
                            first_boot_seen = True
                    require(status == 'LINE', '原串口解析损坏')
                    gate.receive(decoded, sample)
                offset += count
            elif kind == 'QUALIFICATION_PRE_BOOT_ENCODING_DAMAGE':
                require(isinstance(gate, QualificationGate) and first_boot_seen and
                        pre_boot_encoding_damage and not pre_boot_event_seen,
                        'RESET 前断行标记与原始字节不符')
                pre_boot_event_seen = True
            elif kind == 'TX_REQUEST' and isinstance(gate, QualificationGate) and event.get('ascii') == STATUS.decode('ascii'):
                gate.preflight(sample)
                require(status_request is None and not gate.status_sent and
                        bytes.fromhex(event['wire_hex']) == STATUS, '重复或损坏的资格 STATUS 请求')
                status_request = event['tx_id']
            elif kind == 'TX_SENT_LOCAL' and status_request is not None and event.get('tx_id') == status_request:
                require(event['bytes'] == len(STATUS), 'STATUS 串口写入不完整')
                gate.status_sent = True
                status_request = None
            elif kind == 'CALIBRATION_MANUAL_START_GATE':
                require(scope and pending is None and starts == 0, '存在未关联或重复的 START 门禁')
                evidence = gate.start(sample)
                require(all(event.get(k)==v for k,v in evidence.items()), 'START 门禁与原串口重放不一致')
                pending = 'WAIT_REQUEST'
            elif kind == 'TX_REQUEST' and event.get('ascii', '').startswith('EXP START'):
                if scope:
                    require(pending == 'WAIT_REQUEST' and event['ascii'] == START.decode('ascii')
                            and bytes.fromhex(event['wire_hex']) == START,
                            '缺少匹配门禁或不是人工 EXP START 30')
                    pending = event['tx_id']
            elif kind == 'TX_SENT_LOCAL' and pending and event.get('tx_id') == pending:
                require(event['bytes'] == len(START), 'START 串口写入不完整')
                pending = None
                starts += 1
                if isinstance(gate, QualificationGate):
                    gate.start_transmission_attempted = True
            elif kind == 'SERIAL_DISCONNECTED':
                gate.invalidate()
    require(offset == len(raw), '原串口存在未关联字节')
    evidence = gate.evidence()
    if isinstance(gate, QualificationGate):
        require(pre_boot_encoding_damage == pre_boot_event_seen and status_request is None,
                '资格原始证据缺少 RESET 断行或 STATUS 关联')
        require(gate.terminal_pass and not gate.failure and gate.accepted_begin == experiment_id,
                '资格原始证据未通过 START ACK、两路 ARM、BEGIN 或终态核验')
        evidence['qualification'] = gate.qualification_evidence()
    if evidence['actual_device_elf'] is None and scope is None:
        evidence['status'] = 'HISTORICAL_IDENTITY_NOT_OBSERVED'
    elif (scope and starts == 1 and pending is None and evidence['same_boot'] and evidence['identity_match']
          and evidence['start_id'] == evidence['begin_id'] == experiment_id):
        evidence['status'] = 'SAME_BOOT_IDENTITY_VERIFIED'
    else:
        evidence['status'] = 'CALIBRATION_START_BLOCKED'
    return evidence
