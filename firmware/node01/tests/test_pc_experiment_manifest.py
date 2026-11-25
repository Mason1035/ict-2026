"""TEST_ONLY: fake build files and real PC gates. No COM/network access."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from experiment_console.manifest import build_manifest, validate_build_config
from experiment_console.console import expected_identity
from experiment_console.core import wire_command


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='NODE01_TEST_ONLY_MANIFEST_')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = {'NODE01_SANDBOX_EXPERIMENT': True, 'NODE01_DIAG_ACQUISITION': True,
                       'NODE01_STARTUP_IMU_FIRST': True, 'NODE01_IMU_DRDY': True,
                       'NODE01_NETWORK_ENABLE': False, 'NODE01_CAPTURE_SECONDS': 120, 'IDF_TARGET': 'esp32s3'}
        for name in ('sdkconfig.local', 'flash_args', 'bootloader/bootloader.bin', 'partition_table/partition-table.bin'):
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b'TEST_ONLY SYNTHETIC FILE')
        (self.root / 'config').mkdir()
        self.write_config()
        self.elf = b'TEST_ONLY SYNTHETIC ELF EXPERIMENT_CONSOLE primary_uart0= EXP_STATUS endpoint='
        (self.root / 'zhishao_node01.elf').write_bytes(self.elf)
        self.binary = bytearray(256)
        self.binary[0] = 0xE9
        self.binary[176:208] = hashlib.sha256(self.elf).digest()
        (self.root / 'zhishao_node01.bin').write_bytes(self.binary)

    def write_config(self):
        (self.root / 'config/sdkconfig.json').write_text(json.dumps(self.config), encoding='utf-8')

    def manifest(self):
        m = build_manifest(self.root)
        path = self.root / 'manifest.json'
        path.write_text(json.dumps(m), encoding='utf-8')
        return path

    def test_formal_build_binds_identity(self):
        self.assertEqual(expected_identity(self.manifest()), hashlib.sha256(self.elf).hexdigest())

    def test_diagnostic_config_rejected(self):
        self.config['NODE01_SANDBOX_EXPERIMENT'] = False
        self.write_config()
        with self.assertRaises(ValueError):
            build_manifest(self.root)

    def test_forged_mode_cannot_override_build_config(self):
        path = self.manifest()
        self.config['NODE01_SANDBOX_EXPERIMENT'] = False
        self.write_config()
        # Keep hash valid to exercise configuration gate rather than hash gate.
        m = json.loads(path.read_text())
        p = self.root / 'config/sdkconfig.json'
        m['files']['config/sdkconfig.json'].update(bytes=p.stat().st_size, sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            expected_identity(path)

    def test_wrong_manifest_mode_rejected(self):
        path = self.manifest()
        m = json.loads(path.read_text());m['mode'] = 'ACQUISITION_DIAGNOSTIC';path.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError, 'Manifest不是沙盘采集模式'):
            expected_identity(path)

    def test_file_corruption_rejected(self):
        path = self.manifest()
        (self.root / 'zhishao_node01.elf').write_bytes(b'not matching ELF')
        with self.assertRaises(ValueError):
            expected_identity(path)

    def test_bin_elf_mismatch_rejected(self):
        self.binary[176] ^= 1
        (self.root / 'zhishao_node01.bin').write_bytes(self.binary)
        with self.assertRaises(ValueError):
            build_manifest(self.root)

    def test_console_entry_missing_rejected(self):
        elf = b'TEST_ONLY Diagnostic without commands'
        (self.root / 'zhishao_node01.elf').write_bytes(elf)
        self.binary[176:208] = hashlib.sha256(elf).digest()
        (self.root / 'zhishao_node01.bin').write_bytes(self.binary)
        with self.assertRaises(ValueError):
            build_manifest(self.root)

    def test_missing_product_rejected(self):
        (self.root / 'bootloader/bootloader.bin').unlink()
        with self.assertRaises(ValueError):
            build_manifest(self.root)

    def test_wrong_startup_rejected(self):
        self.config['NODE01_STARTUP_IMU_FIRST'] = False;self.write_config()
        with self.assertRaises(ValueError):
            validate_build_config(self.root)

    def test_missing_drdy_rejected(self):
        self.config['NODE01_IMU_DRDY'] = False;self.write_config()
        with self.assertRaises(ValueError):
            validate_build_config(self.root)

    def test_network_profile_rejected(self):
        self.config['NODE01_NETWORK_ENABLE'] = True;self.write_config()
        with self.assertRaises(ValueError):
            validate_build_config(self.root)

    def test_path_escape_rejected(self):
        path = self.manifest();m = json.loads(path.read_text())
        m['files']['zhishao_node01.elf']['relative_path'] = '../escape.elf'
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            expected_identity(path)

    def test_wire_commands_preserve_boundaries(self):
        for cmd in ('EXP STATUS', 'EXP START 30', 'EXP STOP'):
            self.assertEqual(wire_command(cmd), (cmd + '\r\n').encode('ascii'))
        for cmd in ('EXP START 0', 'EXP START bad', 'EXP START 301', 'EXP FINALIZE'):
            with self.assertRaises(ValueError):
                wire_command(cmd)

    def test_omitted_config_entry_rejected(self):
        path = self.manifest();m = json.loads(path.read_text())
        del m['files']['config/sdkconfig.json'];path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            expected_identity(path)

    def test_rehashed_bad_bin_rejected_by_reader(self):
        path = self.manifest();m = json.loads(path.read_text())
        self.binary[176] ^= 1
        p = self.root / 'zhishao_node01.bin';p.write_bytes(self.binary)
        m['files']['zhishao_node01.bin']['sha256'] = hashlib.sha256(self.binary).hexdigest()
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):
            expected_identity(path)


if __name__ == '__main__':
    unittest.main(verbosity=2)
