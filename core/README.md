# core 目录说明

`core/` 是 Chef Vision 离线温度检测主线。当前正式入口是
`TrackFood.py`，其余 Python 文件按职责提供配置、标注、追踪、温度统计、
调试输出和最终温度决策能力。

本目录中的代码是当前项目核心，不应把 `旧代码库/` 中的早期版本复制回来
覆盖。修改任何阈值或流程前，建议先阅读根目录
`Chef_Vision_项目总说明.md` ，‘Chef_Vision_主程序全流程图解’和 `后续优化方向.md`。

## 1. 最常用入口

### 1.1 初始手动标注

```powershell
python core/LabelInitialSetup.py
```

统一入口会按顺序打开三步标注窗口：

1. RGB 正向食材标注：左键点食材 FG，右键点背景 BG。
2. RGB 反向锅底标注：左键点锅底 FG，右键点食材 BG。
3. IR 锅区、旋转轴圆心、排除圆标注。

如果 `core/food_labels.json` 中已有视频路径，直接运行上面的最短命令即可。
更换测试数据时可显式指定数据目录：

```powershell
python core/LabelInitialSetup.py --data-dir test_data/test8_1
```

或完全指定输入：

```powershell
python core/LabelInitialSetup.py `
  --video test_data/test8_1/rgb_20260707_153017.mp4 `
  --temp test_data/test8_1/temp_20260707_153017.npy `
  --labels core/food_labels.json
```

标注结果写入 `core/food_labels.json` 和 `data/wok_region.json`。当前 JSON 同时支持：

- `keyframes`：RGB 正向食材的 FG/BG 提示点。
- `bottom_keyframes`：RGB 反向锅底的 FG/BG 提示点。
- `wok_rgb_region`：可选的 RGB 锅区人工椭圆信息。

当前主线只需要各方案的一次初始标注。标注帧不要求是视频第 0 帧，可以选择
食材完整出现、遮挡较少的时刻。统一标注入口默认只做一次初始标注；
RGB 正向仍兼容历史额外食材关键帧，RGB 反向当前只使用一个锅底初始参考，
不做中途关键帧注入。主程序从第一个食材关键帧开始处理。

### 1.2 完整追踪

```powershell
python core/TrackFood.py
```

默认使用：

- `core/food_labels.json` 中记录的视频路径和初始标注；
- `data/homography.npy`；
- `data/wok_region.json`；
- 与 RGB 视频同目录、同时间戳的 `temp_*.npy`；
- `models/sam2.1_hiera_large.pt`；
- 根目录 `output/` 作为结果根目录。

常用覆盖参数：

```powershell
python core/TrackFood.py `
  --labels core/food_labels.json `
  --video test_data/test8_1/rgb_20260707_153017.mp4 `
  --temp test_data/test8_1/temp_20260707_153017.npy `
  --homography data/homography.npy `
  --wok data/wok_region.json `
  --output-root output
```

短测只限制从标注起点开始处理的帧数：

```powershell
python core/TrackFood.py --max-frames 120
```

锅区策略可通过 `--ir-wok-strategy` 选择：

- `legacy`：当前默认，使用已有 IR 锅区更新策略。
- `static`：保持初始锅区不动。
- `frame_shift`：依据 IR 帧间配准平移上一版锅区。

## 2. 当前主流程

```text
food_labels.json
      |
      v
读取视频、RGB/IR 时间轴、标定矩阵、锅区
      |
      v
加载 SAM2 Large
      |
      v
按 100 帧一个 chunk 循环
      |
      +--> 更新/沿用 IR 锅区，并投影为 RGB 锅区约束
      |
      +--> RGB 正向：carry_mask 重检 -> reuse 或 IR_relabel -> SAM2
      |
      +--> RGB 反向：追踪 bottom_mask -> inverse_mask = wok - bottom
      |
      +--> 每帧计算 SAM2 / IR / Inverse / ROI 四路温度
      |
      +--> 最终温度优先级决策
      |
      v
视频、四路候选温度 Excel、最终温度 Excel、温度曲线和调试图
```

当前 `CHUNK_SIZE=100`，在 25 fps 视频中约等于 4 秒。正向和反向不是各跑
完整段视频后再切换，而是在同一个 chunk 内先完成正向追踪，再完成反向追踪，
然后逐帧统计两套结果。

## 3. 模块职责与调用关系

### 3.1 流程编排

| 文件 | 作用 | 是否由主程序调用 |
|---|---|---|
| `TrackFood.py` | 组织完整离线流程、chunk 状态、四路温度和输出 | 正式入口 |
| `track_config.py` | 解析命令行和可选 JSON run config | 是 |
| `label_io.py` | 读取并兼容新旧格式的食材/锅底标注 | 是 |
| `online_pipeline.py` | 近实时接口外壳，默认关闭，未接入离线主线 | 否 |

### 3.2 标注与几何

| 文件 | 作用 | 是否由主程序调用 |
|---|---|---|
| `LabelInitialSetup.py` | 初始手动标注统一入口，按顺序调用正向、反向和 IR 锅区标注 | 运行前手动使用 |
| `LabelFirstFrame.py` | 交互式生成食材、锅底和 RGB 锅区标注，供统一入口调用 | 运行前手动使用 |
| `auto_label.py` | 旧自动标点入口及部分可复用点生成函数 | 主程序动态使用其中部分函数 |
| `projection_utils.py` | RGB mask 投影到 IR；IR 半径换算到 RGB | 是 |

### 3.3 追踪与重采点

| 文件 | 作用 | 是否由主程序调用 |
|---|---|---|
| `sam2_tracking.py` | 加载 SAM2、抽取 chunk、运行追踪、mask 缩放、光流传播 | 是 |
| `rgb_forward.py` | 正向 IR 重采点、reset 指标、轴心和上半锅区驻留判定 | 是 |
| `rgb_inverse.py` | 反向锅底采点、inverse reset、预览图 | 是 |

### 3.4 IR 与温度

| 文件 | 作用 | 是否由主程序调用 |
|---|---|---|
| `ir_timeline.py` | 匹配温度文件并建立 RGB 帧到 IR 帧映射 | 是 |
| `ir_wok.py` | 读取、估计、更新 IR 锅区并投影到 RGB | 是 |
| `ir_food_seg.py` | 统一的 percentile / two-cluster 食材分割入口 | 是 |
| `temp_fusion.py` | 四路候选温度统计 | 是 |
| `final_temperature.py` | 从四路候选温度中选择最终温度 | 是 |

### 3.5 可视化与调试

| 文件 | 作用 | 是否由主程序调用 |
|---|---|---|
| `viz_utils.py` | mask 叠加和滚动温度曲线 | 是 |
| `output_utils.py` | 四路候选温度 Excel、最终温度 Excel、总曲线和 RGB/Inv/IR 合并视频 | 是 |
| `ir_mask_viz.py` | IR 食材 mask 渲染；也可独立生成 IR 视频 | 是 |
| `debug_artifacts.py` | 异常事件、IR 重采点参考图 | 是 |
| `chunk_reference_debug.py` | 保存每个 chunk 的实际启动参考 | 是 |

## 4. 当前关键配置

这些值位于 `TrackFood.py` 或相应算法模块中。文档只说明当前状态，不建议
在不了解完整视频触发情况时直接调整。

| 项目 | 当前值 | 含义 |
|---|---:|---|
| `CHUNK_SIZE` | 100 | 每批约 4 秒 |
| `OPTICAL_FLOW_INTERVAL` | 0 | 纯 SAM2，光流关闭 |
| `RELABEL_INTERVAL_S` | 4 | 与 chunk 周期一致的重检/重采点节奏 |
| `IR_FOOD_SEG_MODE` | `percentile` | IR 分割统一策略 |
| `IR_FOOD_SEG_PERCENTILE` | 40 | 锅内低温 40% 候选食材 |
| `ENABLE_UPRIGHT_WOK_FREEZE` | `False` | 锅直立/空锅冻结关闭 |
| 正向面积范围 | 5% - 60% 锅区 | 过小或过大判异常 |
| 正向锅区重叠 | 至少 60% | mask 大部分应位于锅区 |
| 正向骤降 | 超过 70% | 相对可信参考骤降判异常 |
| 轴心驻留 | 60% x 15 帧 | 连续贴近旋转轴才触发 |
| 上半锅区驻留 | 40% x 25 帧 | 约 1 秒连续驻留才触发 |
| 反向面积范围 | 5% - 60% 锅区 | 判断 inverse_mask |

## 5. 四路温度与最终温度

- `SAM2/RGB 正向`：把正向食材 mask 投影到 IR 后统计温度。
- `IR`：在 IR 锅区内用当前统一分割策略直接统计食材温度。
- `Inverse/RGB 反向`：追踪锅底后取 `锅区 - 锅底`，投影到 IR 统计。
- `ROI`：把现场配置的固定 RGB 圆形 ROI 投影到 IR 统计。

最终温度由 `final_temperature.py` 按以下顺序选择：

```text
可信正向 -> IR -> Inverse -> ROI -> 短时保持上一帧 -> NaN
```

其中 RGB 正向会先经过面积、锅区重叠、骤降、轴心驻留等有效性判断；
Inverse 也会先经过 5% - 60% 锅区面积判断。最终表格会同时保留
`source` 和 `reason`，用于说明该帧采用了哪一路以及原因。

## 6. 当前保留但关闭的路径

- `OPTICAL_FLOW_INTERVAL=0`：光流传播不进入当前主线。
- `ENABLE_UPRIGHT_WOK_FREEZE=False`：剪辑后的测试集不启用锅直立冻结。
- RGB 正向批内 IR-fix：代码保留但条件关闭。
- RGB 反向批内 IR mask 临时覆盖：代码保留但条件关闭。
- 正向 IR-IoU 严格门控：代码保留但条件关闭。
- `online_pipeline.py`：仅定义未来接口形状，默认关闭。

这些机制的用途与局限见根目录 `后续优化方向.md`。它们不是当前结果的
实际来源，排查时不要因为看到相关代码就假定已经启用。

## 7. 运行依赖

根目录 `requirements.txt` 列出可直接通过 `pip install -r requirements.txt`
安装的常规 Python 依赖，包括 `numpy`、`opencv-python`、`matplotlib`、
`torch` 和 `openpyxl`。其中 `openpyxl` 用于写出 Excel；如果缺失，程序会
跳过 xlsx 输出但主追踪仍可继续。

主线还要求：

- 已安装并可导入 `sam2`；
- `ffmpeg` 可选，用于把最终视频转为 H.264；
- CUDA GPU 推荐；CPU 可以被代码识别，但 SAM2 Large 运行会很慢；
- `models/sam2.1_hiera_large.pt` 存在；
- SAM2 包能够找到 `configs/sam2.1/sam2.1_hiera_l.yaml`。

`sam2` 没有简单地写成普通依赖项，是因为它通常需要按本机 CUDA/PyTorch
环境和官方仓库方式安装；换电脑时应先确认 `python -c "import sam2"` 可用。

## 8. 注意事项

1. `food_labels.json` 中的视频路径可能是绝对路径。移动项目或换电脑后，优先
   使用 `--video` 覆盖，或重新标注。
2. RGB 和 IR 最好同时具备时间戳文件。缺少时会按帧数比例估算，快速运动
   场景的对齐精度会下降。
3. `homography.npy`、`wok_region.json` 与相机位置相关。改变相机、焦距或
   画面裁剪后应重新检查。
4. 每次运行会在 `output/时间戳/` 新建目录，不覆盖旧结果，并保存
   `run_config.json` 记录本次输入路径、视频信息、关键开关和阈值。
5. 主流程完成后会删除两个中间 RGB 可视化视频，只保留最终合并视频。
6. 不要把 `旧代码库/TrackFood_*.py` 当作当前入口。
