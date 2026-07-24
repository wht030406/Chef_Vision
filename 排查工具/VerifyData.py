"""
验证热像仪采集数据脚本
功能：
1. 检查 temp_matrices.npy 数据形状和温度范围
2. 可视化第一帧温度热力图
3. 统计全部帧的温度变化趋势
"""

import numpy as np
import os

# ============================================================
# 1. 加载数据
# ============================================================
# 默认验证主追踪温度数据；如需验证其它 .npy，改这里的文件名即可
_HERE    = os.path.dirname(os.path.abspath(__file__))
npy_path = os.path.join(_HERE, "..", "data", "temp_20260428_121546.npy")
if not os.path.exists(npy_path):
    print(f"[错误] 文件不存在: {npy_path}")
    print("请先用 field/FieldCapture.py 采集数据，或修改本脚本顶部的 npy_path")
    exit(1)

data = np.load(npy_path)

# ============================================================
# 2. 基本信息
# ============================================================
print("=" * 50)
print("温度数据基本信息")
print("=" * 50)
print(f"数据形状 (总帧数, 高度, 宽度): {data.shape}")
print(f"总共录制了 {data.shape[0]} 帧")
print(f"温度矩阵分辨率: {data.shape[2]} x {data.shape[1]} 像素")
print(f"数据类型: {data.dtype}")

# ============================================================
# 3. 第一帧详细检查
# ============================================================
first_frame = data[0]
print("\n" + "-" * 50)
print("第一帧温度检查:")
print(f"  最低温: {np.min(first_frame):.2f} ℃")
print(f"  最高温: {np.max(first_frame):.2f} ℃")
print(f"  平均温: {np.mean(first_frame):.2f} ℃")
print(f"  标准差: {np.std(first_frame):.2f} ℃")

h, w = first_frame.shape
center_temp = first_frame[h//2, w//2]
print(f"  画面中心点温度: {center_temp:.2f} ℃")

# 检查异常值
invalid_count = np.sum(first_frame < -50) + np.sum(first_frame > 2000)
print(f"  异常值数量（<-50℃ 或 >2000℃）: {invalid_count}")
if invalid_count == 0:
    print("  [OK] 数据范围正常")

# ============================================================
# 4. 全帧统计（温度随时间变化）
# ============================================================
print("\n" + "-" * 50)
print("全帧温度统计:")
frame_avg = [np.mean(data[i]) for i in range(len(data))]
frame_max = [np.max(data[i]) for i in range(len(data))]
frame_min = [np.min(data[i]) for i in range(len(data))]
print(f"  平均温度范围: {min(frame_avg):.2f}℃ ~ {max(frame_avg):.2f}℃")
print(f"  全局最高温度: {max(frame_max):.2f}℃  (第 {frame_max.index(max(frame_max))} 帧)")
print(f"  全局最低温度: {min(frame_min):.2f}℃  (第 {frame_min.index(min(frame_min))} 帧)")

# ============================================================
# 5. 可视化（尝试用 matplotlib，没安装则跳过）
# ============================================================
try:
    import matplotlib.pyplot as plt
    import matplotlib

    matplotlib.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
    matplotlib.rcParams['axes.unicode_minus'] = False

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # 左图：第一帧温度热力图
    im = axes[0].imshow(first_frame, cmap='jet', aspect='auto')
    axes[0].set_title(f'第一帧温度热力图\n范围: {np.min(first_frame):.1f}℃ ~ {np.max(first_frame):.1f}℃')
    axes[0].set_xlabel('像素列')
    axes[0].set_ylabel('像素行')
    plt.colorbar(im, ax=axes[0], label='温度 (℃)')

    # 在热力图上标注中心点
    axes[0].plot(w//2, h//2, 'w+', markersize=15, markeredgewidth=2)
    axes[0].annotate(f'{center_temp:.1f}℃',
                     xy=(w//2, h//2), xytext=(w//2+10, h//2-10),
                     color='white', fontsize=9,
                     arrowprops=dict(arrowstyle='->', color='white'))

    # 右图：平均温度随帧变化趋势
    frames = range(len(data))
    axes[1].plot(frames, frame_avg, label='平均温度', color='blue', linewidth=1.5)
    axes[1].plot(frames, frame_max, label='最高温度', color='red', linewidth=1, alpha=0.7)
    axes[1].plot(frames, frame_min, label='最低温度', color='cyan', linewidth=1, alpha=0.7)
    axes[1].set_title('温度随时间变化趋势')
    axes[1].set_xlabel('帧编号')
    axes[1].set_ylabel('温度 (℃)')
    axes[1].legend()
    axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    _out_verify = os.path.join(_HERE, "..", "output", "temp_verify.png")
    plt.savefig(_out_verify, dpi=150, bbox_inches='tight')
    print(f"\n[OK] 可视化图已保存: {_out_verify}")
    plt.show()
    print("[OK] 可视化窗口已打开（关闭窗口后程序结束）")

except ImportError:
    print("\n[提示] 未安装 matplotlib，跳过可视化")
    print("       安装命令: pip install matplotlib")

print("\n" + "=" * 50)
print("验证完成！")
print("=" * 50)
