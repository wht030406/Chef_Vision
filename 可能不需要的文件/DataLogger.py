"""
工业双光热像仪厨房数据采集脚本
基于 ThermalCamera.py 封装类，使用 ctypes 实现视频和温度拉流回调与保存逻辑
作者：Claude
版本：1.0
"""

import ctypes
import numpy as np
import cv2
import time
from ctypes import (
    c_int, c_int64, c_uint8, c_uint16, c_uint32, c_uint64, c_void_p,
    POINTER, Structure, CFUNCTYPE, string_at
)
import os
import sys

# 将 sdk/ 目录加入搜索路径，以便 import ThermalCamera
_HERE = os.path.dirname(os.path.abspath(__file__))
_SDK_DIR  = os.path.join(_HERE, "..", "sdk")
_DATA_DIR = os.path.join(_HERE, "..", "data")
os.makedirs(_DATA_DIR, exist_ok=True)
if _SDK_DIR not in sys.path:
    sys.path.insert(0, _SDK_DIR)


# ============================================================================
# SDK 结构体定义 (根据 IRCNetSDK 头文件映射)
# ============================================================================

class IRC_NET_VIDEO_INFO_CB(Structure):
    """
    可见光视频回调信息结构体 (V2版本)
    根据 IRCNetSDKDef.h 定义
    """
    _fields_ = [
        ("frame", POINTER(c_uint8)),     # 帧数据指针 (RGB24格式，3通道)
        ("width", c_int),                # 图像宽度
        ("height", c_int),               # 图像高度
        ("validWidth", c_int),           # 有效宽度
        ("validHeight", c_int),          # 有效高度
        ("timestamp", c_int64),          # 时间戳（毫秒）
    ]


class IRC_NET_TEMP_INFO_CB(Structure):
    """
    红外温度回调信息结构体 (V2版本)
    根据 IRCNetSDKDef.h 定义
    """
    _fields_ = [
        ("temp", POINTER(c_uint8)),      # 温度数据指针 (int16类型，每个像素2字节)
        ("width", c_int),                # 温度矩阵宽度
        ("height", c_int),               # 温度矩阵高度
    ]


class IRC_NET_PREVIEW_INFO(Structure):
    """
    预览信息结构体
    用于 IRC_NET_StartPreview_V2 函数
    """
    _fields_ = [
        ("channel", c_int),      # 通道
        ("streamType", c_int),   # 码流类型，参考IRC_NET_STREAM_TYPE
        ("frameFmt", c_int),     # 帧格式，参考IRC_NET_FRAME_FMT
    ]


# 回调函数类型定义 (V2版本)
VIDEO_CALLBACK = CFUNCTYPE(
    None,                               # 返回类型 void
    c_uint64,                          # 设备句柄 (IRC_NET_HANDLE)
    POINTER(IRC_NET_VIDEO_INFO_CB),    # 视频信息结构体指针
    c_void_p,                          # IVS信息结构体指针 (IRC_NET_IVS_INFO_CB*)，暂不使用
    c_void_p                           # 用户数据指针
)

TEMP_CALLBACK = CFUNCTYPE(
    None,                               # 返回类型 void
    c_uint64,                          # 设备句柄 (IRC_NET_HANDLE)
    POINTER(IRC_NET_TEMP_INFO_CB),     # 温度信息结构体指针
    c_void_p,                          # 温度扩展信息结构体指针 (IRC_NET_TEMP_EXT_INFO_CB*)，暂不使用
    c_void_p                           # 用户数据指针
)


# ============================================================================
# 数据采集主类
# ============================================================================

class DataLogger:
    """
    双光热像仪数据采集器
    功能：
    1. 接收可见光视频流（RGB24格式），保存为 MP4 文件
    2. 接收红外温度流（int16格式），转换为摄氏度并保存为 numpy 数组
    """

    def __init__(self, camera):
        """
        初始化数据采集器

        Args:
            camera: ThermalCamera 实例，必须已成功登录获取句柄
        """
        self.camera = camera
        self._dll = camera._dll  # 复用 DLL 实例

        # 视频录制相关
        self.video_writer = None
        self.video_width = 0
        self.video_height = 0
        self.video_frame_count = 0

        # 温度数据相关
        self.temp_list = []          # 存储每帧温度矩阵（摄氏度）
        self.temp_width = 0
        self.temp_height = 0
        self.temp_frame_count = 0

        # 回调函数对象（必须保存引用，防止被垃圾回收）
        self._video_callback_func = None
        self._temp_callback_func = None

        # 设置 SDK 函数签名（如果尚未设置）
        self._setup_function_signatures()

        # 录制状态
        self.is_recording = False

        print("[DataLogger] 初始化完成")

    def _setup_function_signatures(self):
        """设置 SDK 拉流和停止函数的签名"""
        # IRC_NET_StartPreview_V2: 启动可见光视频预览 (V2版本，使用IRC_NET_VIDEO_CALLBACK_V2回调)
        if hasattr(self._dll, 'IRC_NET_StartPreview_V2'):
            self._dll.IRC_NET_StartPreview_V2.argtypes = [
                c_uint64,                       # 设备句柄
                POINTER(IRC_NET_PREVIEW_INFO),  # 预览信息结构体指针
                VIDEO_CALLBACK,                 # 视频回调函数 (IRC_NET_VIDEO_CALLBACK_V2)
                c_void_p                        # 用户数据指针
            ]
            self._dll.IRC_NET_StartPreview_V2.restype = c_int
        # 向后兼容：如果只有旧版本函数，设置旧版本签名
        elif hasattr(self._dll, 'IRC_NET_StartPreview'):
            self._dll.IRC_NET_StartPreview.argtypes = [
                c_uint64,          # 设备句柄
                POINTER(IRC_NET_PREVIEW_INFO),  # 预览信息结构体指针
                VIDEO_CALLBACK,    # 视频回调函数
                c_void_p           # 用户数据指针
            ]
            self._dll.IRC_NET_StartPreview.restype = c_int

        # IRC_NET_StopPreview: 停止可见光视频预览
        if hasattr(self._dll, 'IRC_NET_StopPreview'):
            self._dll.IRC_NET_StopPreview.argtypes = [
                c_uint64           # 设备句柄
            ]
            self._dll.IRC_NET_StopPreview.restype = c_int

        # IRC_NET_StartPullTemp_V2: 启动温度数据拉流
        if hasattr(self._dll, 'IRC_NET_StartPullTemp_V2'):
            self._dll.IRC_NET_StartPullTemp_V2.argtypes = [
                c_uint64,          # 设备句柄
                TEMP_CALLBACK,     # 温度回调函数 (IRC_NET_TEMP_CALLBACK_V2)
                c_void_p           # 用户数据指针
            ]
            self._dll.IRC_NET_StartPullTemp_V2.restype = c_int

        # IRC_NET_StopPullTemp: 停止温度数据拉流
        if hasattr(self._dll, 'IRC_NET_StopPullTemp'):
            self._dll.IRC_NET_StopPullTemp.argtypes = [
                c_uint64           # 设备句柄
            ]
            self._dll.IRC_NET_StopPullTemp.restype = c_int
        # 向后兼容：如果只有V2版本函数（理论上不存在）
        elif hasattr(self._dll, 'IRC_NET_StopPullTemp_V2'):
            self._dll.IRC_NET_StopPullTemp_V2.argtypes = [
                c_uint64           # 设备句柄
            ]
            self._dll.IRC_NET_StopPullTemp_V2.restype = c_int

    # ------------------------------------------------------------------------
    # 回调函数实现
    # ------------------------------------------------------------------------

    def _on_video_frame(self, handle, video_info_ptr, ivs_info_ptr, user_data):
        """
        可见光视频帧回调函数 (V2版本)
        数据格式：RGB24，3通道
        处理流程：过滤坏帧 → 读取内存 → RGB转BGR → 写入视频文件
        """
        try:
            video_info = video_info_ptr.contents

            # 调试信息
            print(f"[视频调试] 接收到视频帧: width={video_info.width}, height={video_info.height}, validWidth={video_info.validWidth}, validHeight={video_info.validHeight}")
            print(f"[视频调试] frame指针: {video_info.frame}, timestamp={video_info.timestamp}")

            # 1. 过滤坏帧（宽度或高度为0的帧直接丢弃）
            if video_info.width <= 0 or video_info.height <= 0:
                print(f"[视频调试] 过滤坏帧: width={video_info.width}, height={video_info.height}")
                return

            width = video_info.width
            height = video_info.height

            # 2. 延迟初始化 VideoWriter（在拿到第一帧有效分辨率后）
            if self.video_writer is None:
                self.video_width = width
                self.video_height = height

                # 创建视频写入器：MP4格式，25 FPS，BGR颜色空间
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                self.video_writer = cv2.VideoWriter(
                    os.path.join(_DATA_DIR, 'rgb_record.mp4'),
                    fourcc,
                    25.0,
                    (width, height)
                )
                print(f"[视频] 初始化 VideoWriter: {width}x{height}, 25 FPS")

            # 3. 安全读取内存字节（使用 string_at 防止截断）
            # RGB24 数据大小 = 宽度 × 高度 × 3
            data_size = width * height * 3
            print(f"[视频调试] 准备读取视频数据，大小: {data_size}字节")

            if data_size <= 0:
                print(f"[视频调试] 视频数据大小无效: {data_size}")
                return

            frame_data = string_at(video_info.frame, data_size)
            print(f"[视频调试] 成功读取 {len(frame_data)} 字节视频数据")

            # 4. 转换为 numpy 数组并重塑为 RGB 格式
            frame_np = np.frombuffer(frame_data, dtype=np.uint8)
            frame_np = frame_np.reshape((height, width, 3))  # RGB 格式

            # 5. RGB 转 BGR（OpenCV 默认使用 BGR）
            frame_bgr = cv2.cvtColor(frame_np, cv2.COLOR_RGB2BGR)

            # 6. 写入视频文件
            self.video_writer.write(frame_bgr)
            self.video_frame_count += 1

            # 每30帧打印一次进度
            if self.video_frame_count % 30 == 0:
                print(f"[视频] 已录制 {self.video_frame_count} 帧")

        except Exception as e:
            print(f"[视频回调异常] {e}")
            import traceback
            traceback.print_exc()

    def _on_temp_frame(self, handle, temp_info_ptr, ext_info_ptr, user_data):
        """
        红外温度帧回调函数 (V2版本)
        数据格式：int16（2字节），表示开尔文温度 × 10
        处理流程：读取内存 → 转换为 int16 矩阵 → 换算为摄氏度 → 保存到列表
        """
        try:
            temp_info = temp_info_ptr.contents

            # 调试信息：打印接收到的结构体内容
            print(f"[温度调试] 接收到温度帧: width={temp_info.width}, height={temp_info.height}")
            print(f"[温度调试] temp指针: {temp_info.temp}")

            # 过滤坏帧
            if temp_info.width <= 0 or temp_info.height <= 0:
                print(f"[温度调试] 过滤坏帧: width={temp_info.width}, height={temp_info.height}")
                return

            # 检查尺寸是否合理（通常温度矩阵不会超过1000x1000）
            if temp_info.width > 1000 or temp_info.height > 1000:
                print(f"[温度调试] 尺寸异常: {temp_info.width}x{temp_info.height}")
                return

            width = temp_info.width
            height = temp_info.height

            # 记录温度矩阵尺寸（第一次有效帧）
            if self.temp_width == 0:
                self.temp_width = width
                self.temp_height = height
                print(f"[温度] 温度矩阵尺寸: {width}x{height}")

            # 安全读取内存字节（每个像素2字节）
            data_size = width * height * 2
            print(f"[温度调试] 准备读取数据，大小: {data_size}字节")

            if data_size <= 0:
                print(f"[温度调试] 数据大小无效: {data_size}")
                return

            temp_data = string_at(temp_info.temp, data_size)
            print(f"[温度调试] 成功读取 {len(temp_data)} 字节数据")

            # 转换为 int16 numpy 数组并重塑为二维矩阵
            temp_np = np.frombuffer(temp_data, dtype=np.int16)
            temp_np = temp_np.reshape((height, width))

            # 温度换算：原始值 ÷ 10.0 - 273.15 = 摄氏度
            # 原始值 = 开尔文温度 × 10
            temp_celsius = (temp_np.astype(np.float32) / 10.0) - 273.15

            # 保存到列表
            self.temp_list.append(temp_celsius)
            self.temp_frame_count += 1

            # 每30帧打印一次进度
            if self.temp_frame_count % 30 == 0:
                print(f"[温度] 已采集 {self.temp_frame_count} 帧")
                # 显示当前帧温度范围（调试用）
                min_temp = np.min(temp_celsius)
                max_temp = np.max(temp_celsius)
                print(f"      温度范围: {min_temp:.1f}℃ ~ {max_temp:.1f}℃")

        except Exception as e:
            print(f"[温度回调异常] {e}")
            import traceback
            traceback.print_exc()

    # ------------------------------------------------------------------------
    # 公共控制接口
    # ------------------------------------------------------------------------

    def start_record(self):
        """
        开始录制可见光视频和红外温度数据
        1. 启动温度拉流
        2. 启动可见光视频预览
        注意：回调函数对象必须绑定到 self 防止垃圾回收
        """
        if self.is_recording:
            print("[警告] 录制已在进行中")
            return

        handle = self.camera.handle
        if handle is None:
            print("[错误] 设备未登录，无法开始录制")
            return

        print("[DataLogger] 开始录制...")

        # 创建回调函数对象并保存引用
        self._temp_callback_func = TEMP_CALLBACK(self._on_temp_frame)
        self._video_callback_func = VIDEO_CALLBACK(self._on_video_frame)

        # 1. 启动温度拉流
        print("-> 启动温度拉流...")
        temp_result = self._dll.IRC_NET_StartPullTemp_V2(
            handle,
            self._temp_callback_func,
            None  # 用户数据（可传递 self 指针，这里暂不使用）
        )

        if temp_result != self.camera.ERROR_OK:
            print(f"[错误] 启动温度拉流失败，错误码: {temp_result}")
            return

        # 2. 启动可见光视频预览（通道号1）
        print("-> 启动可见光视频预览（通道1）...")

        # 创建预览信息结构体
        preview_info = IRC_NET_PREVIEW_INFO()
        preview_info.channel = 0  # 可见光通道（0=RGB，1=IR）
        preview_info.streamType = 0  # IRC_NET_STREAM_MAIN (主码流)
        preview_info.frameFmt = 1  # IRC_NET_FRAME_FMT_RGB24 (RGB24格式)

        # 尝试使用 V2 版本，如果不存在则使用旧版本
        if hasattr(self._dll, 'IRC_NET_StartPreview_V2'):
            video_result = self._dll.IRC_NET_StartPreview_V2(
                handle,
                ctypes.byref(preview_info),
                self._video_callback_func,
                None  # 用户数据
            )
        else:
            video_result = self._dll.IRC_NET_StartPreview(
                handle,
                ctypes.byref(preview_info),
                self._video_callback_func,
                None  # 用户数据
            )

        if video_result != self.camera.ERROR_OK:
            print(f"[错误] 启动视频预览失败，错误码: {video_result}")
            # 停止已启动的温度拉流
            if hasattr(self._dll, 'IRC_NET_StopPullTemp'):
                self._dll.IRC_NET_StopPullTemp(handle)
            elif hasattr(self._dll, 'IRC_NET_StopPullTemp_V2'):
                self._dll.IRC_NET_StopPullTemp_V2(handle)
            return

        self.is_recording = True
        print("[DataLogger] 录制已启动，等待数据流...")

    def stop_record(self):
        """停止录制并保存数据"""
        if not self.is_recording:
            print("[警告] 未在录制状态")
            return

        handle = self.camera.handle
        if handle is None:
            print("[错误] 设备句柄无效")
            return

        print("\n[DataLogger] 停止录制...")

        # 1. 停止温度拉流
        print("-> 停止温度拉流...")
        if hasattr(self._dll, 'IRC_NET_StopPullTemp'):
            self._dll.IRC_NET_StopPullTemp(handle)
        elif hasattr(self._dll, 'IRC_NET_StopPullTemp_V2'):
            self._dll.IRC_NET_StopPullTemp_V2(handle)
        else:
            print("[警告] 未找到停止温度拉流函数")

        # 2. 停止视频预览
        print("-> 停止视频预览...")
        self._dll.IRC_NET_StopPreview(handle)

        # 3. 释放 VideoWriter
        if self.video_writer is not None:
            self.video_writer.release()
            self.video_writer = None
            print(f"[视频] 视频文件已保存: rgb_record.mp4")
            print(f"      共录制 {self.video_frame_count} 帧")

        # 4. 保存温度数据
        if len(self.temp_list) > 0:
            # 堆叠所有温度帧为一个三维 numpy 数组
            temp_stack = np.stack(self.temp_list, axis=0)

            # 保存为 .npy 文件
            _npy_path = os.path.join(_DATA_DIR, "temp_matrices.npy")
            np.save(_npy_path, temp_stack)
            print(f"[温度] 温度数据已保存: {_npy_path}")
            print(f"      共采集 {self.temp_frame_count} 帧，形状: {temp_stack.shape}")

            # 显示温度统计信息
            if self.temp_frame_count > 0:
                first_frame = self.temp_list[0]
                min_temp = np.min(first_frame)
                max_temp = np.max(first_frame)
                avg_temp = np.mean(first_frame)
                print(f"      第一帧温度范围: {min_temp:.1f}℃ ~ {max_temp:.1f}℃")
                print(f"      第一帧平均温度: {avg_temp:.1f}℃")
        else:
            print("[温度] 未采集到温度数据")

        # 5. 重置状态
        self.is_recording = False

        # 6. 清空回调函数引用（允许垃圾回收）
        self._temp_callback_func = None
        self._video_callback_func = None

        print("[DataLogger] 录制已停止")


# ============================================================================
# 主程序
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("工业双光热像仪厨房数据采集系统")
    print("=" * 60)

    # 设备参数（与 ThermalCamera.py 保持一致）
    DEVICE_IP = "192.168.1.123"
    DEVICE_PORT = 80
    USERNAME = "admin"
    PASSWORD = "ZGTC2026"

    try:
        # 1. 初始化热像仪 SDK
        print("\n[1/4] 初始化热像仪 SDK...")
        from ThermalCamera import ThermalCamera  # noqa: E402 (sdk/ already in sys.path)
        camera = ThermalCamera()

        init_result = camera.init()
        if init_result != camera.ERROR_OK:
            print(f"[错误] SDK 初始化失败: {init_result}")
            sys.exit(1)
        print(f"[OK] SDK 初始化成功")

        # 2. 登录设备
        print(f"\n[2/4] 登录设备 {DEVICE_IP}:{DEVICE_PORT}...")
        login_result = camera.login(DEVICE_IP, DEVICE_PORT, USERNAME, PASSWORD)
        if login_result != camera.ERROR_OK:
            print(f"[错误] 登录失败: {login_result} - {camera.get_error_message(login_result)}")
            camera.deinit()
            sys.exit(1)
        print(f"[OK] 登录成功，设备句柄: {camera.handle}")

        # 3. 创建数据采集器并开始录制
        print("\n[3/4] 创建数据采集器...")
        logger = DataLogger(camera)
        logger.start_record()

        # 4. 等待用户手动停止
        print("\n" + "=" * 60)
        print("正在录制中... 按 Enter 键停止录制")
        print("=" * 60)
        input()

        # 5. 停止录制
        print("\n[4/4] 停止录制...")
        logger.stop_record()

        # 6. 安全退出
        print("\n[清理] 退出登录并释放资源...")
        camera.logout()
        camera.deinit()

        print("\n" + "=" * 60)
        print("数据采集完成！")
        print("生成的文件:")
        print("  1. rgb_record.mp4 - 可见光视频")
        print("  2. temp_matrices.npy - 红外温度数据")
        print("=" * 60)

    except KeyboardInterrupt:
        print("\n\n[中断] 用户中断程序")
        # 尝试安全停止录制
        if 'logger' in locals() and logger.is_recording:
            logger.stop_record()
        if 'camera' in locals():
            camera.logout()
            camera.deinit()
        sys.exit(0)

    except Exception as e:
        print(f"\n[异常] 程序运行出错: {e}")
        import traceback
        traceback.print_exc()

        # 尝试安全清理
        if 'logger' in locals() and logger.is_recording:
            logger.stop_record()
        if 'camera' in locals():
            camera.logout()
            camera.deinit()
        sys.exit(1)