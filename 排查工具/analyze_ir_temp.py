"""
analyze_ir_temp.py — 分析红外温度数据分布
目的：验证锅壁 vs 食材温度差异是否足够大，为选择新的分割方案提供依据

输出：
  - ir_temp_stats.txt     全局温度统计摘要
  - ir_heatmap_*.jpg      若干关键帧热图可视化（伪彩色）
  - ir_hist_*.jpg         若干关键帧温度直方图（判断是否有双峰，即可分割）
"""

import numpy as np
import cv2
import os
import argparse
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── 配置 ──────────────────────────────────────────────────────────────────────
_HERE      = os.path.dirname(os.path.abspath(__file__))
parser = argparse.ArgumentParser(description="分析指定红外温度矩阵的温度分布")
parser.add_argument("--npy", required=True, help="温度矩阵 .npy 路径")
parser.add_argument("--out", default=os.path.join(_HERE, "..", "output", "ir_analysis"),
                    help="输出目录")
args = parser.parse_args()
TEMP_NPY   = args.npy
OUT_DIR    = args.out
os.makedirs(OUT_DIR, exist_ok=True)

# 要分析的帧索引（绝对帧号，和 RGB 视频对齐）
# 根据 food_temp_log.csv：追踪起始帧=780，对应 temp 数据第0帧
# 这里分析整个温度序列
SAMPLE_FRAMES = [0, 50, 100, 200, 400, 600, 800, 1000, 1200, 1500, 1800, 2000]

# ── 加载数据 ──────────────────────────────────────────────────────────────────
print(f"[加载] {TEMP_NPY}")
data = np.load(TEMP_NPY)
if data.ndim == 2:
    data = data[np.newaxis, ...]
print(f"[加载] shape={data.shape}  dtype={data.dtype}")
print(f"[加载] 总帧数={data.shape[0]}  IR分辨率={data.shape[2]}x{data.shape[1]}")

N, H, W = data.shape

# ── 全局统计 ──────────────────────────────────────────────────────────────────
flat = data.reshape(-1)
# 过滤掉明显异常值（传感器噪声）
valid = flat[(flat > -50) & (flat < 2000)]

stats_lines = [
    "=" * 50,
    "红外温度数据全局统计",
    "=" * 50,
    f"总帧数       : {N}",
    f"IR 分辨率    : {W} x {H}",
    f"全局最小温度 : {valid.min():.2f} °C",
    f"全局最大温度 : {valid.max():.2f} °C",
    f"全局均值     : {valid.mean():.2f} °C",
    f"全局中位数   : {np.median(valid):.2f} °C",
    f"全局标准差   : {valid.std():.2f} °C",
    f"5%  分位     : {np.percentile(valid, 5):.2f} °C",
    f"25% 分位     : {np.percentile(valid, 25):.2f} °C",
    f"75% 分位     : {np.percentile(valid, 75):.2f} °C",
    f"95% 分位     : {np.percentile(valid, 95):.2f} °C",
    "",
]

print("\n".join(stats_lines))

# 逐帧统计（均值/最大/最小随时间变化）
frame_means = []
frame_maxs  = []
frame_mins  = []
for i in range(N):
    f = data[i].flatten()
    f = f[(f > -50) & (f < 2000)]
    frame_means.append(float(np.mean(f)) if len(f) > 0 else float("nan"))
    frame_maxs.append(float(np.max(f))  if len(f) > 0 else float("nan"))
    frame_mins.append(float(np.min(f))  if len(f) > 0 else float("nan"))

frame_means = np.array(frame_means)
frame_maxs  = np.array(frame_maxs)
frame_mins  = np.array(frame_mins)

stats_lines += [
    "帧均值统计（逐帧）:",
    f"  均值的均值   : {np.nanmean(frame_means):.2f} °C",
    f"  均值的最大值 : {np.nanmax(frame_means):.2f} °C（最热帧）",
    f"  均值的最小值 : {np.nanmin(frame_means):.2f} °C（最冷帧）",
    f"  最高温的均值 : {np.nanmean(frame_maxs):.2f} °C（各帧最大值平均）",
    f"  最高温的最大值: {np.nanmax(frame_maxs):.2f} °C（全局最高点）",
    "",
    "提示：",
    "  若 '最高温' >> '均值' → 热图中存在明显高温区域（锅壁或食材）",
    "  若温度直方图呈双峰 → 可用阈值分割食材 vs 锅壁",
]

# 保存统计文本
stats_path = os.path.join(OUT_DIR, "ir_temp_stats.txt")
with open(stats_path, "w", encoding="utf-8") as f:
    f.write("\n".join(stats_lines))
print(f"\n[统计] 已保存: {stats_path}")

# ── 绘制帧均值随时间变化曲线 ──────────────────────────────────────────────────
fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True)
t = np.arange(N)

axes[0].plot(t, frame_means, color="orange", linewidth=1, label="帧均值温度")
axes[0].set_ylabel("温度 (°C)")
axes[0].set_title("红外帧均值温度随时间变化")
axes[0].legend()
axes[0].grid(True, alpha=0.3)

axes[1].plot(t, frame_maxs, color="red", linewidth=0.8, label="帧最高温度", alpha=0.7)
axes[1].plot(t, frame_mins, color="blue", linewidth=0.8, label="帧最低温度", alpha=0.7)
axes[1].set_ylabel("温度 (°C)")
axes[1].set_title("红外帧最高/最低温度随时间变化")
axes[1].legend()
axes[1].grid(True, alpha=0.3)

axes[2].fill_between(t, frame_mins, frame_maxs, alpha=0.3, color="gray", label="温度范围")
axes[2].plot(t, frame_means, color="orange", linewidth=1, label="均值")
axes[2].set_xlabel("帧序号（相对于 temp.npy 第0帧）")
axes[2].set_ylabel("温度 (°C)")
axes[2].set_title("温度分布范围（min~max区间）")
axes[2].legend()
axes[2].grid(True, alpha=0.3)

plt.tight_layout()
curve_path = os.path.join(OUT_DIR, "ir_temp_curve.png")
plt.savefig(curve_path, dpi=120)
plt.close()
print(f"[曲线] 已保存: {curve_path}")

# ── 关键帧热图 + 直方图 ───────────────────────────────────────────────────────
print(f"\n[关键帧] 生成 {len(SAMPLE_FRAMES)} 帧热图...")

# 确定伪彩色范围（用全局5%~95%分位，避免极值影响显示）
vmin = np.percentile(valid, 2)
vmax = np.percentile(valid, 98)
print(f"[热图] 伪彩色范围: {vmin:.1f} ~ {vmax:.1f} °C")

for fi in SAMPLE_FRAMES:
    if fi >= N:
        continue
    frame_data = data[fi]
    fv = frame_data.flatten()
    fv = fv[(fv > -50) & (fv < 2000)]
    if len(fv) == 0:
        continue

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    # 左：伪彩色热图
    norm = np.clip((frame_data - vmin) / (vmax - vmin + 1e-6), 0, 1)
    norm_u8 = (norm * 255).astype(np.uint8)
    heatmap = cv2.applyColorMap(norm_u8, cv2.COLORMAP_INFERNO)
    heatmap_rgb = cv2.cvtColor(heatmap, cv2.COLOR_BGR2RGB)
    im = ax1.imshow(heatmap_rgb)
    ax1.set_title(f"IR 热图  frame={fi}  mean={np.mean(fv):.1f}°C  max={np.max(fv):.1f}°C")
    ax1.axis("off")
    # 添加 colorbar（用虚拟 imshow）
    scalar = ax1.imshow([[vmin, vmax]], cmap="inferno", visible=False)
    plt.colorbar(scalar, ax=ax1, label="温度 (°C)", fraction=0.046, pad=0.04)

    # 右：温度直方图（判断是否有双峰）
    ax2.hist(fv, bins=80, color="steelblue", edgecolor="none", alpha=0.8)
    ax2.axvline(np.mean(fv),   color="orange", linewidth=2, label=f"均值={np.mean(fv):.1f}°C")
    ax2.axvline(np.median(fv), color="green",  linewidth=1.5, linestyle="--",
                label=f"中位数={np.median(fv):.1f}°C")
    ax2.set_xlabel("温度 (°C)")
    ax2.set_ylabel("像素数")
    ax2.set_title(f"温度直方图  frame={fi}\n"
                  f"min={np.min(fv):.1f}  max={np.max(fv):.1f}  std={np.std(fv):.1f}°C")
    ax2.legend()
    ax2.grid(True, alpha=0.3)

    plt.tight_layout()
    out_path = os.path.join(OUT_DIR, f"ir_frame_{fi:04d}.png")
    plt.savefig(out_path, dpi=100)
    plt.close()
    print(f"  frame {fi:4d}: mean={np.mean(fv):.1f}°C  max={np.max(fv):.1f}°C  → {out_path}")

# ── 判断建议 ──────────────────────────────────────────────────────────────────
print("\n" + "=" * 50)
print("分析完成！请查看以下输出：")
print(f"  统计文本  : {stats_path}")
print(f"  温度曲线  : {curve_path}")
print(f"  关键帧热图: {OUT_DIR}/ir_frame_XXXX.png")
print("=" * 50)
print("\n判断方法：")
print("  1. 查看直方图：若呈现明显双峰 → 可用阈值分割锅壁 vs 食材")
print("  2. 查看热图：高温（亮白/黄色）区域是锅壁，中温区域是食材")
print("  3. 若 max 远大于 mean（差值 > 50°C）→ 锅壁温度显著高于食材，可分割")
print("  4. 若 max ≈ mean → 温度分布均匀，需要用 RGB 锅口 ROI 辅助")
