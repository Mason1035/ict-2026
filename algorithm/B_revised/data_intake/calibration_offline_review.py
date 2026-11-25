"""只用已核对标定包做离线校正和留出检查，不产生可加载配置。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import statistics as stats
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_intake.calibration_candidates import ACC, GYRO, run, six_face
from local_tools.common import dump, load, sha256

SCOPE = "OFFLINE_DIAGNOSTIC_NOT_DEVICE_CALIBRATION"
ROLES = ("TOP", "TOE")


def corrected_acceleration(raw, candidate):
    return tuple((value-candidate["offset_mps2"][axis])/candidate["scale_dimensionless"][axis]
                 for axis,value in zip("XYZ", raw, strict=True))


def face_check(raw, candidate, face, gravity):
    def metrics(vector):
        norm = math.hypot(*vector)
        signed = vector["XYZ".index(face[1])] * (1 if face[0] == "+" else -1)
        return {"mean_vector_mps2":list(vector), "norm_error_mps2":norm-gravity,
                "angle_to_nominal_deg":math.degrees(math.acos(max(-1.,min(1.,signed/norm)))) if norm else None}
    return {"raw":metrics(raw), "corrected":metrics(corrected_acceleration(raw,candidate))}


def gyro_time_holdout(points):
    """固定在时间跨度中点切分，只用前半段估计，后半段复核。"""
    if len(points)<4 or any(a[0]>=b[0] for a,b in zip(points,points[1:])):
        raise ValueError("陀螺留出需要足够且时间严格递增的样本")
    cut=(points[0][0]+points[-1][0])/2
    fit=[v for t,v in points if t<cut]
    test=[v for t,v in points if t>=cut]
    if len(fit)<2 or len(test)<2:
        raise ValueError("前后时段均需至少两个样本")
    offset=stats.fmean(fit)
    corrected=[v-offset for v in test]
    return {"split_uptime_us":cut,"fit_count":len(fit),"test_count":len(test),"fit_bias_dps":offset,
            "held_out_raw_mean_dps":stats.fmean(test),"held_out_corrected_mean_dps":stats.fmean(corrected),
            "held_out_raw_rms_dps":math.sqrt(stats.fmean(v*v for v in test)),
            "held_out_corrected_rms_dps":math.sqrt(stats.fmean(v*v for v in corrected)),
            "held_out_sample_sd_dps":stats.stdev(test)}


def repeat_holdout(runs):
    """留一轮，与另外两轮的参考均值比较，保留符号及轮次。"""
    if len(runs)!=3 or len({r["member"] for r in runs})!=3:
        raise ValueError("需要三个不同来源的环境重复")
    result=[]
    for i,held in enumerate(runs):
        fit=[r for j,r in enumerate(runs) if j!=i]
        ref=stats.fmean(r["mean"] for r in fit)
        result.append({"held_out":held["member"],"reference_members":[r["member"] for r in fit],
                       "reference_adc":ref,"held_out_adc":held["mean"],"difference_adc":held["mean"]-ref})
    return result


def csv_rows(z, name, evidence):
    data=z.read(name)
    if hashlib.sha256(data).hexdigest()!=evidence["sha256"]:
        raise ValueError("CSV 与候选报告不一致")
    return csv.DictReader(line for line in data.decode("utf-8-sig").splitlines() if not line.startswith("#"))


def review(archive, plan_path, output):
    output=Path(output)
    if output.exists():
        raise FileExistsError("输出目录已存在，拒绝覆盖")
    plan=load(plan_path)
    result=run(archive,plan)
    gravity=plan["gravity_mps2"]
    inventory=result["inventory"]
    faces=result["selection"]["faces"]
    static=result["selection"]["gyro"]
    outputs=[]
    report={"schema":"B.offline_calibration_check.v1","scope":SCOPE,"validated_for_runtime":False,
            "formal_training_ready":False,"thresholds_fitted":False,
            "archive_sha256":result["archive_sha256"],"plan_sha256":sha256(plan_path),
            "producer_sha256":sha256(Path(__file__)),
            "imu":{},"soil":{},"pump":result["pump_reference"],"files":outputs,
            "remaining":["INDEPENDENT_ANGLE_0_15_30_45_WITH_REFERENCE_AND_FIXTURE_EVIDENCE",
                         "SOIL_KNOWN_WATER_CONTENT_AND_AIN2_REPAIR_EVIDENCE",
                         "REPEATED_PUMP_WEIGHING_AND_MEASURED_SPRAY_AREA",
                         "NEW_DRY_SOIL_BASELINE_AND_CONFIRMED_FREEZE_METHOD"]}
    for i,role in enumerate(ROLES):
        acc=result["imu"][role]["accelerometer_candidate"]
        vectors=acc["face_means_mps2"]
        check={"fit_face_comparison":{f:face_check(v,acc,f,gravity) for f,v in vectors.items()},
               "plus_z_repeat_holdout":[],"gyro_same_capture_time_holdout":{}}
        # 只留出 +Z 的另一轮，其他五面没有独立重复，不能把这当六面完整验证。
        plus_z=faces["+Z"]
        if len(plus_z)==2:
            def mean(name):
                return [inventory[name]["observations"][f"imu_{i}"][k]["mean"] for k in ACC]
            for fit,held in (plus_z,plus_z[::-1]):
                local=six_face({**vectors,"+Z":mean(fit)},gravity)
                check["plus_z_repeat_holdout"].append({"fit_plus_z":fit,"held_out_plus_z":held,
                    **face_check(mean(held),local,"+Z",gravity)})
        report["imu"][role]=check
    for ch,envs in result["soil_air_water_reference_not_moisture"].items():
        report["soil"][ch]={env:repeat_holdout(item["runs"]) for env,item in envs.items()}

    output.mkdir(parents=True,exist_ok=False)
    files=[(static,"static")]+[(n,face) for face,paths in faces.items() for n in paths]
    times=defaultdict(list)
    raw_keys=ACC+GYRO
    corrected_keys=tuple("candidate_corrected_"+key for key in raw_keys)
    columns=("experiment_id","sensor","acquisition_index","acquired_uptime_us","validity","error","scope")
    with zipfile.ZipFile(archive) as z:
        for index,(member,kind) in enumerate(files,1):
            entry=inventory[member]
            path=output/f"imu_{index:02d}.csv"
            count=0
            with path.open("x",encoding="utf-8-sig",newline="") as f:
                writer=csv.DictWriter(f,fieldnames=[*columns,*raw_keys,*corrected_keys])
                writer.writeheader()
                for row in csv_rows(z,member,entry):
                    if row["kind"]!="imu": continue
                    role=ROLES[int(row["channel"])]
                    p=result["imu"][role]
                    record={key:row[key] for key in (*columns[2:6],*raw_keys)}
                    record.update(experiment_id=entry["experiment_id"],sensor=role,scope=SCOPE)
                    if row["validity"]=="Valid" and row["error"]=="0":
                        acc=corrected_acceleration([float(row[k]) for k in ACC],p["accelerometer_candidate"])
                        gyro=[float(row[k])-p["gyro_candidate_dps"][k]["mean"] for k in GYRO]
                        record.update(zip(corrected_keys,(*acc,*gyro),strict=True))
                        if kind=="static":
                            for k in GYRO:
                                times[role,k].append((int(row["acquired_uptime_us"]),float(row[k])))
                    writer.writerow(record)
                    count+=1
            outputs.append({"file":path.name,"rows":count,"sha256":sha256(path),"source_member":member,
                            "source_sha256":entry["sha256"],"condition":kind})
    for role in ROLES:
        report["imu"][role]["gyro_same_capture_time_holdout"]={k:gyro_time_holdout(times[role,k]) for k in GYRO}
    report["csv_parameters"]="full selected batch candidates; not the holdout estimates; not independently validated"
    report["parameters"]={role:{"gyro_bias_dps":{k:v["mean"] for k,v in p["gyro_candidate_dps"].items()},
                               "offset_mps2":p["accelerometer_candidate"]["offset_mps2"],
                               "scale_dimensionless":p["accelerometer_candidate"]["scale_dimensionless"]}
                          for role,p in result["imu"].items()}
    dump(output/"offline_review.json",report)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",type=Path); p.add_argument("--output",required=True,type=Path)
    p.add_argument("--plan",type=Path,default=Path(__file__).with_name("calibration_batch_2026-11-12.json"))
    a=p.parse_args(); result=review(a.archive,a.plan,a.output)
    print(f"{result['scope']}: {len(result['files'])} derived CSV; {a.output}")
