# field 目录说明

`field/` 是厨房现场采集与轻量温度监测工具包。它与离线 SAM2 主流程分开，
可以整个文件夹复制到现场低配 Windows 笔记本使用。

本目录刻意自带一份热像仪 SDK DLL 和 `ThermalCamera.py`，因此与根目录
`sdk/` 有约 87 MB 重复。这是为了“拷走即用”，当前不要去重。

详细图形界面操作见 `TempMonitor使用说明.md`。

## 1. 文件职责

| 文件 | 用途 | 是否连接设备 |
|---|---|---|
| `FieldCapture.py` | 同步采集 RGB、IR 视频、温度矩阵和时间戳 | 是 |
| `FieldTempMonitor.py` | 现场选 ROI 并实时记录温度 | 是 |
| `TempMonitor.py` | 离线读取已有 `.npy` 做 ROI 统计 | 否 |
| `ThermalCamera.py` | SDK 的基础 Python 封装 | 是 |
| `roi_config.json` | 当前 RGB 固定 ROI 配置 | 否 |
| `fill_light_token.txt` | TN220 补光灯本地 token | 可选、已忽略 |
| `*.dll` | 热像仪及其 FFmpeg/OpenSSL/Poco 依赖 | 是 |

## 2. 现场采集主流程

```text
热像仪网络视频/温度回调
          |
          v
FieldCapture.py
          |
          +--> rgb_TIMESTAMP.mp4
          +--> ir_TIMESTAMP.mp4
          +--> temp_TIMESTAMP.npy
          +--> rgb_TIMESTAMP_ts.npy
          +--> temp_TIMESTAMP_ts.npy
          +--> roi_config.json
```

### 环境

```powershell
pip install numpy opencv-python matplotlib
```

### 运行

```powershell
cd D:\path\to\field
python FieldCapture.py
```

### 快捷键

| 按键 | 功能 |
|---|---|
| `R` | 进入/退出 ROI 编辑，保存 ROI |
| `S` | 开始录制 |
| `L` | 切换白色补光灯 |
| `Q` | 停止、保存并退出 |

录制文件写到脚本当前工作位置。录制完成后，建议把同一时间戳的全部文件一起
复制到 `test_data/新目录/`，不要只复制 RGB 视频。

## 3. 现场实时 ROI 温度

```powershell
python FieldTempMonitor.py
```

用途是现场快速判断温度趋势，不运行 SAM2。按 `R` 选择 ROI，按 `S` 开始
记录，按 `Q` 保存。结果写入 `field/output/`：

```text
temp_monitor_TIMESTAMP.csv
temp_monitor_TIMESTAMP.png
```

## 4. 离线 ROI 分析

`TempMonitor.py` 不连接设备，读取已有温度矩阵并人工框选 ROI。当前脚本顶部
默认路径仍指向已经删除的早期 `data/temp_20260428_121546.npy`，使用前必须
改为实际 `test_data/.../temp_*.npy` 路径。

输出默认写到根目录 `output/`：

```text
temp_monitor_log.csv
temp_monitor_curve.png
```

## 5. 设备与补光灯配置

设备 IP、端口、用户名和密码位于现场脚本顶部。换设备或换网络后需要检查。
`FieldCapture.py` 同时包含：

- SDK 补光灯控制；
- HTTP token 登录和亮度控制；
- 可选 PTZ AUX 控制；
- 退出时恢复/关闭补光灯的清理流程。

补光灯控制失败通常不应阻止温度采集，但应查看控制台日志确认是否真的开灯。

## 6. 使用前检查

1. Windows 能找到并加载 `IRCNetSDK.dll` 及同目录依赖 DLL。
2. 电脑和热像仪处于同一网段，能够 `ping` 到设备。
3. 没有另一个程序占用同一热像仪会话。
4. RGB 和温度画面都在刷新后再开始录制。
5. 磁盘空间足够；温度矩阵和视频会持续增长。
6. 系统时间稳定，避免时间戳回退。

## 7. 注意事项

- `field/` 不是 SAM2 主程序入口；采集完成后在上位机运行
  `core/TrackFood.py`。
- `roi_config.json` 与当前画面尺寸和构图相关。
- DLL 不进 Git，代码回滚不会恢复误删的二进制文件。
- `fill_light_token.txt` 含本地鉴权信息，不应提交或发给无关人员。
- 现场强反光、白烟和相机震动会同时影响采集和后续标定。
- 旧 `DataLogger.py` 已移至 `可能不需要的文件/`，当前不使用。
