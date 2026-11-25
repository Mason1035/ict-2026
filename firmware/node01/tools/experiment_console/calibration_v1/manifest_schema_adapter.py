"""Resolve only a reviewed build. Artifact verification never grants device access."""
import hashlib
from pathlib import Path

from . import legacy_manifest
from .common import ROOT, Rejected, info, json_read, require, runtime_guard, unchanged

REGISTRY = ROOT / 'manifest_approval_registry_v1.json'
REGISTRY_SHA = 'c75a5b734ecb5080b6456f8dd51bb6e978ea435a4a90a095a1997f614c1c09ad'
CANDIDATE = 'N0000043_CANDIDATE'
ARTIFACT_KEYS = {
    'zhishao_node01.bin': 'bin_sha256',
    'zhishao_node01.elf': 'elf_sha256',
    'bootloader/bootloader.bin': 'bootloader_sha256',
    'partition_table/partition-table.bin': 'partition_table_sha256',
    'sdkconfig.local': 'sdkconfig_sha256',
}
CANDIDATE_PROOF = ROOT / 'candidate_explicit_start_evidence_v1.json'
OLD_PROOF = ROOT / 'stable_source_provenance.json'


def profiles():
    require(info(REGISTRY)['sha256'] == REGISTRY_SHA, '审批登记表SHA不匹配')
    registry = json_read(REGISTRY)
    require(registry['schema'] == 'NODE01_CALIBRATION_REGISTRY_V1', '审批登记表版本不支持')
    return registry['profiles']


def profile_for_sha(digest):
    matches = [value for value in profiles().values() if value['manifest_sha256'] == digest]
    require(len(matches) <= 1, 'Manifest身份登记重复')
    return matches[0] if matches else None


def auto_start_presence(manifest):
    if 'auto_start' not in manifest:
        return 'NOT_PRESENT_IN_MANIFEST'
    require(manifest['auto_start'] is False, 'auto_start 必须为显式布尔 false')
    return 'PRESENT_AND_VERIFIED'


def checked_path(root, relative):
    path = Path(relative)
    resolved = (root / path).resolve()
    require(not path.anchor and '..' not in path.parts and resolved.is_relative_to(root), '相对路径越界')
    return resolved


def candidate_files(path, manifest, profile, proof_path, root):
    required = set(ARTIFACT_KEYS) | {'flash_args', 'config/sdkconfig.json'}
    require(isinstance(manifest.get('files'), dict) and set(manifest['files']) == required, 'B 构建文件清单不完整')
    observed = {str(path): info(path), str(REGISTRY): info(REGISTRY)}
    require(observed[str(path)]['sha256'] == profile['manifest_sha256'], 'B Manifest SHA 不匹配')
    files = {}
    for name, entry in manifest['files'].items():
        require(entry['relative_path'] == name, 'B 构建文件路径不匹配：' + name)
        file = checked_path(root, name)
        actual = info(file)
        require(actual == {k: entry[k] for k in ('bytes', 'sha256')}, '产物大小/SHA 错误：' + name)
        files[name] = {'path': str(file), **actual}
        observed[str(file)] = actual
        if name in ARTIFACT_KEYS:
            require(actual['sha256'] == profile[ARTIFACT_KEYS[name]], '登记产物不匹配：' + name)

    binary = Path(files['zhishao_node01.bin']['path']).read_bytes()
    require(len(binary) >= 208 and binary[0] == 0xE9 and binary[176:208].hex() == profile['elf_sha256'],
            'BIN 内嵌 ELF 不匹配')
    elf = Path(files['zhishao_node01.elf']['path']).read_bytes()
    require(all(tag in elf for tag in (b'EXPERIMENT_CONSOLE primary_uart0=', b'EXP_STATUS endpoint=',
            b'DIAG_V6 app_elf_sha256=', b'EXPERIMENT_READY id=')), 'ELF 未见受审实验入口或启动身份')

    config_path = Path(files['config/sdkconfig.json']['path'])
    require(files['config/sdkconfig.json']['sha256'] == profile['build_configuration_sha256'], '有效配置 SHA 不匹配')
    config = json_read(config_path)
    enabled = ('NODE01_SANDBOX_EXPERIMENT', 'NODE01_DIAG_ACQUISITION', 'NODE01_STARTUP_IMU_FIRST', 'NODE01_IMU_DRDY')
    require(all(config.get(k) is True for k in enabled) and config.get('NODE01_NETWORK_ENABLE') is False
            and config.get('NODE01_CAPTURE_SECONDS') == 120 and config.get('IDF_TARGET') == 'esp32s3',
            '有效配置不符合正式实验')
    local = Path(files['sdkconfig.local']['path']).read_text(encoding='utf-8-sig').splitlines()
    require(all('CONFIG_'+k+'=y' in local for k in enabled), 'sdkconfig.local 不符合正式实验')

    proof_digest = info(proof_path)
    require(proof_digest['sha256'] == profile['approved_source_evidence_sha256'], '显式 START 来源证据 SHA 不匹配')
    proof = json_read(proof_path)
    require(proof['schema'] == 'NODE01_EXPLICIT_START_REVIEW_V1' and
            all(proof[k] == profile[k] for k in ('manifest_sha256','bin_sha256','elf_sha256','build_configuration_sha256')),
            '显式 START 源码证据未绑定当前产物')
    observed[str(Path(proof_path).resolve())] = proof_digest
    require(len(proof['files']) == 5, '显式 START 源码证据不完整')
    for relative, expected in proof['files'].items():
        source = checked_path(Path(proof['source_root']).resolve(), relative)
        require(info(source) == expected, '显式 START 源码大小/SHA 错误：' + relative)
        observed[str(source)] = expected
    unchanged(observed)
    return files, observed


def verify_manifest(path, proof_path=None, *, synthetic=False):
    """A uses its original verifier. B is verified from its immutable sibling files."""
    runtime_guard()
    if synthetic:
        return legacy_manifest.verify_manifest(path, proof_path or OLD_PROOF, synthetic=True)
    require(path is not None and str(path).strip(), '必须显式指定 Manifest')
    path = Path(path).resolve()
    digest = info(path)['sha256']
    profile = profile_for_sha(digest)
    require(profile is not None, 'Manifest SHA 不在受审版本登记表')
    manifest = json_read(path)
    presence = auto_start_presence(manifest)
    require(manifest.get('mode') == profile['mode'], '禁止 Diagnostic 或非正式实验模式')
    if profile['firmware_id'] == 'OLD_STABLE':
        proof = Path(proof_path or OLD_PROOF)
        require(info(proof)['sha256'] == profile['approved_source_evidence_sha256'], 'A 来源证据 SHA 不匹配')
        result = legacy_manifest.verify_manifest(path, proof)
        require(result['status'] == 'MANIFEST_COMPATIBILITY_PASS', 'A 显式 START 来源证据不可验证')
        require(manifest.get('data_source') == profile['source'], 'A 来源模式不匹配')
        bin_bytes = Path(result['files']['zhishao_node01.bin']['path']).read_bytes()
        require(bin_bytes[176:208].hex() == profile['elf_sha256'], 'A BIN/ELF 不匹配')
        require(all(result['files'][k]['sha256'] == profile[v] for k,v in ARTIFACT_KEYS.items()), 'A 产物登记不匹配')
        require(result['files']['sdkconfig.local']['sha256'] == profile['build_configuration_sha256'], 'A 有效配置不符')
        result['inputs'][str(REGISTRY)] = info(REGISTRY)
        unchanged(result['inputs'])
        return {**result, **profile}

    require(manifest.get('format') == profile['manifest_schema'] and manifest.get('source') == profile['source']
            and manifest.get('one_experiment_per_boot') is True and manifest.get('network_enabled') is False,
            'B Manifest schema、来源或运行模式不符')
    # The user selects the artifact set by selecting its manifest. No fallback
    # from a damaged frozen set to the mutable absolute directory in JSON.
    files, observed = candidate_files(path, manifest, profile, proof_path or CANDIDATE_PROOF, path.parent)
    return {**profile, 'status':'MANIFEST_COMPATIBILITY_PASS', 'scope':'OFFLINE_FROZEN_FILES_AND_SOURCE_ONLY',
            'manifest': {'path':str(path), **observed[str(path)]}, 'files':files, 'expected_elf':profile['elf_sha256'],
            'inputs':observed, 'auto_start':{'manifest_presence':presence,
                'replacement_check':'PINNED_EXPLICIT_START_SOURCE_AND_EFFECTIVE_CONFIGURATION',
                'original_manifest_modified':False},
            'runtime_device_identity':'NOT_CONNECTED_NOT_VERIFIED_THIS_RUN'}


def require_start_approval(profile, purpose):
    allowed = {
        'qualification': ('QUALIFICATION_APPROVED','CALIBRATION_APPROVED'),
        'calibration': ('CALIBRATION_APPROVED',),
    }
    record = profile.get('approval_record')
    fields = ('firmware_id','manifest_sha256','bin_sha256','elf_sha256','approval_status')
    require(purpose in allowed and profile['approval_status'] in allowed[purpose] and
            isinstance(record,dict) and all(record.get(k)==profile[k] for k in fields) and
            all(isinstance(record.get(k),str) and record[k].strip() for k in ('approved_by','approved_at','approval_reference')),
            'CALIBRATION_START_BLOCKED：当前版本未获得该用途批准')
