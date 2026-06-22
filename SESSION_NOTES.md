# Chef Vision — 会话记录与项目备忘

> 本文件由 AI 助手自动整理，记录本次对话的完整背景、所有尝试、讨论结论及当前任务状态。
> 新对话开始时请先读取此文件，即可无缝接续。
>
> 最后更新：2026-06-18

---

## 一、项目背景

**目标：** 在炒菜机器人上实现实时菜表面温度监测，用于闭环控制火候和翻炒动作。

**当前阶段：** 预研 + 数据采集阶段，边写代码边用真实炒菜视频测试，尚未部署到下位机。

**硬件：**
- 热像仪（红外 + RGB 双摄集成一体）通过网络 SDK（IRCNetSDK.dll）连接
- 厨房下位机：低配笔记本（只能跑 numpy + opencv，没有 GPU）
- 开发机：RTX 5070 Ti（用于离线跑 SAM2）

---

## 二、系统架构

```
厨房现场（低配笔记本）                开发机（RTX 5070 Ti）
────────────────────────              ─────────────────────────────────
field/FieldCapture.py                 core/TrackFood.py
  ├─ RGB 视频  rgb_{ts}.mp4    ──→     SAM2 逐帧食材追踪 → mask
  ├─ IR 视频   ir_{ts}.mp4             ↓
  ├─ 温度矩阵  temp_{ts}.npy   ──→    温度融合（homography）
  ├─ RGB 时间戳 rgb_{ts}_ts.npy        ↓
  └─ IR 时间戳  temp_{ts}_ts.npy      输出：CSV / Excel / 曲线图 / 并排视频
```

**重要说明：** RGB 和 IR 集成在同一设备，相对位置固定，单应矩阵（homography）是设备固有参数，无需重新标定。RGB 视野 1600×1200，IR 视野 256×192，画面边缘没有对应 IR 像素属正常物理限制。

---

## 三、项目文件结构

```
Chef_Vision/
  field/                    ← 下位机采集脚本（低配电脑用）
    FieldCapture.py           主采集脚本（RGB+IR视频+温度矩阵+时间戳）【本次修改】
    TempMonitor.py            实时温度监控（独立工具）
    DataLogger.py             数据记录工具
    FieldTempMonitor.py       现场温度监控（备用）
    roi_config.json           ROI 圆形区域配置（按 R 键设置）

  core/                     ← 核心算法（开发机 GPU）
    TrackFood.py              SAM2 食材追踪 + 温度融合主程序【本次大量修改】
    LabelFirstFrame.py        第一帧手动标注工具（点击 FG/BG 点）
    auto_label.py             自动标点模块（IR 低温区采点）
    auto_tracking_utils.py    追踪辅助工具
    TrackFood_AutoRecover.py  自动恢复版本（旧）
    food_labels.json          当前使用的标注文件（关键帧坐标）

  sdk/                      ← 热像仪 SDK
    ThermalCamera.py          Python 封装
    IRCNetSDK.dll / .h        设备 SDK（C DLL）
    IRCNetSDKDef.h

  models/                   ← SAM2 模型权重（不提交 git）
    sam2.1_hiera_tiny.pt      149MB，速度优先
    sam2.1_hiera_large.pt     856MB，精度优先（目前使用）

  data/                     ← 标定数据
    homography.npy            RGB→IR 单应矩阵（3×3）
    wok_region.json           锅的椭圆区域（IR坐标系）
    rgb_20260424_*.mp4        旧测试视频（静态场景，动作少）
    temp_20260424_*.npy       旧测试温度数据

  test_data/                ← 测试数据
    test1/                    ← 主要炒菜测试数据【当前使用】
      rgb_20260529_112414.mp4   RGB 炒菜视频
      ir_20260529_112414.mp4    IR 伪彩色视频
      temp_20260529_112414.npy  温度矩阵（IR 帧数组）
      roi_config.json           ROI 配置
    rgb_20260519_154927.mp4   另一段测试视频
    temp_20260519_155641.npy  对应温度数据
    bd/                       另一组数据（rgb+temp 同时间戳）

  output/                   ← 处理结果（按时间戳子目录）

  tools/                    ← 辅助分析工具
    check_ir_align.py         【本次新建】RGB/IR 时间对齐可视化验证脚本
    ir_align_check.jpg        【本次生成】对齐验证图（用旧静态视频生成的，待用炒菜视频重新生成）
    ir_mask_viz.py            IR mask 可视化工具
    analyze_ir_temp.py        IR 温度分析
    browse_video.py           视频浏览工具
    Calibrate.py              标定工具
    check_homography.py       单应矩阵检验工具
    VerifyData.py             数据验证

  backup/                   ← 旧版本备份（不需要维护）
```

---

## 四、本次对话所有代码修改（详细）

### 4.1 field/FieldCapture.py — 新增逐帧时间戳

**修改原因：** RGB 和 IR 两路流的帧率不同（RGB 25fps，IR 约 32-42fps），之前用帧率比例估算对应帧，存在累积误差。加时间戳后可以精确查找最近邻帧，精度从 ±半帧（~20ms）提升到 ~5ms。

**具体修改：**
1. 全局变量区新增 `rgb_ts_list = []` 和 `ir_ts_list = []`
2. `on_video_frame` 回调：写入视频帧时追加 `rgb_ts_list.append(time.time())`
3. `on_temp_frame` 回调：保存温度帧时追加 `ir_ts_list.append(time.time())`
4. 按 S 开始录制时同步清空两个列表
5. 按 Q 停止后，额外保存：
   - `rgb_{ts}_ts.npy`（float64 数组，每个 RGB 帧的 Unix 时间戳）
   - `temp_{ts}_ts.npy`（float64 数组，每个 IR 帧的 Unix 时间戳）

**文件命名约定：**
- `rgb_20260529_112414.mp4` → `rgb_20260529_112414_ts.npy`（RGB 时间戳）
- `temp_20260529_112414.npy` → `temp_20260529_112414_ts.npy`（IR 时间戳）

**注意：** test_data/test1 的老数据没有 `_ts.npy` 文件，FieldCapture 只有重新录制后才会生成。

---

### 4.2 core/TrackFood.py — 帧对齐方式改进（_get_ir_idx）

**修改原因：** 帧率比例估算会有累积误差，尤其是 IR 帧率抖动（异步回调导致帧率不稳定）时误差更大。

**具体修改：**
1. 启动时尝试加载 `_ts.npy` 文件：`_rgb_ts` 和 `_ir_ts`
2. 封装 `_get_ir_idx(rgb_abs_idx)` 函数：
   - 有时间戳：`np.argmin(np.abs(ir_ts - rgb_ts[rgb_abs_idx]))` 最近邻查找
   - 无时间戳：fallback 到 `int(abs_idx * ir_fps_ratio)`（原来的方式）
3. 文件内所有 `int(abs_idx * ir_fps_ratio)` 调用（共 4 处）统一替换为 `_get_ir_idx(abs_idx)`

**向后兼容：** 老录制数据没有 `_ts.npy` 时自动 fallback，行为和之前完全一样。

---

### 4.3 core/TrackFood.py — 旋转轴排除圆

**背景：** 炒菜机器有一个旋转搅拌爪，轴心在锅中心。SAM2 有时会把旋转轴附近的金属部件误标为食材，导致 mask 漂移到那里。

**具体修改：**
1. 从 `wok_region.json` 读取锅中心（cx, cy，IR 坐标），通过 `H_inv` 反投影到 RGB 坐标系
2. 定义变量：`_AXIS_CX_RGB`, `_AXIS_CY_RGB`（旋转轴 RGB 坐标），`_AXIS_EXCL_R = 90`（排除半径 px）
3. 在所有采点循环（IR 低温区采点、腐蚀采点）中，过滤掉距旋转轴 90px 以内的点
4. 每次补强/重置时，把 `[_AXIS_CX_RGB, _AXIS_CY_RGB]` 作为固定背景点注入 SAM2（告诉 SAM2 这里不是食材）

---

### 4.4 core/TrackFood.py — 正常补强路径改用 IR 低温区采点

**背景（补强机制说明）：**
- 每隔 `RELABEL_INTERVAL_S=8` 秒，在当前批次第 0 帧注入补强点
- 之前：从 SAM2 的 `carry_mask`（上批末帧 mask）内部腐蚀后随机采点
- 问题：如果 SAM2 的 mask 本身已经漂移，采的点也是错的，越补越偏

**新策略（本次修改）：**
```
优先路径：从 IR 当前帧低温区采点（物理温度锚点）
  - 取锅内（wok_mask）像素，低于 35 百分位 = 食材候选
  - 随机采 6 个点，反投影到 RGB 坐标系
  - 排除旋转轴附近的点
失败时 fallback：腐蚀 carry_mask 内部采点（原来的方式）
  - 同样排除旋转轴附近的点
```

**为什么 IR 比 SAM2 mask 更可靠：**
- IR 低温区基于物理温度，食材温度 < 锅壁温度是硬性事实
- SAM2 mask 可能已经漂移，基于漂移 mask 采的点会固化错误

---

### 4.5 tools/check_ir_align.py — 新建对齐验证脚本

**功能：**
- 加载 RGB 视频 + IR npy，抽取 N 个时间点（默认 8 个）
- 每行：左=RGB 帧，右=IR 热力图，标注对应帧号/时间/时间差
- 在 RGB 上叠加 wok 椭圆投影（通过 H_inv 反投影），直观看空间对齐
- 在 IR 上叠加 wok 椭圆（IR 坐标系）
- 支持 `--ts` 参数启用时间戳对齐（需要 `_ts.npy` 文件）
- 输出：`tools/ir_align_check.jpg`

**用法：**
```bash
# 用 data/ 里最新数据（帧率比例对齐）
python tools/check_ir_align.py

# 指定文件
python tools/check_ir_align.py --rgb data/rgb_XXX.mp4 --temp data/temp_XXX.npy --n 8

# 用 test_data/test1 炒菜视频
python tools/check_ir_align.py \
  --rgb test_data/test1/rgb_20260529_112414.mp4 \
  --temp test_data/test1/temp_20260529_112414.npy \
  --n 10 --out tools/ir_align_check_test1.jpg

# 若有 _ts.npy 时间戳文件（新录制数据专用）
python tools/check_ir_align.py --rgb ... --temp ... --ts
```

---

## 五、已讨论的技术问题和结论

### 5.1 帧率比例 vs 时间戳对齐

| 方式 | 精度 | 适用场景 |
|------|------|---------|
| 帧率比例 | ±半帧（~20ms @ 25fps IR 抖动时可达 ±100ms） | 老录制数据，无 `_ts.npy` |
| 时间戳对齐 | ~5ms（取决于系统调用精度） | 新录制数据，有 `_ts.npy` |

**结论：** 两种方式都保留，有时间戳用时间戳，没有自动 fallback，不破坏老数据的处理流程。

### 5.2 实时化路线

已讨论的方案（见 PROJECT_STATUS.md 详细说明）：
- SAM2 在 RTX 5070 Ti 上约 12-15fps，无法实时处理 25fps 视频
- 流水线分批（100帧/批）方案理论可行但实测仍超时 3 倍
- **当前结论：** 预研阶段用离线处理，待分析 IR 视频数据后再决定实时化方案
- **IR 温度阈值分割** 是最有希望的实时化路线（延迟 <50ms，CPU 可跑），待验证

### 5.3 SAM2 追踪漂移问题

**已知漂移场景：**
1. 投料盒进入画面（外观与菜相似）
2. 翻炒剧烈时菜被遮挡
3. 旋转搅拌爪/轴心吸引 SAM2

**已实现的对策：**
- 多关键帧注入（`food_labels.json` 支持多个 keyframe，投料帧前后手动标注）
- 分批自动补强（每 8 秒重新采点）
- wok 区域约束（mask AND 锅内区域，防止 mask 跑到锅外）
- 面积异常检测（mask > wok 35% 或骤降 >70% 时重置）
- 旋转轴排除圆（新增，见 4.3）

**尚未解决：**
- 翻炒时 IR 和 RGB 同步倾斜，用 SAM2 采点可能不稳定 → 加了 IR 稳定性检查（var < 200 时跳过补强）

### 5.4 补强策略演变

```
初始版本：每 N 秒从 carry_mask 腐蚀内部随机采点注入 SAM2
↓
问题：SAM2 mask 漂移后，采点也跟着漂移，正反馈导致越补越偏
↓
改进（本次）：优先从 IR 低温区（食材物理温度）采点，失败才用腐蚀
+ 旋转轴排除圆
+ 旋转轴中心作为固定背景点
```

---

## 六、当前任务状态（新对话接入点）

### 2026-06-15 本次完成

1. **git commit cc2d66d**（回滚基准）：
   - `cy+10px` 向下补偿（标定系统偏差）
   - `FieldCapture.py` 更新并替换到低配电脑
   - test2 视频处理完成

2. **git commit 4a6520a**：场景冻结检测改为相对阈值
   - 旧逻辑：`mean>150 and var<800`（绝对值，不同光照/锅型会失效）
   - 新逻辑：**滚动历史相对阈值**
     - 维护近 8 批正常批次的 `rgb_mean_history` / `rgb_var_history` / `ir_mean_history` / `ir_var_history`
     - **白烟检测**：RGB 均值突然 >参考值×1.5 且方差 <参考值×0.2（最低50）
     - **锅直立检测（IR）**：IR 均值突然 >参考值+15°C 且方差 <参考值×0.3（最低50）
     - **fallback**（历史 <3 批时）：宽松绝对值（mean>190 and var<300），比原来更保守
     - 冻结批次不计入基准历史（异常帧不污染参考值）
   - 语法检查通过（`python -m py_compile`）

### 下一步建议

1. **用 test2 或新录制视频跑一遍**，观察冻结检测 log——白烟/锅直立时是否触发，正常炒菜时是否误报
2. **如果发现参数需要调整**，主要调两个：
   - `_SCENE_WIN`（历史窗口大小，默认8批）
   - 相对阈值倍率（1.5、0.2、+15、0.3 这四个数）
3. **如果想看实际效果**，在 relabel 预览图旁边加一行"场景状态"文字，方便 debug

---

## 七、wok_region.json 说明

位置：`data/wok_region.json`
```json
{
  "cx": 116,  // 锅中心 X（IR 坐标系，256×192）
  "cy": 114,  // 锅中心 Y
  "rx": 80,   // 椭圆长半轴
  "ry": 70    // 椭圆短半轴
}
```

这个文件同时被 TrackFood.py（rotatioaxis 排除圆计算）和 check_ir_align.py（wok 椭圆投影可视化）使用。

---

## 八、food_labels.json 格式说明

新格式（支持多关键帧）：
```json
{
  "video_path": "test_data/test1/rgb_20260529_112414.mp4",
  "keyframes": [
    {
      "frame": 350,
      "time_s": 14.0,
      "label": "初始标注",
      "fg_points": [[x1, y1], [x2, y2], ...],
      "bg_points": [[x1, y1], ...]
    },
    {
      "frame": 800,
      "time_s": 32.0,
      "label": "投料后重标",
      "fg_points": [...],
      "bg_points": [...]
    }
  ]
}
```

`LabelFirstFrame.py` 用来交互式标注，点击生成这个文件。

---

## 九、常用命令速查

```bash
# 标注第一帧
python core/LabelFirstFrame.py

# 运行 SAM2 追踪（处理 test1 数据）
python core/TrackFood.py

# 验证时间对齐（炒菜视频）
python tools/check_ir_align.py \
  --rgb test_data/test1/rgb_20260529_112414.mp4 \
  --temp test_data/test1/temp_20260529_112414.npy \
  --n 10 --out tools/ir_align_check_test1.jpg

# 验证单应矩阵
python tools/check_homography.py

# 浏览视频
python tools/browse_video.py

# 语法检查
python -m py_compile core/TrackFood.py
python -m py_compile field/FieldCapture.py
```

---

*本文件由 AI 助手生成，如有遗漏请直接补充。*

---

## 十、2026-06-18 本次对话记录

### 10.1 本次算法更新（基于 commit 4a32c95）

本次对话基于已有的三次 commit 更新：

**commit 7f60ff8**：wok 倾斜检测 + 动态 B-check 阈值
- 检测 wok 中心连续多批 drift 累积 >30px → 判定为锅倾斜/快速移动
- 倾斜期间 B-check 阈值从 50% 降到 30%（提前拦截漂移 mask）

**commit 4a6520a**：场景冻结相对阈值（滚动历史）

**commit 4a32c95**：IR-IoU 改用 K-means + _next_inject 机制
- **K-means 替代固定 P40 阈值**：锅内温度双峰聚类，两类中心差 <30°C 时锅内无有效食材信号，自动跳过 IoU 检查
- **`_next_inject` 机制**：IR-fix 批次命中率 >50% 时，从 IR 末帧 mask 内采 6 个前景点存入 `_next_inject`，下批 SAM2 精细化 IR 粗 mask 边界（而不是直接用 IR 粗 mask 传播）

### 10.2 本次对话发现并修正的问题

**逐帧 IR-fix 触发阈值**：本次误改为 70%，经用户指正已改回 50%。

原则：mask 超过 wok 50% 就是追踪失控，应立即 IR 纠错，不应宽容。70% 只是延迟纠错，没有任何好处。`_next_inject` 精细化和立即 IR 纠错是两件独立的事，不冲突。

### 10.3 测试数据说明

| 数据集 | 路径 | 帧数 | FPS | 标注 |
|--------|------|------|-----|------|
| test4 | `test_data/test4/rgb_20260616_151415.mp4` | 2287 | 25 | 帧90，简单8点初始标注（AI生成） |
| test5 | `test_data/test5/rgb_20260616_153531.mp4` | 3017 | 25 | 帧60，手动精细标注 FG=20 BG=39 |

**test5 food_labels.json（当前使用）：**
```json
{
  "video_path": "D:\\Chef_Vision\\test_data\\test5\\rgb_20260616_153531.mp4",
  "fps": 25.0,
  "keyframes": [{
    "frame": 60, "time_s": 2.4, "label": "初始标注",
    "fg_points": [[778,694],[752,707],[731,733],[720,767],[735,799],[761,821],
                  [795,834],[849,843],[888,843],[894,816],[872,762],[855,733],
                  [811,705],[835,717],[766,731],[818,746],[849,769],[770,772],
                  [811,793],[852,799]],
    "bg_points": (39个背景点，覆盖锅外大范围)
  }]
}
```

### 10.4 最新跑结果对比

| 结果目录 | 数据集 | reset次数 | relabel次数 | 备注 |
|----------|--------|-----------|-------------|------|
| 20260617_165351 | test5（旧算法） | 3 | 8 | 对比基准 |
| 20260618_154140 | test4（新算法） | 7 | 9 | reset增多，待分析 |
| 20260618_160808 | test5（新算法，50%阈值修正后） | **14** | 3 | 前期连续reset，问题待分析 |

### 10.5 待解决问题（下次对话接续）

**问题1：test5 前期 t10-t42 每4秒连续 reset**
- 文件：`reset_t10s_f260.jpg` ~ `reset_t42s_f1060.jpg`，共9张
- 可能原因：帧60食材刚入锅，SAM2 追踪的目标很小，面积骤降 >70% 触发"骤降检测"；或 K-means 在食材量少时双峰差 <30°C 跳过了补强导致下次 IoU 也不行
- 需要看预览图确认

**问题2：t98-t118 大量 IR-fix（约60帧全部触发）**
- 这段时间 SAM2 mask 持续 70%+，IR-fix 每帧都在修正
- 但 IR-fix 成功后 mask 仍在 40%+，说明这段时间食材本身就占了锅的 40%，属于正常还是追踪偏大？
- `_next_inject` 机制在这段有没有起到精细化效果待验证

**用户还需告知：** 这次输出结果的具体问题（还未反馈）

### 10.6 当前 TrackFood.py 主要参数

```python
CHUNK_SIZE          = 100       # 每批帧数（4秒@25fps）
RELABEL_INTERVAL_S  = 4         # 自动补强间隔（秒）
_AXIS_EXCL_R        = 90        # 旋转轴排除半径（RGB px）
_WOK_MAX_DRIFT      = 25        # 单批wok中心最大漂移（IR px）
IR-fix触发阈值       = 50%       # mask超过wok 50%立即IR纠错
面积上限             = 35% wok   # 超过即reset
overlap下限          = 60%       # mask在wok内overlap<60%即reset
骤降阈值             = 70%       # 面积骤降>70%即reset
B-check阈值          = 50%（正常）/ 30%（倾斜期）
K-means gap下限      = 30°C      # 低于此值认为锅内无食材信号
```
