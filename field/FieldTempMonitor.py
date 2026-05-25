"""
FieldTempMonitor.py — 下位机实时温度区域监测工具（优化版）

功能：
1. 连接热像仪，实时显示红外温度热图
2. 使用 OpenCV 内置工具圈选监测区域（更流畅）
3. 按 S 键开始录制温度数据
4. 按 Q 键停止录制并自动导出 CSV + 曲线图
5. 实时显示 ROI 区域的当前温度统计

优化内容：
- 单窗口显示（仅 IR 热图）
- 使用 JET 色彩映射（对比度更强）
- 简化 ROI 选择操作
- 确保温度单位为摄氏度（°C）

依赖：
  pip install numpy opencv-python matplotlib

运行方式：
  python FieldTempMonitor.py

操作说明：
  1. 程序启动后显示温度热图
  2. 按 R 键弹出 ROI 选择框（拖动鼠标框选，按 ENTER 确认）
  3. 按 S 键开始录制温度数据
  4. 按 Q 键停止录制并保存数据
  5. 按 ESC 退出程序
"""

import ctypes
import numpy as np
import cv2
import time
import os
import sys
from datetime import datetime
from ctypes import (
    c_int, c_int64, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p,
    POINTER, Structure, CFUNCTYPE, string_at, c_char
)
import threading
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ═══════════════════════════════════════════════════════════════════════════
# 设备参数（按实际情况修改）
# ═══════════════════════════════════════════════════════════════════════════
DEVICE_IP   = "192.168.1.123"
DEVICE_PORT = 80
USERNAME    = "admin"
PASSWORD    = "ZGTC2026"

# DLL 路径（sdk/ 目录）
_HERE     = os.path.dirname(os.path.abspath(__file__))
DLL_DIR   = os.path.join(_HERE, "..", "sdk")
DLL_PATH  = os.path.join(DLL_DIR, "IRCNetSDK.dll")

# 输出目录
_OUT_DIR      = os.path.join(_HERE, "..", "output")
os.makedirs(_OUT_DIR, exist_ok=True)
OUTPUT_PREFIX = os.path.join(_OUT_DIR, "temp_monitor")

# 伪彩色映射（JET 色彩对比度更强）
COLORMAP = cv2.COLORMAP_JET  # 可选：COLORMAP_INFERNO, COLORMAP_HOT, COLORMAP_RAINBOW

# ═══════════════════════════════════════════════════════════════════════════
# SDK 结构体定义
# ═══════════════════════════════════════════════════════════════════════════

class IRC_NET_LOGIN_INFO(Structure):
    _fields_ = [
        ("ip",       c_char * 16),
        ("port",     c_int),
        ("username", c_char * 256),
        ("password", c_char * 256),
    ]

class IRC_NET_TEMP_INFO_CB(Structure):
    _fields_ = [
        ("temp",   POINTER(c_uint8)),
        ("width",  c_int),
        ("height", c_int),
    ]

TEMP_CALLBACK = CFUNCTYPE(
    None, c_uint64, POINTER(IRC_NET_TEMP_INFO_CB), c_void_p, c_void_p
)

# ═══════════════════════════════════════════════════════════════════════════
# 全局状态
# ═══════════════════════════════════════════════════════════════════════════
latest_temp = None          # 最新一帧温度矩阵（float32，℃）
lock_temp = threading.Lock()

roi_rect = None             # ROI 区域 (x, y, w, h)
is_recording = False        # 是否正在录制
temp_stats_list = []        # 温度统计数据列表
start_time = None           # 录制开始时间
frame_count = 0             # 录制帧计数

# ═══════════════════════════════════════════════════════════════════════════
# DLL 加载与 SDK 初始化
# ═══════════════════════════════════════════════════════════════════════════

def load_dll():
    """加载 SDK DLL"""
    if not os.path.exists(DLL_PATH):
        print(f"[错误] DLL 文件不存在: {DLL_PATH}")
        sys.exit(1)
    
    os.add_dll_directory(DLL_DIR)
    dll = ctypes.CDLL(DLL_PATH)

    # IRC_NET_Init / Deinit
    dll.IRC_NET_Init.argtypes = []
    dll.IRC_NET_Init.restype  = c_int
    dll.IRC_NET_Deinit.argtypes = []
    dll.IRC_NET_Deinit.restype  = None

    # IRC_NET_Login / Logout
    dll.IRC_NET_Login.argtypes  = [POINTER(IRC_NET_LOGIN_INFO), POINTER(c_uint64)]
    dll.IRC_NET_Login.restype   = c_int
    dll.IRC_NET_Logout.argtypes = [c_uint64]
    dll.IRC_NET_Logout.restype  = c_int

    # IRC_NET_StartPullTemp_V2 / StopPullTemp
    dll.IRC_NET_StartPullTemp_V2.argtypes = [c_uint64, TEMP_CALLBACK, c_void_p]
    dll.IRC_NET_StartPullTemp_V2.restype  = c_int
    dll.IRC_NET_StopPullTemp.argtypes = [c_uint64]
    dll.IRC_NET_StopPullTemp.restype  = c_int

    return dll


def sdk_login(dll):
    """SDK 初始化 + 登录，返回 handle"""
    ret = dll.IRC_NET_Init()
    if ret != 0:
        print(f"[错误] SDK 初始化失败: {ret}")
        return None

    info = IRC_NET_LOGIN_INFO()
    info.ip       = DEVICE_IP.encode()
    info.port     = DEVICE_PORT
    info.username = USERNAME.encode()
    info.password = PASSWORD.encode()

    handle = c_uint64()
    ret = dll.IRC_NET_Login(ctypes.byref(info), ctypes.byref(handle))
    if ret != 0:
        print(f"[错误] 登录失败: {ret}")
        print(f"  请检查设备 IP ({DEVICE_IP}) 和密码是否正确")
        return None

    print(f"[成功] 已登录设备: {DEVICE_IP}")
    return handle.value


# ═══════════════════════════════════════════════════════════════════════════
# 温度回调函数
# ═══════════════════════════════════════════════════════════════════════════

def temp_callback(handle, temp_info, ext_info, user_data):
    """
    温度数据回调函数
    SDK 每收到一帧温度数据就会调用此函数
    
    温度数据格式：int16，单位 0.1 开尔文（K）
    需要转换：(值 / 10.0) - 273.15 = 摄氏度（°C）
    例如：值为 2935 → 293.5K → 20.35°C
    """
    global latest_temp, is_recording, temp_stats_list, start_time, frame_count, roi_rect

    if not temp_info:
        return

    info = temp_info.contents
    w, h = info.width, info.height

    # 解析温度数据（int16 格式，单位：0.1 开尔文）
    size = w * h * 2
    raw = string_at(info.temp, size)
    temp_int16 = np.frombuffer(raw, dtype=np.int16).reshape((h, w))
    
    # 转换为摄氏度：先除以 10.0 得到开尔文，再减去 273.15
    temp_celsius = temp_int16.astype(np.float32) / 10.0 - 273.15

    # 更新全局最新温度
    with lock_temp:
        latest_temp = temp_celsius.copy()

    # 如果正在录制且已选择 ROI，记录温度统计
    if is_recording and roi_rect is not None:
        x, y, rw, rh = roi_rect
        
        # 边界检查
        x = max(0, min(x, w - 1))
        y = max(0, min(y, h - 1))
        rw = min(rw, w - x)
        rh = min(rh, h - y)
        
        roi_data = temp_celsius[y:y+rh, x:x+rw]
        
        # 过滤异常值（传感器噪声）
        valid_data = roi_data[(roi_data > -50) & (roi_data < 2000)]
        
        if len(valid_data) > 0:
            elapsed = time.time() - start_time
            max_temp = float(np.max(valid_data))
            min_temp = float(np.min(valid_data))
            mean_temp = float(np.mean(valid_data))
            
            temp_stats_list.append({
                "frame": frame_count,
                "time_s": elapsed,
                "max": max_temp,
                "min": min_temp,
                "mean": mean_temp
            })
            
            frame_count += 1


# ═══════════════════════════════════════════════════════════════════════════
# 热图生成与显示
# ═══════════════════════════════════════════════════════════════════════════

def create_heatmap(temp_frame):
    """
    将温度数据转换为伪彩色热图（JET 色彩映射，对比度强）
    
    Args:
        temp_frame: 2D numpy array, 温度数据（摄氏度）
        
    Returns:
        heatmap_bgr: BGR 格式的伪彩色图像
        vmin, vmax: 实际使用的温度范围
    """
    # 使用全局温度范围（2% ~ 98% 分位数，避免极值影响显示）
    vmin = np.percentile(temp_frame, 2)
    vmax = np.percentile(temp_frame, 98)
    
    # 归一化到 0-255
    norm = np.clip((temp_frame - vmin) / (vmax - vmin + 1e-6), 0, 1)
    norm_u8 = (norm * 255).astype(np.uint8)
    
    # 应用伪彩色映射（JET：蓝色=冷，红色=热）
    heatmap_bgr = cv2.applyColorMap(norm_u8, COLORMAP)
    
    return heatmap_bgr, vmin, vmax


def draw_roi_on_image(img, roi, color=(0, 255, 0), thickness=2):
    """在图像上绘制 ROI 矩形框"""
    if roi is None:
        return img
    x, y, w, h = roi
    cv2.rectangle(img, (x, y), (x+w, y+h), color, thickness)
    return img


def draw_temp_stats(img, temp_frame, roi):
    """在图像上绘制温度统计信息"""
    if roi is None:
        return img
    
    x, y, w, h = roi
    H, W = temp_frame.shape
    
    # 边界检查
    x = max(0, min(x, W - 1))
    y = max(0, min(y, H - 1))
    w = min(w, W - x)
    h = min(h, H - y)
    
    roi_data = temp_frame[y:y+h, x:x+w]
    valid_data = roi_data[(roi_data > -50) & (roi_data < 2000)]
    
    if len(valid_data) == 0:
        return img
    
    max_temp = np.max(valid_data)
    min_temp = np.min(valid_data)
    mean_temp = np.mean(valid_data)
    
    # 绘制半透明背景
    overlay = img.copy()
    cv2.rectangle(overlay, (10, 10), (380, 130), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.7, img, 0.3, 0, img)
    
    # 绘制文本（更大字体，更清晰）
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, f"ROI Temperature Stats:", (20, 40), font, 0.7, (255, 255, 255), 2)
    cv2.putText(img, f"Max:  {max_temp:.1f} C", (20, 70), font, 0.7, (100, 100, 255), 2)
    cv2.putText(img, f"Min:  {min_temp:.1f} C", (20, 100), font, 0.7, (255, 100, 100), 2)
    cv2.putText(img, f"Mean: {mean_temp:.1f} C", (20, 130), font, 0.7, (100, 255, 100), 2)
    
    return img


def draw_colorbar(img, vmin, vmax):
    """在图像右侧绘制色标"""
    h, w = img.shape[:2]
    bar_width = 30
    bar_height = h - 100
    bar_x = w - bar_width - 20
    bar_y = 50
    
    # 创建色标
    gradient = np.linspace(255, 0, bar_height).astype(np.uint8)
    gradient = np.tile(gradient.reshape(-1, 1), (1, bar_width))
    colorbar = cv2.applyColorMap(gradient, COLORMAP)
    
    # 绘制色标
    img[bar_y:bar_y+bar_height, bar_x:bar_x+bar_width] = colorbar
    
    # 绘制边框
    cv2.rectangle(img, (bar_x, bar_y), (bar_x+bar_width, bar_y+bar_height), (255, 255, 255), 2)
    
    # 绘制温度标签
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, f"{vmax:.0f}C", (bar_x+bar_width+5, bar_y+15), font, 0.5, (255, 255, 255), 1)
    cv2.putText(img, f"{vmin:.0f}C", (bar_x+bar_width+5, bar_y+bar_height-5), font, 0.5, (255, 255, 255), 1)
    
    return img


# ═══════════════════════════════════════════════════════════════════════════
# 数据导出
# ═══════════════════════════════════════════════════════════════════════════

def export_to_csv(stats, output_path):
    """导出统计数据到 CSV 文件"""
    print(f"\n[导出] CSV 文件: {output_path}")
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("帧序号,时间(秒),最高温度(°C),最低温度(°C),平均温度(°C)\n")
        for s in stats:
            f.write(f"{s['frame']},{s['time_s']:.3f},{s['max']:.2f},{s['min']:.2f},{s['mean']:.2f}\n")
    
    print(f"[导出] 成功！共 {len(stats)} 行数据")


def plot_temperature_curve(stats, output_path):
    """绘制温度曲线图"""
    print(f"[绘图] 温度曲线: {output_path}")
    
    times = [s["time_s"] for s in stats]
    max_temps = [s["max"] for s in stats]
    min_temps = [s["min"] for s in stats]
    mean_temps = [s["mean"] for s in stats]
    
    fig, axes = plt.subplots(2, 1, figsize=(14, 10))
    
    # 子图 1: 平均温度曲线
    ax1 = axes[0]
    ax1.plot(times, mean_temps, color="orange", linewidth=2, label="Average Temperature")
    ax1.fill_between(times, min_temps, max_temps, alpha=0.2, color="gray", label="Temperature Range")
    ax1.set_xlabel("Time (seconds)", fontsize=12)
    ax1.set_ylabel("Temperature (°C)", fontsize=12)
    ax1.set_title("ROI Average Temperature vs Time", fontsize=14, fontweight="bold")
    ax1.legend(loc="best", fontsize=10)
    ax1.grid(True, alpha=0.3, linestyle="--")
    
    mean_avg = np.mean(mean_temps)
    mean_max = np.max(mean_temps)
    mean_min = np.min(mean_temps)
    info_text = f"Statistics:\n  Avg: {mean_avg:.2f}°C\n  Max: {mean_max:.2f}°C\n  Min: {mean_min:.2f}°C"
    ax1.text(0.02, 0.98, info_text, transform=ax1.transAxes, 
             fontsize=10, verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    
    # 子图 2: 最高/最低温度曲线
    ax2 = axes[1]
    ax2.plot(times, max_temps, color="red", linewidth=1.5, label="Max Temperature", alpha=0.8)
    ax2.plot(times, min_temps, color="blue", linewidth=1.5, label="Min Temperature", alpha=0.8)
    ax2.plot(times, mean_temps, color="orange", linewidth=1, label="Mean Temperature", alpha=0.6, linestyle="--")
    ax2.set_xlabel("Time (seconds)", fontsize=12)
    ax2.set_ylabel("Temperature (°C)", fontsize=12)
    ax2.set_title("ROI Temperature Range (Max/Min/Mean)", fontsize=14, fontweight="bold")
    ax2.legend(loc="best", fontsize=10)
    ax2.grid(True, alpha=0.3, linestyle="--")
    
    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    
    print(f"[绘图] 成功！")


def print_summary(stats):
    """打印统计摘要"""
    if len(stats) == 0:
        print("\n[提示] 没有录制数据")
        return
    
    mean_temps = [s["mean"] for s in stats]
    max_temps = [s["max"] for s in stats]
    min_temps = [s["min"] for s in stats]
    
    print("\n" + "="*70)
    print("温度监测统计摘要")
    print("="*70)
    print(f"总帧数        : {len(stats)}")
    print(f"总时长        : {stats[-1]['time_s']:.2f} 秒")
    print()
    print("平均温度统计:")
    print(f"  均值        : {np.mean(mean_temps):.2f} °C")
    print(f"  最高        : {np.max(mean_temps):.2f} °C")
    print(f"  最低        : {np.min(mean_temps):.2f} °C")
    print(f"  标准差      : {np.std(mean_temps):.2f} °C")
    print()
    print("全局温度范围:")
    print(f"  最高温度    : {np.max(max_temps):.2f} °C")
    print(f"  最低温度    : {np.min(min_temps):.2f} °C")
    print("="*70)


# ═══════════════════════════════════════════════════════════════════════════
# 主程序
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """主函数"""
    global is_recording, temp_stats_list, start_time, frame_count, roi_rect
    
    print("\n" + "="*70)
    print("下位机实时温度区域监测工具 (FieldTempMonitor - 优化版)")
    print("="*70)
    print(f"设备 IP: {DEVICE_IP}")
    print()
    print("操作说明:")
    print("  R 键 - 选择监测区域（弹出框选工具，拖动鼠标框选，按 ENTER 确认）")
    print("  S 键 - 开始录制温度数据")
    print("  Q 键 - 停止录制并保存数据")
    print("  ESC  - 退出程序")
    print()
    print("色彩说明:")
    print("  蓝色 = 低温    绿色 = 中温    红色 = 高温")
    print("="*70)
    
    # 加载 DLL 并登录
    dll = load_dll()
    handle = sdk_login(dll)
    if handle is None:
        print("[错误] 无法连接设备，程序退出")
        return
    
    # 启动温度拉流
    temp_cb = TEMP_CALLBACK(temp_callback)
    ret = dll.IRC_NET_StartPullTemp_V2(handle, temp_cb, None)
    if ret != 0:
        print(f"[错误] 启动温度拉流失败: {ret}")
        dll.IRC_NET_Logout(handle)
        dll.IRC_NET_Deinit()
        return
    
    print("[成功] 温度拉流已启动")
    print("\n等待温度数据...")
    
    # 等待第一帧数据
    while latest_temp is None:
        time.sleep(0.1)
    
    print("[成功] 收到温度数据，开始显示\n")
    
    # 创建显示窗口
    window_name = "IR Temperature Monitor - Press R to select ROI, S to start, Q to stop"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 800, 600)
    
    # 主循环
    try:
        while True:
            # 获取最新温度数据
            with lock_temp:
                if latest_temp is None:
                    time.sleep(0.01)
                    continue
                temp_frame = latest_temp.copy()
            
            # 生成热图
            heatmap, vmin, vmax = create_heatmap(temp_frame)
            
            # 放大显示（如果分辨率太小）
            H, W = temp_frame.shape
            if W < 400:
                scale = 3.0  # 固定放大3倍
                new_w = int(W * scale)
                new_h = int(H * scale)
                heatmap = cv2.resize(heatmap, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
                display_scale = scale
            else:
                display_scale = 1.0
            
            # 绘制色标
            heatmap = draw_colorbar(heatmap, vmin, vmax)
            
            # 绘制 ROI 框和温度统计
            if roi_rect is not None:
                scaled_roi = tuple(int(v * display_scale) for v in roi_rect)
                heatmap = draw_roi_on_image(heatmap, scaled_roi, (0, 255, 0), 3)
                heatmap = draw_temp_stats(heatmap, temp_frame, roi_rect)
            
            # 绘制状态信息
            status_y = heatmap.shape[0] - 20
            if is_recording:
                elapsed = time.time() - start_time
                status_text = f"RECORDING - {elapsed:.1f}s - {frame_count} frames"
                cv2.putText(heatmap, status_text, (10, status_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
            elif roi_rect is not None:
                status_text = "ROI selected - Press S to start recording"
                cv2.putText(heatmap, status_text, (10, status_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
            else:
                status_text = "Press R to select ROI"
                cv2.putText(heatmap, status_text, (10, status_y),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            # 显示热图
            cv2.imshow(window_name, heatmap)
            
            # 键盘控制
            key = cv2.waitKey(30) & 0xFF
            
            if key == ord('r') or key == ord('R'):
                # 使用 OpenCV 内置 ROI 选择工具
                if not is_recording:
                    print("\n[ROI] 请在弹出的窗口中框选监测区域...")
                    print("      拖动鼠标框选，按 ENTER 确认，按 C 取消")
                    
                    # 创建用于选择的热图
                    select_heatmap, _, _ = create_heatmap(temp_frame)
                    if W < 400:
                        select_heatmap = cv2.resize(select_heatmap, (int(W*display_scale), int(H*display_scale)), 
                                                    interpolation=cv2.INTER_NEAREST)
                    
                    # 使用 cv2.selectROI
                    roi_selected = cv2.selectROI("Select ROI - Press ENTER to confirm, C to cancel", 
                                                 select_heatmap, showCrosshair=True, fromCenter=False)
                    cv2.destroyWindow("Select ROI - Press ENTER to confirm, C to cancel")
                    
                    if roi_selected[2] > 0 and roi_selected[3] > 0:
                        # 缩放回原始坐标
                        roi_rect = tuple(int(v / display_scale) for v in roi_selected)
                        x, y, w, h = roi_rect
                        print(f"[ROI] 选择完成: x={x}, y={y}, w={w}, h={h}")
                    else:
                        print("[ROI] 取消选择")
                else:
                    print("[提示] 录制中无法重新选择 ROI")
            
            elif key == ord('s') or key == ord('S'):
                # 开始录制
                if roi_rect is None:
                    print("[提示] 请先按 R 键选择 ROI 区域")
                elif not is_recording:
                    is_recording = True
                    temp_stats_list = []
                    start_time = time.time()
                    frame_count = 0
                    print("\n[录制] 开始录制温度数据...")
                else:
                    print("[提示] 已经在录制中")
            
            elif key == ord('q') or key == ord('Q'):
                # 停止录制并保存
                if is_recording:
                    is_recording = False
                    print(f"\n[录制] 停止录制，共 {frame_count} 帧")
                    
                    if len(temp_stats_list) > 0:
                        # 生成文件名
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        csv_path = f"{OUTPUT_PREFIX}_{timestamp}.csv"
                        curve_path = f"{OUTPUT_PREFIX}_{timestamp}.png"
                        
                        # 导出数据
                        export_to_csv(temp_stats_list, csv_path)
                        plot_temperature_curve(temp_stats_list, curve_path)
                        print_summary(temp_stats_list)
                        
                        print(f"\n输出文件:")
                        print(f"  CSV 数据  : {csv_path}")
                        print(f"  温度曲线  : {curve_path}")
                    else:
                        print("[提示] 没有录制数据")
                else:
                    print("[提示] 当前未在录制")
            
            elif key == 27:  # ESC
                print("\n[退出] 用户按下 ESC 键")
                break
    
    except KeyboardInterrupt:
        print("\n[中断] 用户按下 Ctrl+C")
    
    finally:
        # 清理资源
        print("\n[清理] 停止温度拉流...")
        dll.IRC_NET_StopPullTemp(handle)
        dll.IRC_NET_Logout(handle)
        dll.IRC_NET_Deinit()
        cv2.destroyAllWindows()
        print("[清理] 完成")


if __name__ == "__main__":
    main()
