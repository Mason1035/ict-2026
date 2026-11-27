"""独立校验稳定manifest；不调用、不修改历史校验器，也不补 auto_start。"""
from pathlib import Path
from .common import (ROOT, STABLE_ELF, STABLE_BIN, STABLE_MANIFEST, Rejected,
                    info, json_read, require, snapshot, unchanged, runtime_guard)

ARTIFACTS = ('zhishao_node01.bin', 'zhishao_node01.elf', 'sdkconfig.local',
             'bootloader/bootloader.bin', 'partition_table/partition-table.bin', 'flash_args')


def verify_manifest(path, proof_path=ROOT / 'stable_source_provenance.json', *, synthetic=False):
    runtime_guard()
    require(path is not None and str(path).strip(), '必须显式指定manifest，禁止默认LATEST')
    path = Path(path).resolve()
    original = info(path)
    m = json_read(path)
    require(m.get('mode') == 'SANDBOX_EXPERIMENT_CAPTURE', 'manifest模式错误')
    require(isinstance(m.get('files'), dict) and set(ARTIFACTS) <= set(m['files']), '缺少六项产物')
    proof = json_read(proof_path) if proof_path and Path(proof_path).is_file() else None
    if synthetic:
        require(m.get('source') == 'SYNTHETIC' and proof and proof.get('source') == 'SYNTHETIC', '合成模式需明确SYNTHETIC输入')
        expected_elf, expected_bin = proof['expected_elf'], proof['expected_bin']
    else:
        expected_elf, expected_bin = STABLE_ELF, STABLE_BIN
        require(original['sha256'] == STABLE_MANIFEST, '非已审查稳定manifest，拒绝默认旧manifest或篡改副本')
    root = Path(m['build_directory']).resolve()
    files = {}
    for name, entry in m['files'].items():
        require(isinstance(entry, dict), '产物条目格式错误')
        p = (root / entry['relative_path']).resolve()
        require(p.is_relative_to(root), '产物路径越界')
        actual = info(p)
        require(actual == {'bytes': entry['bytes'], 'sha256': entry['sha256']}, '产物大小/SHA错误：' + name)
        files[name] = {'path': str(p), **actual}
    require(files['zhishao_node01.elf']['sha256'] == expected_elf, 'ELF不是预期稳定身份')
    require(files['zhishao_node01.bin']['sha256'] == expected_bin, 'BIN不是预期稳定身份')
    presence = 'PRESENT_AND_VERIFIED' if 'auto_start' in m else 'NOT_PRESENT_IN_MANIFEST'
    if 'auto_start' in m:
        require(type(m['auto_start']) is bool and m['auto_start'] is False, '禁止auto_start或非布尔auto_start')
    applicability, evidence, reasons = 'NOT_VERIFIABLE', [], []
    input_files = [path] + [v['path'] for v in files.values()]
    if proof:
        input_files.append(Path(proof_path).resolve())
        try:
            require(proof.get('schema') == 'NODE01_NO_AUTO_START_SOURCE_PROOF_V1', '来源证据schema错误')
            require(proof['manifest_sha256'] == original['sha256'], '来源证据未绑定当前manifest')
            require(proof['expected_elf'] == expected_elf and proof['expected_bin'] == expected_bin, '来源证据身份不匹配')
            reference = json_read(ROOT / 'stable_source_provenance.json')
            require(proof['files'] == reference['files'], '源码证明不是人工审查过的冻结哈希集合')
            source_root = Path(proof['source_root']).resolve()
            for rel, entry in proof['files'].items():
                p = (source_root / rel).resolve()
                require(p.is_relative_to(source_root), '来源路径越界')
                require(info(p) == entry and m.get('source_files', {}).get(rel) == entry, '源码/manifest哈希不一致：' + rel)
                input_files.append(p)
                evidence.append({'path': str(p), **entry})
            config = Path(files['sdkconfig.local']['path']).read_text(encoding='utf-8-sig')
            require('CONFIG_NODE01_SANDBOX_EXPERIMENT=y' in config.splitlines(), '未证明编译启用显式START门禁')
            applicability = 'NOT_APPLICABLE'  # 自动采集功能不适用；其“禁止自动采集”意图仍独立核验。
        except (KeyError, OSError, ValueError) as exc:
            reasons.append(str(exc))
    else:
        reasons.append('缺少绑定manifest及冻结源码的启动门禁证据')
    before = snapshot(input_files)
    require(info(path) == original, '验证期间manifest改变')
    require(all(info(v['path']) == {'bytes':v['bytes'],'sha256':v['sha256']} for v in files.values()), '验证期间产物改变')
    require(all(info(v['path']) == {'bytes':v['bytes'],'sha256':v['sha256']} for v in evidence), '验证期间冻结源码改变')
    unchanged(before)
    return {'status': 'MANIFEST_COMPATIBILITY_PASS' if applicability == 'NOT_APPLICABLE' else 'NOT_VERIFIABLE',
            'scope': 'SYNTHETIC_TEST_ONLY' if synthetic else 'OFFLINE_FROZEN_FILES_AND_SOURCE_ONLY',
            'manifest': {'path': str(path), **original}, 'files': files, 'expected_elf': expected_elf,
            'schema_keys': sorted(m), 'auto_start': {'manifest_presence': presence, 'feature_applicability': applicability,
                'replacement_check': 'EXPLICIT_START_GATE_SOURCE_AND_CONFIG_VERIFICATION', 'reasons': reasons,
                'source_evidence': evidence, 'original_manifest_modified': False}, 'inputs': before,
            'runtime_device_identity': 'NOT_CONNECTED_NOT_VERIFIED_THIS_RUN'}
