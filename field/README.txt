# field 目录说明

`field/` 是厨房现场采集与轻量温度监测工具包。它与离线 SAM2 主流程分开，
可以整个文件夹复制到现场低配 Windows 笔记本使用。

本目录刻意自带一份热像仪 SDK DLL 和 `ThermalCamera.py`，因此与根目录
`sdk/` 有约 87 MB 重复。这是为了“拷走即用”，当前不要去重。

详细图形界面操作见 `TempMonitor使用说明.md`。

## 1. 文件职责

| 文件 | 用途 | 是否连接设备 |
|---|---|---|
| `FieldCapture.py` | 同步采集 RGB、IR 视频、温度矩阵和时间戳，并在录制结束后校正视频播放速度 | 是 |
| `FieldTempMonitor.py` | 现场选 ROI 并实时记录温度 | 是 |
| `TempMonitor.py` | 离线读取已有 `.npy` 做 ROI 统计 | 否 |
| `ThermalCamera.py` | SDK 的基础 Python 封装 | 是 |
| `homography.npy` | RGB ROI 到 IR 温度矩阵的标定映射 | 否 |
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
          +--> roi_temp_TIMESTAMP.csv
          +--> roi_temp_curve_TIMESTAMP.png
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

启动并登录设备后，终端会打印当前测温档位：

```text
[TEMP LEVEL] 当前测温档位: 高增益 HG
[TEMP LEVEL] 当前测温档位: 低增益 LG
[TEMP LEVEL] 当前测温档位: 自动 AUTO
```

右侧 IR 预览页和录制的 IR 伪彩色视频也会显示 `Temp Level` / `LEVEL`。
IR 左上角的 `ROI MAX / ROI MIN / ROI AVG` 只统计 RGB 圈选 ROI 映射到
IR 后的区域，不再显示整幅 IR 画面的最高、最低和平均温度。
默认启动时会请求把设备测温档位设置为 `AUTO`，然后再次查询确认最终档位。
若现场不希望程序主动设置档位，可在 `FieldCapture.py` 顶部把
`TEMP_LEVEL_MODE_ON_START` 改为 `"keep"`。可选值包括：

```text
"auto"  自动 AUTO
"low"   低增益 LG
"high"  高增益 HG
"keep"  只查询，不修改
```

若设备处于 `HG` 而不是 `AUTO`，温度超过高增益量程时不会自动切到低增益。
若采集数据长期卡在约 196°C，可优先检查这里是否显示为 `HG`。

启动时还会调用 SDK 同步设备系统时间到当前电脑时间：

```text
[TIME SYNC] 已同步设备时间为本机时间: 2026-07-28 10:53:32
```

这用于让 RGB 画面右上角的设备 OSD 时间与录制电脑时间对齐。若现场不希望
程序改设备时间，可在 `FieldCapture.py` 顶部把 `SYNC_DEVICE_TIME_ON_START`
改为 `False`。

### 快捷键

| 按键 | 功能 |
|---|---|
| `R` | 进入/退出 ROI 编辑，保存 ROI |
| `S` | 开始录制 |
| `L` | 切换白色补光灯 |
| `1` | 切换到高增益 `HG` |
| `2` | 切换到低增益 `LG` |
| `3` | 切换到自动档位 `AUTO` |
| `Q` | 停止、保存并退出 |

建议在按 `S` 录制前确定测温档位，日常优先使用 `3`（`AUTO`）。录制过程中
也可以切换，但同一段数据会包含不同档位；CSV 的 `temp_level` 字段会逐帧记录。

每次录制还会现场生成逐帧 ROI 温度文件和曲线图：

```text
roi_temp_TIMESTAMP.csv
roi_temp_curve_TIMESTAMP.png
```

CSV 包含帧号、时间戳、已录制秒数、ROI 最低/最高/平均温度、ROI 像素数和
当时的测温档位。曲线图显示 ROI 平均温度以及最低到最高温度范围，不需要回到
主电脑后处理。

### 录制时间与视频播放速度

录制生成的 RGB 和 IR 视频会在画面中写入两行时间：

```text
YYYY-MM-DD HH:MM:SS.mmm   当前电脑的实际时间
REC HH:MM:SS.ss           从本次开始录制起累计的时长
```

低配置电脑上的实际回调帧率可能随负载变化。按 `Q` 停止后，程序会根据
`rgb_*_ts.npy` 和 `temp_*_ts.npy` 中的逐帧时间戳，校正原 RGB/IR 视频的播放
帧率，使视频时长尽量与真实录制时间一致。该过程不增删帧，也不改变帧顺序和
温度矩阵；校正成功后仍使用原来的 `rgb_*.mp4`、`ir_*.mp4` 文件名，不会额外
生成一套正常速度视频。

校速时终端会显示 `[校速]` 进度，完成后显示：

```text
[OK] RGB 播放速度已校正: ... FPS，时长约 ... 秒
[OK] IR 播放速度已校正: ... FPS，时长约 ... 秒
```

看到两路完成信息后再关闭终端或复制文件。若校速失败，程序会保留原视频并
输出警告，不会用未通过校验的临时视频覆盖原文件。

录制文件写到脚本当前工作位置。录制完成后，建议把同一时间戳的全部文件一起
复制到 `test_data/新目录/`，不要只复制 RGB 视频。

## 3. 现场实时 ROI 温度

`field/homography.npy` 是 RGB 圈选区域映射到 IR 温度矩阵所需的标定文件，
已随现场采集目录提供。迁移到低配电脑时请复制完整 `field/` 文件夹；
若该文件缺失，程序会按画面比例估算映射，精度会低于标定矩阵。

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
- 现场运行所需的 SDK DLL 已随项目保留，复制完整 `field/` 即可使用。
- `fill_light_token.txt` 是当前设备的补光灯鉴权信息，已随现场目录保留；更换
  设备后需要同步更新，并避免发给无关人员。
- 现场强反光、白烟和相机震动会同时影响采集和后续标定。
- 旧 `DataLogger.py` 已移至 `可能不需要的文件/`，当前不使用。
