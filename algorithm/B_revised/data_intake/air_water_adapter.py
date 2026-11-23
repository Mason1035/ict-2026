"""独立研究结果适配器。输入工程观测，不改写冻结Telemetry。"""
import json,math
from pathlib import Path
from .air_water_20261122 import relative_percent,VERSION

def load_parameters(path=None):
    path=Path(path) if path else Path(__file__).with_name('air_water_20261122.parameters.json')
    data=json.loads(path.read_text(encoding='utf-8'))
    expected=json.loads(Path(__file__).with_name('air_water_20261122.parameters.json').read_text(encoding='utf-8'))
    if data!=expected:raise ValueError('只接受当前已审计版本；新参数须重新审计')
    return data

def evaluate_observation(*,channel,raw,valid,firmware_sha256,parameters=None):
    p=load_parameters() if parameters is None else parameters
    expected=load_parameters()
    if p!=expected:raise ValueError('参数未通过当前版本审核')
    if type(valid) is not bool:raise ValueError('valid必须是布尔值')
    if type(channel) is not int or channel not in (0,1,2):raise ValueError('非法通道')
    flags=[]
    if firmware_sha256!=p['firmware_elf_sha256']:flags.append('FIRMWARE_NOT_APPLICABLE')
    if not valid:flags.append('INVALID_OBSERVATION')
    value=None
    if not flags:
        result=relative_percent(channel,raw,p['parameters']);value=result['value'];flags=result['flags']
    return {'schema':'B.air_water.research_result.v1','version':VERSION,'channel':channel,
            'w_rel_pct':value,'unit':'air_water_relative_percent','quality_flags':flags,
            'vwc_pct':None,'risk_eligible':False,'fusion_eligible':False,
            'status':'RESEARCH_ONLY','source_archive_sha256':p['source_archive_sha256']}
