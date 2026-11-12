"""可选 Matplotlib 绘图；分析核心无需第三方库。用装有 matplotlib 的 Python 运行。"""
import argparse
import csv
import hashlib
import html
import json
from pathlib import Path


def render(root):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    root=Path(root)
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8"))
    if manifest["schema"]!="B.engineering_exploration.v1": raise ValueError("分析类型不匹配")
    # 作图前复核输入统计文件，避免把被修改的汇总误称为原分析。
    for name,meta in manifest["files"].items():
        path=(root/name).resolve()
        if not path.is_relative_to(root.resolve()) or hashlib.sha256(path.read_bytes()).hexdigest()!=meta["sha256"]:
            raise ValueError("分析文件校验失败")
    out=root/"plots"; out.mkdir(exist_ok=False)
    blocks=[]
    for capture in manifest["captures"]:
        folder=(root/capture["directory"]).resolve()
        if folder.parent != root.resolve(): raise ValueError("场次目录超出分析目录")
        rows=list(csv.DictReader((folder/"bins.csv").open(encoding="utf-8-sig")))
        fig,axes=plt.subplots(5,1,figsize=(13,15),constrained_layout=True)
        series=[("soil",["soil_raw"],"ADC codes; probes uncalibrated"),
                ("imu_0",["ax_mps2","ay_mps2","az_mps2"],"TOP acceleration (m/s2, firmware converted)"),
                ("imu_1",["ax_mps2","ay_mps2","az_mps2"],"TOE acceleration (m/s2, firmware converted)"),
                ("imu_0",["gx_dps","gy_dps","gz_dps"],"TOP angular rate (deg/s, uncalibrated)"),
                ("imu_1",["gx_dps","gy_dps","gz_dps"],"TOE angular rate (deg/s, uncalibrated)")]
        for ax,(channel,metrics,title) in zip(axes,series):
            channels=["soil_0","soil_1","soil_2"] if channel=="soil" else [channel]
            for ch in channels:
                for metric in metrics:
                    r=sorted((x for x in rows if x["channel"]==ch and x["metric"]==metric),key=lambda x:float(x["bin_start_s"]))
                    if not r: continue
                    t=[float(x["bin_start_s"]) for x in r]
                    # 空箱断线，避免图上跨缺测区间连接成貌似连续的信号。
                    lookup={float(x["bin_start_s"]):x for x in r}
                    width=manifest["bin_us"]/1e6
                    grid=[round(t[0]+i*width,9) for i in range(round((t[-1]-t[0])/width)+1)]
                    if len(grid)>len(t):
                        r=[lookup.get(x,{"median":"nan","minimum":"nan","maximum":"nan"}) for x in grid]
                        t=grid
                    line,=ax.plot(t,[float(x["median"]) for x in r],label=ch+" "+metric,linewidth=1)
                    ax.fill_between(t,[float(x["minimum"]) for x in r],[float(x["maximum"]) for x in r],alpha=.18,color=line.get_color())
            ax.set_title(title); ax.set_xlabel("Device-relative seconds (bin start)")
            ax.grid(alpha=.2); ax.legend(loc="best",fontsize=8)
        fig.suptitle(capture["directory"]+" | EXPLORATORY ONLY\n"+str(manifest["bin_us"]/1e6)+" s bins: median and min/max envelope; no threshold")
        name=capture["directory"]+".png"; fig.savefig(out/name,dpi=130); plt.close(fig)
        changes=list(csv.DictReader((folder/"largest_changes.csv").open(encoding="utf-8-sig")))
        top=[x for x in changes if x["rank"]=="1"]
        tr=''.join('<tr>'+''.join('<td>'+html.escape(str(x[k]))+'</td>' for k in ("channel","metric","from_index","to_index","to_relative_s","absolute_change","unit"))+'</tr>' for x in top)
        blocks.append('<section><h2>'+html.escape(capture["source_member"])+'</h2><img src="'+name+'"><p>变化排名第一的原始相邻观测（不是异常标签）：</p><table><tr><th>通道</th><th>指标</th><th>起点 index</th><th>终点 index</th><th>相对秒</th><th>绝对变化</th><th>单位</th></tr>'+tr+'</table><p>完整变化排名、间隔排名及计数保存在对应场次 CSV。</p></section>')
    page='<!doctype html><meta charset="utf-8"><title>四场工程数据探索报告</title><style>body{font:16px sans-serif;margin:32px;max-width:1200px}img{width:100%}td,th{border:1px solid #ccc;padding:6px}table{border-collapse:collapse}section{margin:40px 0}</style><h1>四场工程数据探索报告</h1><p>真实传感器工程数据，未完成物理标定。R4 是雨后静置，不是干土基线。曲线、排名和分箱参数不构成阈值、校准、滑坡标签或因果结论。各探头 ADC 不能直接比较成含水量差异。</p>'+''.join(blocks)
    (out/"index.html").write_text(page,encoding="utf-8")
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/"plot_manifest.json").write_text(json.dumps({"scope":"UNCALIBRATED_EXPLORATION","files_sha256":hashes},indent=2),encoding="utf-8")
    print(out/"index.html")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("analysis_dir",type=Path)
    render(p.parse_args().analysis_dir)
