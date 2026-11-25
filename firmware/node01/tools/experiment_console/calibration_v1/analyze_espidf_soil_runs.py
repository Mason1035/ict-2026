"""ESP-IDF六场离线分析；原始数据只读，输出排他创建，默认不生成参数。"""
import argparse
import json
from pathlib import Path
from .common import (ROOT, Rejected, require, info, json_read, snapshot, unchanged,
    new_output, write_csv, write_json, runtime_guard, finite_number)
from .manifest_schema_adapter import require_start_approval, verify_manifest
from .verify_espidf_run import verify_run
from .soil_run_schema import validate_field_log, ROLES
from .soil_statistics import channel_statistics
from .repeatability import summarize
from .endpoint_separation import separation, moisture

POLICY_FIELDS=('min_valid_count','min_valid_fraction','min_rate_hz','max_rate_hz','max_sample_sd',
               'max_abs_drift','max_abs_slope','max_repeat_mean_range','min_endpoint_separation',
               'min_separation_to_repeat_range','max_gap_seconds','max_latency_seconds')


def approved_policy(policy, synthetic):
    if not policy or policy.get('approval',{}).get('status') not in ('APPROVED_TEST_ONLY' if synthetic else 'APPROVED',):
        return False
    approval=policy['approval']
    require(all(isinstance(approval.get(k),str) and approval[k].strip() for k in ('approved_by','approval_reference','approved_at')), '批准来源必须明确记录')
    require(policy.get('schema')=='NODE01_AW_QUALITY_POLICY_V1', '质量策略schema错误')
    for c in ('0','1'):
        values=policy.get('channels',{}).get(c,{})
        require(all(k in values for k in POLICY_FIELDS),'缺少该通道独立质量门槛')
        for k in POLICY_FIELDS:
            finite_number(values[k],k)
            require(values[k]>=0,'质量门槛不能为负')
        require(values['min_valid_count']>=2 and values['min_valid_fraction']<=1 and values['min_rate_hz']<=values['max_rate_hz'], '质量门槛范围错误')
    return True


def evaluate_channel(s, p):
    reasons=[]
    tests=[(s['N_valid']>=p['min_valid_count'],'有效点数不足'),
           (s['N_attempted']>0 and s['N_valid']/s['N_attempted']>=p['min_valid_fraction'],'有效率不足'),
           (not(s['N_error'] or s['N_unavailable']),'存在Error/Unavailable'),
           (p['min_rate_hz']<=s['valid_rate_window_hz']<=p['max_rate_hz'],'有效Hz不符'),
           (s['sample_sd'] is not None and s['sample_sd']<=p['max_sample_sd'],'轮内样本SD超限'),
           (s['first_last_mean_difference'] is not None and abs(s['first_last_mean_difference'])<=p['max_abs_drift'],'首末漂移超限'),
           (s['ols_raw_per_second'] is not None and abs(s['ols_raw_per_second'])<=p['max_abs_slope'],'趋势超限'),
           (s['gap_seconds']['max'] is not None and s['gap_seconds']['max']<=p['max_gap_seconds'],'读取间隙超限'),
           (s['latency_seconds']['max'] is not None and s['latency_seconds']['max']<=p['max_latency_seconds'],'读取延迟超限')]
    reasons.extend(reason for ok,reason in tests if not ok)
    return reasons


def analyze_document(document, *, synthetic=False):
    runtime_guard()
    require(document.get('schema')=='NODE01_ESP_IDF_AW_INPUT_V1','分析输入schema错误')
    require(document.get('source')==('SYNTHETIC' if synthetic else 'REAL_SENSOR'),'真实/合成模式不匹配')
    require(isinstance(document.get('runs'),list) and document['runs'],'必须显式给出run列表，不自动发现或挑选')
    # All input paths are absolute: no cwd-dependent accidental source substitution.
    require(all(Path(document[k]).is_absolute() for k in ('manifest','field_log')),'manifest和现场表需绝对路径')
    manifest=verify_manifest(document['manifest'],document.get('proof'),synthetic=synthetic)
    if manifest.get('firmware_id') == 'N0000043_CANDIDATE':
        require_start_approval(manifest, 'calibration')
    field_doc=json_read(document['field_log']);fields=validate_field_log(field_doc)
    input_paths=[document['field_log']]+list(manifest['inputs'])
    if document.get('policy'):input_paths.append(document['policy'])
    before=snapshot(input_paths)
    policy=json_read(document['policy']) if document.get('policy') else None
    approved=approved_policy(policy,synthetic)
    seen=set();roles=set();runs=[];stats=[];invalid=[];boundary=[];global_reasons=[]
    for spec in document['runs']:
        eid=spec.get('experiment_id')
        require(eid and eid not in seen,'重复完整experiment_id；不自动合并')
        seen.add(eid)
        require(eid in fields,'缺少完整ID绑定的现场记录，禁止猜工况')
        field=fields[eid];role=field['run_role']
        require(role not in roles,'同一角色重复提交，不自动选择最好场次')
        roles.add(role)
        require(all(Path(spec[k]).is_absolute() for k in ('csv','begin','end','session')),'run输入必须绝对路径')
        run=verify_run(spec,manifest,synthetic=synthetic);run['run_role']=role
        run['field_record']=field
        runs.append(run);before.update(run['inputs'])
        if run['status']!='FILES_AND_UART_VERIFIED':
            global_reasons.append({'experiment_id':eid,'role':role,'reasons':run['reasons']})
        if 'end' not in run or not run['rows']:
            continue
        for c in range(3):
            s=channel_statistics(run['rows'],run['end'],c)
            s.update(experiment_id=eid,run_role=role)
            if run['status']!='FILES_AND_UART_VERIFIED':
                s.update(quality='INVALID_RUN_EVIDENCE',quality_reasons=run['reasons'])
            elif c==2:
                s.update(quality='DIAGNOSTIC_ONLY',quality_reasons=['AIN2_NOT_USED_FOR_PARAMETERS'])
            elif approved:
                reasons=evaluate_channel(s,policy['channels'][str(c)])
                s.update(quality='REVIEW_REQUIRED' if reasons else 'MEETS_APPROVED_RUN_CRITERIA',quality_reasons=reasons)
            stats.append(s)
        invalid.extend({'experiment_id':eid,**r} for r in run['rows'] if r['kind']=='soil' and (r['validity']!='Valid' or r['raw'] is None))
        boundary.extend({'experiment_id':eid,**r} for r in run['boundary_records'])
    require(set(fields)==seen,'现场表有未提交run，防止静默删除失败/不好看的场次')
    repeat=[];separations=[];parameters={};reference_reasons={}
    formal={f'{c}-{i}' for c in ('AIR','WATER') for i in (1,2,3)}
    for c in (0,1):
        a,w=summarize(stats,c,'AIR'),summarize(stats,c,'WATER');repeat.extend([a,w]);sep=separation(stats,c,a,w)
        reasons=[]
        if not formal<=roles:reasons.append('缺少全部六个正式角色')
        formal_runs=[r for r in runs if r['run_role'] in formal]
        if any(r['status']!='FILES_AND_UART_VERIFIED' for r in formal_runs):reasons.append('正式场有失败/不完整证据，不自动替换')
        if any(r.get('end',{}).get('stop_reason')!='TIME_LIMIT' for r in formal_runs):reasons.append('正式场提前STOP，不能自动纳入完整参考重复')
        if len({r['field_record'][f'probe_label_ain{c}'] for r in formal_runs})!=1:reasons.append('该通道六场实体探头标签不一致')
        if len([s for s in stats if s['channel']==c and s['run_role'] in formal])!=6:reasons.append('该通道缺少六场统计')
        if not approved:reasons.append('QUALITY_THRESHOLDS_PENDING_USER_APPROVAL')
        if sep['direction']=='EQUAL' or sep['p5_p95_pair_overlap'] or not sep['all_pair_mean_direction_consistent']:
            reasons.append('端点相等、分布重叠或极性不一致')
        if approved:
            p=policy['channels'][str(c)]
            if any(s['quality']!='MEETS_APPROVED_RUN_CRITERIA' for s in stats if s['channel']==c and s['run_role'] in formal):reasons.append('该通道轮内质量未全部满足')
            if any(x['mean_range'] is None or x['mean_range']>p['max_repeat_mean_range'] for x in (a,w)):reasons.append('三次重复均值离散超限')
            delta=sep['absolute_endpoint_difference']
            noise=max(a['mean_range'] or 0,w['mean_range'] or 0)
            if delta is None or delta<=max(p['min_endpoint_separation'],p['min_separation_to_repeat_range']*noise):reasons.append('端差未超过已批准重复噪声/分离要求')
        sep['reference_reasons']=reasons
        if not reasons:
            sep['reference_status']='VALID_FOR_REFERENCE_TEST_ONLY' if synthetic else 'VALID_FOR_REFERENCE'
            parameters[str(c)]={'AIR_raw':a['endpoint_equal_run_weight'],'WATER_raw':w['endpoint_equal_run_weight'],
                'source_experiment_ids':[r['experiment_id'] for r in formal_runs], 'scope':'SYNTHETIC_TEST_ONLY' if synthetic else 'TEMPORARY_RELATIVE_INDEX_NOT_VWC',
                'ain2_included':False,'clip':False,'approval':policy['approval']}
        reference_reasons[str(c)]=reasons;separations.append(sep)
    unchanged(before)
    return {'source':'SYNTHETIC_TEST_ONLY' if synthetic else 'REAL_SENSOR','manifest':manifest,'input_manifest':before,
        'runs':runs,'statistics':stats,'repeatability':repeat,'separation':separations,'parameters':parameters,
        'invalid_records':invalid,'boundary_records':boundary,'field_log':field_doc,
        'threshold_status':'APPROVED_TEST_ONLY' if approved and synthetic else 'USER_SUPPLIED_APPROVAL_RECORDED' if approved else 'PENDING_USER_APPROVAL',
        'reference_reasons':reference_reasons,'failed_runs':global_reasons,
        'status':'FAILED_OR_INCOMPLETE' if global_reasons else 'REFERENCE_CANDIDATES_AVAILABLE' if parameters else 'REVIEW_REQUIRED',
        'hardware_acceptance':'NOT_ASSESSED','new_hardware_collection':False}


def export(result, directory):
    d=Path(directory)
    require(d.is_dir() and not any(d.iterdir()),'输出目录必须是新建空目录，禁止覆盖')
    inputs={path:{'path':path,**v} for path,v in result['input_manifest'].items()}
    for run in result['runs']:
        for path in run['inputs']:inputs[path].setdefault('experiment_ids',[]).append(run['experiment_id'])
    write_json(d/'input_manifest.json',inputs)
    integrity=[{k:v for k,v in r.items() if k!='rows'} for r in result['runs']]
    write_json(d/'run_integrity_report.json',integrity)
    (d/'run_integrity_report.md').write_text('# 三件套与会话核验\n\n来源：'+result['source']+'。文件与UART一致性不等于标定或硬件验收。\n\n'+ '\n'.join('- '+r['experiment_id']+'：'+r['status']+'；'+str(r['reasons']) for r in result['runs']),encoding='utf-8')
    tagged=lambda rows:[{'source':result['source'],**r} for r in rows]
    write_csv(d/'per_run_channel_statistics.csv',tagged(result['statistics']))
    write_csv(d/'six_run_repeatability.csv',tagged(result['repeatability']))
    write_csv(d/'air_water_endpoint_separation.csv',tagged(result['separation']))
    write_csv(d/'ain2_diagnostic_only.csv',tagged(s for s in result['statistics'] if s['channel']==2))
    write_csv(d/'invalid_and_missing_records.csv',tagged(result['invalid_records']))
    write_csv(d/'boundary_inflight_records.csv',tagged(result['boundary_records']))
    write_json(d/'field_log_used.json',result['field_log'])
    if result['parameters']:
        prefix='synthetic_' if result['source']=='SYNTHETIC_TEST_ONLY' else ''
        write_json(d/(prefix+'calibration_candidate_parameters.json'),{'source':result['source'],'channels':result['parameters'],'not_vwc':True})
        indices=[]
        for run in result['runs']:
            for r in run['rows']:
                p=result['parameters'].get(str(r['channel'])) if r['kind']=='soil' else None
                if p and r['validity']=='Valid' and r['raw'] is not None:
                    indices.append({'experiment_id':run['experiment_id'],'channel':r['channel'],'index':r['index'],'raw':r['raw'],
                                    'M':moisture(r['raw'],p['AIR_raw'],p['WATER_raw']),'source':result['source'],'clipped':False})
        write_csv(d/(prefix+'relative_moisture_indices.csv'),indices)
    summary='# ESP-IDF AIR/WATER离线分析\n\n来源：'+result['source']+'；状态：'+result['status']+'。\n\n阈值：'+result['threshold_status']+'。参数通道：'+str(list(result['parameters']))+'。\n\n'
    summary+='AIN2仅诊断；所有失败场、边界在途、Error/Unavailable原样保留。没有滤波、删点、补值或裁剪。清水端点不是VWC。\n\n'
    summary+='没有参数时不生成calibration_candidate_parameters.json；即使全部软件测试通过，也不是实测标定成功。\n\n'+json.dumps(result['reference_reasons'],ensure_ascii=False,indent=2)
    (d/'analysis_summary_zh.md').write_text(summary,encoding='utf-8')
    unchanged(result['input_manifest'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input',required=True);p.add_argument('--output-root',required=True)
    p.add_argument('--synthetic',action='store_true',help='仅SYNTHETIC合成夹具，不可混用真实输入')
    a=p.parse_args();out=new_output(a.output_root,'synthetic-analysis' if a.synthetic else 'analysis')
    try:
        descriptor_info=info(a.input)
        result=analyze_document(json_read(a.input),synthetic=a.synthetic)
        require(info(a.input)==descriptor_info,'分析输入描述文件改变')
        result['input_manifest'][str(Path(a.input).resolve())]=descriptor_info
        export(result,out)
        code=2 if result['status']=='FAILED_OR_INCOMPLETE' else 3 if result['status']=='REVIEW_REQUIRED' else 0
        print(json.dumps({'output':str(out),'status':result['status'],'source':result['source'],'exit_code':code},ensure_ascii=False))
        return code
    except (ValueError,OSError,KeyError,TypeError) as exc:
        failure={'status':'FAILED_OR_INCOMPLETE','reason':str(exc),'hardware_not_run':True,'input_descriptor':str(Path(a.input).resolve()),'source':'SYNTHETIC_TEST_ONLY' if a.synthetic else 'REAL_SENSOR_NOT_VERIFIED'}
        write_json(out/'analysis_failure.json',failure)
        # Schema/field-log failures must also leave auditable reports, never a fake empty success.
        metadata={'path':str(Path(a.input).resolve()),'status':'MISSING_OR_UNREADABLE'}
        try:metadata.update(info(a.input))
        except (ValueError,OSError):pass
        if not (out/'input_manifest.json').exists():write_json(out/'input_manifest.json',[metadata])
        if not (out/'run_integrity_report.json').exists():write_json(out/'run_integrity_report.json',[failure])
        if not (out/'run_integrity_report.md').exists():
            (out/'run_integrity_report.md').write_text('# 分析阻塞\n\n'+str(exc)+'\n\n未通过，不生成参考参数。',encoding='utf-8')
        for name in ('per_run_channel_statistics.csv','six_run_repeatability.csv','air_water_endpoint_separation.csv','ain2_diagnostic_only.csv','invalid_and_missing_records.csv','boundary_inflight_records.csv'):
            if not (out/name).exists():write_csv(out/name,[],['source','status','reason'])
        if not (out/'field_log_used.json').exists():write_json(out/'field_log_used.json',{'status':'NOT_VERIFIED','reason':str(exc)})
        if not (out/'analysis_summary_zh.md').exists():
            (out/'analysis_summary_zh.md').write_text('# 分析未完成\n\n'+str(exc)+'\n\n没有产生参考参数。没有硬件操作。',encoding='utf-8')
        print(json.dumps({'output':str(out),'reason':str(exc),'exit_code':2},ensure_ascii=False));return 2


if __name__=='__main__':
    raise SystemExit(main())
