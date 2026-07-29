# output 结果目录说明

`output/` 保存 `core/TrackFood.py` 每次运行生成的结果。主程序会按启动时间
新建子目录，例如：

```text
output/20260724_115656/
```

真实输出视频、调试图和 Excel 由本地运行生成。删除旧结果不会影响代码，
但会失去对应的视频、温度表和异常证据；当前用户要求保留全部历史输出。

## 1. 建议查看顺序

1. 先看 `track_result_combined.mp4`，确认三块画面和最终温度是否连续。
2. 再看 `food_temp_curve.png`，对比四路候选温度与最终温度。
3. 用 `temp_final.xlsx` 检查最终值、来源和选择原因。
4. 打开 `run_config.json`，确认本次使用的视频、温度矩阵、标注、锅区、
   分割模式和关键阈值。
5. 若某一时段异常，再按时间或帧号查看 `violation_events/`、
   `relabel_previews/`、`ir_relabel_frames/`。
6. 若要判断某个 chunk 从什么参考启动，查看
   `forward_chunk_references/` 或 `inverse_chunk_references/`。

## 2. 合并视频怎么看

当前同时有正向和反向标注时，顶部通常是三栏：

```text
左：RGB 正向食材 mask | 中：RGB 反向 inverse mask | 右：IR 温度与食材分割
```

- 左栏绿色区域：RGB 正向 SAM2 食材 mask。
- 中栏紫色区域：`inverse_mask = RGB 锅区 - bottom_mask`。
- 右栏：IR 热图、锅区轮廓、旋转轴排除圆和 IR 食材边界。
- 信息条：帧号、时间、mask 占比、SAM2/ROI/IR/Inv/Final 温度和最终来源。
- 上层曲线：SAM2、ROI、IR、Inverse 四路候选温度。
- 下层红线：最终温度输出。

若没有锅底标注，中间反向栏和 Inverse 曲线不会出现，视频会退化为
RGB + IR 两栏。

## 3. 主结果文件

| 文件 | 内容 | 重点字段 |
|---|---|---|
| `track_result_combined.mp4` | 最终合并视频 | 画面、状态、滚动曲线 |
| `food_temp_curve.png` | 全程温度对比 | 四路候选 + 单独最终温度 |
| `temp_sam2.xlsx` | RGB 正向温度 | mask 像素、占比、均值/最小/最大温度 |
| `temp_ir.xlsx` | IR 分割温度 | IR 食材区域均温 |
| `temp_inverse.xlsx` | RGB 反向温度 | inverse mask 均温 |
| `temp_roi.xlsx` | 固定 ROI 温度 | ROI 均温 |
| `temp_final.xlsx` | 最终输出 | `final_temp_c`、`source`、`reason` |
| `run_config.json` | 本次运行配置快照 | 输入路径、视频信息、IR 策略、关键开关和阈值 |

每个 Excel 都有：

- `frame_data`：逐帧记录。
- `summary`：总帧数、有效温度帧数、均值、峰值、标准差等摘要。

`temp_final.xlsx` 的 `source` 常见值：

| source | 含义 |
|---|---|
| `sam2_forward` | 正向 mask 可信，使用 RGB 正向温度 |
| `ir` | 正向无效或为空，使用 IR |
| `inverse` | 正向和 IR 都不可用，且反向 inverse mask 通过有效性判断 |
| `roi` | 前三路都不可用，使用固定 ROI |
| `hold` | 四路均不可用，短时保持上一帧 |
| `none` | 没有任何可用温度且无历史值 |

## 4. 调试子目录

### `violation_events/`

保存一次异常事件的第一张失败帧，不是逐帧无限保存。红色区域表示失败 mask，
文字给出面积、锅区重叠、骤降、轴心驻留等指标。下一批真正采取的动作会
追加为角标，例如 `IR_relabel`、`reuse_carry` 或 `manual_fallback`。

用途：回答“为什么判坏”和“判坏后最终做了什么”。

### `relabel_previews/`

保存下一批开头最终采用的参考结果，包括复用 carry、IR 重采点和人工兜底。

用途：回答“这一批 SAM2 最终是靠什么启动的”。

### `ir_relabel_frames/`

只在真正使用 IR 重新采点时保存。图中包含 IR 锅区、food/hot 边界、旋转轴
排除区域以及映射前的 FG/BG 点。

用途：回答“IR 分割和候选点本身是否正确”。

### `forward_chunk_references/`

逐 chunk 保存 RGB 正向启动参考。文件名包含：

```text
forward_chunk004_t014.4s_f360_ir_relabel.jpg
```

即第 4 个 chunk、14.4 秒、绝对帧 360，以 IR_relabel 启动。

### `inverse_chunk_references/`

与正向目录相同，但记录反向锅底追踪的启动参考。

### `ir_fix_mask_compare/`

用于批内 IR-fix 的旧对比图。当前该机制关闭，因此正常运行时通常为空。

### `_quick_check/`

不是 `TrackFood.py` 的固定输出合同。它是某次运行后人工抽帧检查生成的
联系表和样例帧；其他运行目录可能没有。

## 5. 一次实际结果示例

`output/20260724_115656/` 是当前可参考的完整 test8_1 结果：

- 处理 3177 帧；
- 约 32 个正向 chunk 和 32 个反向 chunk；
- 生成 5 个逐帧 Excel；
- 保存正向/反向 chunk 参考图、异常事件和 3 次正向 IR 重采点参考图；
- 最终视频为 `track_result_combined.mp4`。

这个目录适合作为理解文件结构的样本，但它不是自动化验收标准。判断算法是否
更好仍需比较同一视频、同一标注和不同代码状态下的完整结果。

## 6. 注意事项

1. 输出目录可能非常大，尤其合并视频和逐 chunk 调试图。当前不要自动清理。
2. 不要只看最终曲线是否平滑；还要看 `source` 是否频繁切换以及 mask 是否
   真正覆盖食材。
3. SAM2 表中的 `temp_min_c`/`temp_max_c` 是 mask 内范围，不等于最终输出。
4. 空单元格通常表示该帧温度为 NaN 或对应方案不可用，不一定是程序崩溃。
5. 输出目录名只表示运行开始时间，不表示测试集名称。需要结合
   `run_config.json`、chunk 图和 Excel 帧数确认是哪一组输入。
