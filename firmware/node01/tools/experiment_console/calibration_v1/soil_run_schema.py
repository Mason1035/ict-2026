"""正式22列与外部现场表；不推断工况，不改原schema。"""
import csv
import io
import re
from .common import Rejected, natural, require, finite_number

FIELDS = ('kind,channel,acquisition_index,attempted_uptime_us,acquired_uptime_us,timestamp_ms,'
          'time_synced,validity,error,ax_raw,ay_raw,az_raw,gx_raw,gy_raw,gz_raw,'
          'ax_mps2,ay_mps2,az_mps2,gx_dps,gy_dps,gz_dps,soil_raw').split(',')
ROLES = {f'{c}-{i}': (c, i) for c in ('AIR', 'WATER') for i in (1, 2, 3)}
ROLES.update({'OBSERVE_AIR': ('OBSERVE', 0), 'OBSERVE_WATER': ('OBSERVE', 0)})
FIELD_REQUIRED = ('experiment_id', 'run_role', 'condition', 'repeat_index',
    'probe_label_ain0', 'probe_label_ain1', 'probe_label_ain2', 'probe_sku_version',
    'air_setup', 'water_container', 'water_level', 'immersion_depth', 'water_temperature',
    'water_boundary_confirmed', 'power_on_time', 'reset_time', 'placement_time',
    'settling_time', 'observed_begin_time', 'observed_end_time', 'pc_timezone',
    'utc_offset', 'operator', 'pump_off', 'anomalies', 'notes')


def int_text(value, name, low=0, high=2**64 - 1):
    require(isinstance(value, str) and re.fullmatch(r'-?\d+', value) is not None, '整数字段错误：' + name)
    n = int(value)
    require(low <= n <= high, '整数越界：' + name)
    return n


def parse_csv(raw):
    require(raw.endswith(b'\n'), 'CSV末尾缺少换行/完整EOF记录')
    lines = raw.decode('utf-8-sig').splitlines()
    comments = [l for l in lines if l.startswith('#')]
    reader = csv.DictReader(io.StringIO('\n'.join(l for l in lines if not l.startswith('#'))))
    require(reader.fieldnames == FIELDS, '必须是正式ESP-IDF 22列且顺序相同')
    rows = []
    for n, row in enumerate(reader, 1):
        require(set(row) == set(FIELDS) and all(v is not None for v in row.values()), f'CSV第{n}行列数错误')
        kind, state = row['kind'], row['validity']
        require(kind in ('imu', 'soil') and state in ('Valid', 'Unavailable', 'Error'), f'CSV第{n}行kind/validity非法')
        channel = int_text(row['channel'], 'channel', 0, 2 if kind == 'soil' else 1)
        index = int_text(row['acquisition_index'], 'acquisition_index')
        attempted = int_text(row['attempted_uptime_us'], 'attempted')
        acquired = None if row['acquired_uptime_us'] == '' else int_text(row['acquired_uptime_us'], 'acquired')
        error = int_text(row['error'], 'error', -(2**31), 2**31 - 1)
        require(row['timestamp_ms'] == '' and row['time_synced'] == 'false', '冻结固件不提供可信UTC')
        value = None
        if state == 'Valid':
            require(acquired is not None and acquired >= attempted and error == 0, 'Valid时间/错误状态不一致')
            if kind == 'soil':
                value = int_text(row['soil_raw'], 'soil_raw', -32768, 32767)
                require(all(row[k] == '' for k in FIELDS[9:21]), 'Soil行混入IMU数值')
            else:
                require(row['soil_raw'] == '', 'IMU行混入Soil数值')
                for k in FIELDS[9:15]:
                    int_text(row[k], k, -32768, 32767)
                for k in FIELDS[15:21]:
                    try:
                        finite_number(float(row[k]), k)
                    except ValueError:
                        raise Rejected('IMU物理量错误：' + k)
        else:
            require(acquired is None and all(row[k] == '' for k in FIELDS[9:]), '无效样本不得填0、旧raw或伪造时间')
        rows.append({'kind': kind, 'channel': channel, 'index': index, 'attempted': attempted,
                     'acquired': acquired, 'validity': state, 'error': error, 'raw': value, 'data_row': n})
    return rows, comments


def validate_field_log(document):
    require(document.get('schema') == 'NODE01_AW_FIELD_LOG_V1' and isinstance(document.get('runs'), list), '现场表schema错误')
    result = {}
    for row in document['runs']:
        require(all(k in row for k in FIELD_REQUIRED), '现场表字段不完整')
        eid = row['experiment_id']
        require(isinstance(eid, str) and eid.strip() and eid not in result, '现场表完整ID缺失或重复')
        require(row['run_role'] in ROLES, '现场表工况/轮次必须显式指定')
        condition, repeat = ROLES[row['run_role']]
        require(row['condition'] == condition and type(row['repeat_index']) is int and row['repeat_index'] == repeat,
                '现场表role/condition/repeat不一致')
        require(row['pump_off'] is True, '必须明确记录水泵关闭')
        for k in ('probe_label_ain0', 'probe_label_ain1', 'probe_label_ain2', 'operator'):
            require(isinstance(row[k], str) and row[k].strip() not in ('', 'UNKNOWN'), '现场标签或操作者未明确：' + k)
        if 'WATER' in row['run_role']:
            require(row['water_boundary_confirmed'] is True, 'WATER安全接水边界尚未确认')
            require(all(row[k] not in ('', None, 'UNKNOWN') for k in ('water_container', 'water_level', 'immersion_depth')), 'WATER条件缺失')
        result[eid] = row
    return result
