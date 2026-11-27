"""离线、只读输入；所有持久化输出必须使用新目录。仅依赖标准库。"""
import csv
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parent
STABLE_ELF = '288e76253c36efcc1939959443c2ae58c245eb2ea0f7ba667e950d9d2372119d'
STABLE_BIN = '2be566f0195877656610ae2ebf17437ae41fdae280457f7b914e4dd64fadd422'
STABLE_MANIFEST = 'bf529da2f31d02977bcf69e1a0e83cf773c9e4dff657d09701662f70a454d54f'


class Rejected(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Rejected(reason)


def runtime_guard():
    require(not sys.flags.optimize, '禁止 -O / PYTHONOPTIMIZE；不得优化绕过检查')


def info(path):
    p = Path(path).resolve()
    require(p.is_file(), f'输入文件不存在：{p}')
    with p.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    return {'bytes': p.stat().st_size, 'sha256': digest}


def json_read(path):
    p = Path(path)
    require(p.stat().st_size <= 8 * 1024 * 1024, f'JSON超过8MiB：{p}')
    def pairs(items):
        out = {}
        for k, v in items:
            require(k not in out, 'JSON重复键：' + k)
            out[k] = v
        return out
    return json.loads(p.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(Rejected('非有限JSON数值：' + x)))


def natural(value, name):
    require(type(value) is int and value >= 0, '需要非负整数：' + name)
    return value


def snapshot(paths):
    return {str(Path(p).resolve()): info(p) for p in paths}


def unchanged(before):
    require(all(info(p) == v for p, v in before.items()), '验证期间输入文件发生变化')


def new_output(parent, label):
    root = Path(parent).resolve()
    root.mkdir(parents=True, exist_ok=True)
    result = root / (label + '-' + uuid.uuid4().hex[:12])
    result.mkdir(exist_ok=False)
    return result


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)


def write_csv(path, rows, fields=None):
    rows = list(rows)
    fields = fields or list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with Path(path).open('x', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False, allow_nan=False) if isinstance(v, (dict, list)) else v
                             for k, v in row.items()})


def finite_number(value, name):
    require(type(value) in (int, float) and math.isfinite(value), '需要有限数值：' + name)
    return value
