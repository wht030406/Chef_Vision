# 排查工具说明

这个目录收纳的是开发和测试过程中使用的一次性分析、可视化、短测脚本。它们不属于当前 `core/TrackFood.py` 的主流程入口，但部分工具仍可在排查时手动运行。

- `analyze_run.py`：分析一次运行输出目录中的关键结果和异常情况。
- `analyze_result.py`：检查输出结果中的温度、mask 或统计信息。
- `analyze_ir_temp.py`：分析 IR 温度矩阵的分布和食材温度统计表现。
- `check_ir_align.py`：检查 RGB 与 IR 的映射对齐效果。
- `check_homography.py`：检查单应矩阵映射是否合理。
- `test_wok_shift.py`：测试锅区中心或锅区位置变化相关逻辑。
- `gen_wok_compare.py`：生成锅区对比图，用于查看不同锅区估计结果。
- `inspect_frames.py`：抽取或查看指定帧，辅助定位异常时刻。
- `extract_frames.py`：从视频中批量抽帧，方便人工检查。
- `browse_video.py`：浏览视频帧，用于查找合适标注帧或异常帧。
- `bench_chunk.py`：测试 SAM2 分 chunk 追踪速度和运行表现。
- `run_track_short.ps1`：快速运行短测流程的 PowerShell 脚本。
- `relabel_test1_1.ps1`：针对 `test1_1` 的重新标注与运行辅助脚本。

验证类（原在 `tools/`，2026-07-24 移入）：

- `VerifyData.py`：检查采集温度 `.npy` 的形状、温度范围，并可视化第一帧热力图与全帧趋势。默认读 `data/temp_20260428_121546.npy`，可在脚本顶部改文件名。
- `SegmentFood.py`：用 SAM2.1 对单帧预览图做自动分割验证，确认模型/权重工作正常。
- `TempFilter.py`：温度过滤算法验证（Homography 对齐 RGB→IR + HSV 分割 + 四联可视化）。
- `_check_syntax.py`：检查 `core/TrackFood.py` 语法是否正确的一次性小脚本。

备注：这些工具主要服务于调试和阶段性验证，后续如果某个工具长期稳定使用，可以再从这里移回 `tools/` 或重构成正式模块。`ir_mask_viz.py` 因为会被合并视频输出调用，已放回 `core/ir_mask_viz.py`。
