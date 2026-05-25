# Chef Vision — 炒菜机器人热像仪温度感知系统

## 项目目标

利用 **AT20 双光热像仪**（RGB可见光 + IR红外一体）为炒菜机器人提供精确的**菜温检测**。

**核心问题**：Web端圈选区域只能获取最高/最低/平均温度，区域内混有锅底、搅拌铲等非菜像素，导致温度数据不可信。

**解决思路**：通过 SDK 拉取完整的逐像素温度矩阵（IR）+ 可见光视频（RGB），用 RGB 图像做像素级分类掩膜，识别出哪些像素是菜、哪些是锅底/搅拌铲，只统计菜像素的温度。

**最终用途**：为炒菜机器人提供可靠的实时菜温信号，用于判断翻炒时机、调节火候。

---

## 设备信息

| 参数 | 值 |
|------|-----|
| 产品型号 | AT20 双光模组（RGB + IR） |
| 设备 IP | `192.168.1.123` |
| 端口 | `80` |
| 用户名 | `admin` |
| 密码 | `ZGTC2026` |
| SDK | IRCNetSDK（Windows x64 DLL） |
| SDK 文档 | `D:/desktop/AT20/SDK_NET_Windows_X86_X64_V1.0.9.14/` |

---

## 项目文件结构

```
D:/Chef_Vision/
├── README.md               ← 本文件，项目说明
├── PROJECT_STATUS.md       ← 当前开发进度记录
├── requirements.txt        ← Python 依赖列表
│
├── sdk/                    ← 热像仪 SDK（DLL + Python 封装）
│   ├── ThermalCamera.py    ← SDK ctypes 封装类（init/login/logout）
│   ├── IRCNetSDK.dll       ← SDK 主库
│   ├── IRCNetSDK.h / IRCNetSDKDef.h  ← C 头文件（参考）
│   └── *.dll               ← FFmpeg、SSL、Poco 等依赖库
│
├── core/                   ← 主体追踪与标注脚本（需要 GPU + SAM2）
│   ├── LabelFirstFrame.py  ← 交互式食材标注工具（生成 food_labels.json）
│   ├── TrackFood.py        ← SAM2 分批追踪 + 温度融合（主流程）
│   ├── TrackFood_AutoRecover.py  ← 自动恢复版追踪（小批量+质量监控）
│   ├── auto_tracking_utils.py    ← 追踪工具函数库
│   └── food_labels.json    ← 标注数据（由 LabelFirstFrame.py 生成）
│
├── field/                  ← 厨房现场采集脚本（低配笔记本用，无需 GPU）
│   ├── FieldCapture.py     ← 主采集脚本（RGB+IR 双流录制）
│   ├── FieldTempMonitor.py ← 实时温度区域监测
│   ├── DataLogger.py       ← 早期采集脚本（已被 FieldCapture 替代）
│   └── TempMonitor.py      ← 离线温度分析工具
│
├── tools/                  ← 分析与调试工具（按需运行）
│   ├── Calibrate.py        ← RGB/IR 像素对齐标定（生成 homography.npy）
│   ├── VerifyData.py       ← 验证采集数据质量
│   ├── TempFilter.py       ← 温度过滤算法验证
│   ├── analyze_ir_temp.py  ← 红外温度分布分析
│   ├── analyze_result.py   ← 追踪结果质量分析
│   ├── browse_video.py     ← 交互式视频浏览器（找关键帧号）
│   ├── extract_frames.py   ← 提取视频预览帧
│   ├── inspect_frames.py   ← 提取关键帧截图（诊断 mask 异常）
│   └── SegmentFood.py      ← SAM2 单帧分割验证
│
├── data/                   ← 原始采集数据（视频 + 温度矩阵 + 标定矩阵）
│   ├── rgb_*.mp4           ← 可见光视频
│   ├── temp_*.npy          ← 红外温度矩阵（float32, shape=(N,H,W), 单位℃）
│   └── homography.npy      ← RGB→IR 对齐矩阵（由 Calibrate.py 生成）
│
├── output/                 ← 脚本生成的输出文件（可重新生成）
│   ├── track_result*.mp4   ← 追踪可视化视频
│   ├── food_temp_log*.csv  ← 逐帧温度日志
│   ├── food_temp_curve.png ← 温度曲线图
│   └── ...                 ← 其他分析图表
│
└── backup/                 ← 历史版本备份
```

---

## 数据格式说明

### temp_matrices.npy
- **形状**：`[帧数, 高度, 宽度]`，float32
- **单位**：摄氏度（℃）
- **换算**：SDK 原始 int16 值 → `值 / 10.0 - 273.15 = ℃`
- **查看方式**：运行 `python VerifyData.py`

### rgb_record.mp4
- **格式**：MP4，RGB24转BGR，25 FPS
- **通道**：`channel=0`（RGB可见光），`channel=1`（IR热像）

---

## 当前进展

### 已完成
- [x] SDK DLL ctypes 封装（ThermalCamera.py）
- [x] 双流同步采集（DataLogger.py）：RGB视频 + 温度矩阵
- [x] 修复视频通道：`channel=1`（IR）→ `channel=0`（RGB）
- [x] 去掉10秒录制限制，改为按 Enter 手动停止

### 进行中
- [ ] 验证现有 `temp_matrices.npy` 数据有效性
- [ ] 验证修复后的 `channel=0` 确实输出 RGB 可见光视频

### 待开发
- [ ] **温度过滤算法**（核心）：RGB 图像像素分类 + 温度掩膜，提取纯菜区域温度
- [ ] **低配笔记本版采集脚本**：轻量化，用于厨房现场数据采集
- [ ] **可视化工具**：将温度热力图叠加到 RGB 视频上，辅助算法调试
- [ ] **温度统计与预警**：基于纯菜温度的阈值报警（后期）

---

## 两台设备分工

| 设备 | 用途 |
|------|------|
| 算力主机（当前）| 算法开发、数据处理、模型训练 |
| 低配笔记本 | 携带进厨房，现场连接热像仪录制数据 |

---

## 快速开始

### 1. 环境依赖

```bash
pip install numpy opencv-python
```

### 2. 采集数据

```bash
cd D:/Chef_Vision
python DataLogger.py
# 按 Enter 停止录制
```

### 3. 验证数据

```bash
python VerifyData.py
```

---

## 核心算法思路（待实现）

```
输入：RGB帧 + 同步温度矩阵
      ↓
[RGB像素分类]
  - 颜色特征识别菜区域（绿/黄/棕色系）
  - 排除锅底（暗黑色）
  - 排除搅拌铲（金属灰色/高亮）
      ↓
[生成掩膜] → 菜像素 mask
      ↓
[温度提取] → 仅统计 mask 内像素的温度
      ↓
输出：菜的平均温度 / 最高温度 / 温度分布
```

---

## 注意事项

- SDK DLL 为 **Windows x64**，必须用 64位 Python 运行
- 所有 SDK DLL 必须放在**同一目录**（当前为 `D:/Chef_Vision/`）
- 回调函数对象必须保存引用（防止被 Python GC 回收导致崩溃）
- 温度矩阵为 IR 通道数据，与 RGB 视频的像素坐标系**需要对齐校准**
