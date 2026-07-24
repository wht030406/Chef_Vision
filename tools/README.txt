tools/ — 数据准备工具集
==============================

本目录收纳的是为主流程「准备输入数据」的工具，它们生成主程序
(core/TrackFood.py) 运行所需的配置或干净数据集。它们不是主流程的
一部分，按需手动运行一次即可。

（原先混在这里的验证/调试脚本 SegmentFood / TempFilter / VerifyData /
 _check_syntax 已于 2026-07-24 移入 排查工具/。）


工具说明
--------

  Calibrate.py              【RGB/IR 标定】
                            多帧手动点选对应点，计算 RGB→IR 单应矩阵。
                            输出：data/homography.npy
                            主程序追踪时用它把 mask 映射到红外坐标。

  auto_wok_detect.py        【锅区自动检测】
                            从 IR 温度数据自动检测锅的椭圆区域
                            （锅壁高温圆环 → 温度阈值分割 + 椭圆拟合）。
                            输出：data/wok_region.json
                            主程序追踪时读它定位锅区与旋转轴排除圆。
                            用法示例：
                              python tools/auto_wok_detect.py \
                                --temp data/temp_20260428_121546.npy \
                                --start_sec 5 --out data/wok_region.json

  trim_dataset_segments.py  【数据集片段裁剪】
                            按指定时间段（秒）从 RGB 视频 + IR + 温度数据
                            中同步剪掉片段（如锅直立、空锅等无效时段），
                            生成对齐的新数据集目录。
                            用法示例：
                              python tools/trim_dataset_segments.py \
                                --src-dir data --dst-dir data_trimmed \
                                --rgb rgb_xxx.mp4 --ir ir_xxx.mp4 \
                                --temp temp_xxx.npy --segments 33-38 40-46


说明
----
  这三个工具生成的 homography.npy / wok_region.json 是主程序的必需
  配置，存放在 data/ 目录（主程序以 ../data 相对路径读取）。
