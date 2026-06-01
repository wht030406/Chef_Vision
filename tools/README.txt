tools/ — 分析与调试工具集
==============================

这些脚本用于数据分析、标定和调试，不是主流程的一部分。

标定工具：
  Calibrate.py          RGB / IR 像素对齐标定。
                        手动点击对应角点，计算 Homography 矩阵。
                        输出：data/homography.npy
                              output/calibration_verify.png

  VerifyData.py         验证采集数据的质量。
                        检查 .npy 文件的形状和温度范围，输出热力图。
                        输出：output/temp_verify.png

分析工具：
  TempFilter.py         温度过滤算法验证。
                        用 Homography 对齐 RGB 到 IR，用 HSV 分割食材区域，
                        输出四联可视化图（原图/对齐/Mask/热图）。
                        输出：output/filter_result.png

  analyze_ir_temp.py    红外温度数据分布分析。
                        输出帧均值曲线、关键帧热图和直方图，
                        辅助判断锅壁 vs 食材温差是否足够分割。
                        输出：output/ir_analysis/

  analyze_result.py     追踪结果质量分析。
                        读取 food_temp_log.csv，统计 mask 丢失率、
                        扩张率、温度范围，打印批次交接处的连续性。

视频查看工具：
  browse_video.py       交互式视频浏览器。
                        键盘跳帧，Space 记录帧号，用于找到关键帧号
                        再交给 LabelFirstFrame.py 追加标注。

  extract_frames.py     快速提取视频预览帧（6个关键位置）。
                        输出：output/preview_frame_*.jpg

  inspect_frames.py     从追踪结果中提取关键帧截图。
                        诊断 mask 异常扩张的原因。
                        输出：output/inspect_frames/

分割验证：
  SegmentFood.py        SAM2 单帧分割验证。
                        对 preview_frame_0.jpg 做点提示分割，
                        确认模型和权重工作正常。
                        输出：output/segment_result.png
