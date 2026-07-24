"""
FieldTempMonitor.py — 下位机实时温度区域监测工具

功能：
1. 连接热像仪，实时显示 RGB 视频 + 红外温度热图（双窗口）
2. 按 R 键圈选监测区域（ROI）
3. 按 S 键开始录制温度数据
4. 按 Q 键停止录制并自动导出 CSV + 曲线图
5. 实时显示 ROI 区域的当前温度统计

特点：
- 完全独立于主项目的 SAM 追踪系统
- 临时工具，用完即可删除
- 与 FieldCapture.py 类似的操作方式
- 双窗口显示：左侧 RGB 视频，右侧温度热图

依赖：
  pip install numpy opencv-python matplotlib

运行方式：
  python FieldTempMonitor.py

操作说明：
  1. 程序启动后显示 RGB 视频（左）+ 温度热图（右）
  2. 按 R 键在热图窗口中框选要监测的区域
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

# DLL 路径（脚本所在目录）
DLL_DIR = os.path.dirname(os.path.abspath(__file__))
DLL_PATH = os.path.join(DLL_DIR, "IRCNetSDK.dll")

# 输出文件前缀
OUTPUT_PREFIX = "temp_monitor"

# 伪彩色显示范围（None = 自动调整）
DISPLAY_TEMP_MIN = None
DISPLAY_TEMP_MAX = None

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

class IRC_NET_VIDEO_INFO_CB(Structure):
    _fields_ = [
        ("frame",       POINTER(c_uint8)),
        ("width",       c_int),
        ("height",      c_int),
        ("validWidth",  c_int),
        ("validHeight", c_int),
        ("timestamp",   c_int64),
    ]

class IRC_NET_TEMP_INFO_CB(Structure):
    _fields_ = [
        ("temp",   POINTER(c_uint8)),
        ("width",  c_int),
        ("height", c_int),
    ]

class IRC_NET_PREVIEW_INFO(Structure):
    _fields_ = [
        ("channel",    c_int),
        ("streamType", c_int),
        ("frameFmt",   c_int),
    ]

VIDEO_CALLBACK = CFUNCTYPE(
    None, c_uint64, POINTER(IRC_NET_VIDEO_INFO_CB), c_void_p, c_void_p
)

TEMP_CALLBACK = CFUNCTYPE(
    None, c_uint64, POINTER(IRC_NET_TEMP_INFO_CB), c_void_p, c_void_p
)

# ═══════════════════════════════════════════════════════════════════════════
# 全局状态
# ═══════════════════════════════════════════════════════════════════════════
latest_rgb = None           # 最新一帧 RGB 视频（BGR格式）
latest_temp = None          # 最新一帧温度矩阵（float32，℃）
lock_rgb = threading.Lock()
lock_temp = threading.Lock()

roi_rect = None             # ROI 区域 (x, y, w, h)
is_selecting_roi = False    # 是否正在选择 ROI
roi_start = None            # ROI 起始点
roi_end = None              # ROI 结束点

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

    # IRC_NET_StartPreview_V2 / StopPreview
    dll.IRC_NET_StartPreview_V2.argtypes = [
        c_uint64, POINTER(IRC_NET_PREVIEW_INFO), VIDEO_CALLBACK, c_void_p
    ]
    dll.IRC_NET_StartPreview_V2.restype  = c_int
    dll.IRC_NET_StopPreview.argtypes = [c_uint64]
    dll.IRC_NET_StopPreview.restype  = c_int

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
# 视频和温度回调函数
# ═══════════════════════════════════════════════════════════════════════════

def video_callback(handle, video_info, ivs_info, user_data):
    """
    RGB 视频回调函数
    SDK 每收到一帧视频就会调用此函数
    """
    global latest_rgb

    if not video_info:
        return

    info = video_info.contents
    w, h = info.width, info.height

    # 解析 RGB24 数据
    size = w * h * 3
    raw = string_at(info.frame, size)
    rgb_frame = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
    
    # 转换为 BGR（OpenCV 格式）
    bgr_frame = cv2.cvtColor(rgb_frame, cv2.COLOR_RGB2BGR)

    # 更新全局最新视频帧
    with lock_rgb:
        latest_rgb = bgr_frame.copy()


def temp_callback(handle, temp_info, ext_info, user_data):
    """
    温度数据回调函数
    SDK 每收到一帧温度数据就会调用此函数
    """
    global latest_temp, is_recording, temp_stats_list, start_time, frame_count, roi_rect

    if not temp_info:
        return

    info = temp_info.contents
    w, h = info.width, info.height

    # 解析温度数据（int16 格式，单位：0.1℃）
    size = w * h * 2
    raw = string_at(info.temp, size)
    temp_int16 = np.frombuffer(raw, dtype=np.int16).reshape((h, w))
    temp_celsius = temp_int16.astype(np.float32) / 10.0

    # 更新全局最新温度
    with lock_temp:
        latest_temp = temp_celsius.copy()

    # 如果正在录制且已选择 ROI，记录温度统计
    if is_recording and roi_rect is not None:
        x, y, rw, rh = roi_rect
        roi_data = temp_celsius[y:y+rh, x:x+rw]
        
        # 过滤异常值
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

def create_heatmap(temp_frame, vmin=None, vmax=None):
    """将温度数据转换为伪彩色热图"""
    if vmin is None:
        vmin = np.percentile(temp_frame, 2)
    if vmax is None:
        vmax = np.percentile(temp_frame, 98)
    
    norm = np.clip((temp_frame - vmin) / (vmax - vmin + 1e-6), 0, 1)
    norm_u8 = (norm * 255).astype(np.uint8)
    heatmap_bgr = cv2.applyColorMap(norm_u8, cv2.COLORMAP_INFERNO)
    
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
    roi_data = temp_frame[y:y+h, x:x+w]
    valid_data = roi_data[(roi_data > -50) & (roi_data < 2000)]
    
    if len(valid_data) == 0:
        return img
    
    max_temp = np.max(valid_data)
    min_temp = np.min(valid_data)
    mean_temp = np.mean(valid_data)
    
    # 绘制半透明背景
    overlay = img.copy()
    cv2.rectangle(overlay, (10, 10), (350, 120), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.6, img, 0.4, 0, img)
    
    # 绘制文本
    font = cv2.FONT_HERSHEY_SIMPLEX
    cv2.putText(img, f"ROI Temp Stats:", (20, 35), font, 0.6, (255, 255, 255), 1)
    cv2.putText(img, f"Max:  {max_temp:.1f} C", (20, 60), font, 0.6, (255, 100, 100), 1)
    cv2.putText(img, f"Min:  {min_temp:.1f} C", (20, 85), font, 0.6, (100, 100, 255), 1)
    cv2.putText(img, f"Mean: {mean_temp:.1f} C", (20, 110), font, 0.6, (100, 255, 100), 1)
    
    return img


# ═══════════════════════════════════════════════════════════════════════════
# ROI 选择（鼠标交互）
# ═══════════════════════════════════════════════════════════════════════════

def mouse_callback(event, x, y, flags, param):
    """鼠标回调函数，用于 ROI 选择"""
    global is_selecting_roi, roi_start, roi_end, roi_rect
    
    if not is_selecting_roi:
        return
    
    if event == cv2.EVENT_LBUTTONDOWN:
        roi_start = (x, y)
        roi_end = None
    
    elif event == cv2.EVENT_MOUSEMOVE:
        if roi_start is not None:
            roi_end = (x, y)
    
    elif event == cv2.EVENT_LBUTTONUP:
        if roi_start is not None:
            roi_end = (x, y)
            # 计算 ROI 矩形
            x1, y1 = roi_start
            x2, y2 = roi_end
            rx = min(x1, x2)
            ry = min(y1, y2)
            rw = abs(x2 - x1)
            rh = abs(y2 - y1)
            
            if rw > 5 and rh > 5:  # 最小尺寸限制
                roi_rect = (rx, ry, rw, rh)
                print(f"[ROI] 选择完成: x={rx}, y={ry}, w={rw}, h={rh}")
            
            is_selecting_roi = False
            roi_start = None
            roi_end = None


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
    ax1.plot(times, mean_temps, color="orange", linewidth=2, label="平均温度")
    ax1.fill_between(times, min_temps, max_temps, alpha=0.2, color="gray", label="温度范围")
    ax1.set_xlabel("时间 (秒)", fontsize=12)
    ax1.set_ylabel("温度 (°C)", fontsize=12)
    ax1.set_title("ROI 区域平均温度随时间变化", fontsize=14, fontweight="bold")
    ax1.legend(loc="best", fontsize=10)
    ax1.grid(True, alpha=0.3, linestyle="--")
    
    mean_avg = np.mean(mean_temps)
    mean_max = np.max(mean_temps)
    mean_min = np.min(mean_temps)
    info_text = f"平均温度统计:\n  均值: {mean_avg:.2f}°C\n  最高: {mean_max:.2f}°C\n  最低: {mean_min:.2f}°C"
    ax1.text(0.02, 0.98, info_text, transform=ax1.transAxes, 
             fontsize=10, verticalalignment="top",
             bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.5))
    
    # 子图 2: 最高/最低温度曲线
    ax2 = axes[1]
    ax2.plot(times, max_temps, color="red", linewidth=1.5, label="最高温度", alpha=0.8)
    ax2.plot(times, min_temps, color="blue", linewidth=1.5, label="最低温度", alpha=0.8)
    ax2.plot(times, mean_temps, color="orange", linewidth=1, label="平均温度", alpha=0.6, linestyle="--")
    ax2.set_xlabel("时间 (秒)", fontsize=12)
    ax2.set_ylabel("温度 (°C)", fontsize=12)
    ax2.set_title("ROI 区域温度范围（最高/最低/平均）", fontsize=14, fontweight="bold")
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
    global is_selecting_roi, is_recording, temp_stats_list, start_time, frame_count, roi_rect
    
    print("\n" + "="*70)
    print("下位机实时温度区域监测工具 (FieldTempMonitor)")
    print("="*70)
    print(f"设备 IP: {DEVICE_IP}")
    print()
    print("操作说明:")
    print("  R 键 - 在热图窗口中框选监测区域（ROI）")
    print("  S 键 - 开始录制温度数据")
    print("  Q 键 - 停止录制并保存数据")
    print("  ESC  - 退出程序")
    print()
    print("窗口说明:")
    print("  左侧窗口 - RGB 可见光视频（用于调整摄像头角度）")
    print("  右侧窗口 - 红外温度热图（用于选择 ROI 和监测温度）")
    print("="*70)
    
    # 加载 DLL 并登录
    dll = load_dll()
    handle = sdk_login(dll)
    if handle is None:
        print("[错误] 无法连接设备，程序退出")
        return
    
    # 启动 RGB 视频流
    preview_info = IRC_NET_PREVIEW_INFO()
    preview_info.channel = 1
    preview_info.streamType = 0
    preview_info.frameFmt = 0
    
    video_cb = VIDEO_CALLBACK(video_callback)
    ret = dll.IRC_NET_StartPreview_V2(handle, ctypes.byref(preview_info), video_cb, None)
    if ret != 0:
        print(f"[警告] 启动 RGB 视频流失败: {ret}（将仅显示温度热图）")
    else:
        print("[成功] RGB 视频流已启动")
    
    # 启动温度拉流
    temp_cb = TEMP_CALLBACK(temp_callback)
    ret = dll.IRC_NET_StartPullTemp_V2(handle, temp_cb, None)
    if ret != 0:
        print(f"[错误] 启动温度拉流失败: {ret}")
        dll.IRC_NET_StopPreview(handle)
        dll.IRC_NET_Logout(handle)
        dll.IRC_NET_Deinit()
        return
    
    print("[成功] 温度拉流已启动")
    print("\n等待数据...")
    
    # 等待第一帧数据
    while latest_temp is None:
        time.sleep(0.1)
    
    print("[成功] 收到数据，开始显示\n")
    
    # 创建显示窗口
    rgb_window = "RGB Video (Left)"
    ir_window = "IR Temperature (Right) - Press R to select ROI"
    cv2.namedWindow(rgb_window, cv2.WINDOW_NORMAL)
    cv2.namedWindow(ir_window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(ir_window, mouse_callback)
    
    # 设置窗口位置（左右并排）
    cv2.moveWindow(rgb_window, 50, 50)
    cv2.moveWindow(ir_window, 750, 50)
    
    # 主循环
    try:
        while True:
            # 显示 RGB 视频
            with lock_rgb:
                if latest_rgb is not None:
                    rgb_display = latest_rgb.copy()
                    # 添加状态文本
                    cv2.putText(rgb_display, "RGB Video", (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    cv2.imshow(rgb_window, rgb_display)
            
            # 显示温度热图
            with lock_temp:
                if latest_temp is None:
                    time.sleep(0.01)
                    continue
                temp_frame = latest_temp.copy()
            
            # 生成热图
            heatmap, vmin, vmax = create_heatmap(temp_frame, DISPLAY_TEMP_MIN, DISPLAY_TEMP_MAX)
            
            # 放大显示（如果分辨率太小）
            H, W = temp_frame.shape
            if W < 400:
                scale = 400 / W
                new_w = int(W * scale)
                new_h = int(H * scale)
                heatmap = cv2.resize(heatmap, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
                display_scale = scale
            else:
                display_scale = 1.0
            
            # 绘制 ROI 框
            if roi_rect is not None:
                scaled_roi = tuple(int(v * display_scale) for v in roi_rect)
                heatmap = draw_roi_on_image(heatmap, scaled_roi, (0, 255, 0), 2)
                heatmap = draw_temp_stats(heatmap, temp_frame, roi_rect)
            
            # 绘制正在选择的 ROI（临时）
            if is_selecting_roi and roi_start is not None and roi_end is not None:
                x1, y1 = roi_start
                x2, y2 = roi_end
                cv2.rectangle(heatmap, (x1, y1), (x2, y2), (255, 255, 0), 2)
            
            # 绘制状态信息
            status_text = ""
            if is_recording:
                elapsed = time.time() - start_time
                status_text = f"RECORDING - {elapsed:.1f}s - {frame_count} frames"
                cv2.putText(heatmap, status_text, (10, heatmap.shape[0] - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            elif roi_rect is not None:
                status_text = "ROI selected - Press S to start recording"
                cv2.putText(heatmap, status_text, (10, heatmap.shape[0] - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
            else:
                status_text = "Press R to select ROI"
                cv2.putText(heatmap, status_text, (10, heatmap.shape[0] - 20),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            
            # 显示热图
            cv2.imshow(ir_window, heatmap)
            
            # 键盘控制
            key = cv2.waitKey(30) & 0xFF
            
            if key == ord('r') or key == ord('R'):
                # 开始选择 ROI
                if not is_recording:
                    print("\n[ROI] 请在窗口中拖动鼠标框选监测区域...")
                    is_selecting_roi = True
                    roi_start = None
                    roi_end = None
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
        print("\n[清理] 停止数据流...")
        dll.IRC_NET_StopPullTemp(handle)
        dll.IRC_NET_StopPreview(handle)
        dll.IRC_NET_Logout(handle)
        dll.IRC_NET_Deinit()
        cv2.destroyAllWindows()
        print("[清理] 完成")


if __name__ == "__main__":
    main()
