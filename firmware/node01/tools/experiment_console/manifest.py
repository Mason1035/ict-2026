"""Offline build-to-console manifest binding. Never opens a serial port."""
import argparse
import hashlib
import json
from pathlib import Path

MODE = 'SANDBOX_EXPERIMENT_CAPTURE'
SOURCE = 'REAL_SENSOR_EXPERIMENT_UNCALIBRATED'


def validate_build_config(root):
    root = Path(root).resolve()
    path = root / 'config/sdkconfig.json'
    config = json.loads(path.read_text(encoding='utf-8-sig'))
    required = ('NODE01_SANDBOX_EXPERIMENT', 'NODE01_DIAG_ACQUISITION',
                'NODE01_STARTUP_IMU_FIRST', 'NODE01_IMU_DRDY')
    if any(config.get(key) is not True for key in required):
        raise ValueError('构建配置不是正式实验模式：须启用Sandbox、IMU_FIRST和DRDY；不能重标Diagnostic')
    if config.get('NODE01_NETWORK_ENABLE') is True or not 30 <= config.get('NODE01_CAPTURE_SECONDS', 0) <= 300:
        raise ValueError('正式实验候选必须网络关闭且默认采集时长为30..300秒')
    if config.get('IDF_TARGET') != 'esp32s3':
        raise ValueError('候选目标不是ESP32-S3')
    return config


def build_manifest(build_directory):
    root = Path(build_directory).resolve()
    config = validate_build_config(root)
    names = ('zhishao_node01.bin', 'zhishao_node01.elf', 'sdkconfig.local',
             'config/sdkconfig.json', 'bootloader/bootloader.bin',
             'partition_table/partition-table.bin', 'flash_args')
    entries = {}
    for name in names:
        file = (root / name).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError('缺少受控构建产物：' + name)
        entries[name] = {'relative_path': name, 'bytes': file.stat().st_size,
                         'sha256': hashlib.sha256(file.read_bytes()).hexdigest()}
    binary = (root / 'zhishao_node01.bin').read_bytes()
    elf = (root / 'zhishao_node01.elf').read_bytes()
    if len(binary) < 208 or binary[0] != 0xE9 or binary[176:208].hex() != entries['zhishao_node01.elf']['sha256']:
        raise ValueError('BIN内嵌ELF摘要不匹配')
    if b'EXPERIMENT_CONSOLE primary_uart0=' not in elf or b'EXP_STATUS endpoint=' not in elf:
        raise ValueError('ELF未包含正式Experiment Console入口')
    return {'format': 'NODE01_EXPERIMENT_CONSOLE_MANIFEST_V1', 'mode': MODE,
            'source': SOURCE, 'build_directory': str(root), 'files': entries,
            'software_verification_only': True, 'hardware_status': 'NOT_RUN',
            'calibration_status': 'NOT_READY', 'capture_default_seconds': config['NODE01_CAPTURE_SECONDS'],
            'network_enabled': False, 'one_experiment_per_boot': True}


def main():
    parser = argparse.ArgumentParser(description='仅离线生成匹配构建的实验Manifest；不连接设备')
    parser.add_argument('--build-directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    value = build_manifest(args.build_directory)
    # Never overwrite a historical approval/manifest.
    with args.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(str(args.output.resolve()))


if __name__ == '__main__':
    main()
