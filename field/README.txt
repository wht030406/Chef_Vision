field/ — 厨房现场采集脚本（低配笔记本用）
==========================================

这些脚本设计用于带进厨房的低配置笔记本，
只需 numpy + opencv（部分脚本还需 matplotlib），不依赖 SAM2 等重型库。

【重要】本文件夹已自带一份 SDK 二进制（IRCNetSDK.dll 及全部依赖 DLL
和 ThermalCamera.py），可直接整个文件夹拷贝到低配机使用，无需再去
根目录 sdk/ 找文件。这些 DLL 不纳入 git（见根目录 .gitignore 的
field/*.dll），拷贝时请连同 .dll 文件一起复制。


脚本说明
--------

  FieldCapture.py       【主采集脚本，当前主力】
                        实时显示 RGB + IR 双画面预览。
                        按 S 开始录制，按 Q 停止保存。
                        自动以时间戳命名，输出到脚本所在目录。
                        DLL 从脚本同目录加载 → 整个 field/ 拷走即可运行。
                        输出：rgb_YYYYMMDD_HHMMSS.mp4
                              temp_YYYYMMDD_HHMMSS.npy

  FieldTempMonitor.py   【实时温度监测】
                        连接热像仪，显示 IR 热图。
                        按 R 框选 ROI，按 S 录制，按 Q 保存。
                        DLL 从脚本同目录加载，输出到同目录的 output/ 子目录，
                        与 FieldCapture.py 一致，整个 field/ 拷走即可运行。
                        输出：output/temp_monitor_TIMESTAMP.csv
                              output/temp_monitor_TIMESTAMP.png

  TempMonitor.py        【离线温度分析工具，上位机用】
                        加载已录制的 .npy 文件，手动圈选 ROI，
                        提取温度统计并导出 CSV + 曲线图。
                        不连设备、不需要 DLL。
                        输出：temp_monitor_log.csv、temp_monitor_curve.png

  详细的下位机/上位机操作步骤见 TempMonitor使用说明.md。


随附配置文件
------------

  roi_config.json       预览/RGB 画面的 ROI 圆心与半径配置。
  fill_light_token.txt  TN220 补光灯 HTTP 控制的本地鉴权 token（不入库）。


设备参数（各脚本顶部修改）
--------------------------
  DEVICE_IP   = "192.168.1.123"
  DEVICE_PORT = 80
  USERNAME    = "admin"
  PASSWORD    = "ZGTC2026"


Python 依赖
-----------
  pip install numpy opencv-python matplotlib


归档说明
--------
  早期的 DataLogger.py（已被 FieldCapture.py 替代）已移至根目录
  「可能不需要的文件」文件夹，不再随 field/ 一起分发。
