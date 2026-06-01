core/ — 主体追踪与标注脚本
==============================

工作流程（按顺序执行）：

1. LabelFirstFrame.py
   交互式标注工具。打开视频，用鼠标在食材入锅帧上点击前景/背景点。
   支持多关键帧追加（--append --frame N）。
   输出：food_labels.json

2. TrackFood.py
   主追踪脚本（大批量版，CHUNK_SIZE=200）。
   读取 food_labels.json，用 SAM2 VideoPredictor 分批追踪食材，
   融合红外温度数据，输出可视化视频和温度 CSV。
   输出：output/track_result.mp4、output/food_temp_log.csv、output/food_temp_curve.png

3. TrackFood_AutoRecover.py
   自动恢复版追踪脚本（小批量版，CHUNK_SIZE=12）。
   在 TrackFood.py 基础上增加 Mask 质量监控和自动恢复功能。
   适合长时间无人值守录制场景。
   输出：output/track_result_auto.mp4、output/food_temp_log_auto.csv

辅助文件：
  food_labels.json      标注数据（由 LabelFirstFrame.py 生成）
  auto_tracking_utils.py  TrackFood_AutoRecover.py 的工具函数库

依赖：
  pip install sam2 opencv-python numpy matplotlib
  SAM2 权重：D:/sam2_checkpoints/sam2.1_hiera_large.pt
