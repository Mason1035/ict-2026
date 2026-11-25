"""工程原始量的分箱统计与最大变化索引；不识别滑坡，不拟合阈值。"""
from __future__ import annotations

import argparse
import csv
import hashlib
import heapq
import io
import json
import math
import statistics
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from data_intake.engineering_archive import audit_archive
from local_tools.common import dump, loads, sha256

UNITS = {"soil_raw": "ADC_code", **{k: "m/s2_firmware_conversion_uncalibrated" for k in ("ax_mps2","ay_mps2","az_mps2")},
         **{k: "deg/s_firmware_conversion_uncalibrated" for k in ("gx_dps","gy_dps","gz_dps")}}


def describe(data, *, start_us, bin_us=1_000_000, top_n=20):
    if type(bin_us) is not int or bin_us <= 0 or type(top_n) is not int or top_n <= 0:
        raise ValueError("bin_us、top_n 需要显式正整数")
    bins, values = defaultdict(list), defaultdict(list)
    changes, gaps, previous = defaultdict(list), defaultdict(list), {}
    exclusions = []
    reader = csv.DictReader(line for line in data.decode("utf-8-sig").splitlines() if not line.startswith("#"))
    required = {"kind","channel","acquired_uptime_us","acquisition_index","validity","error",*UNITS}
    if not required <= set(reader.fieldnames or []):
        raise ValueError("工程 CSV 缺少原始量字段")
    for row in reader:
        key = row["kind"] + "_" + row["channel"]
        if key not in ("soil_0","soil_1","soil_2","imu_0","imu_1"):
            raise ValueError("未知通道身份")
        index = int(row["acquisition_index"])
        if row["validity"] != "Valid" or row["error"] != "0":
            previous.pop(key, None)
            exclusions.append({"channel":key,"acquisition_index":index,"reason":"INVALID_OR_ERROR_NO_BRIDGING"})
            continue
        t = int(row["acquired_uptime_us"])
        names = ["soil_raw"] if row["kind"] == "soil" else list(UNITS)[1:]
        sample = {name: float(row[name]) for name in names}
        if not all(math.isfinite(v) for v in sample.values()):
            raise ValueError("原始量包含非有限数值")
        prev = previous.get(key)
        if prev is not None:
            pt, pi, pv = prev
            if t <= pt:
                raise ValueError("通道时间倒退，停止跨边界计算变化")
            gap={"channel":key,"from_index":pi,"to_index":index,
                 "from_relative_s":(pt-start_us)/1e6,"to_relative_s":(t-start_us)/1e6,"interval_us":t-pt}
            heapq.heappush(gaps[key],(t-pt,-index,gap))
            if len(gaps[key])>top_n: heapq.heappop(gaps[key])
            for name, value in sample.items():
                change={"channel":key,"metric":name,"unit":UNITS[name],
                    "from_index":pi,"to_index":index,"from_relative_s":(pt-start_us)/1e6,
                    "to_relative_s":(t-start_us)/1e6,"before":pv[name],"after":value,
                    "signed_change":value-pv[name],"absolute_change":abs(value-pv[name])}
                heapq.heappush(changes[key,name],(change["absolute_change"],-index,change))
                if len(changes[key,name])>top_n: heapq.heappop(changes[key,name])
        previous[key] = t,index,sample
        for name, value in sample.items():
            bins[key,name,(t-start_us)//bin_us].append(value)
            values[key,name].append(value)
    if not values:
        raise ValueError("没有有效观测，不能输出空分析")
    summaries = []
    for (key,name), v in sorted(values.items()):
        summaries.append({"channel":key,"metric":name,"unit":UNITS[name],"count":len(v),
                          "minimum":min(v),"maximum":max(v),"median":statistics.median(v),
                          "mean":statistics.fmean(v),"population_std":statistics.pstdev(v)})
    binned = [{"channel":key,"metric":name,"unit":UNITS[name],"bin_start_s":b*bin_us/1e6,
               "count":len(v),"median":statistics.median(v),"minimum":min(v),"maximum":max(v)}
              for (key,name,b),v in sorted(bins.items())]
    ranked = []
    for v in changes.values():
        ranked.extend({"rank":i,**item} for i,(_,_,item) in enumerate(sorted(v,reverse=True),1))
    gap_rows = []
    for v in gaps.values():
        gap_rows.extend({"rank":i,**item} for i,(_,_,item) in enumerate(sorted(v,reverse=True),1))
    return {"summary":summaries,"bins":binned,"largest_changes":ranked,"largest_intervals":gap_rows,
            "exclusions":exclusions,"bin_us":bin_us,"top_n":top_n}


def write_csv(path, rows):
    if not rows:
        return
    with path.open("x",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def export_analysis(archive_path, output, *, bin_us=1_000_000, top_n=20):
    output=Path(output)
    if output.exists():
        raise FileExistsError("输出目录已存在，拒绝覆盖")
    audit=audit_archive(archive_path)
    if not audit["captures"] or any(c.get("engineering_integrity") != "CHECKED" or c.get("missing_companions") for c in audit["captures"]):
        raise ValueError("工程完整性或配套文件待核对，先处理质检问题")
    output.mkdir(parents=True,exist_ok=False)
    dump(output/"engineering_audit.json",audit)
    manifest={"schema":"B.engineering_exploration.v1","archive_sha256":audit["archive_sha256"],
              "scope":"REAL_ENGINEERING_UNCALIBRATED_EXPLORATION","formal_training_ready":False,
              "thresholds_fitted":False,"bin_us":bin_us,"top_n":top_n,"captures":[],"files":{}}
    with zipfile.ZipFile(archive_path) as z:
        for capture in audit["captures"]:
            name=capture["file"]; stem=name.rsplit(".",1)[0]
            end=loads(z.read(stem+".END").decode("utf-8-sig"))
            result=describe(z.read(name),start_us=end["start_us"],bin_us=bin_us,top_n=top_n)
            folder=output/Path(stem).name; folder.mkdir()
            for key in ("summary","bins","largest_changes","largest_intervals"):
                write_csv(folder/(key+".csv"),result[key])
            dump(folder/"excluded_observations.json",result["exclusions"])
            manifest["captures"].append({"directory":folder.name,"source_member":name,
                "experiment_id":capture["experiment_id"],"csv_sha256":capture["sha256"],
                "duration_s":capture["duration_seconds"],"excluded_count":len(result["exclusions"])})
    manifest["method_notes"]=["分箱仅用于探索显示，不是算法窗口或阈值；区间为左闭右开。",
        "每箱同时保留最小/最大值和计数，不以中位数曲线掩盖尖峰；原件未修改。",
        "变化排名是每通道/指标按幅度排序的人工复核入口，不是故障或滑坡事件判定。",
        "有效性失败切断相邻比较；有效观测的长时间间隔列于 interval 表，不隐式插值。",
        "不对不同场次作因果排序；R4 是雨后静置，不是干土基线；不推算含水量或雨强。"]
    manifest["producer_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    for p in sorted(output.rglob("*")):
        if p.is_file(): manifest["files"][p.relative_to(output).as_posix()]={"sha256":sha256(p),"bytes":p.stat().st_size}
    dump(output/"manifest.json",manifest)
    return manifest


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",type=Path); p.add_argument("--output",type=Path,required=True)
    p.add_argument("--bin-us",type=int,default=1_000_000); p.add_argument("--top-n",type=int,default=20)
    a=p.parse_args(); r=export_analysis(a.archive,a.output,bin_us=a.bin_us,top_n=a.top_n)
    print(json.dumps({"captures":len(r["captures"]),"output":str(a.output),"formal_training_ready":False},ensure_ascii=False))
