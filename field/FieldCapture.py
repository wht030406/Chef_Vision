"""
厨房现场数据采集脚本（笔记本便携版）
功能：
  1. 实时显示 RGB 可见光画面（方便调整摄像头角度）
  2. 实时显示 IR 温度热力图（确认锅/菜拍到了）
  3. 按 S 键开始录制，按 Q 键停止并保存数据
  4. 自动以时间戳命名文件，不会覆盖之前的录制

依赖：
  pip install numpy opencv-python

运行方式：
  python FieldCapture.py

操作说明：
  - 先调整好摄像头角度（看左侧 RGB 预览窗口）
  - 确认锅出现在画面中后按 S 开始录制
  - 录制完成后按 Q 停止，数据自动保存
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

# ============================================================
# 设备参数（按实际情况修改）
# ============================================================
DEVICE_IP   = "192.168.1.123"
DEVICE_PORT = 80
USERNAME    = "admin"
PASSWORD    = "ZGTC2026"

# DLL 路径（与本脚本同目录，适配下位机所有文件放在同一文件夹的情况）
_HERE    = os.path.dirname(os.path.abspath(__file__))
DLL_DIR  = _HERE
DLL_PATH = os.path.join(DLL_DIR, "IRCNetSDK.dll")

# 数据输出目录（与本脚本同目录）
_DATA_DIR = _HERE
os.makedirs(_DATA_DIR, exist_ok=True)

# ============================================================
# SDK 结构体定义
# ============================================================

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

# ============================================================
# 全局状态
# ============================================================
latest_rgb   = None    # 最新一帧 RGB（BGR格式，给 OpenCV 显示）
latest_ir    = None    # 最新一帧温度矩阵（float32，℃）
lock_rgb     = threading.Lock()
lock_ir      = threading.Lock()

is_recording    = False
video_writer    = None
ir_video_writer = None   # IR 伪彩色视频写入器
temp_list       = []
frame_count     = 0
temp_count      = 0
ir_frame_count  = 0
rec_ts          = None   # 录制开始时间戳（按 S 时记录，视频和 npy 共用）

# IR 视频输出分辨率（原始 192×256 放大 2 倍，方便查看）
IR_VIDEO_W = 512
IR_VIDEO_H = 384

# ============================================================
# ROI 配置（圆形监测区域，在 RGB 预览坐标系下定义）
# 默认位置：预览画面中心偏下，半径 60px（预览尺寸 640×480）
# ============================================================
ROI_CONFIG_PATH = os.path.join(_DATA_DIR, "roi_config.json")

# ROI 状态（预览坐标系，640×480）
roi_cx      = 320    # 圆心 X
roi_cy      = 320    # 圆心 Y（偏下）
roi_radius  = 60     # 半径（像素，预览坐标系）
roi_editing = False  # 是否处于 ROI 编辑模式
roi_dragging = False # 是否正在拖拽圆心

# ============================================================
# DLL 加载与 SDK 初始化
# ============================================================

def load_dll():
    """加载 SDK DLL（先设置 DLL 搜索路径）"""
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

    handle = c_uint64(0)
    ret = dll.IRC_NET_Login(ctypes.byref(info), ctypes.byref(handle))
    if ret != 0:
        print(f"[错误] 登录失败，错误码: {ret}")
        dll.IRC_NET_Deinit()
        return None

    print(f"[OK] 登录成功，句柄: {handle.value}")
    return handle.value

# ============================================================
# 回调函数
# ============================================================

def on_video_frame(handle, video_info_ptr, ivs_ptr, user_data):
    global latest_rgb, is_recording, video_writer, frame_count, rec_ts
    try:
        vi = video_info_ptr.contents
        if vi.width <= 0 or vi.height <= 0:
            return

        data_size = vi.width * vi.height * 3
        if data_size <= 0:
            return

        raw = string_at(vi.frame, data_size)
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((vi.height, vi.width, 3))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)

        with lock_rgb:
            latest_rgb = bgr.copy()

        if is_recording:
            if video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                # 使用 rec_ts（按 S 时记录），与 npy 文件保持同一时间戳
                ts    = rec_ts if rec_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = os.path.join(_DATA_DIR, f"rgb_{ts}.mp4")
                video_writer = cv2.VideoWriter(fname, fourcc, 25.0, (vi.width, vi.height))
                print(f"[视频] 开始写入: {fname}")
            video_writer.write(bgr)
            frame_count += 1

    except Exception as e:
        pass  # 回调中不打印，避免卡顿


def on_temp_frame(handle, temp_info_ptr, ext_ptr, user_data):
    global latest_ir, is_recording, temp_list, temp_count
    global ir_video_writer, ir_frame_count, rec_ts
    try:
        ti = temp_info_ptr.contents
        if ti.width <= 0 or ti.height <= 0:
            return
        if ti.width > 2000 or ti.height > 2000:
            return

        data_size = ti.width * ti.height * 2
        raw = string_at(ti.temp, data_size)
        arr = np.frombuffer(raw, dtype=np.int16).reshape((ti.height, ti.width))
        celsius = arr.astype(np.float32) / 10.0 - 273.15

        with lock_ir:
            latest_ir = celsius.copy()

        if is_recording:
            # 保存温度矩阵（精度数据）
            temp_list.append(celsius)
            temp_count += 1

            # 同步录制 IR 伪彩色视频
            if ir_video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                ts = rec_ts if rec_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
                ir_fname = os.path.join(_DATA_DIR, f"ir_{ts}.mp4")
                # IR 帧率由实际回调频率决定，这里用 25fps 作为标称值
                ir_video_writer = cv2.VideoWriter(
                    ir_fname, fourcc, 25.0, (IR_VIDEO_W, IR_VIDEO_H)
                )
                print(f"[IR视频] 开始写入: {ir_fname}")

            # 温度矩阵 → 伪彩色图（不加文字，保持干净）
            t_min = float(celsius.min())
            t_max = float(celsius.max())
            if t_max - t_min < 0.1:
                norm = np.zeros_like(celsius, dtype=np.uint8)
            else:
                norm = ((celsius - t_min) / (t_max - t_min) * 255).astype(np.uint8)
            colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
            colored = cv2.resize(colored, (IR_VIDEO_W, IR_VIDEO_H),
                                 interpolation=cv2.INTER_NEAREST)

            # 叠加温度信息文字
            cv2.putText(colored, f"MAX:{t_max:.1f}C", (4, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(colored, f"MIN:{t_min:.1f}C", (4, 40),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(colored, f"AVG:{float(celsius.mean()):.1f}C", (4, 60),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            ir_video_writer.write(colored)
            ir_frame_count += 1

    except Exception as e:
        pass

# ============================================================
# ROI 工具函数
# ============================================================

def load_roi_config():
    """从文件加载 ROI 配置，不存在则用默认值"""
    global roi_cx, roi_cy, roi_radius
    if os.path.exists(ROI_CONFIG_PATH):
        try:
            import json
            with open(ROI_CONFIG_PATH, "r") as f:
                cfg = json.load(f)
            roi_cx     = cfg.get("preview_cx", roi_cx)
            roi_cy     = cfg.get("preview_cy", roi_cy)
            roi_radius = cfg.get("preview_radius", roi_radius)
            print(f"[ROI] 已加载配置: 圆心=({roi_cx},{roi_cy}) 半径={roi_radius}px")
        except Exception:
            pass


def save_roi_config(preview_w, preview_h, rgb_w, rgb_h):
    """保存 ROI 配置到 JSON，同时记录原始 RGB 坐标系下的值"""
    import json
    # 将预览坐标系换算回原始 RGB 坐标系
    sx = rgb_w / preview_w
    sy = rgb_h / preview_h
    cfg = {
        "preview_cx":     roi_cx,
        "preview_cy":     roi_cy,
        "preview_radius": roi_radius,
        "preview_w":      preview_w,
        "preview_h":      preview_h,
        "rgb_cx":         int(roi_cx * sx),
        "rgb_cy":         int(roi_cy * sy),
        "rgb_radius":     int(roi_radius * max(sx, sy)),
        "rgb_w":          rgb_w,
        "rgb_h":          rgb_h,
    }
    with open(ROI_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    print(f"[ROI] 已保存: {ROI_CONFIG_PATH}")
    print(f"  预览坐标: 圆心=({roi_cx},{roi_cy}) 半径={roi_radius}px")
    print(f"  原始RGB坐标: 圆心=({cfg['rgb_cx']},{cfg['rgb_cy']}) 半径={cfg['rgb_radius']}px")


def draw_roi_on_frame(img, editing=False):
    """在图像上绘制 ROI 圆形，编辑模式下用黄色，正常模式用青色"""
    color  = (0, 255, 255) if editing else (255, 200, 0)
    thick  = 2 if not editing else 3
    cv2.circle(img, (roi_cx, roi_cy), roi_radius, color, thick)
    cv2.circle(img, (roi_cx, roi_cy), 4, color, -1)
    if editing:
        cv2.putText(img, "[R]=退出编辑  拖拽=移动  滚轮=调半径",
                    (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
    else:
        cv2.putText(img, f"ROI r={roi_radius}px  [R]=编辑",
                    (roi_cx - 40, roi_cy + roi_radius + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 200, 0), 1)


def roi_mouse_callback(event, x, y, flags, param):
    """ROI 编辑模式下的鼠标回调"""
    global roi_cx, roi_cy, roi_radius, roi_dragging
    if not roi_editing:
        return
    if event == cv2.EVENT_LBUTTONDOWN:
        # 点击圆心附近开始拖拽
        if abs(x - roi_cx) < roi_radius and abs(y - roi_cy) < roi_radius:
            roi_dragging = True
    elif event == cv2.EVENT_MOUSEMOVE and roi_dragging:
        roi_cx = max(roi_radius, min(param["w"] - roi_radius, x))
        roi_cy = max(roi_radius, min(param["h"] - roi_radius, y))
    elif event == cv2.EVENT_LBUTTONUP:
        roi_dragging = False
    elif event == cv2.EVENT_MOUSEWHEEL:
        if flags > 0:
            roi_radius = min(200, roi_radius + 5)
        else:
            roi_radius = max(10, roi_radius - 5)


# ============================================================
# 温度矩阵 → 伪彩色图（用于预览）
# ============================================================

def temp_to_colormap(temp_matrix, width=640, height=480):
    """将温度矩阵转换为 jet 伪彩色图，用于实时预览"""
    t_min = np.min(temp_matrix)
    t_max = np.max(temp_matrix)
    if t_max - t_min < 0.1:
        norm = np.zeros_like(temp_matrix, dtype=np.uint8)
    else:
        norm = ((temp_matrix - t_min) / (t_max - t_min) * 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    resized = cv2.resize(colored, (width, height))

    # 叠加温度范围文字
    cv2.putText(resized, f"MAX: {t_max:.1f}C", (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(resized, f"MIN: {t_min:.1f}C", (10, 65),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    cv2.putText(resized, f"AVG: {np.mean(temp_matrix):.1f}C", (10, 100),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
    return resized

# ============================================================
# 主程序
# ============================================================

def main():
    global is_recording, video_writer, ir_video_writer, ir_frame_count
    global temp_list, frame_count, temp_count, rec_ts
    global roi_editing, roi_cx, roi_cy, roi_radius, roi_dragging

    print("=" * 55)
    print("  Chef Vision — 厨房数据采集（现场版）")
    print("=" * 55)
    print(f"  设备 IP : {DEVICE_IP}:{DEVICE_PORT}")
    print(f"  DLL 路径: {DLL_PATH}")
    print("-" * 55)
    print("  操作说明：")
    print("    [S] 开始录制")
    print("    [Q] 停止录制并保存，退出程序")
    print("=" * 55)

    # 1. 加载 DLL & 登录
    try:
        dll = load_dll()
    except Exception as e:
        print(f"[错误] DLL 加载失败: {e}")
        print("请确认所有 .dll 文件与本脚本在同一文件夹！")
        input("按 Enter 退出...")
        return

    handle = sdk_login(dll)
    if handle is None:
        input("按 Enter 退出...")
        return

    # 2. 注册回调
    _video_cb = VIDEO_CALLBACK(on_video_frame)
    _temp_cb  = TEMP_CALLBACK(on_temp_frame)

    # 3. 启动温度拉流
    ret = dll.IRC_NET_StartPullTemp_V2(handle, _temp_cb, None)
    if ret != 0:
        print(f"[错误] 启动温度拉流失败: {ret}")

    # 4. 启动 RGB 预览（channel=0）
    pi = IRC_NET_PREVIEW_INFO()
    pi.channel    = 0   # RGB 可见光
    pi.streamType = 0   # 主码流
    pi.frameFmt   = 1   # RGB24
    ret = dll.IRC_NET_StartPreview_V2(handle, ctypes.byref(pi), _video_cb, None)
    if ret != 0:
        print(f"[错误] 启动视频预览失败: {ret}")

    print("\n[等待数据流...] 画面出现后按 S 开始录制，按 Q 退出")
    print("  [R] 进入/退出 ROI 编辑模式（拖拽移动，滚轮调半径）")

    # 5. 主循环：显示双画面预览
    PREVIEW_W, PREVIEW_H = 640, 480
    WIN_NAME = "Chef Vision — [S] 录制  [Q] 退出  [R] 编辑ROI"

    # 加载已有 ROI 配置
    load_roi_config()

    cv2.namedWindow(WIN_NAME)
    cv2.setMouseCallback(WIN_NAME, roi_mouse_callback,
                         {"w": PREVIEW_W, "h": PREVIEW_H})

    # 获取原始 RGB 分辨率（等第一帧到来后才知道）
    rgb_orig_w, rgb_orig_h = 1600, 1200  # 默认值，回调到来后更新

    while True:
        # 读取最新帧
        with lock_rgb:
            rgb_frame = latest_rgb.copy() if latest_rgb is not None else None
        with lock_ir:
            ir_matrix = latest_ir.copy() if latest_ir is not None else None

        # 构建左画面（RGB）
        if rgb_frame is not None:
            left = cv2.resize(rgb_frame, (PREVIEW_W, PREVIEW_H))
        else:
            left = np.zeros((PREVIEW_H, PREVIEW_W, 3), dtype=np.uint8)
            cv2.putText(left, "等待 RGB 信号...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)

        # 构建右画面（IR 热力图）
        if ir_matrix is not None:
            right = temp_to_colormap(ir_matrix, PREVIEW_W, PREVIEW_H)
        else:
            right = np.zeros((PREVIEW_H, PREVIEW_W, 3), dtype=np.uint8)
            cv2.putText(right, "等待 IR 信号...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)

        # 更新原始 RGB 分辨率
        if rgb_frame is not None:
            rgb_orig_h, rgb_orig_w = rgb_frame.shape[:2]

        # 在 RGB 预览上绘制 ROI 圆形
        draw_roi_on_frame(left, editing=roi_editing)

        # 在 IR 预览上绘制对应映射区域（通过单应矩阵，若无则按比例估算）
        hom_path = os.path.join(_HERE, "..", "data", "homography.npy")
        if ir_matrix is not None:
            try:
                H = np.load(hom_path)
                # ROI 圆心（预览坐标 → 原始 RGB 坐标 → IR 坐标）
                sx = rgb_orig_w / PREVIEW_W
                sy = rgb_orig_h / PREVIEW_H
                rgb_pt = np.array([[[roi_cx * sx, roi_cy * sy]]], dtype=np.float32)
                ir_pt  = cv2.perspectiveTransform(rgb_pt, H)[0][0]
                # IR 坐标 → 预览坐标（IR 原始 192×256 → 640×480）
                ir_h, ir_w = ir_matrix.shape[:2]
                ir_px = int(ir_pt[0] / ir_w * PREVIEW_W)
                ir_py = int(ir_pt[1] / ir_h * PREVIEW_H)
                ir_pr = int(roi_radius * (PREVIEW_W / ir_w) * (ir_w / rgb_orig_w) * sx)
                ir_pr = max(5, min(100, ir_pr))
                cv2.circle(right, (ir_px, ir_py), ir_pr, (255, 200, 0), 2)
                cv2.circle(right, (ir_px, ir_py), 4, (255, 200, 0), -1)
                # 显示 ROI 区域温度
                mask = np.zeros(ir_matrix.shape[:2], dtype=np.uint8)
                cv2.circle(mask,
                           (int(ir_pt[0]), int(ir_pt[1])),
                           max(2, int(roi_radius * ir_w / rgb_orig_w * sx)),
                           255, -1)
                roi_temps = ir_matrix[mask > 0]
                if len(roi_temps) > 0:
                    roi_t = float(np.mean(roi_temps))
                    cv2.putText(right, f"ROI: {roi_t:.1f}C",
                                (ir_px - 40, ir_py - ir_pr - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
            except Exception:
                pass  # 单应矩阵不存在时跳过

        # 录制状态指示
        status_color = (0, 0, 255) if is_recording else (0, 200, 0)
        status_text  = f"● REC  帧:{frame_count}" if is_recording else "● 预览中  [S]=录制  [Q]=退出  [R]=ROI"
        cv2.putText(left,  status_text, (10, PREVIEW_H - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 2)
        cv2.putText(right, "IR 热力图", (10, PREVIEW_H - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        # 左右拼接
        combined = np.hstack([left, right])
        cv2.imshow(WIN_NAME, combined)

        key = cv2.waitKey(30) & 0xFF

        if key == ord('r') or key == ord('R'):
            roi_editing = not roi_editing
            if not roi_editing:
                # 退出编辑时保存配置
                save_roi_config(PREVIEW_W, PREVIEW_H, rgb_orig_w, rgb_orig_h)
                print(f"[ROI] 编辑完成，已保存")
            else:
                print("[ROI] 进入编辑模式：拖拽圆心移动，滚轮调节半径，再按 R 保存退出")

        elif key == ord('s') or key == ord('S'):
            if not is_recording:
                rec_ts          = datetime.now().strftime("%Y%m%d_%H%M%S")  # 统一时间戳
                is_recording    = True
                temp_list       = []
                frame_count     = 0
                temp_count      = 0
                ir_frame_count  = 0
                ir_video_writer = None   # 确保下次录制创建新文件
                print(f"\n[录制] 已开始录制！时间戳: {rec_ts}  按 Q 停止")
            else:
                print("[提示] 已在录制中")

        elif key == ord('q') or key == ord('Q'):
            print("\n[停止] 正在保存数据...")
            break

    # 6. 停止流
    is_recording = False
    dll.IRC_NET_StopPreview(handle)
    dll.IRC_NET_StopPullTemp(handle)
    cv2.destroyAllWindows()

    # 7. 保存视频
    if video_writer is not None:
        video_writer.release()
        print(f"[OK] RGB 视频已保存，共 {frame_count} 帧")

    # 7b. 保存 IR 视频
    if ir_video_writer is not None:
        ir_video_writer.release()
        print(f"[OK] IR 视频已保存，共 {ir_frame_count} 帧  ({IR_VIDEO_W}×{IR_VIDEO_H})")

    # 8. 保存温度矩阵（使用 rec_ts，与视频保持同一时间戳）
    ts = rec_ts if rec_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
    if len(temp_list) > 0:
        stack = np.stack(temp_list, axis=0)
        npy_name = os.path.join(_DATA_DIR, f"temp_{ts}.npy")
        np.save(npy_name, stack)
        print(f"[OK] 温度数据已保存: {npy_name}")
        print(f"     形状: {stack.shape}，共 {temp_count} 帧")
        t_all_max = np.max(stack)
        t_all_min = np.min(stack)
        print(f"     温度范围: {t_all_min:.1f}℃ ~ {t_all_max:.1f}℃")
    else:
        print("[警告] 未采集到温度数据（是否忘记按 S 开始录制？）")

    # 9. 登出
    dll.IRC_NET_Logout(handle)
    dll.IRC_NET_Deinit()
    print("\n[完成] 设备已断开，文件保存在脚本所在文件夹")
    input("按 Enter 退出...")


if __name__ == "__main__":
    main()
