"""分析最新一次 TrackFood 运行结果"""
import csv, numpy as np, os, glob

# 找最新输出目录
out_dirs = sorted(glob.glob("output/2*"))
latest = out_dirs[-1] if out_dirs else None
if not latest:
    print("找不到输出目录"); exit()
print(f"分析目录: {latest}")

rows = list(csv.DictReader(open(f"{latest}/food_temp_log.csv")))
masks = [float(r["mask_ratio"]) for r in rows]
temps_raw = [r["temp_mean"] for r in rows]
temps = [float(t) for t in temps_raw if t != "nan"]

print(f"\n=== 基本统计 ===")
print(f"总帧数: {len(rows)}")
print(f"有效温度帧: {len(temps)} ({len(temps)/len(rows)*100:.1f}%)")
print(f"mask<0.1%帧数: {sum(1 for m in masks if m < 0.1)} ({sum(1 for m in masks if m < 0.1)/len(rows)*100:.1f}%)")
if temps:
    print(f"温度范围: {min(temps):.1f} ~ {max(temps):.1f}°C  均值: {np.mean(temps):.1f}°C")

print(f"\n=== 有mask但无温度 ===")
no_temp = [r for r in rows if float(r["mask_ratio"]) > 0.5 and r["temp_mean"] == "nan"]
has_temp = [r for r in rows if float(r["mask_ratio"]) > 0.5 and r["temp_mean"] != "nan"]
print(f"mask>0.5%的帧: {len(no_temp)+len(has_temp)}")
print(f"  有温度: {len(has_temp)}")
print(f"  无温度: {len(no_temp)}")
if no_temp:
    times = [float(r["time_s"]) for r in no_temp]
    print(f"  无温度帧时间范围: {min(times):.1f}s ~ {max(times):.1f}s")
    print(f"  前5帧示例:")
    for r in no_temp[:5]:
        print(f"    t={float(r['time_s']):.1f}s  mask={float(r['mask_ratio']):.1f}%  abs_frame={r['frame_abs']}")

print(f"\n=== mask丢失分析 ===")
lost_segments = []
in_lost = False
seg_start = None
for r in rows:
    if float(r["mask_ratio"]) < 0.1:
        if not in_lost:
            in_lost = True
            seg_start = float(r["time_s"])
    else:
        if in_lost:
            lost_segments.append((seg_start, float(r["time_s"])))
            in_lost = False
if in_lost:
    lost_segments.append((seg_start, float(rows[-1]["time_s"])))

print(f"mask丢失片段数: {len(lost_segments)}")
for s, e in lost_segments[:10]:
    print(f"  {s:.1f}s ~ {e:.1f}s  (持续 {e-s:.1f}s)")
