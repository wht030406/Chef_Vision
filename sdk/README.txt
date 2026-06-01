sdk/ — 热像仪 SDK 文件
==============================

包含内容：
  ThermalCamera.py      热像仪 SDK 的 Python ctypes 封装类
                        提供 init / login / logout / deinit 接口
                        DLL 路径默认自动指向本目录

  IRCNetSDK.dll         热像仪网络 SDK 主库
  IRCNetSDK.h           SDK C 头文件（参考用）
  IRCNetSDKDef.h        SDK 数据结构定义头文件
  IvsPlaySDK.dll        IVS 播放库（SDK 依赖）
  StdPlaySDK.dll        标准播放库（SDK 依赖）
  avcodec-58.dll        FFmpeg 编解码库
  avdevice-58.dll       FFmpeg 设备库
  avfilter-7.dll        FFmpeg 滤镜库
  avformat-58.dll       FFmpeg 格式库
  avutil-56.dll         FFmpeg 工具库
  swresample-3.dll      FFmpeg 音频重采样库
  swscale-5.dll         FFmpeg 视频缩放库
  libcurl.dll           HTTP 传输库
  libcrypto-1_1-x64.dll OpenSSL 加密库
  libssl-1_1-x64.dll    OpenSSL SSL 库
  lz4.dll               LZ4 压缩库
  PocoCrypto64.dll      Poco 加密库
  PocoFoundation64.dll  Poco 基础库
  PocoJSON64.dll        Poco JSON 库
  SDL2.dll              SDL2 多媒体库

使用方式：
  from sdk.ThermalCamera import ThermalCamera
  camera = ThermalCamera()   # 自动加载本目录的 IRCNetSDK.dll
  camera.init()
  camera.login("192.168.1.123", 80, "admin", "ZGTC2026")
