"""
厨房现场数据采集脚本（笔记本便携版）
功能：
  1. 实时显示 RGB 可见光画面（方便调整摄像头角度）
  2. 实时显示 IR 温度热力图（确认锅/菜拍到了）
  3. 按 S 键开始录制，按 Q 键停止并保存数据
  4. 自动以时间戳命名文件，不会覆盖之前的录制

依赖：
  pip install numpy opencv-python matplotlib

运行方式：
  python FieldCapture.py

操作说明：
  - 先调整好摄像头角度（看左侧 RGB 预览窗口）
  - 确认锅出现在画面中后按 S 开始录制
  - 录制完成后按 Q 停止，数据自动保存
"""

import ctypes
import csv
import numpy as np
import cv2
import time
import os
import sys
import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from ctypes import (
    c_int, c_int64, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p,
    POINTER, Structure, CFUNCTYPE, string_at, c_char, c_char_p
)
import threading

# ============================================================
# 设备参数（按实际情况修改）
# ============================================================
DEVICE_IP   = "192.168.1.123"
DEVICE_PORT = 80
USERNAME    = "admin"
PASSWORD    = "ZGTC2026"

# Fill light control. Press L to toggle white fill light for RGB:
# 0 -> 100 -> 0. Startup and exit both force the light off.
FILL_LIGHT_HOTKEY_ENABLE = True
FILL_LIGHT_ON_LEVEL      = 100
FILL_LIGHT_MAX           = 100
FILL_LIGHT_IR_LEVEL      = 100
FILL_LIGHT_HFOV          = 100
FILL_LIGHT_HTTP_ENABLE   = True
FILL_LIGHT_HTTP_AUTO_LOGIN = True
FILL_LIGHT_HTTP_PASSWORD_PARAM = "G3D2cWdjF+Rp6EYEOj7ZTg=="
FILL_LIGHT_USE_PTZ_AUX   = False
PTZ_CMD_LIGHT            = 15

# Sync the device OSD/system clock to this laptop when the capture script starts.
SYNC_DEVICE_TIME_ON_START = True

# Temperature range/gain mode to apply at startup:
#   "auto" = AUTO, "low" = LG, "high" = HG, "keep" = query only.
TEMP_LEVEL_MODE_ON_START = "auto"

# DLL 路径（与本脚本同目录，适配下位机所有文件放在同一文件夹的情况）
_HERE    = os.path.dirname(os.path.abspath(__file__))
DLL_DIR  = _HERE
DLL_PATH = os.path.join(DLL_DIR, "IRCNetSDK.dll")

# 数据输出目录（与本脚本同目录）
_DATA_DIR = _HERE
os.makedirs(_DATA_DIR, exist_ok=True)

# RGB -> IR spatial calibration. Prefer a self-contained copy next to this
# script, then fall back to the main project's data directory.
HOMOGRAPHY_PATHS = (
    os.path.join(_HERE, "homography.npy"),
    os.path.join(_HERE, "..", "data", "homography.npy"),
)

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

class IRC_NET_FILL_LIGHT_CONFIG_INFO(Structure):
    _fields_ = [
        ("fillLightMode", c_int),
        ("infraredLight", c_int),
        ("whiteLight", c_int),
        ("hFov", c_int),
        ("hFovFactor", ctypes.c_float),
    ]

class IRC_NET_PTZ_CONTROL_INFO(Structure):
    _fields_ = [
        ("channel", c_int),
        ("cmd", c_int),
        ("param1", c_int),
        ("param2", c_int),
        ("param3", c_int),
        ("stop", c_int),
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
roi_temp_rows   = []     # 逐帧 ROI 温度统计，用于 CSV 和曲线图
rgb_ts_list     = []     # RGB 逐帧时间戳（Unix float64）
ir_ts_list      = []     # IR 逐帧时间戳（Unix float64）
frame_count     = 0
temp_count      = 0
ir_frame_count  = 0
fill_light_level = 0
fill_light_original_config = None
fill_light_http_token = ""
temperature_level_label = "UNKNOWN"
rec_ts          = None   # 录制开始时间戳（按 S 时记录，视频和 npy 共用）
rgb_source_w    = 1600   # RGB 原始尺寸，由视频回调持续更新
rgb_source_h    = 1200
roi_homography  = None
roi_mapping_label = "SCALE"
_roi_mask_cache_key = None
_roi_mask_cache = None

# IR 视频输出分辨率（原始 192×256 放大 2 倍，方便查看）
IR_VIDEO_W = 512
IR_VIDEO_H = 384
PREVIEW_W  = 640
PREVIEW_H  = 480

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

    # IRC_NET_SyncSystemTime
    if hasattr(dll, "IRC_NET_SyncSystemTime"):
        dll.IRC_NET_SyncSystemTime.argtypes = [c_uint64, c_char_p]
        dll.IRC_NET_SyncSystemTime.restype = c_int

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

    # Optional temperature range/gain query and setting.
    if hasattr(dll, "IRC_NET_GetTempLevel"):
        dll.IRC_NET_GetTempLevel.argtypes = [c_uint64, POINTER(c_int)]
        dll.IRC_NET_GetTempLevel.restype = c_int
    if hasattr(dll, "IRC_NET_SetTempLevel"):
        dll.IRC_NET_SetTempLevel.argtypes = [c_uint64, c_int]
        dll.IRC_NET_SetTempLevel.restype = c_int

    # Optional fill light control.
    if hasattr(dll, "IRC_NET_GetFillLightConfigInfo"):
        dll.IRC_NET_GetFillLightConfigInfo.argtypes = [
            c_uint64, POINTER(IRC_NET_FILL_LIGHT_CONFIG_INFO)
        ]
        dll.IRC_NET_GetFillLightConfigInfo.restype = c_int
    if hasattr(dll, "IRC_NET_SetFillLightConfigInfo"):
        dll.IRC_NET_SetFillLightConfigInfo.argtypes = [
            c_uint64, POINTER(IRC_NET_FILL_LIGHT_CONFIG_INFO)
        ]
        dll.IRC_NET_SetFillLightConfigInfo.restype = c_int
    if hasattr(dll, "IRC_NET_PtzControl"):
        dll.IRC_NET_PtzControl.argtypes = [
            c_uint64, POINTER(IRC_NET_PTZ_CONTROL_INFO)
        ]
        dll.IRC_NET_PtzControl.restype = c_int

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


def print_temperature_level(dll, handle):
    """Print the current camera temperature range/gain mode when supported."""
    global temperature_level_label

    if not hasattr(dll, "IRC_NET_GetTempLevel"):
        print("[TEMP LEVEL] 当前 SDK 不支持查询测温档位")
        temperature_level_label = "UNKNOWN"
        return None

    level = c_int(-1)
    ret = dll.IRC_NET_GetTempLevel(handle, ctypes.byref(level))
    if ret != 0:
        print(f"[TEMP LEVEL] 查询测温档位失败: {ret}")
        temperature_level_label = "UNKNOWN"
        return None

    names = {
        0: ("高增益", "HG"),
        1: ("低增益", "LG"),
        2: ("自动", "AUTO"),
    }
    cn_name, short_name = names.get(level.value, ("未知档位", f"UNKNOWN-{level.value}"))
    temperature_level_label = short_name
    print(f"[TEMP LEVEL] 当前测温档位: {cn_name} {short_name}")
    return level.value


def apply_temperature_level_mode(dll, handle):
    """Set the camera temperature range/gain mode when configured."""
    mode = str(TEMP_LEVEL_MODE_ON_START).strip().lower()
    targets = {
        "high": (0, "高增益 HG"),
        "hg": (0, "高增益 HG"),
        "low": (1, "低增益 LG"),
        "lg": (1, "低增益 LG"),
        "auto": (2, "自动 AUTO"),
        "keep": (None, "保持设备当前档位"),
    }
    if mode not in targets:
        print(f"[TEMP LEVEL] 未知启动档位配置: {TEMP_LEVEL_MODE_ON_START!r}，保持当前档位")
        return print_temperature_level(dll, handle)

    target_value, target_name = targets[mode]
    if target_value is None:
        print("[TEMP LEVEL] 启动档位配置: 保持当前档位")
        return print_temperature_level(dll, handle)

    return set_temperature_level(dll, handle, target_value, target_name)


def set_temperature_level(dll, handle, target_value, target_name):
    """Set one device temperature range and query the applied value."""
    if not hasattr(dll, "IRC_NET_SetTempLevel"):
        print("[TEMP LEVEL] 当前 SDK 不支持设置测温档位，仅查询当前档位")
        return print_temperature_level(dll, handle)

    ret = dll.IRC_NET_SetTempLevel(handle, int(target_value))
    if ret != 0:
        print(f"[TEMP LEVEL] 设置测温档位为 {target_name} 失败: {ret}")
    else:
        print(f"[TEMP LEVEL] 已请求设置测温档位为: {target_name}")
    return print_temperature_level(dll, handle)


def switch_temperature_level(dll, handle, mode):
    """Switch temperature range from a runtime hotkey."""
    targets = {
        "high": (0, "高增益 HG"),
        "low": (1, "低增益 LG"),
        "auto": (2, "自动 AUTO"),
    }
    target_value, target_name = targets[mode]
    return set_temperature_level(dll, handle, target_value, target_name)


def sync_device_time(dll, handle):
    """Synchronize the camera's system/OSD clock to the laptop clock."""
    if not SYNC_DEVICE_TIME_ON_START:
        print("[TIME SYNC] 已关闭启动同步设备时间")
        return False
    if not hasattr(dll, "IRC_NET_SyncSystemTime"):
        print("[TIME SYNC] 当前 SDK 不支持同步设备时间")
        return False

    now_text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ret = dll.IRC_NET_SyncSystemTime(handle, now_text.encode("utf-8"))
    if ret != 0:
        print(f"[TIME SYNC] 同步设备时间失败: {ret}  本机时间={now_text}")
        return False

    print(f"[TIME SYNC] 已同步设备时间为本机时间: {now_text}")
    return True


def clone_fill_light_config(config):
    copied = IRC_NET_FILL_LIGHT_CONFIG_INFO()
    copied.fillLightMode = config.fillLightMode
    copied.infraredLight = config.infraredLight
    copied.whiteLight = config.whiteLight
    copied.hFov = config.hFov
    copied.hFovFactor = config.hFovFactor
    return copied


def read_fill_light_config(dll, handle):
    if not hasattr(dll, "IRC_NET_GetFillLightConfigInfo"):
        return None

    config = IRC_NET_FILL_LIGHT_CONFIG_INFO()
    ret = dll.IRC_NET_GetFillLightConfigInfo(handle, ctypes.byref(config))
    if ret != 0:
        print(f"[LIGHT] Get fill light config failed: {ret}")
        return None
    return config


def get_fill_light_token_path():
    return os.path.join(_HERE, "fill_light_token.txt")


def save_fill_light_http_token(token):
    if not token:
        return

    token_path = get_fill_light_token_path()
    try:
        with open(token_path, "w", encoding="utf-8") as f:
            f.write(token.strip() + "\n")
    except Exception as e:
        print(f"[LIGHT] Save fill_light_token.txt failed: {e}")


def find_token_in_response(value):
    if isinstance(value, str):
        token = value.strip()
        if token.startswith("eyJ") and token.count(".") >= 2:
            return token
        return ""

    if isinstance(value, dict):
        for key in ("X-Token", "XToken", "Token", "token", "AccessToken", "access_token"):
            token = find_token_in_response(value.get(key))
            if token:
                return token
        for nested in value.values():
            token = find_token_in_response(nested)
            if token:
                return token

    if isinstance(value, list):
        for item in value:
            token = find_token_in_response(item)
            if token:
                return token

    return ""


def login_fill_light_http_token():
    global fill_light_http_token

    if not FILL_LIGHT_HTTP_AUTO_LOGIN:
        return ""

    username = os.environ.get("TN220_HTTP_USERNAME", USERNAME).strip()
    password_param = os.environ.get(
        "TN220_HTTP_PASSWORD_PARAM", FILL_LIGHT_HTTP_PASSWORD_PARAM
    ).strip()
    if not username or not password_param:
        print("[LIGHT] HTTP auto login skipped: missing username or password parameter.")
        return ""

    query = urllib.parse.urlencode({
        "username": username,
        "password": password_param,
    })
    url = f"http://{DEVICE_IP}/v1/token/?{query}"
    req = urllib.request.Request(
        url,
        data=b"",
        method="POST",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Origin": f"http://{DEVICE_IP}",
            "Referer": f"http://{DEVICE_IP}/",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = text

        token = find_token_in_response(result)
        if not token:
            print(f"[LIGHT] HTTP auto login did not return a token: {text[:160]}")
            return ""

        fill_light_http_token = token
        save_fill_light_http_token(token)
        print("[LIGHT] HTTP auto login OK; token refreshed.")
        return token
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        print(f"[LIGHT] HTTP auto login failed: {e.code} {text[:160]}")
    except Exception as e:
        print(f"[LIGHT] HTTP auto login failed: {e}")
    return ""


def get_fill_light_http_token(force_login=False):
    global fill_light_http_token

    if not force_login:
        token = os.environ.get("TN220_X_TOKEN", "").strip()
        if token:
            return token

        if fill_light_http_token:
            return fill_light_http_token

    token_path = get_fill_light_token_path()
    if os.path.exists(token_path):
        try:
            with open(token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
            if token and not force_login:
                fill_light_http_token = token
                return token
        except Exception as e:
            print(f"[LIGHT] Read fill_light_token.txt failed: {e}")

    return login_fill_light_http_token()


def send_fill_light_level_http(white_level, token):
    if not FILL_LIGHT_HTTP_ENABLE:
        return None, False

    if not token:
        return None, False

    level = max(0, min(FILL_LIGHT_MAX, int(white_level)))
    payload = {
        "FillLightMode": 1,
        "HFovFactor": 1,
        "WhiteLight": level,
        "InfraredLight": FILL_LIGHT_IR_LEVEL if level > 0 else 0,
        "HFov": FILL_LIGHT_HFOV,
    }
    body = json.dumps(payload).encode("utf-8")
    url = f"http://{DEVICE_IP}/v1/peripheral/filllight?debug=false"
    req = urllib.request.Request(
        url,
        data=body,
        method="PUT",
        headers={
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "Origin": f"http://{DEVICE_IP}",
            "Referer": f"http://{DEVICE_IP}/",
            "X-Token": token,
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            print(f"[LIGHT] HTTP fill light level {level}: {resp.status} {text[:120]}")
            try:
                result = json.loads(text)
            except json.JSONDecodeError:
                result = None

            if isinstance(result, dict):
                code = result.get("Code")
                if code in (0, "0", 200, "200", None):
                    return True, False
                else:
                    message = result.get("Message") or result.get("Translate") or text[:160]
                    print(f"[LIGHT] HTTP fill light rejected: Code={code}, {message}")
                    if str(code) == "400701":
                        print("[LIGHT] Token invalid. Refreshing token and retrying once.")
                        return False, True
                    return False, False
        return True, False
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        print(f"[LIGHT] HTTP fill light failed: {e.code} {text[:160]}")
    except Exception as e:
        print(f"[LIGHT] HTTP fill light failed: {e}")
    return False, False


def set_fill_light_level_http(white_level):
    if not FILL_LIGHT_HTTP_ENABLE:
        return None

    token = get_fill_light_http_token()
    if not token:
        print("[LIGHT] HTTP control skipped: auto login failed and no fill_light_token.txt token is available.")
        return None

    ok, token_invalid = send_fill_light_level_http(white_level, token)
    if ok is True:
        return True

    if token_invalid:
        new_token = get_fill_light_http_token(force_login=True)
        if new_token:
            ok, _ = send_fill_light_level_http(white_level, new_token)
            return ok

    return ok


def set_fill_light_level(dll, handle, white_level):
    if not hasattr(dll, "IRC_NET_SetFillLightConfigInfo"):
        print("[LIGHT] Fill light setting is not supported by this SDK.")
        return False

    current = read_fill_light_config(dll, handle)
    if current is None:
        current = IRC_NET_FILL_LIGHT_CONFIG_INFO()

    level = max(0, min(FILL_LIGHT_MAX, int(white_level)))
    current.fillLightMode = 1
    current.whiteLight = level
    current.infraredLight = FILL_LIGHT_IR_LEVEL if level > 0 else 0
    current.hFov = FILL_LIGHT_HFOV

    ret = dll.IRC_NET_SetFillLightConfigInfo(handle, ctypes.byref(current))
    if ret != 0:
        print(f"[LIGHT] Set white fill light {level} failed: {ret}")
        return False

    print(f"[LIGHT] White fill light level: {level}")
    updated = read_fill_light_config(dll, handle)
    if updated is not None:
        print(
            "[LIGHT] Device config now: "
            f"mode={updated.fillLightMode}, "
            f"white={updated.whiteLight}, "
            f"infrared={updated.infraredLight}, "
            f"hFov={updated.hFov}, "
            f"hFovFactor={updated.hFovFactor:.3f}"
        )
    return True


def set_fill_light_aux_state(dll, handle, enabled):
    if not FILL_LIGHT_USE_PTZ_AUX:
        return True
    if not hasattr(dll, "IRC_NET_PtzControl"):
        return True

    control = IRC_NET_PTZ_CONTROL_INFO()
    control.channel = 0
    control.cmd = PTZ_CMD_LIGHT
    control.param1 = 0
    control.param2 = 0
    control.param3 = 0
    control.stop = 0 if enabled else 1

    ret = dll.IRC_NET_PtzControl(handle, ctypes.byref(control))
    if ret != 0:
        state = "on" if enabled else "off"
        print(f"[LIGHT] PTZ light {state} command failed: {ret}")
        return False
    return True


def apply_fill_light_level(dll, handle, white_level):
    level = max(0, min(FILL_LIGHT_MAX, int(white_level)))
    http_ok = set_fill_light_level_http(level)
    if http_ok is True:
        return True

    config_ok = set_fill_light_level(dll, handle, level)
    aux_ok = set_fill_light_aux_state(dll, handle, level > 0)
    return config_ok and aux_ok


def init_fill_light_control(dll, handle):
    global fill_light_original_config, fill_light_level

    if not FILL_LIGHT_HOTKEY_ENABLE:
        return

    print("[LIGHT] Resetting fill light to OFF at startup.")
    apply_fill_light_level(dll, handle, 0)
    fill_light_level = 0

    if not hasattr(dll, "IRC_NET_GetFillLightConfigInfo") or not hasattr(dll, "IRC_NET_SetFillLightConfigInfo"):
        print("[LIGHT] SDK fill light config is not available; HTTP control will still be used.")
        print("[LIGHT] Hotkey ready. Press L to toggle white fill light: 100/0")
        return

    config = read_fill_light_config(dll, handle)
    if config is not None:
        fill_light_original_config = clone_fill_light_config(config)

    print("[LIGHT] Hotkey ready. Press L to toggle white fill light: 100/0")


def toggle_fill_light_level(dll, handle):
    global fill_light_level

    next_level = 0 if fill_light_level > 0 else FILL_LIGHT_ON_LEVEL

    if apply_fill_light_level(dll, handle, next_level):
        fill_light_level = next_level


def restore_fill_light_config(dll, handle):
    global fill_light_original_config, fill_light_level

    print("[LIGHT] Turning fill light OFF before exit.")
    apply_fill_light_level(dll, handle, 0)
    fill_light_level = 0
    fill_light_original_config = None


def shutdown_fill_light_now(dll, handle):
    global fill_light_level

    print("[LIGHT] Turning fill light OFF now.")
    apply_fill_light_level(dll, handle, 0)
    fill_light_level = 0

# ============================================================
# 回调函数
# ============================================================

def on_video_frame(handle, video_info_ptr, ivs_ptr, user_data):
    global latest_rgb, is_recording, video_writer, frame_count, rec_ts, rgb_ts_list
    global rgb_source_w, rgb_source_h
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
            rgb_source_w = vi.width
            rgb_source_h = vi.height

        if is_recording:
            if video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                # 使用 rec_ts（按 S 时记录），与 npy 文件保持同一时间戳
                ts    = rec_ts if rec_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = os.path.join(_DATA_DIR, f"rgb_{ts}.mp4")
                video_writer = cv2.VideoWriter(fname, fourcc, 25.0, (vi.width, vi.height))
                print(f"[视频] 开始写入: {fname}")
            video_writer.write(bgr)
            rgb_ts_list.append(time.time())   # 记录本帧时间戳
            frame_count += 1

    except Exception as e:
        pass  # 回调中不打印，避免卡顿


def on_temp_frame(handle, temp_info_ptr, ext_ptr, user_data):
    global latest_ir, is_recording, temp_list, temp_count, ir_ts_list
    global ir_video_writer, ir_frame_count, rec_ts
    global temperature_level_label, roi_temp_rows
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
            frame_ts = time.time()
            roi_stats, roi_mask = compute_roi_temperature_stats(celsius)

            # 保存温度矩阵（精度数据）
            temp_list.append(celsius)
            ir_ts_list.append(frame_ts)       # 记录本帧时间戳
            roi_temp_rows.append({
                "frame_index": temp_count,
                "unix_timestamp": frame_ts,
                "elapsed_s": frame_ts - ir_ts_list[0],
                "roi_min_c": roi_stats["min"] if roi_stats else float("nan"),
                "roi_max_c": roi_stats["max"] if roi_stats else float("nan"),
                "roi_avg_c": roi_stats["avg"] if roi_stats else float("nan"),
                "roi_pixel_count": roi_stats["pixel_count"] if roi_stats else 0,
                "temp_level": temperature_level_label,
            })
            temp_count += 1

            # 同步录制 IR 伪彩色视频
            if ir_video_writer is None:
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                ts = rec_ts if rec_ts else datetime.now().strftime("%Y%m%d_%H%M%S")
                ir_fname = os.path.join(_DATA_DIR, f"ir_{ts}.mp4")
                # IR 实际回调约 40fps，标称帧率设为 40.0 确保视频播放时长正常
                ir_video_writer = cv2.VideoWriter(
                    ir_fname, fourcc, 40.0, (IR_VIDEO_W, IR_VIDEO_H)
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

            draw_ir_roi_outline(colored, roi_mask)
            if roi_stats:
                cv2.putText(colored, f"ROI MAX:{roi_stats['max']:.1f}C", (4, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(colored, f"ROI MIN:{roi_stats['min']:.1f}C", (4, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(colored, f"ROI AVG:{roi_stats['avg']:.1f}C", (4, 60),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            else:
                cv2.putText(colored, "ROI TEMP:N/A", (4, 40),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(colored, f"LEVEL:{temperature_level_label}", (4, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            ir_video_writer.write(colored)
            ir_frame_count += 1

    except Exception as e:
        pass

# ============================================================
# ROI 工具函数
# ============================================================

def load_roi_homography():
    """Load RGB -> IR calibration, with proportional mapping as fallback."""
    global roi_homography, roi_mapping_label
    for path in HOMOGRAPHY_PATHS:
        if not os.path.exists(path):
            continue
        try:
            matrix = np.load(path)
            if matrix.shape != (3, 3):
                raise ValueError(f"shape={matrix.shape}")
            roi_homography = matrix.astype(np.float64)
            roi_mapping_label = "H"
            print(f"[ROI] 已加载 RGB->IR 标定矩阵: {os.path.abspath(path)}")
            return True
        except Exception as exc:
            print(f"[ROI] 标定矩阵读取失败: {path}  {exc}")

    roi_homography = None
    roi_mapping_label = "SCALE"
    print("[ROI] 未找到 homography.npy，将按画面比例映射 ROI")
    return False


def build_ir_roi_mask(temp_shape):
    """Project the current RGB preview ROI into one IR-frame mask."""
    global _roi_mask_cache_key, _roi_mask_cache

    ir_h, ir_w = temp_shape[:2]
    rgb_w = max(int(rgb_source_w), 1)
    rgb_h = max(int(rgb_source_h), 1)
    cache_key = (
        ir_h, ir_w, rgb_w, rgb_h,
        int(roi_cx), int(roi_cy), int(roi_radius),
        id(roi_homography),
    )
    if cache_key == _roi_mask_cache_key and _roi_mask_cache is not None:
        return _roi_mask_cache

    sx = rgb_w / PREVIEW_W
    sy = rgb_h / PREVIEW_H
    angles = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
    points_rgb = np.column_stack((
        roi_cx * sx + roi_radius * sx * np.cos(angles),
        roi_cy * sy + roi_radius * sy * np.sin(angles),
    )).astype(np.float32).reshape(-1, 1, 2)

    if roi_homography is not None:
        points_ir = cv2.perspectiveTransform(points_rgb, roi_homography).reshape(-1, 2)
    else:
        points_ir = points_rgb.reshape(-1, 2)
        points_ir[:, 0] *= ir_w / rgb_w
        points_ir[:, 1] *= ir_h / rgb_h

    points_ir = points_ir[np.isfinite(points_ir).all(axis=1)]
    if len(points_ir) < 3:
        return None

    points_ir[:, 0] = np.clip(points_ir[:, 0], 0, ir_w - 1)
    points_ir[:, 1] = np.clip(points_ir[:, 1], 0, ir_h - 1)
    polygon = np.round(points_ir).astype(np.int32)
    mask = np.zeros((ir_h, ir_w), dtype=np.uint8)
    cv2.fillPoly(mask, [polygon], 255)
    if not np.any(mask):
        return None

    _roi_mask_cache_key = cache_key
    _roi_mask_cache = mask
    return mask


def compute_roi_temperature_stats(temp_matrix):
    """Return min/max/average temperature inside the current RGB ROI."""
    roi_mask = build_ir_roi_mask(temp_matrix.shape)
    if roi_mask is None:
        return None, None
    values = temp_matrix[roi_mask > 0]
    values = values[np.isfinite(values)]
    if values.size == 0:
        return None, roi_mask
    return {
        "min": float(np.min(values)),
        "max": float(np.max(values)),
        "avg": float(np.mean(values)),
        "pixel_count": int(values.size),
    }, roi_mask


def draw_ir_roi_outline(image, roi_mask):
    """Draw the projected ROI boundary on an IR preview or recorded frame."""
    if roi_mask is None:
        return
    resized_mask = cv2.resize(
        roi_mask, (image.shape[1], image.shape[0]), interpolation=cv2.INTER_NEAREST
    )
    contours, _ = cv2.findContours(
        resized_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cv2.drawContours(image, contours, -1, (255, 200, 0), 2)


def save_roi_temperature_outputs(rows, timestamp, output_dir=None):
    """Save per-frame ROI statistics to CSV and a temperature curve PNG."""
    if not rows:
        print("[ROI] 没有可保存的 ROI 温度记录")
        return None, None

    output_dir = output_dir or _DATA_DIR
    os.makedirs(output_dir, exist_ok=True)
    csv_path = os.path.join(output_dir, f"roi_temp_{timestamp}.csv")
    curve_path = os.path.join(output_dir, f"roi_temp_curve_{timestamp}.png")
    fieldnames = [
        "frame_index", "unix_timestamp", "elapsed_s",
        "roi_min_c", "roi_max_c", "roi_avg_c",
        "roi_pixel_count", "temp_level",
    ]
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"[OK] ROI 温度数据已保存: {csv_path}  ({len(rows)} 帧)")

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        elapsed = np.array([row["elapsed_s"] for row in rows], dtype=float)
        roi_min = np.array([row["roi_min_c"] for row in rows], dtype=float)
        roi_max = np.array([row["roi_max_c"] for row in rows], dtype=float)
        roi_avg = np.array([row["roi_avg_c"] for row in rows], dtype=float)
        valid = (
            np.isfinite(elapsed) & np.isfinite(roi_min)
            & np.isfinite(roi_max) & np.isfinite(roi_avg)
        )
        if not np.any(valid):
            raise ValueError("没有有效 ROI 温度值")

        fig, ax = plt.subplots(figsize=(12, 5.5))
        ax.fill_between(
            elapsed[valid], roi_min[valid], roi_max[valid],
            color="#f4a261", alpha=0.22, label="ROI min-max",
        )
        ax.plot(
            elapsed[valid], roi_avg[valid], color="#d1495b",
            linewidth=1.4, label="ROI average",
        )
        ax.plot(
            elapsed[valid], roi_max[valid], color="#e76f51",
            linewidth=0.7, alpha=0.75, label="ROI maximum",
        )
        ax.plot(
            elapsed[valid], roi_min[valid], color="#2a9d8f",
            linewidth=0.7, alpha=0.75, label="ROI minimum",
        )
        ax.set_title("ROI Temperature Curve")
        ax.set_xlabel("Elapsed time (s)")
        ax.set_ylabel("Temperature (C)")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(curve_path, dpi=160)
        plt.close(fig)
        print(f"[OK] ROI 温度曲线已保存: {curve_path}")
    except Exception as exc:
        curve_path = None
        print(f"[警告] ROI 温度曲线生成失败: {exc}")

    return csv_path, curve_path

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

def temp_to_colormap(temp_matrix, width=640, height=480,
                     roi_stats=None, roi_mask=None):
    """将温度矩阵转换为 jet 伪彩色图，并显示 RGB ROI 温度。"""
    t_min = np.min(temp_matrix)
    t_max = np.max(temp_matrix)
    if t_max - t_min < 0.1:
        norm = np.zeros_like(temp_matrix, dtype=np.uint8)
    else:
        norm = ((temp_matrix - t_min) / (t_max - t_min) * 255).astype(np.uint8)
    colored = cv2.applyColorMap(norm, cv2.COLORMAP_JET)
    resized = cv2.resize(colored, (width, height))

    draw_ir_roi_outline(resized, roi_mask)
    if roi_stats:
        cv2.putText(resized, f"ROI MAX: {roi_stats['max']:.1f}C", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
        cv2.putText(resized, f"ROI MIN: {roi_stats['min']:.1f}C", (10, 62),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
        cv2.putText(resized, f"ROI AVG: {roi_stats['avg']:.1f}C", (10, 94),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    else:
        cv2.putText(resized, "ROI TEMP: N/A", (10, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.72, (255, 255, 255), 2)
    return resized

# ============================================================
# 主程序
# ============================================================

def main():
    global is_recording, video_writer, ir_video_writer, ir_frame_count
    global temp_list, roi_temp_rows, frame_count, temp_count, rec_ts
    global rgb_ts_list, ir_ts_list
    global roi_editing, roi_cx, roi_cy, roi_radius, roi_dragging

    print("=" * 55)
    print("  Chef Vision — 厨房数据采集（现场版）")
    print("=" * 55)
    print(f"  设备 IP : {DEVICE_IP}:{DEVICE_PORT}")
    print(f"  DLL 路径: {DLL_PATH}")
    print("-" * 55)
    print("  操作说明：")
    print("    [S] 开始录制")
    print("    [1] 高增益 HG  [2] 低增益 LG  [3] 自动 AUTO")
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
    apply_temperature_level_mode(dll, handle)
    sync_device_time(dll, handle)
    load_roi_homography()

    # 2. 注册回调
    init_fill_light_control(dll, handle)

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
    print("  [1] 高增益 HG  [2] 低增益 LG  [3] 自动 AUTO")

    # 5. 主循环：显示双画面预览
    WIN_NAME = "Chef Vision [S] REC [Q] Quit [R] ROI [L] Light [1/2/3] Temp Level"

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
            roi_stats, roi_mask = compute_roi_temperature_stats(ir_matrix)
            right = temp_to_colormap(
                ir_matrix, PREVIEW_W, PREVIEW_H,
                roi_stats=roi_stats, roi_mask=roi_mask,
            )
        else:
            right = np.zeros((PREVIEW_H, PREVIEW_W, 3), dtype=np.uint8)
            cv2.putText(right, "等待 IR 信号...", (150, 240),
                        cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)

        # 更新原始 RGB 分辨率
        if rgb_frame is not None:
            rgb_orig_h, rgb_orig_w = rgb_frame.shape[:2]

        # 在 RGB 预览上绘制 ROI 圆形
        draw_roi_on_frame(left, editing=roi_editing)

        # 录制状态指示
        status_color = (0, 0, 255) if is_recording else (0, 200, 0)
        status_text  = f"● REC  帧:{frame_count}" if is_recording else "● 预览中  [S]=录制  [Q]=退出  [R]=ROI"
        cv2.putText(left,  status_text, (10, PREVIEW_H - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, status_color, 2)
        cv2.putText(right, "IR 热力图", (10, PREVIEW_H - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

        # 左右拼接
        light_text = f"White Light: {fill_light_level}  [L]=ON/OFF"
        cv2.putText(right, light_text, (10, PREVIEW_H - 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        level_text = f"Temp Level: {temperature_level_label}  [1]HG [2]LG [3]AUTO"
        cv2.putText(right, level_text, (10, PREVIEW_H - 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)

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
                roi_temp_rows   = []
                # Reset the shared timestamp buffers used by the callbacks and final save.
                rgb_ts_list     = []
                ir_ts_list      = []
                frame_count     = 0
                temp_count      = 0
                ir_frame_count  = 0
                ir_video_writer = None   # 确保下次录制创建新文件
                print(f"\n[录制] 已开始录制！时间戳: {rec_ts}  按 Q 停止")
            else:
                print("[提示] 已在录制中")

        elif key == ord('l') or key == ord('L'):
            toggle_fill_light_level(dll, handle)

        elif key == ord('1'):
            switch_temperature_level(dll, handle, "high")

        elif key == ord('2'):
            switch_temperature_level(dll, handle, "low")

        elif key == ord('3'):
            switch_temperature_level(dll, handle, "auto")

        elif key == ord('q') or key == ord('Q'):
            print("\n[停止] 正在保存数据...")
            shutdown_fill_light_now(dll, handle)
            # 无论 ROI 有没有手动编辑，都强制保存一份当前状态
            save_roi_config(PREVIEW_W, PREVIEW_H, rgb_orig_w, rgb_orig_h)
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

    # 8. 保存温度矩阵 + 逐帧时间戳（使用 rec_ts，与视频保持同一时间戳）
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
        # 保存 IR 逐帧时间戳
        if len(ir_ts_list) > 0:
            ir_ts_arr  = np.array(ir_ts_list, dtype=np.float64)
            ir_ts_name = os.path.join(_DATA_DIR, f"temp_{ts}_ts.npy")
            np.save(ir_ts_name, ir_ts_arr)
            print(f"[OK] IR 时间戳已保存: {ir_ts_name}  ({len(ir_ts_arr)} 帧)")
    else:
        print("[警告] 未采集到温度数据（是否忘记按 S 开始录制？）")
    # 保存 RGB 逐帧时间戳
    if len(rgb_ts_list) > 0:
        rgb_ts_arr  = np.array(rgb_ts_list, dtype=np.float64)
        rgb_ts_name = os.path.join(_DATA_DIR, f"rgb_{ts}_ts.npy")
        np.save(rgb_ts_name, rgb_ts_arr)
        print(f"[OK] RGB 时间戳已保存: {rgb_ts_name}  ({len(rgb_ts_arr)} 帧)")

    save_roi_temperature_outputs(roi_temp_rows, ts)

    # 9. 登出
    restore_fill_light_config(dll, handle)
    dll.IRC_NET_Logout(handle)
    dll.IRC_NET_Deinit()
    print("\n[完成] 设备已断开，文件保存在脚本所在文件夹")
    input("按 Enter 退出...")


if __name__ == "__main__":
    main()
