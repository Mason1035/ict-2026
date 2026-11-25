"""只读独立三件套/UART/会话校验。失败证据不被丢弃。无串口模块。"""
import argparse
import codecs
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import re
import zlib
from .common import (Rejected, info, json_read, require, snapshot, unchanged, natural,
                    runtime_guard, new_output, write_json)
from .soil_run_schema import parse_csv

ANSI = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
PREFIX = re.compile(r'^[IWEVD]\s+\(\s*\d+\)\s+[^:\r\n]+:\s*(.*)$')


def event_lines(text, name):
    result = []
    for n, line in enumerate(text.splitlines()):
        line = ANSI.sub('', line)
        m = PREFIX.match(line)
        body = m[1] if m else line
        if body.split(' ', 1)[0] == name:
            fields = dict(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*)=([^\s;]+)', body))
            result.append((n, fields, body))
    return result


def check_journal(session_path, eid, end, elf, synthetic):
    path = Path(session_path).resolve()
    s = json_read(path)
    require(s.get('format') == 'NODE01_PC_SESSION_V1', '控制台会话schema不支持')
    require(s.get('closed') is True and s.get('capture_complete') is True and not s.get('fatal'), '会话未关闭、断线或保存不完整')
    require(s.get('test_only', False) is synthetic, '真实与SYNTHETIC会话不得混用')
    require(not s.get('clock_issues') and not [x for x in s.get('parse_issues', []) if x != 'PARTIAL_LINE_AT_CLOSE'], '会话时钟/解析证据异常')
    prefix = 'synthetic-' if synthetic else ''
    paths = {name: path.parent / (prefix + name) for name in ('serial.bin', 'device.txt', 'events.jsonl')}
    journal_before = snapshot([path] + list(paths.values()))
    for name, p in paths.items():
        require(info(p) == s.get('evidence_files', {}).get(p.name), '会话证据SHA/长度不符：' + p.name)
    require(paths['serial.bin'].stat().st_size <= 256 * 1024 * 1024, '串口日志超过256MiB')
    raw = paths['serial.bin'].read_bytes()
    text = raw.decode('utf-8', errors='backslashreplace')
    require(text.encode('utf-8') == paths['device.txt'].read_bytes(), 'device.txt不是原始串口的完整解码')
    exps = [e for e in s.get('experiments', []) if e.get('experiment_id') == eid]
    require(len(exps) == 1, '会话缺唯一完整experiment_id')
    exp = exps[0]
    require(exp.get('device_finalized') is True and not any(exp.get(k) for k in ('failed', 'interrupted', 'conflict')), '会话终态失败/重启/冲突')
    require(exp.get('device_monotonic_us') == end['start_us'] and exp.get('requested_seconds') == end['requested_seconds'], '会话BEGIN与END不一致')
    anchor = exp.get('begin_observation')
    require(anchor and s.get('clock_confirmed') is True and anchor.get('operator_clock_confirmed') is True, '缺少已确认主机BEGIN时间锚，不得完整归档')
    require(datetime.fromisoformat(anchor['iso8601']).tzinfo is not None and exp.get('time_source') == 'HOST_OBSERVED_EXPERIMENT_BEGIN', '时间锚来源或时区无效')
    events, covered = [], 0
    with paths['events.jsonl'].open(encoding='utf-8') as f:
        for line in f:
            require(len(line) <= 65536, '单个事件超过64KiB')
            event = json.loads(line)
            if event['kind'] == 'RX_CHUNK':
                require(event['raw_offset'] == covered and type(event['bytes']) is int and event['bytes'] > 0, 'RX分块有缺口/重复')
                covered += event['bytes']
            require(event['kind'] != 'SERIAL_DISCONNECTED', '实际串口断线证据')
            events.append(event)
    require(covered == len(raw), 'RX分块未覆盖全部原始字节')
    anchors = [e for e in events if e['kind'] == 'HOST_OBSERVED_EXPERIMENT_BEGIN' and e.get('experiment_id') == eid]
    require(len(anchors) == 1 and anchors[0]['host_observed'] == anchor and int(anchors[0]['device_monotonic_us']) == end['start_us'], 'BEGIN事件与会话摘要不符')
    anchor_index = events.index(anchors[0])
    require(not any(e['kind'] == 'DEVICE_BOOT_OBSERVED' for e in events[anchor_index + 1:]), 'BEGIN之后出现设备重启')
    unchanged(journal_before)
    return text, journal_before


def verify_run(spec, manifest, *, synthetic=False):
    runtime_guard()
    result = {'experiment_id': spec.get('experiment_id'), 'status': 'FAILED_OR_INCOMPLETE',
              'source': 'SYNTHETIC_TEST_ONLY' if synthetic else 'REAL_SENSOR', 'reasons': [],
              'requested_inputs': dict(spec),
              'rows': [], 'boundary_records': [], 'inputs': {}, 'hardware_acceptance': 'NOT_ASSESSED',
              'device_sd_readback': 'NOT_VERIFIED', 'host_byte_integrity': 'HOST_FILES_INCOMPLETE',
              'host_file_copy': 'NOT_ASSESSED', 'power_loss_safety': 'NOT_VERIFIED'}
    paths = [Path(spec[k]).resolve() for k in ('csv', 'begin', 'end', 'session') if k in spec]
    initial = {}
    try:
        require(manifest['status'] == 'MANIFEST_COMPATIBILITY_PASS', 'manifest启动语义NOT_VERIFIABLE')
        require(len(paths) == 4, '缺少CSV/BEG/END/会话路径')
        initial = snapshot(paths)
        csv_path, beg_path, end_path, session_path = paths
        journal_prefix='synthetic-' if synthetic else ''
        for name in ('serial.bin','device.txt','events.jsonl'):
            journal_file=session_path.parent/(journal_prefix+name)
            if journal_file.is_file():
                initial[str(journal_file)]=info(journal_file)
        require(csv_path.stem == beg_path.stem == end_path.stem and csv_path.suffix == '.CSV' and beg_path.suffix == '.BEG' and end_path.suffix == '.END', '三件套文件名不匹配')
        name_pattern = r'(?:synthetic-)?N\d{7}\.CSV' if synthetic else r'N\d{7}\.CSV'
        require(re.fullmatch(name_pattern, csv_path.name), '不是当前支持的原始CSV命名')
        b, e = json_read(beg_path), json_read(end_path)
        result['end'] = e
        require(b.get('record_type') == 'START_INTENT' and b.get('start_us') == 0 and e.get('record_type') == 'END', 'BEG不是START_INTENT或END缺失')
        for key in ('experiment_id', 'elf_sha256', 'mode', 'source', 'requested_seconds', 'csv', 'calibration_status'):
            require(b.get(key) == e[key], 'BEG/END字段不匹配：' + key)
        require(e['experiment_id'] == spec['experiment_id'] and e['experiment_id'].endswith('-' + csv_path.name), '完整ID/文件绑定不匹配')
        require(Path(e['csv']).name == csv_path.name and e['elf_sha256'] == manifest['expected_elf'], 'CSV路径或ELF身份错误')
        require(e['mode'] == 'SANDBOX_EXPERIMENT_CAPTURE' and e['calibration_status'] == 'NOT_READY', '模式或标定状态不符')
        require(e['source'] == ('TEST_ONLY_SYNTHETIC' if synthetic else 'REAL_SENSOR'), '数据来源错误，禁止混用')
        require(30 <= natural(e['requested_seconds'], 'requested_seconds') <= 300, '时长范围错误')
        for k in ('start_us', 'stop_us', 'actual_duration_us', 'last_producer_ack_us', 'produced', 'enqueued', 'dequeued', 'accepted', 'verified_rows', 'queue_drop', 'internal_drop', 'errors', 'uncertain', 'replay', 'i2c_errors', 'lock_timeouts', 'sensor_errors', 'top_valid', 'toe_valid', 'csv_bytes'):
            natural(e[k], k)
        require(0 < e['start_us'] < e['stop_us'] <= e['last_producer_ack_us'], '起止/最终生产者时间不合法')
        require(e['actual_duration_us'] == e['stop_us'] - e['start_us'], '实际时长不匹配')
        require(e['stop_reason'] in ('TIME_LIMIT', 'USER_STOP'), '异常停止原因')
        if e['stop_reason'] == 'TIME_LIMIT':
            require(e['actual_duration_us'] >= e['requested_seconds'] * 1000000, 'TIME_LIMIT实际时长不足')
        require(csv_path.stat().st_size <= 64 * 1024 * 1024, 'CSV超过64MiB')
        raw = csv_path.read_bytes()
        require(len(raw) == e['csv_bytes'] and f'{zlib.crc32(raw):08x}' == e['csv_crc32'], 'CSV字节数或CRC不匹配')
        rows, comments = parse_csv(raw)
        result['rows'] = rows
        required_source = 'source=TEST_ONLY_SYNTHETIC' if synthetic else 'source=REAL_SENSOR_EXPERIMENT_UNCALIBRATED'
        require(any(required_source in l for l in comments) and any('app_elf_sha256=' + e['elf_sha256'] in l for l in comments), 'CSV注释来源/ELF未绑定')
        require(len(rows) == e['verified_rows'], 'CSV行数与END不一致')
        require(e['produced'] == len(rows), 'produced与CSV行数不一致，不创建无界索引范围')
        indices = [r['index'] for r in rows]
        require(len(set(indices)) == len(indices), '全CSV重复index')
        require(set(indices) == set(range(e['produced'])), '全CSV索引缺行、范围或首尾计数不符')
        counts = Counter((r['kind'], r['channel']) for r in rows if r['validity'] == 'Valid')
        require(counts['imu', 0] == e['top_valid'] and counts['imu', 1] == e['toe_valid'], 'IMU有效计数不符')
        require(e['soil_valid'] == [counts['soil', c] for c in range(3)], 'Soil逐路有效计数不符')
        require(e['sensor_errors'] == sum(r['validity'] == 'Error' for r in rows), 'sensor_errors与实际Error行不符')
        require(all(r['attempted'] <= e['last_producer_ack_us'] and (r['acquired'] is None or r['acquired'] <= e['last_producer_ack_us']) for r in rows), '样本晚于最终生产者确认')
        result['boundary_records'] = [r for r in rows if not e['start_us'] <= r['attempted'] < e['stop_us'] or (r['acquired'] is not None and r['acquired'] >= e['stop_us'])]
        for kind, c in sorted(set((r['kind'], r['channel']) for r in rows)):
            group = [r for r in rows if r['kind'] == kind and r['channel'] == c]
            require(all(a['attempted'] < z['attempted'] for a, z in zip(group, group[1:])), '每通道attempted非单调')
            ts = [r['acquired'] for r in group if r['acquired'] is not None]
            require(all(a < z for a, z in zip(ts, ts[1:])), '每通道acquired非单调')
        text, journal_before = check_journal(session_path, spec['experiment_id'], e, e['elf_sha256'], synthetic)
        initial.update(journal_before)
        strict = manifest.get('firmware_id') == 'N0000043_CANDIDATE' and not synthetic
        if not strict:
            identity = re.findall(r'\bapp_elf_sha256=([0-9a-f]{64})\b', text)
            require(identity and set(identity) == {e['elf_sha256']}, '启动ELF缺失/不一致')
        def one(event):
            values = [x for x in event_lines(text, event) if x[1].get('id') == e['experiment_id']]
            require(len(values) == 1, '缺少唯一准确UART事件：' + event)
            return values[0]
        begin, final = one('EXPERIMENT_BEGIN'), one('EXPERIMENT_FINALIZED')
        require(begin[0] < final[0] and int(begin[1]['monotonic_us']) == e['start_us'] and int(begin[1]['requested_seconds']) == e['requested_seconds'], 'UART BEGIN值不符')
        require(not event_lines(text, 'EXPERIMENT_FINALIZE_FAILED'), 'UART存在失败终态，不能覆盖')
        require(not re.search(r'ESP-ROM:|rst:0x|Rebooting|Guru Meditation', '\n'.join(text.splitlines()[begin[0]+1:])), '采集中/采后出现重启或崩溃')
        require(all(final[1].get(k) == '1' for k in ('csv_verified', 'metadata_verified', 'within_stop_budget', 'storage_clean', 'sensors_clean')), '最终校验标志未全部通过')
        for key, value in [('reason', e['stop_reason']), ('actual_duration_us', str(e['actual_duration_us'])), ('last_producer_ack_us', str(e['last_producer_ack_us'])), ('requested_s', str(e['requested_seconds']))]:
            require(final[1].get(key) == value, 'UART最终结果与END不符：' + key)
        stop = event_lines(text, 'EXPERIMENT_STOP_REQUEST')
        require(len(stop) == 1 and stop[0][1].get('actual_us') == str(e['stop_us']) and stop[0][1].get('reason') == e['stop_reason'], 'UART STOP不匹配')
        metadata = [x for x in event_lines(text, 'EXPERIMENT_METADATA_VERIFIED') if x[1].get('stage') == 'START_INTENT' and Path(x[1].get('path', '')).name == beg_path.name]
        require(len(metadata) == 1, '缺少BEG元数据验证事件')
        for file, fields, prefix in ((beg_path, metadata[0][1], ''), (end_path, final[1], 'metadata_')):
            content = file.read_bytes()
            require(fields.get(prefix + 'bytes') == str(len(content)) and fields.get(prefix + 'crc32') == f'{zlib.crc32(content):08x}', 'BEG/END自身UART字节/CRC不匹配')
        require(all(e[k] == len(rows) for k in ('produced', 'enqueued', 'dequeued', 'accepted', 'verified_rows')), '全局产消计数不等')
        require(all(e[k] == 0 for k in ('queue_drop', 'internal_drop', 'errors', 'uncertain', 'replay', 'i2c_errors', 'lock_timeouts', 'sensor_errors')), '共享链路或整体错误非零')
        require(e['csv_verified'] is True and e['storage_clean'] is True and all(counts['soil', c] for c in range(3)) and counts['imu', 0] and counts['imu', 1], '缺少存储完成/有效传感器')
        if strict:
            require(any('mode=SANDBOX_EXPERIMENT_CAPTURE' in line for line in comments), 'CSV未明确实验模式')
            reads = [fields for line, fields, _ in event_lines(text, 'SD_READBACK')
                     if fields.get('path') == e['csv'] and line < final[0]]
            require(len(reads) == 1 and all(reads[0].get(key) == value for key,value in
                    (('rows',str(len(rows))), ('bytes',str(len(raw))), ('crc32',e['csv_crc32']),
                     ('checks','length,actual_rows,crc,eof'))), '缺少匹配的设备 SD 回读')
            result['device_sd_readback'] = 'DEVICE_SD_READBACK_VERIFIED'
            result['host_byte_integrity'] = 'HOST_FILES_BYTES_VERIFIED'
            from .replay import replay
            result['runtime_identity'] = replay(session_path,e['experiment_id'],manifest)
            require(result['runtime_identity']['status'] == 'SAME_BOOT_IDENTITY_VERIFIED',
                    result['runtime_identity']['status'])
            if 'qualification' in result['runtime_identity']:
                from .qualification import verify_sensor_counts
                verify_sensor_counts(rows)
        else:
            # Keep A's original acceptance rules and distinguish the source of evidence.
            result['device_sd_readback'] = 'DEVICE_SD_READBACK_VERIFIED' if any(
                fields.get('path') == e['csv'] and fields.get('crc32') == e['csv_crc32']
                for _,fields,_ in event_lines(text,'SD_READBACK')) else 'END_AND_TERMINAL_ONLY'
            result['host_byte_integrity'] = 'HOST_FILES_BYTES_VERIFIED'
        result['status'] = 'FILES_AND_UART_VERIFIED'
    except (ValueError, OSError, KeyError, TypeError, OverflowError) as exc:
        result['reasons'].append(str(exc))
    finally:
        try:
            unchanged(initial)
        except (ValueError, OSError) as exc:
            result['status'] = 'FAILED_OR_INCOMPLETE'
            result['host_byte_integrity'] = 'HOST_FILES_INCOMPLETE'
            result['device_sd_readback'] = 'NOT_VERIFIED'
            result['reasons'].append(str(exc))
        result['inputs'] = initial
    return result


def main():
    from .manifest_schema_adapter import verify_manifest
    p = argparse.ArgumentParser(description=__doc__)
    for key in ('manifest', 'csv', 'begin', 'end', 'session', 'experiment-id', 'output-root'):
        p.add_argument('--' + key, required=True)
    a = p.parse_args()
    out = new_output(a.output_root, 'single-run-verification')
    try:
        manifest = verify_manifest(a.manifest)
        result = verify_run({'experiment_id': a.experiment_id, 'csv': a.csv, 'begin': a.begin, 'end': a.end, 'session': a.session}, manifest)
    except (ValueError, OSError, KeyError) as exc:
        result = {'status': 'FAILED_OR_INCOMPLETE', 'reasons': [str(exc)]}
    result['host_status'] = 'HOST_FILES_VERIFIED' if result['status'] == 'FILES_AND_UART_VERIFIED' else 'HOST_FILES_INCOMPLETE'
    write_json(out / 'run_integrity_report.json', {k:v for k,v in result.items() if k != 'rows'})
    print(json.dumps({'output': str(out), 'status': result['status']}, ensure_ascii=False))
    return 0 if result['status'] == 'FILES_AND_UART_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
