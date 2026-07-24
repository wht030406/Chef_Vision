"""
红外热像仪 SDK (IRCNetSDK) Python ctypes 封装
用于视觉测温系统的底层接口
"""

import ctypes
import os
from ctypes import c_char, c_int, c_uint64, POINTER, Structure

# SDK DLL 所在目录（与本文件同目录）
_SDK_DIR = os.path.dirname(os.path.abspath(__file__))

class IRC_NET_LOGIN_INFO(Structure):
    """登录信息结构体"""
    _fields_ = [
        ("ip", c_char * 16),          # 设备IP
        ("port", c_int),              # 设备端口
        ("username", c_char * 256),   # 用户名
        ("password", c_char * 256),   # 密码
    ]

class ThermalCamera:
    """热像仪 SDK 封装类"""

    # 错误码定义
    ERROR_OK = 0
    ERROR_FAILED = 1
    ERROR_NOT_SUPPORTED = 2
    ERROR_PARAM_WRONG = 3
    ERROR_TEMP_CALLBACK_WRONG = 4
    ERROR_BLACK_LIST = 1001
    ERROR_NONE_USER = 1002
    ERROR_PWD_WRONG = 1003
    ERROR_ACCOUNT_LOCK = 1005
    ERROR_USER_LIMIT = 1006
    ERROR_SYSTEM_EXCEPTION = 1007

    def __init__(self, dll_path: str = None):
        """
        初始化热像仪封装类
        Args:
            dll_path: SDK DLL 文件路径
        """
        self._dll = None
        self._handle = None
        if dll_path is None:
            dll_path = os.path.join(_SDK_DIR, "IRCNetSDK.dll")
        self._load_dll(dll_path)

    def _load_dll(self, dll_path: str):
        """加载 SDK DLL"""
        if not os.path.exists(dll_path):
            raise FileNotFoundError(f"SDK DLL 未找到: {dll_path}")

        # 将 SDK 目录加入 DLL 搜索路径（Windows 需要）
        os.add_dll_directory(_SDK_DIR)
        self._dll = ctypes.CDLL(dll_path)
        self._setup_function_signatures()

    def _setup_function_signatures(self):
        """设置函数签名"""
        # IRC_NET_Init: 初始化
        self._dll.IRC_NET_Init.argtypes = []
        self._dll.IRC_NET_Init.restype = c_int

        # IRC_NET_Login: 登录
        self._dll.IRC_NET_Login.argtypes = [
            POINTER(IRC_NET_LOGIN_INFO),
            POINTER(c_uint64)
        ]
        self._dll.IRC_NET_Login.restype = c_int

        # IRC_NET_Logout: 退出登录
        self._dll.IRC_NET_Logout.argtypes = [c_uint64]
        self._dll.IRC_NET_Logout.restype = c_int

        # IRC_NET_Deinit: 反初始化
        self._dll.IRC_NET_Deinit.argtypes = []
        self._dll.IRC_NET_Deinit.restype = None

    def init(self) -> int:
        """初始化 SDK"""
        return self._dll.IRC_NET_Init()

    def login(self, ip: str, port: int, username: str, password: str) -> int:
        """登录设备"""
        login_info = IRC_NET_LOGIN_INFO()
        login_info.ip = ip.encode('utf-8')
        login_info.port = port
        login_info.username = username.encode('utf-8')
        login_info.password = password.encode('utf-8')

        # 创建句柄变量
        handle = c_uint64()

        result = self._dll.IRC_NET_Login(
            ctypes.byref(login_info),
            ctypes.byref(handle)
        )

        # 登录成功后保存句柄
        if result == self.ERROR_OK:
            self._handle = handle.value

        return result

    def logout(self) -> int:
        """退出登录"""
        if self._handle is None:
            return self.ERROR_FAILED

        result = self._dll.IRC_NET_Logout(self._handle)
        if result == self.ERROR_OK:
            self._handle = None
        return result

    def deinit(self) -> None:
        """反初始化 SDK"""
        self._dll.IRC_NET_Deinit()

    @property
    def handle(self):
        """获取当前句柄"""
        return self._handle

    def get_error_message(self, error_code: int) -> str:
        """获取错误码对应的错误信息"""
        error_messages = {
            self.ERROR_OK: "成功",
            self.ERROR_FAILED: "失败",
            self.ERROR_NOT_SUPPORTED: "不支持",
            self.ERROR_PARAM_WRONG: "参数错误",
            self.ERROR_TEMP_CALLBACK_WRONG: "温度回调未开启",
            self.ERROR_BLACK_LIST: "用户不在白名单",
            self.ERROR_NONE_USER: "用户名不存在",
            self.ERROR_PWD_WRONG: "密码错误",
            self.ERROR_ACCOUNT_LOCK: "账号锁定",
            self.ERROR_USER_LIMIT: "用户数量超出限制",
            self.ERROR_SYSTEM_EXCEPTION: "系统异常",
        }
        return error_messages.get(error_code, f"未知错误码: {error_code}")


if __name__ == "__main__":
    # ========== 执行脚本 ==========
    # 已经替换为你真实的设备参数！
    DEVICE_IP = "192.168.1.123"      # 设备IP
    DEVICE_PORT = 80                 # 设备端口
    USERNAME = "admin"               # 账号
    PASSWORD = "ZGTC2026"            # 密码

    print("=" * 50)
    print("热像仪 SDK 测试 (阶段一：连接验证)")
    print("=" * 50)

    # 加载SDK
    try:
        camera = ThermalCamera()
        print(f"[OK] SDK DLL 加载成功")
    except Exception as e:
        print(f"[ERROR] DLL加载失败: {e}")
        print("-> 请确保已将 x64 文件夹内的所有 .dll 文件放到了 D:/Chef_Vision/ 目录下！")
        exit(1)

    # 初始化
    result = camera.init()
    if result != camera.ERROR_OK:
        print(f"[ERROR] 初始化失败，错误码: {result} - {camera.get_error_message(result)}")
        exit(1)
    print(f"[OK] 初始化成功")

    # 登录
    print(f"\n正在登录设备 {DEVICE_IP}:{DEVICE_PORT} ...")
    result = camera.login(DEVICE_IP, DEVICE_PORT, USERNAME, PASSWORD)
    if result != camera.ERROR_OK:
        print(f"[ERROR] 登录失败，错误码: {result} - {camera.get_error_message(result)}")
        camera.deinit()
        exit(1)

    print(f"[OK] 登录成功，拿到硬件句柄: {camera.handle}")

    # 退出登录
    print("\n正在退出登录 ...")
    result = camera.logout()
    if result != camera.ERROR_OK:
        print(f"[ERROR] 退出失败，错误码: {result} - {camera.get_error_message(result)}")
    else:
        print(f"[OK] 退出成功")

    # 反初始化
    camera.deinit()
    print(f"[OK] SDK 反初始化完成")
    print("\n测试流程完美结束！")