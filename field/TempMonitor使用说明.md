# 现场采集与温度监测工具使用说明（field 文件夹）

## 📋 目录

1. [工具概述](#工具概述)
2. [运行环境准备](#运行环境准备)
3. [下位机使用指南](#下位机使用指南)
4. [上位机使用指南](#上位机使用指南)
5. [常见问题](#常见问题)

---

## 🎯 工具概述

`field` 文件夹提供三个脚本，**完全独立于主项目的 SAM 追踪系统**：

| 工具 | 用途 | 运行位置 | 需要硬件 | 备注 |
|------|------|----------|----------|------|
| **FieldCapture.py** | RGB+IR 双画面采集录制 | 下位机（现场） | ✅ 需要热像仪 | 当前主力采集脚本，带补光灯控制（按 L 切换白光） |
| **FieldTempMonitor.py** | 实时温度监测 | 下位机（现场） | ✅ 需要热像仪 | 框选 ROI 实时显示温度统计 |
| **TempMonitor.py** | 离线温度分析 | 上位机（办公室） | ❌ 不需要 | 读取已录制的 .npy 文件分析 |

> 三个脚本的 DLL 都从**脚本同目录**加载，所需依赖库已全部放进 `field` 文件夹。
> 整个 `field` 文件夹拷到目标电脑，装好下面的 Python 环境即可运行。

---

## 🛠️ 运行环境准备

拷走 `field` 文件夹后，目标电脑还需要满足两个条件（DLL 已随文件夹自带，无需单独安装）：

### 1️⃣ 安装 Python

脚本是 `.py` 文件，需要 Python 解释器才能运行。

- 到 https://www.python.org/downloads/ 下载并安装 Python 3.8 及以上版本。
- 安装时**务必勾选 “Add Python to PATH”**（把 Python 加入环境变量），否则命令行找不到 `python` 命令。
- 安装完成后，打开 CMD 或 PowerShell 验证：

```bash
python --version
```

能打印出版本号（如 `Python 3.11.5`）即安装成功。

### 2️⃣ 安装 3 个 Python 库

在 CMD 或 PowerShell 中运行：

```bash
pip install numpy opencv-python matplotlib
```

- **numpy**：温度矩阵数值计算
- **opencv-python**：图像/视频读写与显示（即代码里的 cv2）
- **matplotlib**：温度曲线图绘制

> 装好 Python + 这 3 个库之后，`field` 文件夹里的脚本就能反复使用，无需重复安装。

---

## 🔧 下位机使用指南

下位机（现场笔记本）有两个采集脚本：主力的 `FieldCapture.py`（RGB+IR 采集录制，带补光灯控制）和 `FieldTempMonitor.py`（实时温度监测）。下面分别说明。

---

## 📹 FieldCapture.py（主力采集脚本）

### 1️⃣ 修改设备参数

用记事本或 VSCode 打开 `FieldCapture.py`，修改第 41-44 行的设备参数：

```python
DEVICE_IP   = "192.168.1.123"    # 改为实际的热像仪 IP 地址
DEVICE_PORT = 80                 # 通常不需要改
USERNAME    = "admin"            # 通常不需要改
PASSWORD    = "ZGTC2026"         # 改为实际密码
```

### 2️⃣ 运行程序

在 CMD 或 PowerShell 中，进入 `field` 文件夹并运行：

```bash
cd field文件夹路径
python FieldCapture.py
```

**示例**（假设 field 文件夹拷到了 D 盘根目录）：

```bash
cd D:\field
python FieldCapture.py
```

### 3️⃣ 操作快捷键

| 按键 | 功能 |
|------|------|
| **R** | 进入/退出 ROI 编辑（拖拽圆心移动，滚轮调半径） |
| **S** | 开始录制（画面出现后按） |
| **L** | 切换白色补光灯（0 → 100 → 0） |
| **1** | 切换到高增益 `HG` |
| **2** | 切换到低增益 `LG` |
| **3** | 切换到自动档位 `AUTO` |
| **Q** | 停止录制并保存 |

建议在按 **S** 之前选好测温档位，常规采集优先使用 **3（AUTO）**。录制中
仍可切换档位，但同一段数据会混合不同量程，CSV 会在 `temp_level` 字段逐帧记录。

### 4️⃣ 输出文件

录制完成后，在 `field` 文件夹（脚本同目录）生成以下 8 项结果：

```
rgb_YYYYMMDD_HHMMSS.mp4      # 可见光视频
ir_YYYYMMDD_HHMMSS.mp4       # IR 伪彩色视频，显示 ROI 温度与档位
temp_YYYYMMDD_HHMMSS.npy     # 对应的红外温度矩阵（float32，单位 ℃）
rgb_YYYYMMDD_HHMMSS_ts.npy   # RGB 逐帧时间戳
temp_YYYYMMDD_HHMMSS_ts.npy  # IR 逐帧时间戳
roi_temp_YYYYMMDD_HHMMSS.csv # ROI 逐帧最低/最高/平均温度
roi_temp_curve_YYYYMMDD_HHMMSS.png # ROI 温度曲线
roi_config.json              # RGB 圈选 ROI 的位置和大小
```

`field/homography.npy` 用于将 RGB ROI 准确映射到 IR 温度矩阵，已随现场采集
目录提供。迁移时复制完整 `field/` 文件夹即可；该文件缺失时程序仍可运行，
但只会按 RGB/IR 画面比例估算 ROI 位置。

右侧 IR 预览和录制的 IR 视频左上角只显示 RGB 圈选 ROI 映射到 IR 后的
`ROI MAX / ROI MIN / ROI AVG`，不再显示整幅 IR 画面的温度统计。CSV 会同时
记录每帧使用的 `HG / LG / AUTO` 档位，便于查看录制中途的档位切换。CSV 和
曲线图在低配置电脑停止录制时直接生成，不依赖主电脑后处理。

录制的 RGB 和 IR 视频画面还会写入当前电脑的实际时间，以及从按下 **S** 开始
累计的 `REC` 录制时长。低配置电脑实际收到的 RGB/IR 帧率可能随负载变化，
因此按 **Q** 停止后，程序会读取两路逐帧时间戳，自动校正原视频的播放帧率，
使视频时长与真实录制时长一致。校正只调整视频播放帧率，不增删帧、不改变帧
顺序，也不影响温度矩阵与时间戳数据。

终端出现以下两路完成信息后，再关闭终端或复制录制文件：

```text
[OK] RGB 播放速度已校正: ... FPS，时长约 ... 秒
[OK] IR 播放速度已校正: ... FPS，时长约 ... 秒
```

校正后的文件仍叫 `rgb_*.mp4` 和 `ir_*.mp4`，不会另外生成一套正常速度视频。
如果校正或结果校验失败，程序会保留原视频并在终端显示警告。

---

## 🌡️ FieldTempMonitor.py（实时温度监测）

### 文件：`FieldTempMonitor.py`

### 1️⃣ 准备工作

#### 在下位机电脑上准备以下文件：

```
下位机文件夹/
├── FieldTempMonitor.py          # 主程序（本文件）
├── IRCNetSDK.dll                # SDK 动态库
├── avcodec-58.dll               # 依赖库
├── avdevice-58.dll
├── avfilter-7.dll
├── avformat-58.dll
├── avutil-56.dll
├── libcrypto-1_1-x64.dll
├── libcurl.dll
├── libssl-1_1-x64.dll
├── lz4.dll
├── PocoCrypto64.dll
├── PocoFoundation64.dll
├── PocoJSON64.dll
├── IvsPlaySDK.dll
├── StdPlaySDK.dll
├── swresample-3.dll
├── swscale-5.dll
└── SDL2.dll
```

**💡 提示**：直接复制整个 `field` 文件夹到下位机即可，所有依赖 DLL 都已放在 `field` 文件夹内。无需复制整个 `Chef_Vision` 项目。

---

### 2️⃣ 安装 Python 环境

按上面「运行环境准备」一节，先装好 Python 和 3 个库：

```bash
pip install numpy opencv-python matplotlib
```

---

### 3️⃣ 修改设备参数

用记事本或 VSCode 打开 `FieldTempMonitor.py`，修改第 48-51 行的设备参数：

```python
DEVICE_IP   = "192.168.1.123"    # 改为实际的热像仪 IP 地址
DEVICE_PORT = 80                 # 通常不需要改
USERNAME    = "admin"            # 通常不需要改
PASSWORD    = "ZGTC2026"         # 改为实际密码
```

**如何查看热像仪 IP？**
- 方法 1：在热像仪设置菜单中查看网络配置
- 方法 2：使用网络扫描工具（如 Advanced IP Scanner）
- 方法 3：咨询设备管理员

---

### 4️⃣ 运行程序

在命令行中，进入文件夹并运行：

```bash
cd 下位机文件夹路径
python FieldTempMonitor.py
```

**示例**（假设 field 文件夹拷到了 D 盘根目录）：
```bash
cd D:\field
python FieldTempMonitor.py
```

---

### 5️⃣ 操作步骤

#### 启动后会看到两个窗口：

```
┌─────────────────────┐    ┌─────────────────────┐
│  RGB Video (Left)   │    │ IR Temperature      │
│                     │    │     (Right)         │
│  可见光视频          │    │  红外温度热图        │
│  用于调整角度        │    │  用于选择ROI        │
└─────────────────────┘    └─────────────────────┘
```

#### 操作流程：

1. **调整摄像头角度**
   - 观察左侧 RGB 视频窗口
   - 确保锅和食材在画面中央
   - 调整热像仪位置和角度

2. **选择监测区域（ROI）**
   - 按 **R** 键
   - 在右侧热图窗口中，用鼠标拖动框选要监测的区域
   - 松开鼠标完成选择
   - 右侧窗口会显示 ROI 区域的实时温度统计

3. **开始录制**
   - 按 **S** 键开始录制
   - 窗口底部会显示 "RECORDING" 和录制时间
   - 录制期间会实时显示温度统计

4. **停止录制**
   - 按 **Q** 键停止录制
   - 程序会自动保存数据并生成报告
   - 输出文件会保存在脚本同目录下的 `output/` 子文件夹

5. **退出程序**
   - 按 **ESC** 键退出

---

### 6️⃣ 输出文件

录制完成后，会在脚本同目录下的 `output/` 子文件夹生成以下文件：

```
output/temp_monitor_20260518_113045.csv      # 温度数据（CSV格式）
output/temp_monitor_20260518_113045.png      # 温度曲线图
```

**CSV 文件格式**：
```csv
帧序号,时间(秒),最高温度(°C),最低温度(°C),平均温度(°C)
0,0.000,156.23,45.67,98.45
1,0.040,157.12,46.01,99.12
2,0.080,158.45,46.89,100.23
...
```

**曲线图内容**：
- 上图：平均温度随时间变化曲线 + 温度范围阴影
- 下图：最高/最低/平均温度对比曲线

---

### 7️⃣ 快捷键总结

| 按键 | 功能 |
|------|------|
| **R** | 框选监测区域（ROI） |
| **S** | 开始录制温度数据 |
| **Q** | 停止录制并保存数据 |
| **ESC** | 退出程序 |

---

## 💻 上位机使用指南

### 文件：`TempMonitor.py`

### 1️⃣ 使用场景

- 在办公室电脑上分析已录制的温度数据
- 不需要连接热像仪
- 处理 `.npy` 格式的温度文件

---

### 2️⃣ 准备工作

确保已安装 Python 依赖：

```bash
pip install numpy opencv-python matplotlib
```

---

### 3️⃣ 修改配置

用编辑器打开 `TempMonitor.py`，修改第 18 行的文件路径：

```python
TEMP_NPY_PATH = "temp_20260428_121546.npy"  # 改为你的温度文件路径
```

**温度文件在哪？**
- 当前通常在主项目的 `test_data/测试集名/` 中，文件名格式：
  `temp_YYYYMMDD_HHMMSS.npy`
- 例如：`temp_20260428_121546.npy`

---

### 4️⃣ 运行程序

```bash
python TempMonitor.py
```

---

### 5️⃣ 操作步骤

1. **程序启动**
   - 自动加载温度数据
   - 弹出第一帧的热图窗口

2. **选择 ROI**
   - 在热图窗口中，用鼠标拖动框选要分析的区域
   - 按 **ENTER** 或 **SPACE** 确认
   - 按 **C** 重新选择
   - 按 **ESC** 退出

3. **自动处理**
   - 选择完成后，程序自动处理所有帧
   - 显示进度条
   - 自动生成 CSV 和曲线图

4. **查看结果**
   - 输出文件保存在当前文件夹
   - 控制台显示统计摘要

---

### 6️⃣ 输出文件

```
temp_monitor_log.csv       # 温度数据
temp_monitor_curve.png     # 温度曲线图
```

---

## ❓ 常见问题

### Q1: 下位机连接不上热像仪怎么办？

**A1**: 检查以下几点：
1. 确认热像仪已开机并连接到网络
2. 检查 IP 地址是否正确（ping 测试）
3. 检查密码是否正确
4. 确认电脑和热像仪在同一网段
5. 关闭防火墙试试

**测试连接**：
```bash
ping 192.168.1.123
```

---

### Q2: 程序提示缺少 DLL 文件怎么办？

**A2**: 
1. 确保所有 DLL 文件都在同一文件夹（`field` 文件夹内已自带全部 DLL）
2. 完整复制整个 `field` 文件夹到下位机
3. 不要单独复制 `FieldTempMonitor.py`，要连同 DLL 一起复制

---

### Q3: 窗口显示不全或太小怎么办？

**A3**: 
- 窗口是可调整大小的，用鼠标拖动边缘调整
- 或者修改代码中的显示缩放参数

---

### Q4: 录制的数据在哪里？

**A4**: 
- 输出文件保存在运行程序的文件夹
- 文件名包含时间戳，例如：`temp_monitor_20260518_113045.csv`

---

### Q5: 可以同时运行多个监测任务吗？

**A5**: 
- 不建议，因为热像仪同时只能被一个程序连接
- 如果需要多个监测区域，可以在一次录制中选择较大的 ROI

---

### Q6: 这个工具会影响主项目吗？

**A6**: 
- **不会！** 这两个工具完全独立
- 不依赖 SAM 追踪系统
- 不会影响 `TrackFood.py` 等主项目文件
- `field/` 是现场采集工具包，当前项目仍需要，使用后不要随意删除

---

### Q7: 温度数据的单位是什么？

**A7**: 
- 所有温度数据单位都是 **摄氏度（°C）**
- CSV 文件中的温度已经转换好，可以直接使用

---

### Q8: 如何选择合适的 ROI 区域？

**A8**: 
- 在热图中，高温区域显示为亮黄色/白色
- 中温区域显示为橙色/红色
- 低温区域显示为蓝色/紫色
- 选择你想监测的食材或锅的区域即可

---

## 📞 技术支持

如有问题，请联系项目负责人或查看主项目文档。

---

## 📝 更新日志

- **2026-07-24**: 结构整理 + 文档补全
  - `field` 文件夹自带全部 SDK DLL，整个文件夹拷走即用
  - `FieldTempMonitor.py` 改为从脚本同目录加载 DLL，输出到同目录 `output/` 子文件夹
  - 说明改为「复制 field 文件夹」而非整个 Chef_Vision 项目
  - 新增「运行环境准备」一节：安装 Python + numpy/opencv-python/matplotlib
  - 补充主力脚本 `FieldCapture.py` 的运行说明与快捷键
  - 修正示例路径（D:\Chef_Vision → field 文件夹路径）

- **2026-05-18**: 初始版本
  - 创建 `FieldTempMonitor.py`（下位机实时采集）
  - 创建 `TempMonitor.py`（上位机离线分析）
  - 添加双窗口显示（RGB + IR）
  - 添加实时温度统计显示

---

**祝使用愉快！** 🎉
