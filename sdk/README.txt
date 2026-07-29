# sdk 目录说明

`sdk/` 保存热像仪 Windows SDK 的 Python 封装、头文件和运行依赖。当前
离线主程序 `core/TrackFood.py` 不调用本目录；它服务于现场设备连接和后续
SDK 开发。

`field/` 内有一份相同运行库副本，目的是现场文件夹整体拷走即用。两个目录
暂时都保留。

## 1. 主要内容

| 文件类型 | 作用 |
|---|---|
| `ThermalCamera.py` | `ctypes` 封装，提供 init/login/logout/deinit |
| `IRCNetSDK.dll` | 热像仪网络 SDK 主库 |
| `IRCNetSDK.h` | SDK C 接口声明 |
| `IRCNetSDKDef.h` | SDK 结构体和常量定义 |
| `IvsPlaySDK.dll`、`StdPlaySDK.dll` | 播放依赖 |
| `av*.dll`、`sw*.dll` | FFmpeg 编解码依赖 |
| `libcurl.dll` | 网络传输依赖 |
| `libcrypto*.dll`、`libssl*.dll` | OpenSSL 依赖 |
| `Poco*.dll` | Poco 基础/JSON/加密依赖 |
| `lz4.dll`、`SDL2.dll` | 压缩和多媒体依赖 |

## 2. 基础用法

```python
from sdk.ThermalCamera import ThermalCamera

camera = ThermalCamera()
camera.init()
camera.login("设备IP", 80, "用户名", "密码")

# 按设备 SDK 接口进行预览或温度回调

camera.logout()
camera.deinit()
```

项目当前更完整的回调、录像和补光灯示例位于
`field/FieldCapture.py` 和 `field/FieldTempMonitor.py`。

## 3. 注意事项

1. 仅适用于 Windows，且 DLL 位数必须与 Python 位数一致，通常均为 64 位。
2. 主 DLL 的依赖必须位于可搜索路径；最稳妥是保持所有 DLL 在同一目录。
3. 登录失败时检查 IP、端口、账号、密码、网段、防火墙和设备占用。
4. SDK 回调中的缓冲区通常只在回调期间有效，需及时复制数据。
5. 退出时必须按顺序停止预览、注销并反初始化，避免设备连接残留。
6. DLL 和头文件已被 `.gitignore` 排除，不参与代码版本回滚。
7. 不要在现场目录和根 `sdk/` 之间只复制一两个 DLL；版本不一致可能造成
   难以定位的加载错误。
