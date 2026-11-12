"""可追溯的台架标定候选统计。输出是 REVIEW_REQUIRED，不能加载到设备。"""
from __future__ import annotations

import argparse
import csv
import math
import statistics as stats
import sys
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_intake.engineering_archive import inspect_capture
from local_tools.common import dump, load, loads, sha256

ACC = tuple(f"a{a}_mps2" for a in "xyz")
GYRO = tuple(f"g{a}_dps" for a in "xyz")


def summarize(rows):
    if len(rows) < 2 or not all(math.isfinite(v) for _, v in rows):
        raise ValueError("至少需要两个有限有效观测")
    values = [v for _, v in rows]
    t0, t1 = rows[0][0], rows[-1][0]
    edge = (t1-t0) / 10
    return {"n": len(values), "mean": stats.fmean(values), "sample_sd": stats.stdev(values),
            "median": stats.median(values), "min": min(values), "max": max(values),
            "last_minus_first_10pct_time_mean": stats.fmean(v for t,v in rows if t >= t1-edge)
                                                - stats.fmean(v for t,v in rows if t <= t0+edge)}


def observations(data):
    series = defaultdict(list)
    reader = csv.DictReader(line for line in data.decode("utf-8-sig").splitlines() if not line.startswith("#"))
    for row in reader:
        if row["validity"] != "Valid" or row["error"] != "0":
            continue
        kind, channel = row["kind"], int(row["channel"])
        names = ACC+GYRO if kind == "imu" else ("soil_raw",)
        for k in names:
            series[kind,channel,k].append((int(row["acquired_uptime_us"]), float(row[k])))
    return {f"{kind}_{ch}": {field:summarize(series[kind,ch,field])
                              for field in (ACC+GYRO if kind=="imu" else ("soil_raw",))}
            for kind,ch in sorted({(kind,ch) for kind,ch,_ in series})}


def six_face(vectors, gravity):
    if not math.isfinite(gravity) or gravity <= 0 or set(vectors) != {s+a for s in "+-" for a in "XYZ"}:
        raise ValueError("六个方向和正重力参考必须齐全")
    for face, v in vectors.items():
        if len(v)!=3 or not all(math.isfinite(x) for x in v):
            raise ValueError(f"{face} 需要三轴有限数值")
        i = "XYZ".index(face[1]); signed = v[i] * (1 if face[0]=="+" else -1)
        if signed <= max(abs(v[j]) for j in range(3) if j!=i):
            raise ValueError(f"{face} 的符号或主轴与现场方向不一致")
    offsets, scales = {}, {}
    for i,axis in enumerate("XYZ"):
        plus, minus = vectors["+"+axis][i], vectors["-"+axis][i]
        offsets[axis]=(plus+minus)/2
        scales[axis]=(plus-minus)/(2*gravity)
    checks = {}
    for face,v in vectors.items():
        c=[(x-offsets[a])/scales[a] for a,x in zip("XYZ",v)]
        norm=math.hypot(*c)
        signed=c["XYZ".index(face[1])]*(1 if face[0]=="+" else -1)
        checks[face]={"corrected_mean_mps2":c,"norm_minus_g_mps2":norm-gravity,
                      "angle_to_nominal_face_deg":math.degrees(math.acos(max(-1.,min(1.,signed/norm))))}
    return {"offset_mps2":offsets,"scale_dimensionless":scales,
            "application":"(firmware_acceleration_mps2 - offset_mps2) / scale_dimensionless",
            "face_means_mps2":vectors,"in_sample_only":checks}


def pump_reference(spec):
    seconds, area = spec["seconds"], spec["top_area_m2"]
    if not all(math.isfinite(v) and v>0 for v in (seconds,area)):
        raise ValueError("称重时长和面积必须为正")
    rows=[]
    for pwm,mass,role in spec["readings"]:
        if not 0<=pwm<=100 or not math.isfinite(mass) or mass<0:
            raise ValueError("PWM 或称重值非法")
        flow=mass/seconds*60/1000
        rows.append({"pwm_pct":pwm,"mass_g":mass,"role":role,"flow_l_min_approx":flow,
                     "whole_top_area_equivalent_mm_h":flow*60/area})
    return {"source":spec["source"],"seconds":seconds,"top_area_m2":area,"rows":rows,
            "status":"SINGLE_MEASUREMENT_REFERENCE_NO_CURVE_NO_LOCAL_RAINFALL"}


def run(path, plan):
    digest=sha256(path)
    if digest!=plan["archive_sha256"]:
        raise ValueError("ZIP 哈希与本批选样清单不同；请重新核对选样")
    imu_root,soil_root=plan["imu_root"],plan["soil_root"]
    gyro_file=imu_root+plan["gyro"]
    faces={f:[imu_root+n for n in paths] for f,paths in plan["faces"].items()}
    soils={env:[soil_root+n for n in paths] for env,paths in plan["soil_repeats"].items()}
    chosen=[gyro_file]+[n for paths in (*faces.values(),*soils.values()) for n in paths]
    if len(chosen)!=len(set(chosen)) or any(not p for p in (*faces.values(),*soils.values())):
        raise ValueError("候选选样不能为空或重复")
    inventory={}
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)): raise ValueError("ZIP 有重复成员名")
        by_parent=defaultdict(list)
        for n in names:
            if n.endswith(".BEG"):
                by_parent[str(PurePosixPath(n).parent)].append((n,loads(z.read(n).decode("utf-8-sig"))))
        for n in (x for x in names if x.upper().endswith(".CSV")):
            end_name=n[:-3]+"END"
            entry={"selection":"CANDIDATE_INPUT" if n in chosen else "RETAINED_NOT_SELECTED"}
            inventory[n]=entry
            if end_name not in names:
                entry["integrity"]="MISSING_END"; continue
            end=loads(z.read(end_name).decode("utf-8-sig"))
            expected=PurePosixPath(n).name
            pairs=[(f,b) for f,b in by_parent[str(PurePosixPath(n).parent)]
                   if b.get("experiment_id")==end.get("experiment_id")
                   and PurePosixPath(b.get("csv","")).name==expected]
            if len(pairs)!=1 or PurePosixPath(end.get("csv","")).name!=expected:
                entry["integrity"]="MISSING_OR_AMBIGUOUS_BEG_IDENTITY"; continue
            f,begin=pairs[0]; data=z.read(n)
            result=inspect_capture(data,begin,end)
            entry.update(integrity=result["engineering_integrity"],issues=result["issues"],sha256=result["sha256"],
                         beg=f,end=end_name,experiment_id=result["experiment_id"],
                         duration_s=result["duration_seconds"],channels=result["channels"])
            # 问题轮仍保留完整性结果；只有通过工程核对才生成描述统计。
            if entry["integrity"]=="CHECKED": entry["observations"]=observations(data)
    for n in chosen:
        if inventory.get(n,{}).get("integrity")!="CHECKED": raise ValueError(f"候选输入工程核验失败：{n}")
    for n in [gyro_file]+[n for paths in faces.values() for n in paths]:
        c=inventory[n]
        minimum=300 if n==gyro_file else 30
        if c["duration_s"]<minimum or any(c["channels"][f"imu_{i}"]["valid_samples_per_capture_second"]<95 for i in (0,1)):
            raise ValueError(f"候选输入时长不足或触发 95 Hz 工程筛查：{n}")
    for n in [n for paths in soils.values() for n in paths]:
        if inventory[n]["duration_s"]<30 or any(inventory[n]["channels"][f"soil_{i}"]["validity"].get("Valid")!=60 for i in (0,1)):
            raise ValueError(f"AIR/WATER 正式重复不满足本批 30 秒、60 个有效样本记录：{n}")
    imu={}
    for i,role in enumerate(("TOP","TOE")):
        ch=f"imu_{i}"
        means={f:[stats.fmean(inventory[n]["observations"][ch][k]["mean"] for n in paths) for k in ACC]
               for f,paths in faces.items()}
        imu[role]={"gyro_candidate_dps":{k:inventory[gyro_file]["observations"][ch][k] for k in GYRO},
                   "accelerometer_candidate":six_face(means,plan["gravity_mps2"])}
    soil={}
    for i in (0,1):
        ch=f"soil_{i}"; soil[ch]={}
        for env,paths in soils.items():
            if len(paths)!=3: raise ValueError("需要三轮正式环境重复")
            rows=[{"member":n,**inventory[n]["observations"][ch]["soil_raw"]} for n in paths]
            means=[r["mean"] for r in rows]
            soil[ch][env]={"runs":rows,"mean_of_run_means":stats.fmean(means),"run_mean_range":max(means)-min(means)}
    return {"schema":"B.calibration_review.v1","status":"REVIEW_REQUIRED","archive_sha256":digest,
            "validated_for_runtime":False,"formal_training_ready":False,"thresholds_fitted":False,
            "selection":{"gyro":gyro_file,"faces":faces,"soil":soils,"min_imu_hz_engineering_screen_only":95},
            "imu":imu,"soil_air_water_reference_not_moisture":soil,"pump_reference":pump_reference(plan["pump"]),
            "inventory":inventory}


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",type=Path); p.add_argument("--output",required=True,type=Path)
    p.add_argument("--plan",type=Path,default=Path(__file__).with_name("calibration_batch_2026-11-12.json"))
    a=p.parse_args(); result=run(a.archive,load(a.plan)); result["plan_sha256"]=sha256(a.plan)
    dump(a.output,result); print(f"{result['status']}: {len(result['inventory'])} CSV; {a.output}")
