data/ — 原始采集数据
==============================

存放所有原始采集数据文件，不存放脚本和生成结果。

文件命名规则：
  rgb_YYYYMMDD_HHMMSS.mp4     可见光视频（由 FieldCapture.py 录制）
  temp_YYYYMMDD_HHMMSS.npy    对应的红外温度矩阵（由 FieldCapture.py 录制）
  homography.npy              RGB→IR 对齐矩阵（由 Calibrate.py 生成）

当前文件：
  rgb_20260424_173635.mp4     第一次测试录制
  rgb_20260427_114305.mp4     标定用视频
  rgb_20260428_121157.mp4     主追踪视频（food_labels.json 对应）
  temp_20260424_173656.npy    第一次测试温度数据
  temp_20260427_114341.npy    标定用温度数据
  temp_20260428_121546.npy    主追踪温度数据
  homography.npy              已标定的 RGB→IR 单应矩阵

注意：
  - .npy 文件格式：float32，shape=(N, H, W)，单位 ℃
  - 视频和温度文件应时间戳对应（用 find_temp_npy() 自动匹配）
  - 大文件不要提交到 git（建议在 .gitignore 中排除 *.mp4 和 *.npy）
