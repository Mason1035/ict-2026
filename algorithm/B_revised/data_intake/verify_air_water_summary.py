"""对8场交接汇总做逐通道原件重算，包括W01串口表。不拟合土样。"""
import argparse,csv,hashlib,io,json,statistics,zipfile
from pathlib import Path,PurePosixPath
from .air_water_20261122 import relative_percent,rows
from .air_water_adapter import load_parameters

def checked_record(headers,record):
    if len(set(headers))!=len(headers):raise ValueError('表头重复')
    if len(record)!=len(headers):return None
    return dict(zip(headers,record))

def run(archive,output):
    archive,output=Path(archive),Path(output)
    if output.exists():raise FileExistsError('请选择新输出目录')
    p=load_parameters();blob=archive.read_bytes()
    if hashlib.sha256(blob).hexdigest()!=p['source_archive_sha256']:raise ValueError('归档哈希不匹配')
    checks=[];observations=[];malformed=[]
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        summaries=[n for n in z.namelist() if n.endswith('/soil_calibration_summary.csv')]
        if len(summaries)!=1:raise ValueError('汇总表不唯一')
        member=summaries[0];base=str(PurePosixPath(member).parent)+'/'
        records=csv.reader(io.StringIO(z.read(member).decode('utf-8-sig')))
        headers=next(records)
        for row_number,record in enumerate(records,2):
            meta=checked_record(headers,record)
            if meta is None:
                malformed.append({'csv_line':row_number,'run_id':record[0] if record else None,
                    'expected_columns':len(headers),'actual_columns':len(record),
                    'status':'QUARANTINED_NOT_AUTO_REPAIRED'})
                continue
            source=base+meta['primary_soil_csv'];data=z.read(source)
            grouped={i:[] for i in range(3)}
            is_serial=meta['csv_has_comment_header']=='false'
            for r in rows(data):
                if r['kind']!='soil':continue
                ch=int(r['channel']);valid=r['validity']=='Valid' and r['error']=='0'
                raw=int(r['soil_raw']) if r['soil_raw'] else None
                v=relative_percent(ch,raw,p['parameters']) if valid else {'value':None,'flags':['INVALID']}
                observations.append({'run_id':meta['run_id'],'member':source,
                    'record_index':r['seq'] if is_serial else r['acquisition_index'],
                    'index_semantics':'SERIAL_RECORD_SEQ_NOT_TELEMETRY_SEQ' if is_serial else 'ACQUISITION_INDEX_NOT_TELEMETRY_SEQ',
                    'acquired_uptime_us':r['acquired_uptime_us'],'channel':ch,'raw':raw,
                    'validity':r['validity'],'error':r['error'],'reference_w_rel_pct':v['value'],
                    'usage':'DIAGNOSTIC_REFERENCE_PROJECTION_NOT_RUNTIME_CALIBRATION',
                    'firmware_matches':meta['app_elf_sha256']==p['firmware_elf_sha256']})
                if valid and raw is not None:grouped[ch].append(raw)
            for ch,values in grouped.items():
                if not values:raise ValueError('通道没有有效数据')
                computed={'valid':len(values),'median':statistics.median(values),'min':min(values),'max':max(values)}
                mismatches=[k for k,v in computed.items() if v!=float(meta[f'ain{ch}_{k}'])]
                ref=relative_percent(ch,computed['median'],p['parameters'])['value']
                published=float(meta[f'w_rel_ain{ch}_pct'])
                if abs(ref-published)>.005000001:mismatches.append('w_rel_pct_rounded_to_2_decimals')
                checks.append({'run_id':meta['run_id'],'channel':ch,**computed,'reference_w_rel_pct':ref,
                    'reported_w_rel_pct':published,'mismatches':mismatches,
                    'firmware_matches':meta['app_elf_sha256']==p['firmware_elf_sha256'],
                    'selected_for_endpoint_calibration':meta['use_for_calibration']=='true',
                    'source_sha256':hashlib.sha256(data).hexdigest()})
    output.mkdir(parents=True)
    report={'scope':'DIAGNOSTIC_ONLY','archive_sha256':p['source_archive_sha256'],
            'run_channels':len(checks),'observation_rows':len(observations),
            'mismatched_run_channels':sum(bool(c['mismatches']) for c in checks),'checks':checks,
            'malformed_summary_rows':malformed,'formal_training_ready':False,'thresholds_fitted':False,
            'warning':'跨固件投影仅用于复核交接表，不能当作可适用运行时标定。串口seq不是Telemetry序号。'}
    (output/'summary_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    for filename,records in [('run_channel_summary.csv',checks),('diagnostic_observations.csv',observations)]:
        with (output/filename).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)
    print(json.dumps({k:report[k] for k in ('run_channels','observation_rows','mismatched_run_channels','malformed_summary_rows')}))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();r=run(a.archive,a.output)
    raise SystemExit(1 if r['mismatched_run_channels'] or r['malformed_summary_rows'] else 0)
