"""NODE01 20261122 Air-Water离线接入；相对指标不是VWC，不写Telemetry。"""
from __future__ import annotations
import argparse,csv,hashlib,io,json,math,statistics,zipfile
from pathlib import Path,PurePosixPath

VERSION='NODE01_AIR_WATER_20261122_REVIEW'
def digest(data):return hashlib.sha256(data).hexdigest()
def relative_percent(channel,raw,parameters):
    if type(channel) is not int or channel not in (0,1,2):raise ValueError('channel必须为0/1/2整数')
    if raw is None:return {'value':None,'flags':['MISSING'],'unit':'air_water_relative_percent'}
    if type(raw) not in (int,float) or not math.isfinite(raw) or not -32768<=raw<=32767:
        raise ValueError('raw必须为有效ADS1115有限读数或None')
    p=parameters[str(channel)];air,water=p['raw_air'],p['raw_water']
    if not all(math.isfinite(x) for x in (air,water)) or air<=water:raise ValueError('端点无效')
    value=(air-raw)/(air-water)*100
    return {'value':max(0.,min(100.,value)),'flags':[] if 0<=value<=100 else ['CLIPPED'],
            'unit':'air_water_relative_percent'}

def rows(data):
    return csv.DictReader(x for x in data.decode('utf-8-sig').splitlines() if not x.startswith('#'))

def build(archive,output):
    archive,output=Path(archive),Path(output)
    if output.exists():raise FileExistsError('请使用新的输出目录，禁止覆盖已有复核结果')
    output.mkdir(parents=True,exist_ok=False)
    before=digest(archive.read_bytes())
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        if len(names)!=len(set(names)):raise ValueError('ZIP重复成员名')
        bad=z.testzip()
        if bad:raise ValueError('ZIP CRC失败 '+bad)
        inventories=[{'member':i.filename,'bytes':i.file_size,'sha256':digest(z.read(i))}
                     for i in z.infolist() if not i.is_dir()]
        tables=[n for n in names if n.endswith('/air_water_calibration_parameters.csv')]
        if len(tables)!=1:raise ValueError('参数表不唯一')
        table=tables[0];base=str(PurePosixPath(table).parent)+'/'
        parameters={};checks=[]
        for record in csv.DictReader(io.StringIO(z.read(table).decode('utf-8-sig'))):
            ch=int(record['channel'])
            if str(ch) in parameters or ch not in (0,1,2):raise ValueError('参数通道重复或非法')
            ends={}
            for role in ('air','water'):
                member=base+record[role+'_csv'];data=z.read(member)
                actual=digest(data);parent=str(PurePosixPath(member).parent.parent)
                manifest=json.loads(z.read(parent+'/sha256.json').decode('utf-8-sig'))
                match=[v for v in manifest if v['Path'].replace('\\','/').endswith('/'+PurePosixPath(member).name)]
                if len(match)!=1 or match[0]['Hash'].lower()!=actual or match[0]['Bytes']!=len(data):
                    raise ValueError('原件清单哈希或大小不符 '+member)
                if record['firmware_elf_sha256'] not in data[:2500].decode('utf-8-sig'):raise ValueError('固件不一致')
                samples=[r for r in rows(data) if r['kind']=='soil' and int(r['channel'])==ch]
                valid=[r for r in samples if r['validity']=='Valid' and r['error']=='0']
                values=[int(r['soil_raw']) for r in valid];times=[int(r['acquired_uptime_us']) for r in valid]
                if len(values)!=int(record[role+'_valid_samples']) or len(valid)!=len(samples):raise ValueError('端点样本不匹配')
                if any(a>=b for a,b in zip(times,times[1:])):raise ValueError('端点时间不递增')
                med=statistics.median(values)
                if med!=float(record['raw_'+role+'_median']):raise ValueError('中位数与参数表不匹配')
                if min(values)!=float(record['raw_'+role+'_min']) or max(values)!=float(record['raw_'+role+'_max']):raise ValueError('极值不匹配')
                ends[role]=med
                checks.append({'channel':ch,'role':role,'member':member,'sha256':actual,'count':len(values),
                    'median':med,'min':min(values),'max':max(values),'duration_between_samples_s':(times[-1]-times[0])/1e6,
                    'median_abs_adjacent_difference':statistics.median(abs(a-b) for a,b in zip(values,values[1:])),
                    'has_beg':member[:-3]+'BEG' in names,'has_end':member[:-3]+'END' in names})
            if ends['air']-ends['water']!=float(record['span_raw']):raise ValueError('跨度不一致')
            parameters[str(ch)]={'raw_air':ends['air'],'raw_water':ends['water'],'span':ends['air']-ends['water']}
        if set(parameters)!={'0','1','2'}:raise ValueError('三通道参数不完整')
        config={'version':VERSION,'source_archive_sha256':before,'parameters':parameters,
            'unit':'air_water_relative_percent','vwc_calibrated':False,'risk_eligible':False,
            'firmware_elf_sha256':record['firmware_elf_sha256'],'status':'OFFLINE_REVIEW_ONLY'}
        count=0;members=[]
        with (output/'relative_observations.csv').open('w',encoding='utf-8-sig',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=['member','acquisition_index','acquired_uptime_us','channel','raw','validity','error','w_rel_pct','flags','calibration_version'])
            writer.writeheader()
            for member in names:
                if not member.startswith(base) or '/sd_original/' not in member or not member.endswith('.CSV'):continue
                data=z.read(member)
                if b'NODE01_ENGINEERING_DIAGNOSTIC_V1' not in data[:200]:continue
                header=data[:2500].decode('utf-8-sig');compatible=config['firmware_elf_sha256'] in header
                members.append({'member':member,'firmware_matches':compatible})
                for r in rows(data):
                    if r['kind']!='soil':continue
                    ch=int(r['channel']);valid=r['validity']=='Valid' and r['error']=='0'
                    converted=relative_percent(ch,int(r['soil_raw']),parameters) if valid and compatible else {'value':None,'flags':['INVALID_OR_INCOMPATIBLE_FIRMWARE']}
                    writer.writerow(dict(member=member,acquisition_index=r['acquisition_index'],acquired_uptime_us=r['acquired_uptime_us'],channel=ch,raw=r['soil_raw'],validity=r['validity'],error=r['error'],w_rel_pct=converted['value'],flags='|'.join(converted['flags']),calibration_version=VERSION));count+=1
    if digest(archive.read_bytes())!=before:raise ValueError('原件发生变化')
    report={'archive_sha256':before,'inventory':inventories,'endpoint_checks':checks,'converted_rows':count,'conversion_members':members,
        'limitations':['端点无BEG/END的情况仅完成清单哈希与CSV统计核验，不等同三件套验收','相对指标不能填入Telemetry体积含水率字段','AIN2可离线计算，但正式通道启用需三方确认','独立测角、土样真值、泵重复标定、新干土基线及13场历史仍待核对，未冻结风险阈值']}
    for name,value in [('parameters.json',config),('intake_report.json',report)]:
        (output/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'结果与后续事项.txt').write_text('2026-11-23 新标定接入结果\n端点三通道逐路原件哈希、固件、有效样本数、中位数、极值与参数表匹配。\n输出相对湿度，不是VWC；不改Telemetry、固件和正式风险。\n旧报告保留，新模块显式使用本批端点；不迁移旧阈值到新刻度。\n回算保留原始身份与原码，固件不匹配或无效行输出空值。\n缺项：独立0/15/30/45度测角与安装照片；真实土样VWC映射；泵五档重复和覆盖面积；合格新干土基线；13场历史与参数适用审核。\n先交何宇轩与李青原确认通道、单位及参数适用范围，再集成平台。\n原件未改动，风险阈值未冻结。详见intake_report.json。\n',encoding='utf-8')
    print(json.dumps({'endpoint_checks':checks,'converted_rows':count},ensure_ascii=False,indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',required=True);p.add_argument('--output',required=True);a=p.parse_args();build(a.archive,a.output)
