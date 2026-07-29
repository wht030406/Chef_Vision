# 排查工具说明

本目录保存开发和测试过程中用于定位问题的脚本。它们不被
`core/TrackFood.py` 自动导入，运行前应先确认输入/输出参数。已经删除的
早期示例数据不再作为默认路径；需要视频或温度矩阵的脚本应通过
`--video`、`--npy`、`--rgb` 或 `--temp` 显式指定。

## 1. 结果汇总与温度分析

| 工具 | 作用 | 当前注意事项 |
|---|---|---|
| `analyze_run.py` | 汇总一次运行中的表格和异常 | 通常需在脚本参数/顶部指定结果目录 |
| `analyze_result.py` | 检查输出温度和统计结果 | 先确认输入文件名 |
| `analyze_ir_temp.py` | 查看 IR 温度分布、曲线和关键帧热图 | 使用 `--npy` 指定温度矩阵 |
| `inspect_frames.py` | 根据 CSV 中的关键值抽取 RGB 帧 | 使用 `--csv` 和 `--video` 指定输入 |

## 2. RGB/IR 对齐与锅区

| 工具 | 作用 | 推荐用法 |
|---|---|---|
| `check_ir_align.py` | 生成 RGB/IR 对齐联系图 | 支持 `--rgb`、`--temp`、`--n`、`--ts` |
| `check_homography.py` | 快速检查单应矩阵和映射范围 | 内部路径较固定，运行前阅读 |
| `test_wok_shift.py` | 对比锅中心位置偏移 | 当前硬编码为 test1 |
| `gen_wok_compare.py` | 绘制不同锅区结果对比 | 运行前指定/检查输入 |

示例：

```powershell
python 排查工具/check_ir_align.py `
  --rgb test_data/test8_1/rgb_20260707_153017.mp4 `
  --temp test_data/test8_1/temp_20260707_153017.npy `
  --n 8 `
  --ts
```

## 3. 视频浏览与抽帧

| 工具 | 作用 | 当前注意事项 |
|---|---|---|
| `browse_video.py` | 逐帧浏览、跳转并寻找标注/异常时刻 | 必须使用 `--video` 指定视频 |
| `extract_frames.py` | 按视频均匀抽取预览帧 | 必须使用 `--video`，可用 `--out` 指定输出 |
| `inspect_frames.py` | 按结果统计抽取重点帧 | 必须使用 `--csv` 和 `--video` |

```powershell
python 排查工具/browse_video.py `
  --video test_data/test8_1/rgb_20260707_153017.mp4 `
  --start 0
```

## 4. SAM2 与短测

| 工具 | 作用 | 当前注意事项 |
|---|---|---|
| `bench_chunk.py` | 运行少量 chunk 观察耗时和显存 | 直接导入 `TrackFood` 常量，受当前环境影响 |
| `SegmentFood.py` | 单图验证 SAM2 Image Predictor | 保留外部权重路径，可能尝试联网下载 |
| `_check_syntax.py` | 仅解析 `core/TrackFood.py` 语法 | 不代表运行逻辑正确 |
| `run_track_short.ps1` | 辅助执行短测 | 内含特定测试路径，先打开确认 |
| `relabel_test1_1.ps1` | test1_1 的重标/测试辅助 | 不适用于 test8_1 |

正式短测优先使用主程序自身参数：

```powershell
python core/TrackFood.py --max-frames 120
```

## 5. 早期算法验证

| 工具 | 作用 | 当前状态 |
|---|---|---|
| `VerifyData.py` | 检查温度矩阵形状、范围和趋势 | 使用 `--npy` 指定温度矩阵 |
| `TempFilter.py` | RGB/IR 对齐 + HSV 温度过滤实验 | 使用 `--video` 和 `--npy`；不属于当前 percentile 主线 |
| `SegmentFood.py` | 单图 SAM2 分割实验 | 不等于视频追踪主线 |

## 6. 安全使用原则

1. 先阅读脚本顶部常量和输出路径，再运行。
2. 尽量把输出写到新的 `output/排查名称/`，不要覆盖正式结果。
3. 不要把个人测试集写死为默认路径；优先通过命令行参数传入。
4. PowerShell 脚本可能会调用重标程序或启动较长测试，不要双击盲跑。
5. `SegmentFood.py` 可能下载大模型并写到外部路径；当前主程序已经有本地
   `models/` 权重，排查前先决定是否真的需要。
6. `core/ir_mask_viz.py` 没有放在这里，因为最终合并视频仍会调用它。
