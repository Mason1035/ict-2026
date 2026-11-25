"""Trial VWC: independent derived values, never frozen Telemetry or risk."""
import argparse,csv,hashlib,io,json,math,statistics,zipfile
from pathlib import Path,PurePosixPath
VERSION='NEW_SOIL_VWC_TRIAL_20261124'
def sha(data):return hashlib.sha256(data).hexdigest()
def csv_rows(data):
    reader=csv.reader(io.StringIO(data.decode('utf-8-sig')));header=next(reader)
    for row in reader:
        if not row:continue
        if len(row)!=len(header):raise ValueError('CSV列数不一致')
        yield dict(zip(header,row))
def load_parameters():return json.loads(Path(__file__).with_suffix('.parameters.json').read_text(encoding='utf-8'))
def evaluate_trial(channel,soil_raw,parameters=None):
    p=load_parameters() if parameters is None else parameters
    if p['version']!=VERSION:raise ValueError('不支持的标定版本')
    if type(channel) is not int or channel not in (0,1,2):raise ValueError('通道必须为0/1/2')
    result={'soil_raw':soil_raw,'channel':channel,'vwc_est_pct':None,'vwc_calibration_version':p['version'],
            'w_rel_pct':None,'w_rel_calibration_version':p['air_water_version'],'in_range':None,
            'status':'TRIAL_OFFLINE_ONLY','risk_eligible':False,'flags':['CONDITIONAL_ESTIMATE_NOT_VALIDATED_VWC']}
    if soil_raw is None:result['flags'].append('MISSING');return result
    if type(soil_raw) not in (int,float) or not math.isfinite(soil_raw) or not -32768<=soil_raw<=32767:raise ValueError('ADC必须为有限有效读数')
    entry=p['channels'][str(channel)];points=entry['points']
    if len(points)!=3 or not all(a['raw']>b['raw'] and a['vwc_est_pct']<b['vwc_est_pct'] for a,b in zip(points,points[1:])):raise ValueError('插值节点必须单调')
    air,water=entry['raw_air'],entry['raw_water']
    if air<=water:raise ValueError('Air-Water端点非法')
    w=(air-soil_raw)/(air-water)*100;result['w_rel_pct']=max(0.,min(100.,w))
    if not 0<=w<=100:result['flags'].append('W_REL_CLIPPED')
    result['in_range']=points[-1]['raw']<=soil_raw<=points[0]['raw']
    if not result['in_range']:
        result['vwc_est_pct']=points[0 if soil_raw>points[0]['raw'] else -1]['vwc_est_pct']
        result['flags'].append('VWC_OUT_OF_CALIBRATION_RANGE_CLIPPED')
    else:
        for a,b in zip(points,points[1:]):
            if a['raw']>=soil_raw>=b['raw']:
                result['vwc_est_pct']=a['vwc_est_pct']+(b['vwc_est_pct']-a['vwc_est_pct'])*(a['raw']-soil_raw)/(a['raw']-b['raw']);break
    return result

def run(archive,output):
    archive,output=Path(archive),Path(output)
    if output.exists():raise FileExistsError('输出目录必须全新')
    blob=archive.read_bytes();config={'version':VERSION,'archive_sha256':sha(blob),'air_water_version':'NODE01_AIR_WATER_20261122_REVIEW',
        'status':'TRIAL_OFFLINE_ONLY','risk_eligible':False,'channels':{}}
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        if len(z.namelist())!=len(set(z.namelist())) or z.testzip():raise ValueError('ZIP CRC或重复成员错误')
        def unique(suffix):
            found=[n for n in z.namelist() if n.endswith('/'+suffix)]
            if len(found)!=1:raise ValueError('来源不唯一 '+suffix)
            return found[0]
        params=unique('vwc_calibration_20261124_parameters.csv');base=str(PurePosixPath(params).parent)+'/'
        airfile=unique('air_water_calibration_parameters.csv')
        airs={r['channel']:r for r in csv_rows(z.read(airfile))}
        summaries=list(csv_rows(z.read(unique('vwc_calibration_20261124_runs_summary.csv'))))
        series={};audits=[]
        for meta in summaries:
            run_id=meta['run_id'];prefix=base+run_id+'/'
            members=[n for n in z.namelist() if n.startswith(prefix+'analysis/') and n.endswith('_serial_soil_capture.csv')]
            if len(members)!=1:raise ValueError('串口原始表不唯一')
            member=members[0];data=z.read(member);manifest=json.loads(z.read(prefix+'sha256.json').decode('utf-8-sig'))
            if isinstance(manifest,dict):expected=manifest.get(member.removeprefix(prefix))
            else:
                matches=[r.get('Hash') for r in manifest if r.get('Path','').replace('\\','/').endswith('/'+member.removeprefix(prefix))]
                expected=matches[0] if len(matches)==1 else None
            matched=expected is not None and expected.lower()==sha(data)
            if expected is not None and not matched:raise ValueError('原件清单哈希不匹配 '+member)
            records=list(csv_rows(data));series[run_id]=(member,records)
            for ch in range(3):
                rows=[r for r in records if int(r['channel'])==ch];valid=[r for r in rows if r['validity']=='Valid' and r['error']=='0']
                values=[int(r['soil_raw']) for r in valid];times=[int(r['acquired_uptime_us']) for r in valid]
                if len(values)!=int(meta[f'ain{ch}_valid']) or statistics.median(values)!=float(meta[f'ain{ch}_raw_median']):raise ValueError('通道样本或中位数不匹配')
                if min(values)!=float(meta[f'ain{ch}_raw_min']) or max(values)!=float(meta[f'ain{ch}_raw_max']):raise ValueError('极值不匹配')
                if any(a>=b for a,b in zip(times,times[1:])):raise ValueError('通道时间倒退')
                audits.append({'run_id':run_id,'channel':ch,'count':len(values),'median':statistics.median(values),
                    'source_member':member,'source_sha256':sha(data),'manifest_hash_matched':matched,
                    'duration_between_samples_s':(times[-1]-times[0])/1e6})
        for r in csv_rows(z.read(params)):
            ch=r['channel'];a=airs[ch]
            if ch in config['channels'] or r['cal_version']!=VERSION:raise ValueError('参数版本或通道重复')
            points=[]
            for prefix,field in [('dry_ref','dry_ref_vwc_pct'),('wet1','wet1_est_vwc_pct'),('wet2','wet2_est_vwc_pct')]:
                run_id=r[prefix+'_run_id'];raw=float(r[prefix+'_raw_median'])
                proof=next(v for v in audits if v['run_id']==run_id and v['channel']==int(ch))
                if raw!=proof['median']:raise ValueError('插值点与原始中位数不同')
                points.append({'raw':raw,'vwc_est_pct':float(r[field]),'run_id':run_id,'source_sha256':proof['source_sha256'],'depth_cm_approx':float(r[prefix+'_depth_cm_approx'])})
            config['channels'][ch]={'points':points,'raw_air':float(a['raw_air_median']),'raw_water':float(a['raw_water_median']),'notes':r['notes']}
        if set(config['channels'])!={'0','1','2'}:raise ValueError('通道不齐全')
        output.mkdir(parents=True)
        with (output/'derived_observations.jsonl').open('w',encoding='utf-8') as f:
            count=0
            for run_id,(member,records) in series.items():
                for r in records:
                    valid=r['validity']=='Valid' and r['error']=='0'
                    result=evaluate_trial(int(r['channel']),int(r['soil_raw']) if valid else None,config)
                    result['selected_calibration_run_channel']=any(p['run_id']==run_id for p in config['channels'][r['channel']]['points'])
                    if not result['selected_calibration_run_channel']:result['flags'].append('DIAGNOSTIC_NOT_FIT_INPUT')
                    result.update(run_id=run_id,source_member=member,source_record_seq=r['seq'],acquired_uptime_us=r['acquired_uptime_us'],validity=r['validity'],error=r['error'],original_soil_raw=r['soil_raw'],seq_semantics='SERIAL_RECORD_NOT_TELEMETRY_SEQ')
                    if not valid:result['flags'].append('INVALID_OBSERVATION')
                    f.write(json.dumps(result,ensure_ascii=False)+'\n');count+=1
        pump=list(csv_rows(z.read(unique('pump_pwm_calibration_summary.csv'))));pump_checks=[]
        for r in pump:
            if not r['mass_loss_g']:continue
            flow=float(r['mass_loss_g'])/float(r['test_duration_s'])*60/1000
            if abs(flow-float(r['flow_l_per_min']))>1e-8:raise ValueError('水泵流量换算不一致')
            pump_checks.append({'pwm_pct':r['pwm_pct'],'rain_level':r['rain_level'],'status':r['status'],'reference_flow_l_min':flow,
                'estimated_area_0_0651_mm_h':flow*60/.0651,'top_area_0_1152_mm_h':flow*60/.1152,'field_rainfall_validated':False})
        report={'archive_sha256':sha(blob),'checks':audits,'derived_rows':count,'pump_checks':pump_checks,
            'limitations':['三档为假设与条件估计，未给出独立精度','干点约3cm，湿点约2cm','第二湿点采用f17ee9串口固件，跨固件适用性待复核','测后质量减少1.4g，可能约2.4个百分点影响','120秒干土采集不替代>=300秒系统静态基线','水泵为5秒单次参考，面积含估计口径','不更新正式Telemetry/风险，不发布阈值']}
        for name,obj in [('trial_parameters.json',config),('intake_report.json',report)]:
            (output/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
    if sha(archive.read_bytes())!=config['archive_sha256']:raise ValueError('原始包发生变化')
    print(json.dumps({'derived_rows':count,'run_channel_checks':len(audits),'manifest_matches':sum(v['manifest_hash_matched'] for v in audits)}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.archive,a.output)
