# Chef_Vision — AI 交接文档

> **写给下一个 AI 助手：** 请先完整读完本文件，再开始任何工作。本文涵盖项目背景、当前代码状态、最新算法方案、已知问题和待办事项。
>
> 最后更新：2026-06-24

---

## 一、项目一句话总结

在**自动炒菜机器人**上实现实时菜表面温度监测，用 SAM2 追踪食材区域，结合热像仪（红外 IR）数据，输出每帧食材温度曲线，供火候闭环控制使用。

---

## 二、硬件环境

| 设备 | 规格 | 用途 |
|------|------|------|
| 热像仪（双摄）| IR 256×192 + RGB 1600×1200，集成同体 | 录制炒菜视频 + 温度矩阵 |
| 厨房下位机 | 低配笔记本，仅 CPU | 现场采集（跑 `FieldCapture.py`） |
| 开发机 | RTX 5070 Ti Laptop | 离线 SAM2 追踪（跑 `TrackFood.py`） |

**关键约束：**
- RGB 和 IR 集成同体，`homography.npy`（RGB→IR 单应矩阵）是设备固有参数，已标定，无需重标
- RGB 视野宽于 IR，画面边缘没有对应 IR 像素属正常物理限制

---

## 三、项目文件结构（重要文件）

```
Chef_Vision/
  core/
    TrackFood.py          ★ SAM2 追踪主程序（本次大量改动）
    LabelFirstFrame.py    交互式标注工具（生成 food_labels.json）
    auto_label.py         IR 低温区自动采点模块
    food_labels.json      ★ 当前标注文件（指向 test4 视频）

  field/
    FieldCapture.py       现场采集脚本（RGB+IR+时间戳）

  data/
    homography.npy        RGB→IR 单应矩阵（3×3，已标定）
    wok_region.json       锅椭圆（IR 坐标系）cx=106, cy=118, rx=59, ry=64

  test_data/
    test4/rgb_20260616_151415.mp4   当前测试视频（2287帧，25fps）
    test4/temp_20260616_151415.npy  对应温度矩阵（3531帧，IR@~38.6fps）
    test5/rgb_20260616_153531.mp4   备用测试视频（3017帧，更精细标注）

  output/
    20260623_203118/      ★ 最新一次跑结果（昨天生成）
      track_result_combined.mp4   三栏并排视频（RGB食材+RGB反向语义+IR热图）
      food_temp_curve.png          四条温度曲线对比图
      temp_sam2.xlsx / temp_roi.xlsx / temp_ir.xlsx / temp_inverse.xlsx

  tools/
    gen_wok_compare.py    生成椭圆对比图（可视化圆圈贴合效果）
    ir_mask_viz.py        IR 帧渲染工具（被 stitch_rgb_ir 调用）
    wok_rgb_compare.jpg   ★ 昨天生成的椭圆对比图
```

---

## 四、当前 food_labels.json 标注内容（test4）

```json
{
  "video_path": "D:\\Chef_Vision\\test_data\\test4\\rgb_20260616_151415.mp4",
  "fps": 25.0,
  "keyframes": [{ "frame": 90, "time_s": 3.6, ... FG=28 BG=28 }],
  "bottom_keyframes": [{ "frame": 90, "time_s": 3.6, "label": "锅底初始标注", FG=15 BG=8 }],
  "wok_rgb_region": {
    "cx": 558, "cy": 578,
    "rx": 528, "ry": 515   // 注意：代码运行时会自动 ×0.88，实际生效 465/453
  }
}
```

**`bottom_keyframes`** 是"反向语义方案"的标注——标注锅底（非食材区域），通过 `锅内区域 - 锅底mask = 食材区域` 得到另一条温度曲线（紫色 Inv 线）。

**`wok_rgb_region`** 是 RGB 坐标系下锅的椭圆区域，用于限制反向语义圆圈的范围。

---

## 五、最新算法方案：反向语义（Inverse Semantics）

### 5.1 核心思路

```
传统方案（SAM2 正向追踪食材）：
  → 追踪食材 mask → 温度均值

反向语义方案（昨天新增）：
  → 追踪锅底 mask（底部金属/搅拌爪区域）
  → inverse_mask = 锅内椭圆区域 AND NOT 锅底mask
  → inverse 区域温度 = 近似食材温度（另一条曲线）
```

**优势：** 锅底是固定的金属结构，SAM2 追踪更稳定；食材是"锅内剩余区域"，不需要直接追踪食材

### 5.2 在代码中的实现位置（`core/TrackFood.py`）

| 功能 | 代码位置 |
|------|----------|
| 加载 bottom_keyframes | `load_labels()` 函数，返回 `bottom_keyframes` |
| 锅底 SAM2 追踪 | 主循环内 `bottom_chunk_masks` 块（每批做两次 SAM2）|
| 构建 inverse_mask | `_dyn_wok_bool & ~_bm_full`（动态锅椭圆 AND NOT 锅底）|
| 面积门控 | `_inv_ratio > 50%` 时认为锅直立/异常，跳过该帧 |
| 写入视频 | `writer_inv`（单独一路 `track_result_inv_viz.mp4`）|
| 并排视频 | `stitch_rgb_ir` 三栏模式：RGB食材 ｜ RGB反向 ｜ IR |
| 数据输出 | `temp_inverse.xlsx` |

### 5.3 动态锅椭圆圆心追踪（RGB Hough）

反向语义区域 `inverse_mask` 需要一个"锅内区域"约束，用的是 `wok_rgb_region`（RGB 坐标系椭圆）。  
由于相机手持、锅位置会移动，椭圆圆心需要每批更新：

**当前实现（昨天改）：**
```python
# 每批锅底 SAM2 完成后，用 cv2.HoughCircles 在 RGB 画面检测锅内壁圆弧
# 找到最近候选圆（距当前动态圆心 <200px）即更新 _wok_rgb_cx_dyn / _wok_rgb_cy_dyn
# 找不到则保留上批圆心（不跳变，不回退到 IR 反投影）
```

**已废弃方案（之前用的）：**
```python
# 用 homography 把 IR 锅中心反投影到 RGB 坐标
# 问题：IR→RGB 换算有系统误差，会把圆心拉偏 ~200px
```

### 5.4 椭圆大小参数

`food_labels.json` 里存储的是标注时的原始 rx/ry，代码加载时自动乘以缩放系数：

```python
wok_rgb_rx = float(_wr["rx"]) * 0.88   # 去掉外圈金属沿（昨天改，之前是 1.0）
wok_rgb_ry = float(_wr["ry"]) * 0.88
```

昨天跑完用户反馈圆圈**还是大了点**，建议改成 `* 0.79`（即再缩 90%）。

---

## 六、昨天跑结果发现的问题（待修复）

### 问题1：8秒前 RGB 反向语义栏（中间栏）没有 mask
**原因分析：** `bottom_keyframes` 标注帧号是 90（3.6s），8s 之前是追踪起始阶段，  
锅底 SAM2 追踪可能在最初几批没有有效 mask（carry_mask 为 None 时 SAM2 可能输出空 mask）。  
**还未修复。**

### 问题2：反向语义椭圆圆心明显偏离锅中心
用户在截图中看到粉色圆圈（反向语义椭圆）圆心偏左偏上，没有对准锅内壁。  
**原因：** Hough 圆检测参数（`param1=60, param2=35`）可能在当前场景下检测不到正确的圆，  
导致用了初始标注值（cx=558, cy=578）而没有更新。  
用户提到**希望手动标注圆心位置**，让代码从手动标注的圆心出发做 Hough 更新（而不是从上批圆心出发）。  
**还未实现/修复。**

### 问题3：椭圆圆圈还是大了
已从 1.0 改为 0.88（×465px），用户觉得还要再小，建议改为 `* 0.79`（88% 再 × 90%）。  
**还未修复。**

---

## 七、TrackFood.py 当前关键参数

```python
CHUNK_SIZE           = 100      # 每批帧数（4s @25fps）
RELABEL_INTERVAL_S   = 4        # 自动 IR 补强间隔（秒）
_AXIS_EXCL_R         = 90       # 旋转轴排除半径（RGB px）
_WOK_MAX_DRIFT       = 25       # 单批 wok 中心最大漂移（IR px）
IR-fix触发阈值        = 50%      # mask 超过 wok 50% 立即 IR 纠错
面积上限             = 35% wok   # 超过即 reset
overlap下限          = 60%       # mask 在 wok 内 overlap < 60% 即 reset
骤降阈值             = 70%       # 面积骤降 > 70% 即 reset
B-check 阈值         = 50%（正常）/ 30%（倾斜期）
K-means gap 下限     = 30°C     # 低于此值认为锅内无食材信号
wok_rgb_rx/ry 缩放   = × 0.88  # 实际生效尺寸（待改为 × 0.79）
```

---

## 八、wok_region.json（IR 坐标系锅椭圆）

```json
{
  "cx": 106, "cy": 118,
  "rx": 59, "ry": 64,
  "axis_cx": 106, "axis_cy": 118   // 旋转轴中心（RGB 排除圆用）
}
```

---

## 九、待办事项（按优先级）

### 高优先级（影响当前跑结果质量）

1. **[ ] 修复 8s 前反向语义无 mask 问题**
   - 检查 `bottom_keyframes` 的第一批 SAM2 是否正常初始化
   - 可能需要给锅底第一批（`_bottom_carry is None` 时）单独处理

2. **[ ] 修复椭圆圆心偏离问题**
   - 方案A：在 `food_labels.json` 的 `wok_rgb_region` 增加 `initial_cx/cy` 字段，作为 Hough 的搜索起点（每批不再从上批圆心出发，而是从用户手动标注值出发）
   - 方案B：改进 Hough 参数，或换用 `cv2.fitEllipse` 对锅沿进行边缘拟合
   - 用户倾向方案A（自己标圆心）

3. **[ ] 椭圆缩小**
   - 把 `* 0.88` 改为 `* 0.79`（即当前大小再缩 90%）

### 中优先级

4. **[ ] 重新跑 test4 验证上述修复效果**

5. **[ ] 分析 output/20260623_203118/ 的具体问题**
   - 看 `reset_*.jpg` 预览图，确认 reset 原因是否合理
   - 看各批次 `[wok_rgb动态]` 日志，Hough 多少批触发、圆心漂移了多少

---

## 十、常用命令速查

```bash
# 标注第一帧（生成 food_labels.json）
python core/LabelFirstFrame.py

# 运行 SAM2 追踪
python core/TrackFood.py

# 语法检查
python -m py_compile core/TrackFood.py

# 生成锅椭圆对比图（可视化圆圈贴合效果）
python tools/gen_wok_compare.py

# 验证 RGB/IR 对齐
python tools/check_ir_align.py --rgb test_data/test4/rgb_20260616_151415.mp4 --temp test_data/test4/temp_20260616_151415.npy --n 10

# 打开最新结果视频（Windows）
start output\20260623_203118\track_result_combined.mp4
```

---

## 十一、给新 AI 的关键提示

1. **不要改 `data/homography.npy`**，这是已标定的设备固有参数
2. **`food_labels.json` 指向 test4**，所有改完都要用 test4 验证
3. **反向语义方案**是最近两天新加的，代码在 `TrackFood.py` 的 `bottom_chunk_masks` 和 `inverse_mask` 相关代码块
4. **圆心追踪**用 RGB Hough（`cv2.HoughCircles`），每批更新一次 `_wok_rgb_cx_dyn/_wok_rgb_cy_dyn`
5. **三条温度曲线** = SAM2正向(橙) + ROI固定圆(蓝) + IR自动分割(绿)，**第四条** = 反向语义(紫虚线 Inv)
6. 运行环境：Windows PowerShell，不支持 `&&` 分隔命令，用 `;` 或分开执行
7. **Python 文件有中文注释**，读取 json 时要加 `encoding="utf-8"`

---

*本文档由 Claude Sonnet 4.6 生成，2026-06-24。*
