"""Read-only preview; explicit --copy creates new PC copies, never renames SD files."""
import argparse
import codecs
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import uuid

from .console import REPOSITORY, default_manifest

DEFAULT_OUTPUT = REPOSITORY / 'docs/test_records/NODE-01/sandbox-experiment-archive'
VERIFIER = REPOSITORY / 'docs/test_records/NODE-01/round-15-sandbox-mode/05-manual-retest/Verify-Sandbox-Run.py'


def file_info(path):
    with path.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'bytes': path.stat().st_size, 'sha256': digest}


def read_json(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('JSON超过4MiB检查上限，拒绝无界载入')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def original_check(manifest, csv, begin, end, log):
    if sys.flags.optimize:
        raise RuntimeError('原校验器使用assert：禁止-O或PYTHONOPTIMIZE，否则无法核验')
    if csv.stat().st_size > 64 * 1024 * 1024 or log.stat().st_size > 256 * 1024 * 1024:
        raise ValueError('超过本工具短时实验文件上限，拒绝无界读取')
    sys.dont_write_bytecode = True  # Never create/update caches in protected historical records.
    spec = importlib.util.spec_from_file_location('node01_original_sandbox_verifier', VERIFIER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check(manifest, csv, begin, end, log)


def inspect(sd_dir, session_path=None, manifest_path=None, experiment_id=None):
    root = Path(sd_dir).resolve()
    plan = {'action': 'DRY_RUN_READ_ONLY', 'status': 'INCOMPLETE', 'source_directory': str(root),
            'time_source': 'HOST_OBSERVED_EXPERIMENT_BEGIN', 'device_time_sync': 'NOT_SYNCHRONIZED',
            'hardware_acceptance': 'NOT_ASSESSED', 'sd_originals_modified': False}
    try:
        if not root.is_dir():
            raise ValueError('源目录不存在')
        if not session_path:
            files = []
            for index, path in enumerate(root.glob('*.CSV')):
                if index >= 256:
                    raise ValueError('历史预览超过256文件，请缩小源目录')
                files.append({'csv': path.name, 'bytes': path.stat().st_size,
                              'begin_present': path.with_suffix('.BEG').is_file(),
                              'end_present': path.with_suffix('.END').is_file(),
                              'status': 'UNKNOWN_TIME', 'timestamp_name': None})
            plan.update(status='UNKNOWN_TIME', reason='无真实BEGIN主机观察会话；未使用mtime或N序号推算时间', historical_preview=files)
            return plan
        session_path = Path(session_path).resolve()
        if session_path.is_dir():
            session_path /= 'session.json'
        session = read_json(session_path)
        plan['test_only'] = bool(session.get('test_only'))
        plan['verification_scope'] = 'TEST_ONLY_SIMULATION' if plan['test_only'] else 'FILES_AND_UART_CONSISTENCY_ONLY'
        if not session.get('closed') or not session.get('capture_complete'):
            raise ValueError('控制台尚未关闭或接收证据不完整（断线/写盘失败）；不能标主机核验通过')
        issues = [x for x in session.get('parse_issues', []) if x != 'PARTIAL_LINE_AT_CLOSE']
        if issues:
            raise ValueError('串口解析证据受损：' + ','.join(issues))
        candidates = [e for e in session.get('experiments', []) if not experiment_id or e['experiment_id'] == experiment_id]
        if len(candidates) != 1:
            plan.update(status='UNKNOWN_TIME', reason='缺真实BEGIN或存在多场；显式选择--experiment-id，不凭序号猜测')
            return plan
        experiment = candidates[0]
        if not experiment.get('device_finalized') or experiment.get('failed') or experiment.get('interrupted') or experiment.get('conflict'):
            raise ValueError('此实验没有唯一完整设备终态，或重启/ID冲突；保留不完整证据')
        anchor = experiment.get('begin_observation')
        if not anchor or not session.get('clock_confirmed') or not anchor.get('operator_clock_confirmed') or session.get('clock_issues'):
            plan.update(status='UNKNOWN_TIME', reason='时钟未确认/跳变/时区变化/无观察锚', observed_begin=anchor, clock_issues=session.get('clock_issues'))
            return plan
        observed = datetime.fromisoformat(anchor['iso8601'])
        if observed.tzinfo is None or experiment.get('time_source') != 'HOST_OBSERVED_EXPERIMENT_BEGIN':
            raise ValueError('时间锚必须是带偏移的真实BEGIN主机观察')
        run_dir = session_path.parent
        for name in ['serial.bin', 'device.txt', 'events.jsonl']:
            if file_info(run_dir / name) != session.get('evidence_files', {}).get(name):
                raise ValueError('会话接收证据SHA/长度不一致：' + name)
        anchors = []
        covered_bytes = 0
        with (run_dir / 'events.jsonl').open('r', encoding='utf-8') as stream:
            while line := stream.readline(65537):
                if len(line) > 65536:
                    raise ValueError('事件记录超过64KiB上限')
                event = json.loads(line)
                if event['kind'] == 'RX_CHUNK':
                    if event['raw_offset'] != covered_bytes:
                        raise ValueError('原始RX分块偏移存在缺口/重复')
                    covered_bytes += event['bytes']
                if event['kind'] == 'HOST_OBSERVED_EXPERIMENT_BEGIN' and event['experiment_id'] == experiment['experiment_id']:
                    anchors.append(event)
        if covered_bytes != (run_dir / 'serial.bin').stat().st_size:
            raise ValueError('原始RX字节与事件分块长度不一致')
        if len(anchors) != 1 or anchors[0]['host_observed'] != anchor or int(anchors[0]['device_monotonic_us']) != int(experiment['device_monotonic_us']):
            raise ValueError('BEGIN时间摘要与接收当时的独立事件记录不一致')
        # Prove readable log was derived from complete raw RX, not screen filtering/PC ACKs.
        decoder = codecs.getincrementaldecoder('utf-8')('backslashreplace')
        decoded_sha = hashlib.sha256()
        with (run_dir / 'serial.bin').open('rb') as stream:
            while chunk := stream.read(65536):
                decoded_sha.update(decoder.decode(chunk).encode('utf-8'))
        decoded_sha.update(decoder.decode(b'', final=True).encode('utf-8'))
        if decoded_sha.hexdigest() != file_info(run_dir / 'device.txt')['sha256']:
            raise ValueError('可读日志不是原始串口的完整解码')
        matched = []
        for index, end_path in enumerate(root.glob('*.END')):
            if index >= 256:
                raise ValueError('侧车扫描超过256文件，请缩小源目录')
            try:
                end = read_json(end_path)
            except (ValueError, OSError):
                continue
            if end.get('experiment_id') == experiment['experiment_id']:
                matched.append((end_path, end))
        if len(matched) != 1:
            raise ValueError('实验ID对应的END缺失或有冲突；不猜选文件')
        end_path, end = matched[0]
        original_name = Path(end['csv']).name
        if not re.fullmatch(r'N\d{7}\.CSV', original_name):
            raise ValueError('当前受支持的SD名字应为N+7位.CSV；本工具未修改SD命名')
        csv_path, begin_path = root / original_name, root / original_name.replace('.CSV', '.BEG')
        if end_path.stem != csv_path.stem or not begin_path.is_file() or not csv_path.is_file():
            raise ValueError('CSV/BEG/END不是同一原始文件组')
        manifest_path = Path(manifest_path or default_manifest()).resolve()
        validated_paths = [csv_path, begin_path, end_path, run_dir / 'device.txt', run_dir / 'serial.bin', run_dir / 'events.jsonl', session_path, manifest_path]
        before_check = {str(path): file_info(path) for path in validated_paths}
        for name in ['serial.bin','device.txt','events.jsonl']:
            if before_check[str(run_dir/name)] != session['evidence_files'][name]:
                raise ValueError('原始证据在验证期间变化：'+name)
        checks = original_check(manifest_path, csv_path, begin_path, end_path, run_dir / 'device.txt')
        if any(file_info(path) != before_check[str(path)] for path in validated_paths):
            raise ValueError('原校验器执行期间源文件发生变化，拒绝归档')
        if int(end['start_us']) != int(experiment['device_monotonic_us']):
            raise ValueError('END起点与实际观察BEGIN设备时钟不一致')
        # Source hashes taken after validation are rechecked before and after copy.
        sources = {'CSV': csv_path, 'BEG': begin_path, 'END': end_path,
                   'serial.bin': run_dir / 'serial.bin', 'serial.txt': run_dir / 'device.txt',
                   'events.jsonl': run_dir / 'events.jsonl', 'manifest.json': manifest_path,
                   'console-session.json': session_path}
        safe_id = re.sub(r'[^A-Za-z0-9_-]', '_', experiment['experiment_id'])[:40]
        name = observed.strftime('%Y%m%d_%H%M%S') + '_NODE01_' + safe_id + '_' + uuid.uuid4().hex[:8]
        plan.update(status='HOST_FILES_VERIFIED', suggested_stem=name, observed_begin=anchor,
                    device_monotonic_us=experiment['device_monotonic_us'], experiment_id=experiment['experiment_id'],
                    source_n_filename=original_name, session_path=str(session_path), session_file=file_info(session_path),
                    source_files={key: {'path': str(path), **file_info(path)} for key, path in sources.items()},
                    original_verifier={'path': str(VERIFIER), 'identity': file_info(VERIFIER), 'result': checks},
                    device_status='SIMULATED_DEVICE_FINALIZED_TEST_ONLY' if plan['test_only'] else 'DEVICE_FINALIZED', host_status='HOST_FILES_VERIFIED',
                    calibration='EXPERIMENT_ACQUISITION_NOT_CALIBRATED', integration='INTEGRATION_NOT_READY',
                    accuracy_note='Seconds in the name are host observation precision, NOT device UTC accuracy')
        return plan
    except Exception as error:
        plan.update(status='INCOMPLETE', reason=repr(error), timestamp_name=None)
        return plan


def copy_verified(plan, output_dir):
    if plan.get('status') != 'HOST_FILES_VERIFIED':
        raise ValueError('预览未通过：不复制、不造日期名')
    root = Path(output_dir).resolve()
    source_root = Path(plan['source_directory']).resolve()
    if root == source_root or root.is_relative_to(source_root):
        raise ValueError('PC输出不能位于源SD/源文件目录内；源目录保持只读')
    # Always revalidate immediately before copying; --copy cannot bypass preview.
    session_path = Path(plan['session_path'])
    if file_info(session_path) != plan['session_file']:
        raise ValueError('会话证据在预览后发生变化')
    group = root / (datetime.fromisoformat(plan['observed_begin']['iso8601']).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])
    if os.name == 'nt' and len(str(group / (plan['suggested_stem'] + '.session.json'))) > 240:
        raise ValueError('Windows归档路径过长，请选更短的--output-dir')
    group.mkdir(parents=True, exist_ok=False)
    mapped = {}
    try:
        for extension, entry in plan['source_files'].items():
            source = Path(entry['path'])
            expected = {key: entry[key] for key in ['bytes', 'sha256']}
            if file_info(source) != expected:
                raise ValueError('源文件已变化：' + str(source))
            target = group / (plan['suggested_stem'] + '.' + extension)
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                while data := incoming.read(65536):
                    n = outgoing.write(data)
                    if n != len(data):
                        raise OSError('归档副本部分写入')
                outgoing.flush()
                os.fsync(outgoing.fileno())
            if file_info(target) != expected or file_info(source) != expected:
                raise ValueError('源/副本SHA或长度不同')
            mapped[extension] = {'source': str(source), 'destination': str(target), **expected}
        result = {**plan, 'action': 'COPIED_NOT_MOVED', 'archive_files': mapped,
                  'archive_directory': str(group), 'sd_originals_modified': False,
                  'renamed_copies_note': 'BEG/END内容仍引用原N名；已先校验原件，副本逐项SHA相同，映射保留。'}
        with (group / (plan['suggested_stem'] + '.session.json')).open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        return result
    except Exception as error:
        try:
            with (group / 'ARCHIVE_FAILED.json').open('x', encoding='utf-8') as stream:
                json.dump({'status': 'ARCHIVE_FAILED_PARTIAL_COPIES_RETAINED', 'error': repr(error), 'copied': mapped}, stream, ensure_ascii=False, indent=2)
        except OSError:
            pass
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sd-dir', type=Path, required=True)
    parser.add_argument('--session', type=Path)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--experiment-id')
    parser.add_argument('--output-dir', type=Path, default=DEFAULT_OUTPUT)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--dry-run', action='store_true')
    mode.add_argument('--copy', action='store_true')
    args = parser.parse_args(argv)
    plan = inspect(args.sd_dir, args.session, args.manifest, args.experiment_id)
    if args.copy:
        try:
            plan = copy_verified(plan, args.output_dir)
        except Exception as error:
            plan.update(status='ARCHIVE_FAILED', error=repr(error))
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0 if plan['status'] == 'HOST_FILES_VERIFIED' else 2


if __name__ == '__main__':
    raise SystemExit(main())
