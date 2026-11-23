"""新包IMU来源连续性、端点版本变化及集成门槛。只产出复核材料。"""
import argparse,csv,hashlib,json,zipfile
from pathlib import Path

def sha(b):return hashlib.sha256(b).hexdigest()
def run(root,output):
    root,output=Path(root),Path(output)
    if output.exists():raise FileExistsError('请使用新的输出目录，保留历史结果')
    b=Path(__file__).resolve().parent
    plan=json.loads((b/'calibration_batch_2026-11-12.json').read_text(encoding='utf-8'))
    old=root/'标定数据.zip';new=root/'NODE01_标定数据合集_20261122.zip'
    if sha(old.read_bytes())!=plan['archive_sha256']:raise ValueError('旧参考包哈希不匹配')
    selected=[plan['gyro']]+[p for paths in plan['faces'].values() for p in paths]
    checks=[]
    with zipfile.ZipFile(old) as a,zipfile.ZipFile(new) as z:
        for relative in selected:
            oldpath=plan['imu_root']+relative
            newpath='NODE01_标定数据合集_20261122/01_IMU标定/'+relative
            for extension in ('CSV','BEG','END'):
                op=oldpath[:-3]+extension;np=newpath[:-3]+extension
                checks.append({'old_member':op,'new_member':np,'identical':a.read(op)==z.read(np),
                               'old_sha256':sha(a.read(op)),'new_sha256':sha(z.read(np))})
    prior=root/'标定离线复核_2026-11-12/offline_review.json'
    imu=json.loads(prior.read_text(encoding='utf-8')) if prior.exists() else None
    reuse=all(c['identical'] for c in checks)
    blockers=[
      {'task':'正式IMU精度验收','owner':'A实操、C复核','needed':'独立0/15/30/45度真值及安装方向照片；相同原件重新打包不会补齐独立验证'},
      {'task':'土壤VWC映射','owner':'A实操、B拟合、C复核','needed':'对应土样真值、密度和传感器身份；Air-Water相对刻度不能充当VWC'},
      {'task':'新阈值冻结','owner':'A提供、B计算、C验收','needed':'新干土静态基线、已确认窗口和冻结纪律；不得用问题土样或降雨调参'},
      {'task':'雨强换算','owner':'A提供、C确认口径','needed':'五档各三次60秒称重、实测受雨面积及重复差异口径'},
      {'task':'正式平台集成','owner':'C与A、B共同确认','needed':'相对指标接口位置、R4适用性、AIN2用途和端点缺BEG/END替代验收'},
      {'task':'13场历史回算','owner':'A/C提供身份及适用关系、B回算','needed':'13场完整清单及对应固件/安装/标定适用证据；当前6117行不是13场历史验收'}]
    report={'new_archive_sha256':sha(new.read_bytes()),'imu_provenance_checks':checks,
            'selected_imu_triplet_files':len(checks),'imu_identical_to_previous':reuse,
            'previous_imu_report_sha256':sha(prior.read_bytes()) if imu else None,
            'imu_parameters_reused_for_review':imu.get('parameters') if imu and reuse else None,
            'formal_calibration_approved':False,'thresholds_generated':False,'blockers':blockers}
    output.mkdir(parents=True)
    (output/'followup_review.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    with (output/'待办与交接.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['task','owner','needed']);w.writeheader();w.writerows(blockers)
    text='新标定后续复核 2026-11-23\n\n'
    text+=f'选用IMU三件套共{len(checks)}个文件，与旧包逐字节一致：{reuse}。\n'
    text+='相同原件不重复宣称新实验；既有候选和留出问题仍适用，不自动批准加载。\n'
    text+='新土壤端点是独立Air-Water相对刻度；旧结果保留来源，新增结果不覆盖正式VWC。\n\n'
    text+='\n\n'.join(x['task']+'\n责任：'+x['owner']+'\n需要：'+x['needed'] for x in blockers)
    (output/'后续完成情况与停止点.txt').write_text(text,encoding='utf-8')
    print(json.dumps({'imu_files':len(checks),'identical':reuse,'blocking_tasks':len(blockers)},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();run(a.root,a.output)
