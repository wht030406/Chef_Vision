"""
TempMonitor.py — 独立的温度区域监测工具

功能：
1. 加载红外温度数据（.npy 文件）
2. 在第一帧热图上手动圈选监测区域（ROI）
3. 提取整个时间段内 ROI 区域的温度统计（每秒）
4. 导出 CSV 文件：时间、最高温、最低温、平均温
5. 生成平均温度随时间变化的曲线图

使用方法：
    python TempMonitor.py

注意：这是一个临时工具，与主项目的 SAM 追踪系统完全独立
"""

import os
import sys
import numpy as np
import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime

# ═══════════════════════════════════════════════════════════════════════════
# 配置参数
# ═══════════════════════════════════════════════════════════════════════════

_HERE = os.path.dirname(os.path.abspath(__file__))

# 输入文件（修改为你的温度数据文件）
TEMP_NPY_PATH = os.path.join(_HERE, "..", "data",   "temp_20260428_121546.npy")

# 输出文件
OUTPUT_CSV   = os.path.join(_HERE, "..", "output", "temp_monitor_log.csv")
OUTPUT_CURVE = os.path.join(_HERE, "..", "output", "temp_monitor_curve.png")

# 帧率（用于计算时间戳，根据实际情况调整）
FPS = 25.0

# 伪彩色显示范围（用于 ROI 选择时的热图显示）
# None = 自动根据数据范围调整
DISPLAY_TEMP_MIN = None  # 例如：20.0
DISPLAY_TEMP_MAX = None  # 例如：200.0

# ═══════════════════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════════════════

def load_temperature_data(npy_path):
    """
    加载温度数据文件
    
    Args:
        npy_path: .npy 文件路径
        
    Returns:
        data: numpy array, shape=(N, H, W) 或 (H, W)
        N: 帧数, H: 高度, W: 宽度
    """
    if not os.path.exists(npy_path):
        print(f"[错误] 文件不存在: {npy_path}")
        sys.exit(1)
    
    print(f"[加载] 温度数据: {npy_path}")
    data = np.load(npy_path)
    
    # 确保是 3D 数组 (N, H, W)
    if data.ndim == 2:
        data = data[np.newaxis, ...]
        print(f"[提示] 单帧数据，已扩展为 3D 数组")
    
    N, H, W = data.shape
    print(f"[加载] 数据形状: {data.shape}")
    print(f"[加载] 总帧数: {N}  分辨率: {W}x{H}")
    print(f"[加载] 温度范围: {data.min():.2f} ~ {data.max():.2f} °C")
    
    return data


def create_heatmap(temp_frame, vmin=None, vmax=None):
    """
    将温度数据转换为伪彩色热图（用于显示）
    
    Args:
        temp_frame: 2D numpy array, 温度数据
        vmin, vmax: 显示范围，None = 自动
        
    Returns:
        heatmap_bgr: BGR 格式的伪彩色图像
    """
    # 确定显示范围
    if vmin is None:
        vmin = np.percentile(temp_frame, 2)
    if vmax is None:
        vmax = np.percentile(temp_frame, 98)
    
    # 归一化到 0-255
    norm = np.clip((temp_frame - vmin) / (vmax - vmin + 1e-6), 0, 1)
    norm_u8 = (norm * 255).astype(np.uint8)
    
    # 应用伪彩色映射（INFERNO 热图）
    heatmap_bgr = cv2.applyColorMap(norm_u8, cv2.COLORMAP_INFERNO)
    
    return heatmap_bgr


def select_roi_interactive(first_frame, vmin=None, vmax=None):
    """
    交互式选择 ROI 区域
    
    Args:
        first_frame: 第一帧温度数据 (H, W)
        vmin, vmax: 显示范围
        
    Returns:
        roi: (x, y, w, h) 或 None（用户取消）
    """
    print("\n" + "="*70)
    print("ROI 选择说明：")
    print("  1. 在弹出的热图窗口中，用鼠标框选要监测的区域")
    print("  2. 按 ENTER 或 SPACE 确认选择")
    print("  3. 按 C 取消选择并重新框选")
    print("  4. 按 ESC 退出程序")
    print("="*70)
    
    # 生成热图
    heatmap = create_heatmap(first_frame, vmin, vmax)
    
    # 放大显示（如果分辨率太小）
    H, W = first_frame.shape
    if W < 400:
        scale = 400 / W
        new_w = int(W * scale)
        new_h = int(H * scale)
        heatmap = cv2.resize(heatmap, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
    
    # 添加温度信息文本
    info_text = f"Temp Range: {first_frame.min():.1f} ~ {first_frame.max():.1f} C"
    cv2.putText(heatmap, info_text, (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
    
    # 选择 ROI
    window_name = "Select ROI - Press ENTER to confirm, ESC to cancel"
    roi = cv2.selectROI(window_name, heatmap, showCrosshair=True, fromCenter=False)
    cv2.destroyAllWindows()
    
    # 如果用户取消（roi 全为 0）
    if roi[2] == 0 or roi[3] == 0:
        print("[提示] 用户取消选择")
        return None
    
    # 如果图像被放大过，需要缩放回原始坐标
    if W < 400:
        scale = W / 400
        roi = tuple(int(v * scale) for v in roi)
    
    x, y, w, h = roi
    print(f"\n[ROI] 选择完成: x={x}, y={y}, w={w}, h={h}")
    print(f"[ROI] 区域大小: {w}x{h} 像素")
    
    return roi


def extract_roi_stats(data, roi):
    """
    提取 ROI 区域的温度统计（所有帧）
    
    Args:
        data: 温度数据 (N, H, W)
        roi: (x, y, w, h)
        
    Returns:
        stats: list of dict, 每帧的统计数据
            [{"frame": int, "time_s": float, "max": float, "min": float, "mean": float}, ...]
    """
    x, y, w, h = roi
    N = data.shape[0]
    
    print(f"\n[处理] 开始提取 {N} 帧的温度统计...")
    
    stats = []
    for i in range(N):
        # 提取 ROI 区域
        roi_data = data[i, y:y+h, x:x+w]
        
        # 过滤异常值（可选）
        valid_data = roi_data[(roi_data > -50) & (roi_data < 2000)]
        
        if len(valid_data) == 0:
            # 如果没有有效数据，使用原始数据
            valid_data = roi_data.flatten()
        
        # 计算统计值
        time_s = i / FPS
        max_temp = float(np.max(valid_data))
        min_temp = float(np.min(valid_data))
        mean_temp = float(np.mean(valid_data))
        
        stats.append({
            "frame": i,
            "time_s": time_s,
            "max": max_temp,
            "min": min_temp,
            "mean": mean_temp
        })
        
        # 进度显示
        if (i + 1) % 100 == 0 or i == N - 1:
            print(f"  进度: {i+1}/{N} ({(i+1)/N*100:.1f}%)  "
                  f"当前帧: max={max_temp:.1f}°C  mean={mean_temp:.1f}°C")
    
    print(f"[处理] 完成！共处理 {N} 帧")
    return stats


def export_to_csv(stats, output_path):
    """
    导出统计数据到 CSV 文件
    
    Args:
        stats: 统计数据列表
        output_path: 输出文件路径
    """
    print(f"\n[导出] CSV 文件: {output_path}")
    
    with open(output_path, "w", encoding="utf-8") as f:
        # 写入表头
        f.write("帧序号,时间(秒),最高温度(°C),最低温度(°C),平均温度(°C)\n")
        
        # 写入数据
        for s in stats:
            f.write(f"{s['frame']},{s['time_s']:.3f},{s['max']:.2f},{s['min']:.2f},{s['mean']:.2f}\n")
    
    print(f"[导出] 成功！共 {len(stats)} 行数据")


def plot_temperature_curve(stats, output_path):
    """
    绘制温度曲线图
    
    Args:
        stats: 统计数据列表
        output_path: 输出图片路径
    """
    print(f"\n[绘图] 温度曲线: {output_path}")
    
    # 提取数据
    times = [s["time_s"] for s in stats]
    max_temps = [s["max"] for s in stats]
    min_temps = [s["min"] for s in stats]
    mean_temps = [s["mean"] for s in stats]
    
    # 创建图表
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    
    # ── 子图 1: 平均温度曲线 ──────────────────────────────────────────────
    ax1 = axes[0]
    ax1.plot(times, mean_temps, color="orange", linewidth=2, label="平均温度")
    ax1.fill_between(times, min_temps, max_temps, alpha=0.2, color="gray", label="温度范围 (最低~最高)")
    ax1.set_xlabel("时间 (秒)", fontsize=12)
    ax1.set_ylabel("温度 (°C)", fontsize=12)
    ax1.set_title("ROI 区域平均温度随时间变化", fontsize=14, fontweight="bold")
    ax1.legend(loc="best", fontsize=10)
    ax1.grid(True, alpha=0.3, linestyle="--")
    
    # 添加统计信息
    mean_avg = np.mean(mean_temps)
    mean_max = np.max(mean_temps)
    mean_min = np.min(mean_temps)
    info_text = f"平均温度统计:\n  均值: {mean_avg:.2f}°C\n  最高: {mean_max:.2f}°C\n  最低: {mean_min:.2f}°C"
    ax1.text(0.02, 0.98, info_text, transform=ax1.transAxes, 
             fontsize=10, verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    
    # ── 子图 2: 最高/最低温度曲线 ──────────────────────────────────────────
    ax2 = axes[1]
    ax2.plot(times, max_temps, color="red", linewidth=1.5, label="最高温度", alpha=0.8)
    ax2.plot(times, min_temps, color="blue", linewidth=1.5, label="最低温度", alpha=0.8)
    ax2.plot(times, mean_temps, color="orange", linewidth=1, label="平均温度", alpha=0.6, linestyle="--")
    ax2.set_xlabel("时间 (秒)", fontsize=12)
    ax2.set_ylabel("温度 (°C)", fontsize=12)
    ax2.set_title("ROI 区域温度范围（最高/最低/平均）", fontsize=14, fontweight="bold")
    ax2.legend(loc="best", fontsize=10)
    ax2.grid(True, alpha=0.3, linestyle="--")
    
    # 添加温度差统计
    temp_range_avg = np.mean([s["max"] - s["min"] for s in stats])
    info_text2 = f"温度差统计:\n  平均温差: {temp_range_avg:.2f}°C"
    ax2.text(0.02, 0.98, info_text2, transform=ax2.transAxes, 
             fontsize=10, verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.5))
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    
    print(f"[绘图] 成功！")


def print_summary(stats):
    """
    打印统计摘要
    
    Args:
        stats: 统计数据列表
    """
    mean_temps = [s["mean"] for s in stats]
    max_temps = [s["max"] for s in stats]
    min_temps = [s["min"] for s in stats]
    
    print("\n" + "="*70)
    print("温度监测统计摘要")
    print("="*70)
    print(f"总帧数        : {len(stats)}")
    print(f"总时长        : {stats[-1]['time_s']:.2f} 秒")
    print(f"帧率          : {FPS} FPS")
    print()
    print("平均温度统计:")
    print(f"  均值        : {np.mean(mean_temps):.2f} °C")
    print(f"  最高        : {np.max(mean_temps):.2f} °C  (第 {np.argmax(mean_temps)} 帧)")
    print(f"  最低        : {np.min(mean_temps):.2f} °C  (第 {np.argmin(mean_temps)} 帧)")
    print(f"  标准差      : {np.std(mean_temps):.2f} °C")
    print()
    print("全局温度范围:")
    print(f"  最高温度    : {np.max(max_temps):.2f} °C")
    print(f"  最低温度    : {np.min(min_temps):.2f} °C")
    print(f"  平均温差    : {np.mean([s['max'] - s['min'] for s in stats]):.2f} °C")
    print("="*70)


# ═══════════════════════════════════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """主函数"""
    print("\n" + "="*70)
    print("温度区域监测工具 (TempMonitor)")
    print("="*70)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # ── 步骤 1: 加载温度数据 ──────────────────────────────────────────────
    data = load_temperature_data(TEMP_NPY_PATH)
    
    # ── 步骤 2: 选择 ROI 区域 ─────────────────────────────────────────────
    first_frame = data[0]
    roi = select_roi_interactive(first_frame, DISPLAY_TEMP_MIN, DISPLAY_TEMP_MAX)
    
    if roi is None:
        print("\n[退出] 未选择 ROI，程序终止")
        return
    
    # ── 步骤 3: 提取温度统计 ──────────────────────────────────────────────
    stats = extract_roi_stats(data, roi)
    
    # ── 步骤 4: 导出 CSV ──────────────────────────────────────────────────
    export_to_csv(stats, OUTPUT_CSV)
    
    # ── 步骤 5: 绘制曲线图 ────────────────────────────────────────────────
    plot_temperature_curve(stats, OUTPUT_CURVE)
    
    # ── 步骤 6: 打印摘要 ──────────────────────────────────────────────────
    print_summary(stats)
    
    print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\n输出文件:")
    print(f"  CSV 数据  : {OUTPUT_CSV}")
    print(f"  温度曲线  : {OUTPUT_CURVE}")
    print("\n程序结束！")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消操作")
        sys.exit(0)
    except Exception as e:
        print(f"\n[错误] 程序异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
