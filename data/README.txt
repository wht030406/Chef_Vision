data/ — 主程序配置与采集数据
==============================

本目录同时存放两类东西，按性质区分如下。主程序 core/TrackFood.py
以相对路径 ../data 读取本目录，【目录名 data 不要改】，否则主程序
会找不到配置文件。


一、主程序必需配置（刚需，勿删）
--------------------------------
  homography.npy      RGB→IR 对齐单应矩阵（由 tools/Calibrate.py 生成）。
                      主程序用它把 mask 映射到红外坐标，做温度融合。
                      TrackFood.py 第 47 行读取。

  wok_region.json     锅区椭圆参数 + 旋转轴排除圆（由 tools/auto_wok_detect.py
                      生成，也可由 core/LabelFirstFrame.py 写入）。
                      主程序用它定位锅区。TrackFood.py 第 147 行读取。
                      字段：cx/cy 锅心，rx/ry 椭圆半径，
                            axis_cx/axis_cy 旋转轴心，axis_excl_r_ir 排除半径，
                            ir_h/ir_w 红外分辨率。


二、采集数据（原始视频与温度矩阵）
----------------------------------
  命名规则：
    rgb_YYYYMMDD_HHMMSS.mp4    可见光视频（由 field/FieldCapture.py 录制）
    temp_YYYYMMDD_HHMMSS.npy   对应红外温度矩阵（float32, shape=(N,H,W), 单位 ℃）

  当前主追踪数据（TrackFood.py 默认处理的就是这一组）：
    rgb_20260428_121157.mp4
    temp_20260428_121546.npy

  注意：
    - 视频与温度文件按时间戳对应（find_temp_npy() 自动匹配）。
    - 大文件（*.mp4 / *.npy）不入 git，已在根目录 .gitignore 排除。
    - 历史测试数据（0424 第一次测试、0427 标定用）已于 2026-07-24 清理。
