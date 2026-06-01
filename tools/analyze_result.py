"""分析 food_temp_log.csv 追踪质量"""
import csv
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_CSV  = os.path.join(_HERE, "..", "output", "food_temp_log.csv")

times, masks, temps = [], [], []
with open(_CSV, "r") as f:
    reader = csv.DictReader(f)
    for row in reader:
        times.append(float(row["time_s"]))
        masks.append(float(row["mask_ratio"]))
        t = row["temp_mean"]
        temps.append(float(t) if t not in ("nan", "") else None)

total = len(masks)
zero_frames   = [(i, times[i]) for i, m in enumerate(masks) if m == 0]
big_frames    = [(i, times[i], masks[i]) for i, m in enumerate(masks) if m > 5]
normal_frames = [i for i, m in enumerate(masks) if 0 < m <= 5]
valid_temps   = [t for t in temps if t is not None]

print("=" * 55)
print(f"总帧数          : {total}")
print(f"mask=0  丢失    : {len(zero_frames)} 帧  ({len(zero_frames)/total*100:.1f}%)")
print(f"mask 0~5% 正常  : {len(normal_frames)} 帧  ({len(normal_frames)/total*100:.1f}%)")
print(f"mask >5% 扩张   : {len(big_frames)} 帧  ({len(big_frames)/total*100:.1f}%)")

if zero_frames:
    print(f"\n第一次 mask=0   : frame_rel={zero_frames[0][0]}  t={zero_frames[0][1]:.1f}s")
    print(f"最后 mask=0     : frame_rel={zero_frames[-1][0]}  t={zero_frames[-1][1]:.1f}s")

if big_frames:
    print(f"\n第一次 mask>5%  : frame_rel={big_frames[0][0]}  t={big_frames[0][1]:.1f}s  mask={big_frames[0][2]:.2f}%")
    print(f"最大 mask 值    : {max(m for _,_,m in big_frames):.2f}%")

print(f"\n有效温度帧      : {len(valid_temps)} / {total}")
if valid_temps:
    print(f"温度范围        : {min(valid_temps):.1f} ~ {max(valid_temps):.1f} °C")
    print(f"温度均值        : {sum(valid_temps)/len(valid_temps):.1f} °C")

# 打印批次交接处（每200帧）的 mask 值，验证跨批连续性
print("\n=== 批次交接处 mask (±2帧) ===")
boundaries = list(range(200, total, 200))
for b in boundaries:
    seg = []
    for offset in range(-2, 3):
        idx = b + offset
        if 0 <= idx < total:
            seg.append(f"  [{idx}] t={times[idx]:.1f}s mask={masks[idx]:.2f}%")
    print(f"--- 批次交接 frame_rel≈{b} ---")
    for s in seg:
        print(s)
